"use client";

import { useCallback, useEffect, useId, useState } from "react";

import { useApp } from "@/components/app-shell";
import { api } from "@/lib/client";
import { fill } from "@/lib/i18n";

type User = { id: string; email: string; full_name: string; role: string; status: string };
type Invite = { id: string; email: string | null; expires_at: string; token?: string | null };

export function EmployeesView() {
  const { t, me, lang, refreshBadges } = useApp();
  const e = t.employees;
  const [users, setUsers] = useState<User[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [code, setCode] = useState(me.company.join_code ?? "");
  const [link, setLink] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const inviteId = useId();

  const load = useCallback(() =>
    Promise.all([api<User[]>("users"), api<Invite[]>("invites"), api<{ join_code: string }>("company")]).then(([u, i, c]) => {
      if (u.ok) setUsers(u.data); else setError(t.app.error);
      if (i.ok) setInvites(i.data);
      if (c.ok) setCode(c.data.join_code);
    }), [t]);

  useEffect(() => { void load(); }, [load]);

  async function act(path: string, method = "POST", body?: unknown) {
    setError("");
    const result = await api(path, method, body);
    if (!result.ok) setError(result.error === "offline" ? t.auth.errorOffline : result.error);
    await load();
    refreshBadges();
  }

  async function createInvite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    const result = await api<Invite>("invites", "POST", email ? { email } : {});
    if (!result.ok) return setError(result.error);
    setLink(`${window.location.origin}/${lang}/signup?invite=${encodeURIComponent(result.data.token ?? "")}`);
    setCopied(false);
    await load();
  }

  const pending = (users ?? []).filter((u) => u.status === "pending");
  const team = (users ?? []).filter((u) => u.status !== "pending");
  const date = (value: string) => new Intl.DateTimeFormat(lang === "ar" ? "ar-u-nu-latn" : "en", { dateStyle: "medium" }).format(new Date(value));

  return (
    <div className="stack">
      <div>
        <h1>{e.title}</h1>
        <p className="lead">{e.lead}</p>
      </div>
      {error ? <p className="error" role="alert">{error}</p> : null}

      <section className="card" aria-labelledby="pending">
        <h2 id="pending">{e.pending}</h2>
        {pending.length === 0 ? <p className="muted">{e.noPending}</p> : (
          <ul className="list" style={{ listStyle: "none", padding: 0 }} data-testid="pending">
            {pending.map((u) => (
              <li key={u.id} className="row" style={{ marginBottom: 10 }}>
                <span><strong>{u.full_name}</strong> <span className="muted">{u.email}</span></span>
                <span className="spacer" />
                <button className="btn btn-primary btn-small" onClick={() => void act(`users/${u.id}/approve`)}>{e.approve}</button>
                <button className="btn btn-small btn-danger" onClick={() => void act(`users/${u.id}/status`, "PATCH", { status: "disabled" })}>{e.reject}</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid grid-2">
        <section className="card" aria-labelledby="code">
          <h2 id="code">{e.joinCode}</h2>
          <p style={{ fontSize: "1.6rem", fontWeight: 800, letterSpacing: "0.12em" }} data-testid="join-code" dir="ltr">{code}</p>
          <p className="hint">{e.joinCodeHint}</p>
          <button className="btn btn-small" onClick={async () => {
            const r = await api<{ join_code: string }>("company/join-code", "POST");
            if (r.ok) setCode(r.data.join_code);
          }}>{e.newCode}</button>
        </section>
        <section className="card" aria-labelledby="invite">
          <h2 id="invite">{e.invite}</h2>
          <p className="hint">{e.inviteHint}</p>
          <form onSubmit={createInvite} className="row" style={{ alignItems: "end" }}>
            <div className="field" style={{ flex: 1, margin: 0 }}>
              <label htmlFor={inviteId}>{e.inviteEmail}</label>
              <input id={inviteId} name="email" type="email" />
            </div>
            <button className="btn btn-primary" type="submit">{e.createInvite}</button>
          </form>
          {link ? (
            <div style={{ marginTop: 12 }}>
              <p className="hint">{e.inviteLink}</p>
              <div className="row">
                <input type="text" readOnly value={link} aria-label={e.inviteLink} dir="ltr" style={{ flex: 1 }} />
                <button className="btn btn-small" onClick={async () => { await navigator.clipboard.writeText(link); setCopied(true); }}>
                  {copied ? e.copied : e.copy}
                </button>
              </div>
            </div>
          ) : null}
          {invites.length ? (
            <>
              <h3 style={{ marginTop: 16 }}>{e.openInvites}</h3>
              <ul className="list" style={{ listStyle: "none", padding: 0 }}>
                {invites.map((i) => (
                  <li key={i.id} className="row">
                    <span>{i.email ?? "—"} <span className="muted">· {e.expires} {date(i.expires_at)}</span></span>
                    <span className="spacer" />
                    <button className="btn btn-small" onClick={() => void act(`invites/${i.id}`, "DELETE")}>{e.revoke}</button>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      </div>

      <section className="card" aria-labelledby="team">
        <h2 id="team">{e.team}</h2>
        {users === null ? <p className="muted">{t.app.loading}</p> : (
          <div className="table-wrap">
            <table data-testid="team">
              <thead><tr><th scope="col">{t.dashboard.columns.name}</th><th scope="col">{t.auth.email}</th><th scope="col">{t.app.manager}/{t.app.employee}</th><th scope="col" /><th scope="col" /></tr></thead>
              <tbody>
                {team.map((u) => (
                  <tr key={u.id}>
                    <th scope="row" style={{ color: "var(--text)" }}>{u.full_name}{u.id === me.user.id ? ` (${e.you})` : ""}</th>
                    <td dir="ltr" style={{ textAlign: "start" }}>{u.email}</td>
                    <td>{u.role === "manager" ? t.app.manager : t.app.employee}</td>
                    <td>{u.status === "active" ? e.active : e.disabled}</td>
                    <td className="num">
                      {u.id === me.user.id ? null : u.status === "active" ? (
                        <button className="btn btn-small btn-danger" onClick={() => {
                          if (window.confirm(fill(e.confirmDisable, { name: u.full_name }))) void act(`users/${u.id}/status`, "PATCH", { status: "disabled" });
                        }}>{e.disable}</button>
                      ) : (
                        <button className="btn btn-small" onClick={() => void act(`users/${u.id}/status`, "PATCH", { status: "active" })}>{e.enable}</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
