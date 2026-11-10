import { crossSite, offline } from "@/lib/server/guard";
import { apiFetch, Offline } from "@/lib/server/session";

/**
 * Forwards the signed-in pages' API calls, adding the access token from the httpOnly cookie.
 * Only the parts of the API the website uses are reachable, and every path segment is
 * checked, so this cannot be used to reach anything else.
 */
const ALLOWED = new Set(["reports", "users", "invites", "company", "meeting-requests", "notifications", "chat", "email-log"]);
const SEGMENT = /^[A-Za-z0-9_-]{1,64}$/;

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const refused = crossSite(request);
  if (refused) return refused;
  const { path } = await context.params;
  if (!path.length || !ALLOWED.has(path[0]) || !path.every((part) => SEGMENT.test(part))) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  const url = new URL(request.url);
  const init: RequestInit = { method: request.method, headers: {} };
  if (!["GET", "HEAD"].includes(request.method)) {
    const body = await request.text();
    if (body.length > 64 * 1024) return Response.json({ detail: "Too large" }, { status: 413 });
    if (body) {
      init.body = body;
      init.headers = { "content-type": "application/json" };
    }
  }
  try {
    const response = await apiFetch(`/${path.join("/")}${url.search}`, init);
    if (response.status === 204) return new Response(null, { status: 204 });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Offline) return offline();
    throw error;
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
