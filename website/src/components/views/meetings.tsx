"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { useApp } from "@/components/app-shell";
import { api } from "@/lib/client";
import type { Dict } from "@/lib/i18n";

type Request = {
  id: string; topic: string; note: string | null; proposed_times: string[]; duration_minutes: number;
  status: "pending" | "accepted" | "declined" | "rescheduled" | "cancelled"; chosen_time: string | null;
  decline_reason: string | null; reply_note: string | null; requested_by_name: string; manager_name: string | null;
  created_at: string; waiting_for: "manager" | "employee" | null;
};

/** "2026-11-12T10:00" (a datetime-local value, the visitor's own time) -> ISO with the UTC offset. */
export function withOffset(local: string): string {
  const date = new Date(local);
  const minutes = -date.getTimezoneOffset();
  const sign = minutes >= 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${local.length === 16 ? local + ":00" : local}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

function defaultSlot(days: number) {
  const d = new Date(Date.now() + days * 864e5);
  d.setHours(10, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T10:00`;
}

function useShowTime() {
  const { lang } = useApp();
  return (iso: string) => new Intl.DateTimeFormat(lang === "ar" ? "ar-u-nu-latn" : "en",
    { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
}

function TimesInput({ t, values, onChange, idPrefix }: { t: Dict; values: string[]; onChange: (v: string[]) => void; idPrefix: string }) {
  return (
    <fieldset style={{ border: 0, padding: 0, margin: "0 0 16px" }}>
      <legend style={{ fontWeight: 600, marginBottom: 6 }}>{t.meetings.times}</legend>
      {values.map((value, i) => (
        <div key={i} className="row" style={{ marginBottom: 8 }}>
          <label className="sr-only" htmlFor={`${idPrefix}-${i}`}>{`${t.meetings.times} ${i + 1}`}</label>
          <input id={`${idPrefix}-${i}`} type="datetime-local" value={value} required style={{ maxWidth: 260 }}
                 onChange={(e) => onChange(values.map((v, k) => (k === i ? e.target.value : v)))} />
          {values.length > 1 ? (
            <button type="button" className="btn btn-small" onClick={() => onChange(values.filter((_v, k) => k !== i))}>{t.meetings.remove}</button>
          ) : null}
        </div>
      ))}
      {values.length < 3 ? (
        <button type="button" className="btn btn-small" onClick={() => onChange([...values, defaultSlot(values.length + 1)])}>+ {t.meetings.addTime}</button>
      ) : null}
    </fieldset>
  );
}

function RequestForm({ onSent }: { onSent: () => void }) {
  const { t } = useApp();
  const m = t.meetings;
  const id = useId();
  const [times, setTimes] = useState([defaultSlot(1)]);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    const result = await api("meeting-requests", "POST", {
      topic: data.get("topic"), note: String(data.get("note") ?? "").trim() || null,
      proposed_times: times.map(withOffset), duration_minutes: Number(data.get("duration")),
    });
    setBusy(false);
    if (!result.ok) return setStatus({ ok: false, text: result.error });
    setStatus({ ok: true, text: m.sent });
    form.reset();
    setTimes([defaultSlot(1)]);
    onSent();
  }

  return (
    <section className="card" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{m.request}</h2>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor={`${id}-topic`}>{m.topic}</label>
          <input id={`${id}-topic`} name="topic" type="text" required maxLength={200} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-note`}>{m.note}</label>
          <textarea id={`${id}-note`} name="note" maxLength={1000} />
        </div>
        <TimesInput t={t} values={times} onChange={setTimes} idPrefix={`${id}-time`} />
        <div className="row">
          <label htmlFor={`${id}-duration`} style={{ margin: 0 }}>{m.length}</label>
          <select id={`${id}-duration`} name="duration" defaultValue="30" style={{ width: 120 }}>
            {[15, 30, 45, 60, 90].map((n) => <option key={n} value={n}>{n} {m.minutes}</option>)}
          </select>
          <span className="spacer" />
          <button className="btn btn-primary" type="submit" disabled={busy}>{m.send}</button>
        </div>
        {status ? <p className={status.ok ? "success" : "error"} role="status" style={{ marginTop: 12 }}>{status.text}</p> : null}
      </form>
    </section>
  );
}

function RequestCard({ request, onChanged }: { request: Request; onChanged: (message: string, ok: boolean) => void }) {
  const { t, me } = useApp();
  const m = t.meetings;
  const show = useShowTime();
  const id = useId();
  const manager = me.user.role === "manager";
  const choosing = request.waiting_for === (manager ? "manager" : "employee");
  const [chosen, setChosen] = useState(request.proposed_times[0]);
  const [panel, setPanel] = useState<"" | "decline" | "propose">("");
  const [times, setTimes] = useState([defaultSlot(2)]);

  async function run(path: string, body?: unknown) {
    const result = await api(`meeting-requests/${request.id}/${path}`, "POST", body ?? {});
    setPanel("");
    onChanged(result.ok ? m.done : result.error, result.ok);
  }

  return (
    <article className="card" aria-labelledby={`${id}-topic`} data-testid="meeting">
      <div className="row">
        <h3 id={`${id}-topic`} style={{ margin: 0 }}>{request.topic}</h3>
        <span className="spacer" />
        <span className={`pill-status pill-${request.status}`}>{m.status[request.status]}</span>
      </div>
      <p className="hint">
        {manager ? `${m.from} ${request.requested_by_name}` : `${m.to} ${request.manager_name ?? m.yourManager}`} · {request.duration_minutes} {m.minutes}
      </p>
      {request.note ? <p>“{request.note}”</p> : null}

      {request.status === "accepted" && request.chosen_time ? <p><strong>{m.booked}:</strong> {show(request.chosen_time)}</p> : null}
      {request.status === "pending" || request.status === "rescheduled" ? (
        <fieldset style={{ border: 0, padding: 0, margin: "0 0 12px" }}>
          <legend className="muted">{request.status === "pending" ? m.proposed : m.byManager}{choosing ? ` — ${m.pickOne}` : ""}</legend>
          {request.proposed_times.map((time) => choosing ? (
            <label key={time} className="check" style={{ marginTop: 6 }}>
              <input type="radio" name={`${id}-time`} value={time} checked={chosen === time} onChange={() => setChosen(time)} />
              {show(time)}
            </label>
          ) : <div key={time}>• {show(time)}</div>)}
        </fieldset>
      ) : null}
      {request.reply_note ? <p><strong>{m.managersNote}:</strong> {request.reply_note}</p> : null}
      {request.decline_reason ? <p><strong>{m.reason}:</strong> {request.decline_reason}</p> : null}

      <div className="row">
        {request.status === "rescheduled" && manager ? <span className="hint">{m.waitingEmployee}</span> : null}
        {request.status === "pending" && !manager ? <span className="hint">{m.waitingManager}</span> : null}
        {choosing ? <button className="btn btn-primary btn-small" onClick={() => void run("accept", { time: chosen })}>{m.accept}</button> : null}
        {manager && (request.status === "pending" || request.status === "rescheduled") ? (
          <>
            <button className="btn btn-small" aria-expanded={panel === "propose"} onClick={() => setPanel(panel === "propose" ? "" : "propose")}>{m.propose}</button>
            <button className="btn btn-small btn-danger" aria-expanded={panel === "decline"} onClick={() => setPanel(panel === "decline" ? "" : "decline")}>{m.decline}</button>
          </>
        ) : null}
        {(!manager && ["pending", "rescheduled", "accepted"].includes(request.status)) || (manager && request.status === "accepted") ? (
          <button className="btn btn-small btn-danger" onClick={() => { if (window.confirm(m.confirmCancel)) void run("cancel"); }}>
            {request.status === "accepted" ? m.cancelMeeting : m.cancel}
          </button>
        ) : null}
      </div>

      {panel === "decline" ? (
        <form style={{ marginTop: 14 }} onSubmit={(e) => { e.preventDefault(); void run("decline", { reason: new FormData(e.currentTarget).get("reason") }); }}>
          <div className="field">
            <label htmlFor={`${id}-reason`}>{m.declineReason}</label>
            <textarea id={`${id}-reason`} name="reason" required maxLength={1000} />
          </div>
          <button className="btn btn-small btn-danger" type="submit">{m.decline}</button>
        </form>
      ) : null}
      {panel === "propose" ? (
        <form style={{ marginTop: 14 }} onSubmit={(e) => {
          e.preventDefault();
          const note = String(new FormData(e.currentTarget).get("note") ?? "").trim();
          void run("reschedule", { proposed_times: times.map(withOffset), note: note || null });
        }}>
          <TimesInput t={t} values={times} onChange={setTimes} idPrefix={`${id}-new`} />
          <div className="field">
            <label htmlFor={`${id}-pnote`}>{m.proposeNote}</label>
            <input id={`${id}-pnote`} name="note" type="text" maxLength={1000} />
          </div>
          <button className="btn btn-small btn-primary" type="submit">{m.sendTimes}</button>
        </form>
      ) : null}
    </article>
  );
}

export function MeetingsView() {
  const { t, me, refreshBadges } = useApp();
  const m = t.meetings;
  const manager = me.user.role === "manager";
  const [filter, setFilter] = useState<"open" | "accepted" | "all">("open");
  const [rows, setRows] = useState<Request[] | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  // only the newest request's answer is shown: an older one (another filter, or a reload started
  // before an action) must not overwrite it when it happens to arrive later
  // A reload started by an action (accept, decline...) must use the filter shown *now*, not the
  // one from when the button was clicked; so the filter is read from a ref.
  const latest = useRef(0);
  const filterRef = useRef(filter);
  const load = useCallback(() => {
    const ticket = ++latest.current;
    const current = filterRef.current;
    return api<Request[]>(`meeting-requests${current === "all" ? "" : `?status=${current}`}`)
      .then((result) => { if (ticket === latest.current) setRows(result.ok ? result.data : []); });
  }, []);
  useEffect(() => {
    filterRef.current = filter;
    void load();
  }, [filter, load]);

  useEffect(() => {
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <div className="stack">
      <div>
        <h1>{m.title}</h1>
        <p className="lead">{manager ? m.leadManager : m.leadEmployee}</p>
      </div>
      {notice ? <p className={notice.ok ? "success" : "error"} role="status">{notice.text}</p> : null}
      {!manager ? <RequestForm onSent={() => { void load(); refreshBadges(); }} /> : null}
      <div className="row">
        <label htmlFor="meeting-filter" style={{ margin: 0 }}>{m.show}</label>
        <select id="meeting-filter" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} style={{ width: 180 }}>
          {(["open", "accepted", "all"] as const).map((f) => <option key={f} value={f}>{m.filters[f]}</option>)}
        </select>
      </div>
      {rows === null ? <p className="muted">{t.app.loading}</p> : rows.length === 0 ? <p className="muted">{m.empty}</p> : (
        rows.map((row) => (
          <RequestCard key={`${row.id}-${row.status}-${row.proposed_times.join()}`} request={row}
                       onChanged={(text, ok) => { setNotice({ ok, text }); void load(); refreshBadges(); }} />
        ))
      )}
    </div>
  );
}
