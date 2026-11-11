import Link from "next/link";

import { HeaderTools, MenuToggle, NavLink } from "@/components/header-tools";
import type { Dict, Locale } from "@/lib/i18n";

export const REPO = "https://github.com/marwan55hatem/AI-Office-Assistant-App";

/** The design's logo mark: two circles. */
export function LogoMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" />
      </svg>
    </span>
  );
}

export function GitHubIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
    </svg>
  );
}

export function DownloadIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" /><path d="M7 11l5 5 5-5" /><path d="M5 20h14" />
    </svg>
  );
}

/** A link to another site: new tab, no opener, no referrer, and said out loud for screen readers. */
export function External({ href, className, children, t }: { href: string; className?: string; children: React.ReactNode; t: Dict }) {
  return (
    <a href={href} className={className} target="_blank" rel="noopener noreferrer">
      {children}<span className="sr-only"> {t.nav.newTab}</span>
    </a>
  );
}

export function SiteHeader({ lang, t, signedIn }: { lang: Locale; t: Dict; signedIn: boolean }) {
  const links: [string, string][] = [
    [`/${lang}#features`, t.nav.features],
    [`/${lang}#live`, t.nav.live],
    [`/${lang}#how`, t.nav.how],
    [`/${lang}/privacy`, t.nav.privacy],
    [`/${lang}/download`, t.nav.download],
    [`/${lang}/faq`, t.nav.faq],
  ];
  return (
    <header className="site-header">
      <div className="container header-row">
        <Link className="brand" href={`/${lang}`}>
          <LogoMark />
          {t.nav.brand}
        </Link>
        <nav className="nav" id="site-nav" aria-label={t.nav.menu}>
          {links.map(([href, label]) => <NavLink key={href} href={href}>{label}</NavLink>)}
        </nav>
        <div className="header-tools">
          {signedIn ? (
            <Link className="btn btn-primary btn-small" href={`/${lang}/app`}>{t.nav.dashboard}</Link>
          ) : (
            <>
              <Link className="btn btn-small hide-sm" href={`/${lang}/signin`}>{t.nav.signIn}</Link>
              <Link className="btn btn-primary btn-small" href={`/${lang}/signup`}>{t.nav.signUp}</Link>
            </>
          )}
          <HeaderTools lang={lang} t={t} />
          <MenuToggle t={t} />
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ t }: { t: Dict }) {
  return (
    <footer className="site-footer">
      <div className="container footer-row">
        <span>{t.footer.tagline} · {t.footer.rights}</span>
        <External href={REPO} t={t}>{t.footer.github}</External>
      </div>
    </footer>
  );
}

export function PageTitle({ title, lead }: { title: string; lead?: string }) {
  return (
    <div className="page-title">
      <h1>{title}</h1>
      {lead ? <p className="lead">{lead}</p> : null}
    </div>
  );
}
