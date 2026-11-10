import { cookies } from "next/headers";

import { crossSite } from "@/lib/server/guard";
import { API_URL, clearTokens } from "@/lib/server/session";

/** Sign out: the API revokes the refresh token, and the cookies are removed either way. */
export async function POST(request: Request) {
  const refused = crossSite(request);
  if (refused) return refused;
  const jar = await cookies();
  const refresh = jar.get("oa_rt")?.value;
  if (refresh) {
    try {
      await fetch(`${API_URL}/auth/logout`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        cache: "no-store",
      });
    } catch {
      // offline: the cookies are still removed; the token expires on its own
    }
  }
  clearTokens(jar);
  return new Response(null, { status: 204 });
}
