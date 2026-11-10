import { crossSite, offline, readJson } from "@/lib/server/guard";
import { API_URL, visitorHeaders } from "@/lib/server/session";

/** Join a company with its code or an invite token; the account waits for the manager's approval. */
export async function POST(request: Request) {
  const refused = crossSite(request);
  if (refused) return refused;
  let body: Record<string, unknown>;
  try {
    body = (await readJson(request)) as Record<string, unknown>;
  } catch {
    return Response.json({ detail: "Invalid request" }, { status: 400 });
  }
  const payload: Record<string, unknown> = { full_name: body?.full_name, email: body?.email, password: body?.password };
  if (body?.invite_token) payload.invite_token = body.invite_token;
  else payload.company_code = body?.company_code;
  try {
    const response = await fetch(`${API_URL}/auth/join`, {
      method: "POST",
      headers: { "content-type": "application/json", ...visitorHeaders(request) },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json" } });
  } catch {
    return offline();
  }
}
