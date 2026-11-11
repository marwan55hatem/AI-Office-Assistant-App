import { crossSite, offline, readJson } from "@/lib/server/guard";
import { API_URL, visitorHeaders } from "@/lib/server/session";

/** Use a reset link: set the new password (the API signs the account out everywhere). */
export async function POST(request: Request) {
  const refused = crossSite(request);
  if (refused) return refused;
  let body: Record<string, unknown>;
  try {
    body = (await readJson(request)) as Record<string, unknown>;
  } catch {
    return Response.json({ detail: "Invalid request" }, { status: 400 });
  }
  try {
    const response = await fetch(`${API_URL}/auth/password/reset`, {
      method: "POST",
      headers: { "content-type": "application/json", ...visitorHeaders(request) },
      body: JSON.stringify({ token: body?.token, new_password: body?.new_password }),
      cache: "no-store",
    });
    if (response.status === 204) return new Response(null, { status: 204 });
    return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json" } });
  } catch {
    return offline();
  }
}
