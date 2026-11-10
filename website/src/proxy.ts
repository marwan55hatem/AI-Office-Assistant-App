import { NextResponse, type NextRequest } from "next/server";

import { hasLocale, pickLocale } from "@/lib/i18n";

/**
 * 1. Every page lives under /en or /ar: a path without a language is sent to the visitor's
 *    preferred one (Accept-Language), defaulting to English.
 * 2. The signed-in area (/{lang}/app/...) needs the session cookie; without it the visitor goes
 *    to the sign-in page. (The API checks the real session on every call; this only avoids
 *    showing an empty page.)
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const first = pathname.split("/")[1] ?? "";
  if (!hasLocale(first)) {
    const locale = pickLocale(request.headers.get("accept-language"));
    return NextResponse.redirect(new URL(`/${locale}${pathname === "/" ? "" : pathname}${search}`, request.url));
  }
  if (pathname.startsWith(`/${first}/app`) && !request.cookies.has("oa_rt")) {
    const next = encodeURIComponent(pathname + search);
    return NextResponse.redirect(new URL(`/${first}/signin?next=${next}`, request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|screens|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:png|jpg|svg|ico|webp)$).*)"],
};
