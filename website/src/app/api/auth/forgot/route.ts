import { crossSite, offline, readJson } from "@/lib/server/guard";
import { API_URL, visitorHeaders } from "@/lib/server/session";

/** Ask the API to e-mail a password-reset link. The answer is the same whether or not the address exists. */
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
    const response = await fetch(`${API_URL}/auth/password/forgot`, {
      method: "POST",
      headers: { "content-type": "application/json", ...visitorHeaders(request) },
      body: JSON.stringify({ email: body?.email }),
      cache: "no-store",
    });
    return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json" } });
  } catch {
    return offline();
  }
}
