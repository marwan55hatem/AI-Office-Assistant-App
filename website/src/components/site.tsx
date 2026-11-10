import Link from "next/link";

import { HeaderTools, NavLink } from "@/components/header-tools";
import type { Dict, Locale } from "@/lib/i18n";

export const REPO = "https://github.com/marwan55hatem/AI-Office-Assistant-App";

export function SiteHeader({ lang, t, signedIn }: { lang: Locale; t: Dict; signedIn: boolean }) {
  const links: [string, string][] = [
    ["", t.nav.home],
    ["/how-it-works", t.nav.how],
    ["/features", t.nav.features],
    ["/privacy", t.nav.privacy],
    ["/download", t.nav.download],
    ["/faq", t.nav.faq],
  ];
  return (
    <header className="site-header">
      <div className="container header-row">
        <Link className="brand" href={`/${lang}`}>
          <span className="brand-mark" aria-hidden="true">OA</span>
          Office Assistant
        </Link>
        <nav className="nav" aria-label={t.nav.menu}>
          {links.map(([path, label]) => (
            <NavLink key={path} href={`/${lang}${path}`}>{label}</NavLink>
          ))}
        </nav>
        <div className="header-tools">
          {signedIn ? (
            <Link className="btn btn-primary btn-small" href={`/${lang}/app`}>{t.nav.dashboard}</Link>
          ) : (
            <>
              <Link className="btn btn-small" href={`/${lang}/signin`}>{t.nav.signIn}</Link>
              <Link className="btn btn-primary btn-small" href={`/${lang}/signup`}>{t.nav.signUp}</Link>
            </>
          )}
          <HeaderTools lang={lang} t={t} />
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ t }: { t: Dict }) {
  return (
    <footer className="site-footer">
      <div className="container footer-row">
        <p>© Office Assistant · {t.footer.tagline}</p>
        <p>
          <a href={REPO} rel="noopener">{t.footer.github}</a> · {t.footer.rights}
        </p>
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
