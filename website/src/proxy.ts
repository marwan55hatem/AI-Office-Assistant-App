import { NextResponse, type NextRequest } from "next/server";

import { hasLocale, pickLocale } from "@/lib/i18n";

/**
 * 1. Every page lives under /en or /ar. A path without a language goes to the language the visitor
 *    chose before (the `oa-lang` cookie), else their browser's language, else English.
 * 2. The signed-in area (/{lang}/app/...) needs the session cookie; without it the visitor goes to
 *    the sign-in page. (The API checks the real session on every call; this only avoids an empty page.)
 * 3. A Content Security Policy with a fresh nonce on every page: only this site's own scripts (and the
 *    ones Next.js marks with the nonce) may run; no framing; connections only to this site and the
 *    chat's live channel.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const first = pathname.split("/")[1] ?? "";
  if (!hasLocale(first)) {
    const saved = request.cookies.get("oa-lang")?.value ?? "";
    const locale = hasLocale(saved) ? saved : pickLocale(request.headers.get("accept-language"));
    return NextResponse.redirect(new URL(`/${locale}${pathname === "/" ? "" : pathname}${search}`, request.url));
  }
  if (pathname.startsWith(`/${first}/app`) && !request.cookies.has("oa_rt")) {
    const next = encodeURIComponent(pathname + search);
    return NextResponse.redirect(new URL(`/${first}/signin?next=${next}`, request.url));
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("content-security-policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("content-security-policy", csp);
  return response;
}

function socketOrigin(): string {
  const explicit = process.env.PUBLIC_API_WS_URL;
  const api = explicit ?? (process.env.API_URL ?? "http://localhost:8766").replace(/^http/, "ws");
  try {
    return new URL(api).origin.replace(/^http/, "ws");
  } catch {
    return "";
  }
}

export function contentSecurityPolicy(nonce: string): string {
  const dev = process.env.NODE_ENV === "development";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    // style attributes cannot carry a nonce; scripts stay strict, styles may be inline
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${socketOrigin()}`.trim(),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(dev || process.env.ALLOW_INSECURE_COOKIES === "1" ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|screens|favicon.ico|og.png|robots.txt|sitemap.xml|.*\\.(?:png|jpg|svg|ico|webp)$).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
