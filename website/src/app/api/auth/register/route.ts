import { crossSite, offline, readJson } from "@/lib/server/guard";
import { API_URL, type TokenPair, visitorHeaders } from "@/lib/server/session";
import { signedIn } from "@/lib/server/signin";

/** Create a company and its manager account through the API, then sign the manager in. */
export async function POST(request: Request) {
  const refused = crossSite(request);
  if (refused) return refused;
  let body: Record<string, unknown>;
  try {
    body = (await readJson(request)) as Record<string, unknown>;
  } catch {
    return Response.json({ detail: "Invalid request" }, { status: 400 });
  }
  const payload = {
    company_name: body?.company_name,
    owner_name: body?.owner_name,
    email: body?.email,
    password: body?.password,
  };
  try {
    const response = await fetch(`${API_URL}/auth/register-company`, {
      method: "POST",
      headers: { "content-type": "application/json", ...visitorHeaders(request) },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    if (!response.ok) {
      return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json" } });
    }
    return await signedIn((await response.json()) as TokenPair, true);
  } catch {
    return offline();
  }
}
