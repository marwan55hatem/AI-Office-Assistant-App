import "server-only";

import { cookies } from "next/headers";

import { API_URL, type TokenPair, writeTokens } from "@/lib/server/session";

/** Store the new tokens in httpOnly cookies and answer with the user's profile only. */
export async function signedIn(pair: TokenPair, remember: boolean): Promise<Response> {
  const jar = await cookies();
  writeTokens(jar, pair, remember);
  const me = await fetch(`${API_URL}/auth/me`, {
    headers: { authorization: `Bearer ${pair.access_token}` },
    cache: "no-store",
  });
  return new Response(await me.text(), { status: me.status, headers: { "content-type": "application/json" } });
}
