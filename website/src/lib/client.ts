"use client";

/** Calls from the browser. They go to this site's own server (never straight to the API), with
 *  the header our cross-site check expects. */

export type Result<T> = { ok: true; status: number; data: T } | { ok: false; status: number; error: string };

const HEADERS = { "x-oa-request": "1" };

async function call<T>(url: string, method = "GET", body?: unknown): Promise<Result<T>> {
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? HEADERS : { ...HEADERS, "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return { ok: false, status: 0, error: "offline" };
  }
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const error = typeof detail === "string" ? detail
      : Array.isArray(detail) && detail[0]?.msg ? String(detail[0].msg).replace(/^Value error, /, "")
      : response.status === 503 ? "offline" : "error";
    return { ok: false, status: response.status, error };
  }
  return { ok: true, status: response.status, data: data as T };
}

/** The API through the signed-in proxy, e.g. `api("reports/overview?start=...")`. A lost session sends
 *  the visitor to the sign-in page. */
export async function api<T>(path: string, method = "GET", body?: unknown): Promise<Result<T>> {
  const result = await call<T>(`/api/proxy/${path}`, method, body);
  if (!result.ok && result.status === 401 && typeof window !== "undefined") {
    const lang = window.location.pathname.split("/")[1] || "en";
    // a plain helper (no router here): a full page load also drops any state of the lost session
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/${lang}/signin?next=${encodeURIComponent(window.location.pathname)}`);
  }
  return result;
}

export function authCall<T>(route: "login" | "register" | "join" | "logout" | "session" | "socket" | "forgot" | "reset", body?: unknown) {
  return call<T>(`/api/auth/${route}`, body === undefined && (route === "session" || route === "socket") ? "GET" : "POST", body);
}

export type Me = {
  user: { id: string; email: string; full_name: string; role: "manager" | "employee"; status: string };
  company: { id: string; name: string; join_code: string | null };
};
