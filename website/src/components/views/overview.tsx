"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useApp } from "@/components/app-shell";
import { api } from "@/lib/client";
import { fill } from "@/lib/i18n";

type Counts = { active: number; pending: number; waiting: number; unread: number; focus: number | null; tracked: number };

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function loadCounts(manager: boolean): Promise<Counts> {
  const end = new Date();
  const start = new Date(end.getTime() - 6 * 864e5);
  const [users, waiting, unread, report] = await Promise.all([
    manager ? api<{ status: string; role: string }[]>("users") : Promise.resolve(null),
    api<{ waiting: number }>("meeting-requests/waiting-count"),
    api<{ unread: number }>("chat/unread-count"),
    manager ? api<{ totals: { focus_pct: number; tracked_seconds: number } }>(
      `reports/overview?start=${iso(start)}&end=${iso(end)}&today=${iso(end)}&limit=1`) : Promise.resolve(null),
  ]);
  const people = users && users.ok ? users.data.filter((u) => u.role === "employee") : [];
  return {
    active: people.filter((u) => u.status === "active").length,
    pending: people.filter((u) => u.status === "pending").length,
    waiting: waiting.ok ? waiting.data.waiting : 0,
    unread: unread.ok ? unread.data.unread : 0,
    focus: report && report.ok ? report.data.totals.focus_pct : null,
    tracked: report && report.ok ? report.data.totals.tracked_seconds : 0,
  };
}

/** The portal's first page: who you are, your company, the desktop app, and what waits for you. */
export function OverviewView({ download }: { download: React.ReactNode }) {
  const { me, t, lang } = useApp();
  const o = t.overview;
  const manager = me.user.role === "manager";
  const [counts, setCounts] = useState<Counts | null>(null);

  useEffect(() => {
    let alive = true;
    loadCounts(manager).then((c) => { if (alive) setCounts(c); });
    return () => { alive = false; };
  }, [manager]);

  return (
    <div className="stack">
      <div>
        <h1>{fill(o.welcome, { name: me.user.full_name })}</h1>
        <p className="lead">{me.company.name}</p>
      </div>
      <div className="overview-grid">
        <section className="card" aria-labelledby="ov-profile">
          <h2 id="ov-profile">{o.profile}</h2>
          <dl className="kv">
            <dt>{o.name}</dt><dd>{me.user.full_name}</dd>
            <dt>{o.email}</dt><dd dir="ltr" style={{ textAlign: "start" }}>{me.user.email}</dd>
            <dt>{o.role}</dt><dd>{manager ? t.app.manager : t.app.employee}</dd>
            <dt>{o.company}</dt><dd>{me.company.name}</dd>
            {manager && me.company.join_code ? <><dt>{o.companyCode}</dt><dd className="mono" dir="ltr" style={{ textAlign: "start" }}>{me.company.join_code}</dd></> : null}
          </dl>
        </section>
        <section className="card" aria-labelledby="ov-download">
          <h2 id="ov-download">{o.download}</h2>
          <p className="muted">{o.downloadText}</p>
          {download}
        </section>

        {manager ? (
          <section className="card" aria-labelledby="ov-members" data-testid="overview-members">
            <h2 id="ov-members">{o.members}</h2>
            <p><span className="big-number">{counts ? counts.active : "–"}</span> <span className="muted">{o.active}</span></p>
            <p><span className="big-number">{counts ? counts.pending : "–"}</span> <span className="muted">{o.pending}</span></p>
            <Link className="btn btn-small" href={`/${lang}/app/employees`}>{o.invite}</Link>
          </section>
        ) : null}
        {manager ? (
          <section className="card" aria-labelledby="ov-reports" data-testid="overview-reports">
            <h2 id="ov-reports">{o.reports}</h2>
            {counts && counts.tracked > 0 ? (
              <p><span className="big-number">{counts.focus}%</span> <span className="muted">{o.focusThisWeek}</span></p>
            ) : <p className="muted">{counts ? o.noSessions : t.app.loading}</p>}
            <p className="hint">{o.reportsText}</p>
            <Link className="btn btn-small" href={`/${lang}/app/dashboard`}>{o.open}</Link>
          </section>
        ) : null}
        <section className="card" aria-labelledby="ov-meetings">
          <h2 id="ov-meetings">{o.meetings}</h2>
          <p><span className="big-number">{counts ? counts.waiting : "–"}</span> <span className="muted">{o.meetingsWaiting}</span></p>
          <Link className="btn btn-small" href={`/${lang}/app/meetings`}>{o.open}</Link>
        </section>
        <section className="card" aria-labelledby="ov-messages">
          <h2 id="ov-messages">{o.messages}</h2>
          <p><span className="big-number">{counts ? counts.unread : "–"}</span> <span className="muted">{o.unread}</span></p>
          <Link className="btn btn-small" href={`/${lang}/app/messages`}>{o.open}</Link>
        </section>
      </div>
    </div>
  );
}
