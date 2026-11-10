import { crossSite, offline, readJson } from "@/lib/server/guard";
import { API_URL, type TokenPair, visitorHeaders } from "@/lib/server/session";
import { signedIn } from "@/lib/server/signin";

type Body = { email?: unknown; password?: unknown; remember?: unknown };

/** Sign in: the API's tokens go into httpOnly cookies; the page gets only the user's profile. */
export async function POST(request: Request) {
  const refused = crossSite(request);
  if (refused) return refused;
  let body: Body;
  try {
    body = (await readJson(request)) as Body;
  } catch {
    return Response.json({ detail: "Invalid request" }, { status: 400 });
  }
  const email = typeof body?.email === "string" ? body.email : "";
  const password = typeof body?.password === "string" ? body.password : "";
  try {
    const response = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json", ...visitorHeaders(request) },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
    if (!response.ok) return new Response(await response.text(), { status: response.status, headers: json });
    const pair = (await response.json()) as TokenPair;
    return await signedIn(pair, body?.remember !== false);
  } catch {
    return offline();
  }
}

const json = { "content-type": "application/json" };
