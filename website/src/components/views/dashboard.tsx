"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useApp } from "@/components/app-shell";
import { Donut, LineChart, StackedBars } from "@/components/charts";
import { api } from "@/lib/client";
import { fill, type Dict } from "@/lib/i18n";

/* eslint-disable @typescript-eslint/no-explicit-any -- report payloads are large, read-only JSON */
type Report = any;

const PAGE = 10;

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function periodRange(period: string, today = new Date()): [string, string] {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (period === "30d") return [iso(new Date(end.getTime() - 29 * 864e5)), iso(end)];
  if (period === "month") return [iso(new Date(end.getFullYear(), end.getMonth(), 1)), iso(end)];
  return [iso(new Date(end.getTime() - 6 * 864e5)), iso(end)];
}

export function hoursText(hours: number) {
  const minutes = Math.round(hours * 60);
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

function dayLabel(value: string, lang: string) {
  const [y, mo, d] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-u-nu-latn" : "en", { day: "numeric", month: "short" })
    .format(new Date(y, mo - 1, d));
}

function delta(t: Dict, value: number | null, goodWhenUp: boolean, unit: string): [string, string] {
  if (value === null || value === undefined) return [t.dashboard.noEarlier, "tone-muted"];
  if (Math.abs(value) < 0.05) return [t.dashboard.noChange, "tone-muted"];
  const up = value > 0;
  return [`${up ? "▲" : "▼"} ${Math.abs(value)}${unit}`, up === goodWhenUp ? "tone-good" : "tone-bad"];
}

function csvCell(value: unknown) {
  const text = String(value ?? "");
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;   // never a spreadsheet formula
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** One view of the report: an employee's, or the team's overview with its daily trend. */
async function fetchReport(range: [string, string], employee: string, offset: number, sort: string) {
  const [start, end] = range;
  const today = iso(new Date());
  if (employee) {
    const result = await api<Report>(`reports/employee/${employee}?start=${start}&end=${end}&today=${today}`);
    return result.ok ? { report: result.data, trends: null } : null;
  }
  const [overview, trend] = await Promise.all([
    api<Report>(`reports/overview?start=${start}&end=${end}&today=${today}&limit=${PAGE}&offset=${offset}&sort=${sort}`),
    api<Report>(`reports/trends?start=${start}&end=${end}&bucket=day`),
  ]);
  return overview.ok && trend.ok ? { report: overview.data, trends: trend.data } : null;
}

export function DashboardView() {
  const { t, lang } = useApp();
  const d = t.dashboard;
  const [period, setPeriod] = useState("7d");
  const [employee, setEmployee] = useState("");
  const [sort, setSort] = useState("focus_pct");
  const [offset, setOffset] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const [trends, setTrends] = useState<Report | null>(null);
  const [people, setPeople] = useState<{ id: string; full_name: string }[]>([]);
  const [error, setError] = useState(false);
  const range = useMemo(() => periodRange(period), [period]);

  const latest = useRef(0);       // a slower answer for older filters must not replace a newer one
  const load = useCallback(() => {
    const ticket = ++latest.current;
    return fetchReport(range, employee, offset, sort).then((result) => {
    if (ticket !== latest.current) return;
    setError(result === null);
    if (result === null) return;
    setReport({ ...result.report, __employee: employee });
    setTrends(result.trends);
    });
  }, [range, employee, offset, sort]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    void api<{ id: string; full_name: string; status: string }[]>("users?role=employee").then((r) => {
      if (r.ok) setPeople(r.data.filter((u) => u.status === "active"));
    });
  }, []);

  async function exportCsv() {
    if (!report) return;
    const rows: unknown[][] = [["Office Assistant report"], ["From", range[0], "To", range[1]], []];
    rows.push(["Metric", "This period", "Previous period", "Change"]);
    for (const [label, key] of [["Focus %", "focus_pct"], ["Distracted %", "distraction_pct"], ["Away %", "away_pct"], ["Hours worked", "hours_worked"]]) {
      rows.push([label, report.totals[key], report.previous[key], report.change[key === "hours_worked" ? "hours_worked_pct" : key] ?? ""]);
    }
    if (!employee) {
      const all: Report[] = [];
      for (let start = 0; ; start += 200) {
        const page = await api<Report>(`reports/overview?start=${range[0]}&end=${range[1]}&limit=200&offset=${start}&sort=${sort}`);
        if (!page.ok) break;
        all.push(...page.data.ranking.items);
        if (start + 200 >= page.data.ranking.total) break;
      }
      rows.push([], ["Employee", "Focus %", "Distracted %", "Away %", "Hours worked", "Days present", "Tasks done", "Tasks total"]);
      for (const r of all) rows.push([r.full_name, r.focus_pct, r.distraction_pct, r.away_pct, r.hours_worked, r.days_present, r.tasks_done, r.tasks_total]);
    }
    const blob = new Blob(["﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `report-${range[0]}-${range[1]}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // released later: revoking at once can cancel the download before the browser has read it
    window.setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
  }

  const kpis = useMemo(() => {
    if (!report) return [];
    const c = report.change, tot = report.totals;
    const cards: [string, string, string, string][] = [
      [d.kpi.focus, `${tot.focus_pct}%`, ...delta(t, c.focus_pct, true, ` ${d.points}`)],
      [d.kpi.distracted, `${tot.distraction_pct}%`, ...delta(t, c.distraction_pct, false, ` ${d.points}`)],
      [d.kpi.away, `${tot.away_pct}%`, ...delta(t, c.away_pct, false, ` ${d.points}`)],
      [d.kpi.hours, hoursText(tot.hours_worked), ...delta(t, c.hours_worked_pct, true, "%")],
      [d.kpi.tasks, `${report.tasks.completion_rate}%`, ...delta(t, c.task_completion_rate, true, ` ${d.points}`)],
      report.attendance_rate !== undefined
        ? [d.kpi.attendance, `${report.attendance_rate}%`, `${report.employees_total} ${d.employees}`, "tone-muted"]
        : [d.kpi.days, String(report.days_present), fill(d.ofDays, { n: report.range.days }), "tone-muted"],
    ];
    return cards;
  }, [report, t, d]);

  // draw what was loaded: while a new view loads, the previous report stays on screen as it was
  const shown: string = report?.__employee ?? "";
  const points: Report[] = shown ? report?.daily ?? [] : trends?.points ?? [];
  const labels = points.map((p) => dayLabel(p.start, lang));
  const focusLine = points.map((p) => (p.tracked_seconds ? p.focus_pct : null));
  const hasWork = points.some((p) => p.tracked_seconds);

  return (
    <div>
      <h1>{d.title}</h1>
      <p className="lead">{d.lead}</p>
      <div className="toolbar">
        <div className="field">
          <label htmlFor="period">{d.period}</label>
          <select id="period" value={period} onChange={(e) => { setPeriod(e.target.value); setOffset(0); }}>
            {Object.entries(d.periods).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="employee">{d.employee}</label>
          <select id="employee" value={employee} onChange={(e) => setEmployee(e.target.value)}>
            <option value="">{d.wholeTeam}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </select>
        </div>
        <span className="spacer" />
        <button className="btn" onClick={() => void exportCsv()} disabled={!report}>{d.exportCsv}</button>
      </div>

      {error ? <p className="error" role="alert">{t.app.error} <button className="btn btn-small" onClick={() => void load()}>{t.app.retry}</button></p> : null}
      {!report && !error ? <p className="muted" aria-busy="true">{t.app.loading}</p> : null}

      {report ? (
        <>
          <div className="kpis" data-testid="kpis">
            {kpis.map(([label, value, deltaText, tone]) => (
              <div key={label} className="card kpi">
                <div className="label">{label}</div>
                <div className="value">{value}</div>
                <div className={`delta ${tone}`}>{deltaText}</div>
              </div>
            ))}
          </div>

          <section className="card" style={{ marginBottom: 18 }} aria-labelledby="trend">
            <h2 id="trend">{d.trend}</h2>
            <p className="hint">{d.trendHint}</p>
            {hasWork ? (
              <>
                <div className="legend">
                  <span style={{ ["--dot" as string]: "var(--accent)" }}>{shown ? report.user.full_name : d.kpi.focus}</span>
                  {shown ? <span style={{ ["--dot" as string]: "var(--muted)" }}>{d.teamAverage}</span> : null}
                </div>
                <LineChart labels={labels} summary={`${d.trend}: ${focusLine.filter((v) => v !== null).join("%, ")}%`}
                  series={[{ name: "focus", color: "var(--accent)", values: focusLine },
                    ...(shown ? [{ name: "team", color: "var(--muted)", dashed: true,
                      values: points.map((p: Report) => p.team_focus_pct || null) }] : [])]} />
              </>
            ) : <p className="muted">{d.empty}</p>}
          </section>

          <div className="grid grid-2" style={{ marginBottom: 18 }}>
            <section className="card" aria-labelledby="hours">
              <h2 id="hours">{d.hours}</h2>
              <div className="legend">
                <span style={{ ["--dot" as string]: "var(--chart-focus)" }}>{d.focusLabel}</span>
                <span style={{ ["--dot" as string]: "var(--chart-distracted)" }}>{d.distractedLabel}</span>
                <span style={{ ["--dot" as string]: "var(--chart-away)" }}>{d.awayLabel}</span>
              </div>
              <StackedBars labels={labels} names={[d.focusLabel, d.distractedLabel, d.awayLabel]}
                colors={["var(--chart-focus)", "var(--chart-distracted)", "var(--chart-away)"]}
                rows={points.map((p: Report) => [p.focus_seconds / 3600, p.distraction_seconds / 3600, p.away_seconds / 3600])}
                summary={`${d.hours}: ${hoursText(report.totals.hours_worked)}`} width={400} />
            </section>
            <section className="card" aria-labelledby="apps">
              <h2 id="apps">{d.apps}</h2>
              <p className="hint">{d.appsHint}</p>
              {report.apps.length ? (
                <Donut summary={report.apps.map((a: Report) => `${a.name} ${a.share}%`).join(", ")}
                  center={hoursText(report.apps.reduce((s: number, a: Report) => s + a.seconds, 0) / 3600)}
                  slices={report.apps.map((a: Report) => ({ name: a.name, value: a.seconds, caption: `${a.share}% · ${hoursText(a.seconds / 3600)}` }))} />
              ) : <p className="muted">{d.noData}</p>}
            </section>
          </div>

          {!shown ? (
            <section className="card" aria-labelledby="ranking">
              <div className="toolbar" style={{ marginBottom: 8 }}>
                <h2 id="ranking" style={{ margin: 0 }}>{d.ranking}</h2>
                <span className="spacer" />
                <div className="field">
                  <label htmlFor="sort">{d.sortBy}</label>
                  <select id="sort" value={sort} onChange={(e) => { setSort(e.target.value); setOffset(0); }}>
                    {Object.entries(d.sorts).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
              </div>
              <div className="table-wrap">
                <table data-testid="ranking">
                  <thead>
                    <tr>
                      <th scope="col">{d.columns.name}</th>
                      <th scope="col" className="num">{d.columns.focus}</th>
                      <th scope="col" className="num">{d.columns.distracted}</th>
                      <th scope="col" className="num">{d.columns.away}</th>
                      <th scope="col" className="num">{d.columns.hours}</th>
                      <th scope="col" className="num">{d.columns.days}</th>
                      <th scope="col" className="num">{d.columns.tasks}</th>
                      <th scope="col" className="num">{d.columns.vsTeam}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.ranking.items.map((r: Report) => (
                      <tr key={r.id}>
                        <th scope="row" style={{ fontWeight: 600, color: "var(--text)" }}>
                          <button className="btn btn-small" style={{ border: 0, background: "transparent", padding: 0, minHeight: 0 }}
                                  onClick={() => setEmployee(r.id)}>{r.full_name}</button>
                        </th>
                        <td className="num">{r.focus_pct}%</td>
                        <td className="num">{r.distraction_pct}%</td>
                        <td className="num">{r.away_pct}%</td>
                        <td className="num">{hoursText(r.hours_worked)}</td>
                        <td className="num">{r.days_present}</td>
                        <td className="num">{r.tasks_done}/{r.tasks_total}</td>
                        <td className="num">{r.vs_team_pp === null ? "—" : `${r.vs_team_pp > 0 ? "+" : ""}${r.vs_team_pp} ${d.points}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <span className="muted" data-testid="page-label">
                  {fill(d.pageOf, { from: report.ranking.items.length ? offset + 1 : 0, to: offset + report.ranking.items.length, total: report.ranking.total })}
                </span>
                <span className="spacer" />
                <button className="btn btn-small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>{d.previous}</button>
                <button className="btn btn-small" disabled={offset + PAGE >= report.ranking.total} onClick={() => setOffset(offset + PAGE)}>{d.next}</button>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
