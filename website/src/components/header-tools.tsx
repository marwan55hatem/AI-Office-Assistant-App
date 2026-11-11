"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import type { Dict, Locale } from "@/lib/i18n";

/** A navigation link that marks itself as the current page (in-page "#section" links never do). */
export function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const current = !href.includes("#") && (pathname === href || pathname.startsWith(href + "/"));
  return (
    <Link href={href} aria-current={current ? "page" : undefined}>
      {children}
    </Link>
  );
}

function readTheme(): "light" | "dark" {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function subscribeTheme(callback: () => void) {
  window.addEventListener("oa-theme", callback);
  return () => window.removeEventListener("oa-theme", callback);
}

function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

/** The language switch (same page in the other language, remembered) and the light/dark switch. */
export function HeaderTools({ lang, t }: { lang: Locale; t: Dict }) {
  const pathname = usePathname() ?? `/${lang}`;
  const other: Locale = lang === "en" ? "ar" : "en";
  const otherPath = pathname.replace(/^\/(en|ar)(?=\/|$)/, `/${other}`);
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => null);

  // The boot script sets the theme before the first paint. If the root element is rebuilt
  // afterwards (Next does this for the 404 page), set it again the same way.
  useEffect(() => {
    const root = document.documentElement;
    if (root.dataset.theme) return;
    let saved: string | null = null;
    try {
      saved = localStorage.getItem("oa-theme");
    } catch {
      saved = null;
    }
    root.dataset.theme = saved === "light" || saved === "dark" ? saved
      : matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    window.dispatchEvent(new Event("oa-theme"));
  }, []);

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

  function rememberLanguage() {
    // read by the server (proxy) the next time a page without a language is opened
    document.cookie = `oa-lang=${other}; path=/; max-age=31536000; samesite=lax`;
  }

  return (
    <>
      <Link className="btn btn-small" href={otherPath} hrefLang={other} lang={other} aria-label={t.nav.languageLabel}
            onClick={rememberLanguage}>
        {t.nav.language}
      </Link>
      <button type="button" className="btn btn-small icon-btn" onClick={toggle}
              aria-label={theme === "light" ? t.nav.themeDark : t.nav.themeLight}
              title={theme === "light" ? t.nav.themeDark : t.nav.themeLight}>
        {theme === "light" ? <MoonIcon /> : <SunIcon />}
      </button>
    </>
  );
}

/** The menu button for narrow screens: shows and hides the main navigation. */
export function MenuToggle({ t }: { t: Dict }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  useEffect(() => {
    const nav = document.getElementById("site-nav");
    if (nav) nav.dataset.open = open ? "true" : "false";
  }, [open]);
  useEffect(() => {
    const nav = document.getElementById("site-nav");
    if (nav) nav.dataset.open = "false";
    const close = () => setOpen(false);
    nav?.addEventListener("click", close);
    return () => nav?.removeEventListener("click", close);
  }, [pathname]);
  return (
    <button type="button" className="btn btn-small icon-btn menu-toggle" aria-controls="site-nav" aria-expanded={open}
            aria-label={open ? t.nav.closeMenu : t.nav.openMenu} onClick={() => setOpen(!open)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
      </svg>
    </button>
  );
}
