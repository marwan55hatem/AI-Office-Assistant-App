import "server-only";

import { cookies } from "next/headers";

/**
 * The website's side of signing in ("backend for frontend").
 *
 * The browser never sees the refresh token: it lives in an httpOnly cookie, and every API
 * call goes through this server (`/api/proxy/...`), which adds the access token. So a
 * script injected into a page cannot steal a long-lived token.
 *
 * The API rotates refresh tokens and treats a reused one as theft (it then signs the user
 * out everywhere). Several browser requests can find the access token expired at the same
 * moment, so refreshes are de-duplicated here: requests holding the same refresh token
 * share one refresh call and its result.
 */

export const API_URL = (process.env.API_URL ?? "http://127.0.0.1:8766").replace(/\/$/, "");
const ACCESS = "oa_at";
const REFRESH = "oa_rt";
const REMEMBER = "oa_rem";
const REFRESH_DAYS = 30;
const secure = process.env.NODE_ENV === "production" && process.env.ALLOW_INSECURE_COOKIES !== "1";

export type TokenPair = { access_token: string; refresh_token: string; expires_in: number };
type Jar = Awaited<ReturnType<typeof cookies>>;

const base = { httpOnly: true, secure, sameSite: "lax" as const, path: "/" };

export function writeTokens(jar: Jar, pair: TokenPair, remember: boolean) {
  const keep = remember ? { maxAge: REFRESH_DAYS * 24 * 3600 } : {};
  jar.set(ACCESS, pair.access_token, { ...base, maxAge: Math.max(pair.expires_in - 30, 30) });
  jar.set(REFRESH, pair.refresh_token, { ...base, ...keep });
  jar.set(REMEMBER, remember ? "1" : "0", { ...base, ...keep });
}

export function clearTokens(jar: Jar) {
  for (const name of [ACCESS, REFRESH, REMEMBER]) jar.delete(name);
}

export function hasSession(jar: Jar): boolean {
  return jar.has(REFRESH);
}

/** Headers that let the API rate-limit the visitor, not this server (see the API's WEB_PROXY_SECRET). */
export function visitorHeaders(request: Request): Record<string, string> {
  const secret = process.env.WEB_PROXY_SECRET;
  const ip = (request.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || request.headers.get("x-real-ip");
  return secret && ip ? { "x-client-ip": ip, "x-web-proxy-secret": secret } : {};
}

// ---------------------------------------------------------------- refresh, de-duplicated
const inflight = new Map<string, { result: Promise<TokenPair | null>; at: number }>();
const SHARE_MS = 20_000;

function refreshOnce(refreshToken: string): Promise<TokenPair | null> {
  const now = Date.now();
  for (const [key, entry] of inflight) if (now - entry.at > SHARE_MS) inflight.delete(key);
  const existing = inflight.get(refreshToken);
  if (existing) return existing.result;
  const result = fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  })
    .then(async (response) => (response.ok ? ((await response.json()) as TokenPair) : null))
    .catch(() => {
      inflight.delete(refreshToken); // a network error: let the next request try again
      throw new Error("offline");
    });
  inflight.set(refreshToken, { result, at: now });
  return result;
}

export class Offline extends Error {}

/**
 * Call the API as the signed-in visitor (only from Route Handlers, which may write cookies).
 * Returns the API's response, or a 401 response when there is no valid session any more.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const jar = await cookies();
  let access = jar.get(ACCESS)?.value;
  const refresh = jar.get(REFRESH)?.value;
  if (!refresh) return unauthorized();

  const send = (token: string | undefined) =>
    fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...(init.headers as Record<string, string>), ...(token ? { authorization: `Bearer ${token}` } : {}) },
      cache: "no-store",
    });

  let response: Response;
  try {
    response = access ? await send(access) : new Response(null, { status: 401 });
    if (response.status === 401) {
      const pair = await refreshOnce(refresh);
      if (!pair) {
        clearTokens(jar);
        return unauthorized();
      }
      writeTokens(jar, pair, jar.get(REMEMBER)?.value === "1");
      access = pair.access_token;
      response = await send(access);
    }
  } catch {
    throw new Offline("The server could not be reached");
  }
  return response;
}

/** A fresh access token for the chat's live connection (the browser keeps it in memory only). */
export async function socketToken(): Promise<string | null> {
  const response = await apiFetch("/auth/me");
  if (!response.ok) return null;
  const jar = await cookies();
  return jar.get(ACCESS)?.value ?? null;
}

export function socketUrl(): string {
  const explicit = process.env.PUBLIC_API_WS_URL;
  if (explicit) return explicit.replace(/\/$/, "") + "/chat/ws";
  return API_URL.replace(/^http/, "ws") + "/chat/ws";
}

function unauthorized() {
  return Response.json({ detail: "Not signed in" }, { status: 401 });
}
