import "server-only";

/**
 * Protection against cross-site requests for every state-changing call: the request must
 * come from this site's own pages (same Origin) and carry our custom header, which a
 * plain cross-site form or image cannot send. The session cookie is also SameSite=Lax.
 */
export function crossSite(request: Request): Response | null {
  if (request.method === "GET" || request.method === "HEAD") return null;
  const origin = request.headers.get("origin");
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  let sameOrigin = false;
  try {
    sameOrigin = origin !== null && host !== null && new URL(origin).host === host;
  } catch {
    sameOrigin = false;
  }
  if (!sameOrigin || request.headers.get("x-oa-request") !== "1") {
    return Response.json({ detail: "Cross-site request refused" }, { status: 403 });
  }
  return null;
}

export async function readJson(request: Request, maxBytes = 64 * 1024): Promise<unknown> {
  const text = await request.text();
  if (text.length > maxBytes) throw new Error("too large");
  return text ? JSON.parse(text) : null;
}

export function offline() {
  return Response.json({ detail: "offline" }, { status: 503 });
}
