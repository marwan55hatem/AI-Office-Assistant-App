"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, authCall, type Me } from "@/lib/client";
import type { Dict, Locale } from "@/lib/i18n";

type AppContext = { me: Me; t: Dict; lang: Locale; refreshBadges: () => void };
const Context = createContext<AppContext | null>(null);

export function useApp(): AppContext {
  const value = useContext(Context);
  if (!value) throw new Error("useApp outside the app shell");
  return value;
}

/** The signed-in area: loads who is signed in, shows the side navigation with badges. */
export function AppShell({ lang, t, children }: { lang: Locale; t: Dict; children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);
  const [badges, setBadges] = useState<{ meetings: number; messages: number }>({ meetings: 0, messages: 0 });
  const pathname = usePathname();
  const router = useRouter();

  const load = useCallback(() => authCall<Me>("session").then((result) => {
    setFailed(!result.ok && result.status !== 401);
    if (result.ok) setMe(result.data);
    else if (result.status === 401) router.replace(`/${lang}/signin?next=${encodeURIComponent(pathname)}`);
  }), [lang, pathname, router]);

  const refreshBadges = useCallback(() => Promise.all([
    api<{ waiting: number }>("meeting-requests/waiting-count"),
    api<{ unread: number }>("chat/unread-count"),
  ]).then(([meetings, messages]) => {
    setBadges({ meetings: meetings.ok ? meetings.data.waiting : 0, messages: messages.ok ? messages.data.unread : 0 });
  }), []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!me) return;
    void refreshBadges();
    const timer = window.setInterval(() => void refreshBadges(), 30_000);
    return () => window.clearInterval(timer);
  }, [me, refreshBadges]);

  async function signOut() {
    await authCall("logout", {});
    router.push(`/${lang}`);
    router.refresh();
  }

  if (failed) {
    return (
      <div className="container section">
        <p className="error" role="alert">{t.app.error}</p>
        <button className="btn" onClick={() => void load()}>{t.app.retry}</button>
      </div>
    );
  }
  if (!me) return <div className="container section" aria-busy="true"><p className="muted">{t.app.loading}</p></div>;

  const manager = me.user.role === "manager";
  const items: [string, string, number][] = [
    ...(manager ? ([["dashboard", t.app.nav.dashboard, 0], ["employees", t.app.nav.employees, 0]] as [string, string, number][]) : []),
    ["meetings", t.app.nav.meetings, badges.meetings],
    ["messages", t.app.nav.messages, badges.messages],
  ];

  return (
    <Context.Provider value={{ me, t, lang, refreshBadges }}>
      <div className="container app-shell">
        <nav className="app-nav" aria-label={t.nav.dashboard}>
          <div className="who">
            {t.app.signedInAs}<br />
            <strong style={{ color: "var(--text)" }}>{me.user.full_name}</strong><br />
            {me.company.name} · {manager ? t.app.manager : t.app.employee}
          </div>
          {items.map(([key, label, count]) => {
            const href = `/${lang}/app/${key}`;
            return (
              <Link key={key} href={href} aria-current={pathname.startsWith(href) ? "page" : undefined}>
                <span>{label}</span>
                {count > 0 ? <span className="badge" aria-label={`${count}`}>{count}</span> : null}
              </Link>
            );
          })}
          <button className="btn btn-small" style={{ marginTop: 12 }} onClick={() => void signOut()}>{t.app.nav.signOut}</button>
          {!manager ? <p className="hint" style={{ padding: "8px 12px" }}>{t.app.getApp} <Link href={`/${lang}/download`}>{t.nav.download}</Link></p> : null}
        </nav>
        <div>{children}</div>
      </div>
    </Context.Provider>
  );
}

/** Sends a manager to the reports and an employee to meetings. */
export function AppHome() {
  const { me, lang } = useApp();
  const router = useRouter();
  useEffect(() => {
    router.replace(`/${lang}/app/${me.user.role === "manager" ? "dashboard" : "meetings"}`);
  }, [me, lang, router]);
  return null;
}

/** For manager-only pages. */
export function ManagersOnly({ children }: { children: React.ReactNode }) {
  const { me, lang } = useApp();
  const router = useRouter();
  const allowed = me.user.role === "manager";
  useEffect(() => {
    if (!allowed) router.replace(`/${lang}/app/meetings`);
  }, [allowed, lang, router]);
  return allowed ? <>{children}</> : null;
}
