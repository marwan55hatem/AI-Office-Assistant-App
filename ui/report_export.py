"""CSV and PDF export of the Reports page.

``bundle`` is what the page loaded::

    {"scope": "Whole team" | "<employee name>", "generated": "2026-11-06 14:30",
     "overview": {...} | None,        # whole-team report (GET /reports/overview)
     "employee": {...} | None,        # one employee's report (GET /reports/employee/{id})
     "trends": {...},                 # GET /reports/trends
     "ranking": [rows...]}            # every employee row (all pages), whole-team only

The CSV has plain sections that open in Excel (UTF-8 with a byte-order mark, so Arabic
names survive). Names come from users, so a cell that starts with ``= + - @`` is
neutralised: a spreadsheet would otherwise run it as a formula.
"""
import csv

from ui.charts import hours_text

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

CATEGORY_NAMES = {"productive": "Productive", "neutral": "Neutral", "distraction": "Distracting", "idle": "Idle"}


def safe_cell(value):
    """Text cells that a spreadsheet could read as a formula get a leading apostrophe."""
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


def _report(bundle) -> dict:
    return bundle["employee"] or bundle["overview"]


def _summary_rows(report) -> list:
    totals, previous, change = report["totals"], report["previous"], report["change"]
    tasks, previous_tasks = report["tasks"], report["previous_tasks"]
    rows = [
        ("Focus %", totals["focus_pct"], previous["focus_pct"], change["focus_pct"], "points"),
        ("Distracted %", totals["distraction_pct"], previous["distraction_pct"], change["distraction_pct"], "points"),
        ("Away %", totals["away_pct"], previous["away_pct"], change["away_pct"], "points"),
        ("Hours worked", totals["hours_worked"], previous["hours_worked"], change["hours_worked_pct"], "percent"),
        ("Task completion %", tasks["completion_rate"], previous_tasks["completion_rate"],
         change["task_completion_rate"], "points"),
        ("Sessions", totals["sessions"], previous["sessions"], "", ""),
    ]
    if "attendance_rate" in report:
        rows.append(("Attendance %", report["attendance_rate"], "", "", ""))
    return rows


def write_csv(path: str, bundle: dict) -> None:
    report = _report(bundle)
    rng, before = report["range"], report["previous_range"]
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        out = csv.writer(handle)
        out.writerow(["Office Assistant report"])
        out.writerow(["Scope", safe_cell(bundle["scope"])])
        out.writerow(["From", rng["start"], "To", rng["end"], "Days", rng["days"]])
        out.writerow(["Compared with", before["start"], "to", before["end"]])
        out.writerow(["Generated", bundle["generated"]])
        out.writerow([])

        out.writerow(["Summary"])
        out.writerow(["Metric", "This period", "Previous period", "Change", "Change in"])
        for row in _summary_rows(report):
            out.writerow(row)
        out.writerow([])

        if bundle.get("ranking"):
            out.writerow(["Employees"])
            out.writerow(["Employee", "Focus %", "Distracted %", "Away %", "Hours worked", "Focus hours",
                          "Distracted hours", "Away hours", "Days present", "Sessions", "Tasks done", "Tasks total",
                          "Task completion %", "Focus vs team (points)"])
            for r in bundle["ranking"]:
                out.writerow([safe_cell(r["full_name"]), r["focus_pct"], r["distraction_pct"], r["away_pct"],
                              r["hours_worked"], round(r["focus_seconds"] / 3600, 2),
                              round(r["distraction_seconds"] / 3600, 2), round(r["away_seconds"] / 3600, 2),
                              r["days_present"], r["sessions"], r["tasks_done"], r["tasks_total"],
                              r["completion_rate"], "" if r["vs_team_pp"] is None else r["vs_team_pp"]])
            out.writerow([])

        points = (bundle.get("trends") or {}).get("points") or (bundle.get("employee") or {}).get("daily") or []
        if points:
            out.writerow(["Trend (" + (bundle["trends"]["bucket"] if bundle.get("trends") else "day") + ")"])
            out.writerow(["Start", "Focus %", "Distracted %", "Away %", "Hours worked", "Tracked hours", "Sessions"])
            for p in points:
                out.writerow([p["start"], p["focus_pct"], p["distraction_pct"], p["away_pct"], p["hours_worked"],
                              round(p["tracked_seconds"] / 3600, 2), p["sessions"]])
            out.writerow([])

        attendance = report.get("attendance") or []
        if attendance:
            out.writerow(["Attendance by day"])
            if "total" in attendance[0]:
                out.writerow(["Day", "Employees present", "Employees", "Attendance %"])
                for a in attendance:
                    out.writerow([a["day"], a["present"], a["total"], a["rate"]])
            else:
                out.writerow(["Day", "Present", "Tracked hours"])
                for a in attendance:
                    out.writerow([a["day"], "yes" if a["present"] else "no", round(a["tracked_seconds"] / 3600, 2)])
            out.writerow([])

        if report.get("apps"):
            out.writerow(["Most-used apps (while at the desk)"])
            out.writerow(["App", "Category", "Hours", "Share %"])
            for a in report["apps"]:
                out.writerow([safe_cell(a["name"]), CATEGORY_NAMES.get(a["category"], a["category"]),
                              round(a["seconds"] / 3600, 2), a["share"]])


# ---------------------------------------------------------------- PDF
def _arrow(value, good_when_up=True, suffix=" pts"):
    if value is None:
        return "no earlier data", "muted"
    if abs(value) < 0.05:
        return "no change", "muted"
    up = value > 0
    good = up == good_when_up
    return f"{'▲' if up else '▼'} {abs(value):g}{suffix}", "good" if good else "bad"


def kpi_cards(bundle) -> list:
    """``[(title, value, delta text, tone)]`` for the six figures at the top of the page and the PDF."""
    report = _report(bundle)
    totals, change, tasks = report["totals"], report["change"], report["tasks"]
    cards = [
        ("Focus", f"{totals['focus_pct']:g}%", *_arrow(change["focus_pct"], True)),
        ("Distracted", f"{totals['distraction_pct']:g}%", *_arrow(change["distraction_pct"], False)),
        ("Away", f"{totals['away_pct']:g}%", *_arrow(change["away_pct"], False)),
        ("Hours worked", hours_text(totals["hours_worked"]), *_arrow(change["hours_worked_pct"], True, "%")),
        ("Task completion", f"{tasks['completion_rate']:g}%", *_arrow(change["task_completion_rate"], True)),
    ]
    if "attendance_rate" in report:
        cards.append(("Attendance", f"{report['attendance_rate']:g}%", f"{report['employees_total']} employees", "muted"))
    else:
        cards.append(("Days present", str(report["days_present"]), f"of {report['range']['days']} days", "muted"))
    return cards


def chart_image(chart, width=760, height=340, scale=2):
    """The chart painted with print colours at ``scale`` x for a sharp PDF."""
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QImage, QPainter

    from ui.charts import PRINT_COLORS

    image = QImage(width * scale, height * scale, QImage.Format_ARGB32)
    image.fill(QColor(PRINT_COLORS.background))
    painter = QPainter(image)
    painter.scale(scale, scale)
    chart.paint_to(painter, QRectF(0, 0, width, height), PRINT_COLORS)
    painter.end()
    return image


def write_pdf(path: str, bundle: dict, charts: dict) -> int:
    """Write an A4 report; returns the number of pages. ``charts`` holds the page's chart widgets."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QColor, QFont, QPageSize, QPainter, QPdfWriter

    report = _report(bundle)
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(150)
    writer.setTitle("Office Assistant report")
    painter = QPainter(writer)
    width, height = writer.width(), writer.height()
    margin = 90
    inner = width - 2 * margin
    state = {"y": margin, "page": 1}
    ink, muted, line = QColor("#111827"), QColor("#6B7280"), QColor("#E5E7EB")
    tones = {"good": QColor("#15803D"), "bad": QColor("#B91C1C"), "muted": muted}

    def font(points, bold=False):
        f = QFont("Segoe UI", int(points))
        f.setBold(bold)
        painter.setFont(f)

    def footer():
        font(8)
        painter.setPen(muted)
        painter.drawText(QRectF(margin, height - margin + 10, inner, 30), Qt.AlignLeft | Qt.AlignVCenter,
                         "Office Assistant · " + bundle["generated"])
        painter.drawText(QRectF(margin, height - margin + 10, inner, 30), Qt.AlignRight | Qt.AlignVCenter,
                         f"Page {state['page']}")

    def need(space):
        if state["y"] + space > height - margin:
            footer()
            writer.newPage()
            state["page"] += 1
            state["y"] = margin

    def heading(text, size=13):
        need(70)
        font(size, True)
        painter.setPen(ink)
        painter.drawText(QRectF(margin, state["y"], inner, 50), Qt.AlignLeft | Qt.AlignVCenter, text)
        state["y"] += 60

    # title block
    font(22, True)
    painter.setPen(ink)
    title = "Team report" if bundle["overview"] else f"Employee report: {bundle['scope']}"
    painter.drawText(QRectF(margin, state["y"], inner, 70), Qt.AlignLeft | Qt.AlignVCenter, title)
    state["y"] += 75
    font(10)
    painter.setPen(muted)
    rng, before = report["range"], report["previous_range"]
    painter.drawText(QRectF(margin, state["y"], inner, 34), Qt.AlignLeft | Qt.AlignVCenter,
                     f"{rng['start']} to {rng['end']} ({rng['days']} days) · compared with {before['start']} to {before['end']}")
    state["y"] += 70

    # figures
    gap = 24
    box_w = (inner - 2 * gap) / 3
    box_h = 150
    for i, (name, value, delta, tone) in enumerate(kpi_cards(bundle)):
        if i % 3 == 0 and i:
            state["y"] += box_h + gap
        x = margin + (i % 3) * (box_w + gap)
        painter.setPen(line)
        painter.setBrush(QColor("#F9FAFB"))
        painter.drawRoundedRect(QRectF(x, state["y"], box_w, box_h), 10, 10)
        font(9)
        painter.setPen(muted)
        painter.drawText(QRectF(x + 20, state["y"] + 12, box_w - 40, 34), Qt.AlignLeft | Qt.AlignVCenter, name)
        font(20, True)
        painter.setPen(ink)
        painter.drawText(QRectF(x + 20, state["y"] + 46, box_w - 40, 60), Qt.AlignLeft | Qt.AlignVCenter, value)
        font(9)
        painter.setPen(tones[tone])
        painter.drawText(QRectF(x + 20, state["y"] + 106, box_w - 40, 34), Qt.AlignLeft | Qt.AlignVCenter, delta)
    state["y"] += box_h + 50

    # charts
    for key, caption, chart_height in (("trend", "Focus over time", 340), ("hours", "Hours per period", 340),
                                       ("apps", "Most-used apps", 300), ("ranking", "Focus by employee", None)):
        chart = charts.get(key)
        if chart is None or not chart.has_data():
            continue
        logical_h = chart_height or max(120, chart.minimumHeight())
        draw_h = inner * logical_h / 760
        need(60 + draw_h)
        heading(caption)
        painter.drawImage(QRectF(margin, state["y"], inner, draw_h), chart_image(chart, 760, int(logical_h)))
        state["y"] += draw_h + 40

    # employee table
    rows = bundle.get("ranking") or []
    if rows:
        columns = [("Employee", 0.27), ("Focus", 0.1), ("Distr.", 0.1), ("Away", 0.1), ("Hours", 0.1), ("Days", 0.08),
                   ("Tasks", 0.12), ("vs team", 0.13)]
        heading("Employees")

        def table_header():
            font(9, True)
            painter.setPen(muted)
            x = margin
            for name, share in columns:
                align = Qt.AlignLeft if name == "Employee" else Qt.AlignRight
                painter.drawText(QRectF(x, state["y"], inner * share - 10, 36), align | Qt.AlignVCenter, name)
                x += inner * share
            state["y"] += 40
            painter.setPen(line)
            painter.drawLine(QPointF(margin, state["y"] - 4), QPointF(margin + inner, state["y"] - 4))

        table_header()
        for r in rows:
            if state["y"] + 40 > height - margin:
                footer()
                writer.newPage()
                state["page"] += 1
                state["y"] = margin
                table_header()
            cells = [r["full_name"], f"{r['focus_pct']:g}%", f"{r['distraction_pct']:g}%", f"{r['away_pct']:g}%",
                     hours_text(r["hours_worked"]), str(r["days_present"]), f"{r['tasks_done']}/{r['tasks_total']}",
                     "—" if r["vs_team_pp"] is None else f"{r['vs_team_pp']:+g} pts"]
            font(9)
            painter.setPen(ink)
            x = margin
            for (name, share), cell in zip(columns, cells):
                align = Qt.AlignLeft if name == "Employee" else Qt.AlignRight
                text = painter.fontMetrics().elidedText(cell, Qt.ElideRight, int(inner * share - 14))
                painter.drawText(QRectF(x, state["y"], inner * share - 10, 36), align | Qt.AlignVCenter, text)
                x += inner * share
            state["y"] += 38
    # definitions
    need(260)
    state["y"] += 20
    heading("How the numbers are calculated", 11)
    font(8)
    painter.setPen(muted)
    notes = ("Focus, distracted and away % are shares of the tracked time. Hours worked = focus + distracted time "
             "(time at the desk). Changes compare with the previous period of the same length (percentage points; "
             "hours in percent). Task completion = share of tasks created in the period that are done. Apps count "
             "only the time at the desk and show program names, never window titles.")
    painter.drawText(QRectF(margin, state["y"], inner, 200), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, notes)
    footer()
    painter.end()
    return state["page"]
