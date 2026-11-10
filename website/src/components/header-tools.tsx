"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";

import type { Dict, Locale } from "@/lib/i18n";

/** A navigation link that marks itself as the current page. */
export function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const current = pathname === href || (href.split("/").length > 2 && pathname.startsWith(href + "/"));
  return (
    <Link href={href} aria-current={current ? "page" : undefined}>
      {children}
    </Link>
  );
}

function readTheme(): "light" | "dark" {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function subscribeTheme(callback: () => void) {
  window.addEventListener("oa-theme", callback);
  return () => window.removeEventListener("oa-theme", callback);
}

/** The language switch (same page in the other language) and the light/dark switch. */
export function HeaderTools({ lang, t }: { lang: Locale; t: Dict }) {
  const pathname = usePathname() ?? `/${lang}`;
  const other: Locale = lang === "en" ? "ar" : "en";
  const otherPath = pathname.replace(/^\/(en|ar)(?=\/|$)/, `/${other}`);
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => null);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("oa-theme", next);
    } catch {
      /* private mode: the choice lasts for this page only */
    }
    window.dispatchEvent(new Event("oa-theme"));
  }

  return (
    <>
      <Link className="btn btn-small" href={otherPath} hrefLang={other} lang={other} aria-label={t.nav.languageLabel}>
        {t.nav.language}
      </Link>
      <button
        type="button"
        className="btn btn-small icon-btn"
        onClick={toggle}
        aria-label={theme === "dark" ? t.nav.themeLight : t.nav.themeDark}
        title={theme === "dark" ? t.nav.themeLight : t.nav.themeDark}
      >
        <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
      </button>
    </>
  );
}
