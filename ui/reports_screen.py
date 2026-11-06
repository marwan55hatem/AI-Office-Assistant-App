"""Manager reports with charts: the page behind "Reports" in the manager's sidebar.

The numbers come from the server (``db.reports``, see ``cloud/reports_api.py``): KPI cards with the
change against the previous period, focus over time, hours per day/week, a ranking, the most-used
apps, attendance, and a paginated employee table. Pick a period, pick one employee to compare
them with the team, and export the view as CSV or PDF.

Server calls run on worker threads (``ReportLoader``, ``RankingFetcher``); the page only
draws. A result that arrives after the filters changed again is ignored.
"""
import logging
from datetime import date, datetime, timedelta

from PyQt5.QtCore import QDate, QEvent, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from cloud.api import ApiError, Offline, SessionExpired
from ui import report_export, theme
from ui.charts import DonutChart, HBarChart, LineChart, StackedBarChart, hours_text
from ui.widgets import make_card

logger = logging.getLogger(__name__)

PERIODS = [("Last 7 days", "7d"), ("Last 30 days", "30d"), ("This month", "month"), ("Last month", "lastmonth"),
           ("Custom range", "custom")]
SORTS = [("Best focus", "focus_pct"), ("Most hours", "hours"), ("Most distracted", "distraction_pct"),
         ("Task completion", "tasks"), ("Name", "name")]
PAGE_SIZE = 10
TONE_COLORS = {"good": "SUCCESS", "bad": "DANGER", "muted": "TEXT_MUTED"}
OFFLINE_TEXT = "No connection to the server. Reports need a connection: they are calculated online."


def period_range(key: str, today: date, custom=None):
    """``(start, end)`` for a period key (inclusive local dates)."""
    if key == "30d":
        return today - timedelta(days=29), today
    if key == "month":
        return today.replace(day=1), today
    if key == "lastmonth":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if key == "custom" and custom:
        return custom
    return today - timedelta(days=6), today


def point_label(day) -> str:
    moment = date.fromisoformat(str(day)) if not isinstance(day, date) else day
    return f"{moment:%b} {moment.day}"


class ReportLoader(QThread):
    """Loads one view of the report (never touches a widget)."""

    loaded = pyqtSignal(int, dict)
    failed = pyqtSignal(int, str)

    def __init__(self, reports, generation, params, list_employees, parent=None):
        super().__init__(parent)
        self.reports, self.generation, self.params, self.list_employees = reports, generation, params, list_employees

    def run(self):
        p = self.params
        try:
            employees = self.list_employees()
            if p["employee_id"]:
                payload = {"employee": self.reports.employee(p["employee_id"], p["start"], p["end"], p["today"]),
                           "overview": None, "trends": None}
            else:
                days = (p["end"] - p["start"]).days + 1
                payload = {"overview": self.reports.overview(p["start"], p["end"], p["today"], p["limit"], p["offset"],
                                                             p["sort"]),
                           "trends": self.reports.trends(p["start"], p["end"], "day" if days <= 31 else "week"),
                           "employee": None}
            payload["employees"] = employees
            self.loaded.emit(self.generation, payload)
        except Offline:
            self.failed.emit(self.generation, OFFLINE_TEXT)
        except SessionExpired:
            self.failed.emit(self.generation, "Your sign-in has ended. Please sign in again.")
        except ApiError as error:
            self.failed.emit(self.generation, str(error))
        except Exception as error:                                   # never let a thread die silently
            logger.warning("report loading failed", exc_info=True)
            self.failed.emit(self.generation, f"Could not load the report: {error}")


class RankingFetcher(QThread):
    """Fetches every employee row (all pages) for an export."""

    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, reports, params, parent=None):
        super().__init__(parent)
        self.reports, self.params = reports, params

    def run(self):
        p = self.params
        try:
            self.done.emit(self.reports.whole_ranking(p["start"], p["end"], p["today"], p["sort"]))
        except Offline:
            self.failed.emit(OFFLINE_TEXT)
        except (ApiError, SessionExpired) as error:
            self.failed.emit(str(error))
        except Exception as error:
            logger.warning("ranking fetch failed", exc_info=True)
            self.failed.emit(str(error))


class KpiCard(QFrame):
    """One figure with its change against the previous period."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(132)
        theme.apply_card_shadow(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_3)
        layout.setSpacing(theme.SP_1)
        self.title = QLabel(title)
        self.title.setObjectName("MutedLabel")
        self.value = QLabel("—")
        self.value.setObjectName("StatNumber")
        self.delta = QLabel("")
        self.delta.setWordWrap(True)
        self._tone = "muted"

        for widget in (self.title, self.value, self.delta):
            layout.addWidget(widget)
        layout.addStretch(1)

    def set_content(self, title, value, delta, tone):
        self.title.setText(title)
        self.value.setText(value)
        self.delta.setText(delta)
        self._tone = tone
        self._apply_tone()

    def _apply_tone(self):
        """The change arrow's colour comes from the current theme, so it is re-applied on a theme switch."""
        color = getattr(theme, TONE_COLORS.get(self._tone, "TEXT_MUTED"))
        self.delta.setStyleSheet(f"color: {color}; font-weight: 600;")

    def changeEvent(self, event):
        if event.type() in (QEvent.StyleChange, QEvent.PaletteChange):
            self._apply_tone()
        super().changeEvent(event)


class ReportsScreen(QWidget):
    """The Reports page."""

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": None, "full_name": "Manager"}
        self.db = db
        self.reports = getattr(db, "reports", None)
        self._generation = 0
        self._loader = None
        self._fetcher = None
        self._bundle = None
        self._offset = 0
        self._employees = []
        self._building = False
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_5)

        title = QLabel("Reports")
        title.setObjectName("H1")
        subtitle = QLabel("How the team spends its time: focus, distraction and attendance, compared with the previous period.")
        subtitle.setObjectName("LeadLabel")
        subtitle.setWordWrap(True)
        body.addWidget(title)
        body.addWidget(subtitle)
        body.addLayout(self._build_filters())

        self.notice = QLabel("")
        self.notice.setObjectName("MutedLabel")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        body.addWidget(self.notice)

        self.kpi_grid = QGridLayout()
        self.kpi_grid.setHorizontalSpacing(theme.SP_4)
        self.kpi_grid.setVerticalSpacing(theme.SP_4)
        self.kpi_cards = [KpiCard(name) for name in ("Focus", "Distracted", "Away", "Hours worked", "Task completion",
                                                      "Attendance")]
        for index, card in enumerate(self.kpi_cards):
            self.kpi_grid.addWidget(card, index // 3, index % 3)
            self.kpi_grid.setColumnStretch(index % 3, 1)
        body.addLayout(self.kpi_grid)

        self.trend_chart = LineChart()
        self.hours_chart = StackedBarChart()
        self.ranking_chart = HBarChart()
        self.apps_chart = DonutChart()
        self.attendance_chart = StackedBarChart()
        self.trend_card, trend_layout = make_card("Focus over time", "Share of tracked time spent in focus. Days without "
                                                  "any recorded work are left blank.")
        trend_layout.addWidget(self.trend_chart)
        self.hours_card, hours_layout = make_card("Hours per period", "Focus, distracted and away time.")
        hours_layout.addWidget(self.hours_chart)
        self.ranking_card, ranking_layout = make_card("Focus by employee")
        self.ranking_title = self.ranking_card.findChild(QLabel, "H3")
        ranking_layout.addWidget(self.ranking_chart)
        ranking_layout.addStretch(1)                     # titles stay at the top of side-by-side cards
        self.apps_card, apps_layout = make_card("Most-used apps", "Time at the desk. Only program names are recorded, "
                                                "never window titles.")
        apps_layout.addWidget(self.apps_chart)
        apps_layout.addStretch(1)
        self.attendance_card, attendance_layout = make_card("Attendance by day", "Employees who recorded a work session.")
        attendance_layout.addWidget(self.attendance_chart)

        body.addWidget(self.trend_card)
        body.addWidget(self.hours_card)
        pair = QHBoxLayout()
        pair.setSpacing(theme.SP_4)
        pair.addWidget(self.ranking_card, 1)
        pair.addWidget(self.apps_card, 1)
        body.addLayout(pair)
        body.addWidget(self.attendance_card)
        body.addWidget(self._build_table_card())

        self.explain = QLabel(
            "How the numbers are calculated: focus, distracted and away % are shares of the tracked time. Hours worked = "
            "focus + distracted time (time at the desk). Changes compare with the previous period of the same length "
            "(percentage points; hours in percent). Task completion = tasks created in the period that are done.")
        self.explain.setObjectName("MutedLabel")
        self.explain.setWordWrap(True)
        body.addWidget(self.explain)
        body.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self._set_available(self.reports is not None)

    def _build_filters(self):
        row = QHBoxLayout()
        row.setSpacing(theme.SP_3)
        self.period_combo = QComboBox()
        for label, key in PERIODS:
            self.period_combo.addItem(label, key)
        self.from_edit, self.to_edit = QDateEdit(QDate.currentDate().addDays(-6)), QDateEdit(QDate.currentDate())
        for edit in (self.from_edit, self.to_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setVisible(False)
            edit.dateChanged.connect(self._filters_changed)
        self.employee_combo = QComboBox()
        self.employee_combo.setMinimumWidth(190)
        self.employee_combo.addItem("Whole team", None)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("GhostButton")
        self.csv_button = QPushButton("Export CSV")
        self.csv_button.setObjectName("GhostButton")
        self.pdf_button = QPushButton("Export PDF")
        self.pdf_button.setObjectName("PrimaryButton")
        for caption, widget in (("Period", self.period_combo), ("", self.from_edit), ("", self.to_edit),
                                ("Employee", self.employee_combo)):
            if caption:
                label = QLabel(caption)
                label.setObjectName("MutedLabel")
                row.addWidget(label)
            row.addWidget(widget)
        row.addStretch(1)
        for button in (self.refresh_button, self.csv_button, self.pdf_button):
            button.setCursor(Qt.PointingHandCursor)
            row.addWidget(button)
        self.period_combo.currentIndexChanged.connect(self._period_changed)
        self.employee_combo.currentIndexChanged.connect(self._filters_changed)
        self.refresh_button.clicked.connect(self.refresh)
        self.csv_button.clicked.connect(lambda: self._export("csv"))
        self.pdf_button.clicked.connect(lambda: self._export("pdf"))
        return row

    def _build_table_card(self):
        card, layout = make_card("Employees", "Double-click a row to compare that employee with the team.")
        self.table_card = card
        controls = QHBoxLayout()
        self.sort_combo = QComboBox()
        for label, key in SORTS:
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(self._sort_changed)
        self.page_label = QLabel("")
        self.page_label.setObjectName("MutedLabel")
        self.prev_button, self.next_button = QPushButton("‹ Previous"), QPushButton("Next ›")
        for button in (self.prev_button, self.next_button):
            button.setObjectName("GhostButton")
            button.setCursor(Qt.PointingHandCursor)
        self.prev_button.clicked.connect(lambda: self._page(-1))
        self.next_button.clicked.connect(lambda: self._page(1))
        sort_label = QLabel("Sort by")
        sort_label.setObjectName("MutedLabel")
        for widget in (sort_label, self.sort_combo):
            controls.addWidget(widget)
        controls.addStretch(1)
        for widget in (self.page_label, self.prev_button, self.next_button):
            controls.addWidget(widget)
        layout.addLayout(controls)
        headers = ["Employee", "Focus", "Distracted", "Away", "Hours", "Days", "Tasks", "vs team"]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # the page scrolls, not the table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.cellDoubleClicked.connect(self._open_employee)
        layout.addWidget(self.table)
        return card

    def _set_available(self, available):
        """Without the online server (a local-file copy) the page only explains why it is empty."""
        for widget in (self.refresh_button, self.csv_button, self.pdf_button, self.period_combo, self.employee_combo):
            widget.setEnabled(available)
        if not available:
            self._show_notice("Reports are calculated by your company's server, so they are not available in this "
                              "single-computer copy of the app.")

    # ------------------------------------------------------------------ #
    #  Filters and loading
    # ------------------------------------------------------------------ #
    def _selected_range(self):
        key = self.period_combo.currentData()
        custom = None
        if key == "custom":
            start, end = self.from_edit.date().toPyDate(), self.to_edit.date().toPyDate()
            custom = (start, end) if start <= end else (end, start)
        return period_range(key, date.today(), custom)

    def _params(self):
        start, end = self._selected_range()
        return {"start": start, "end": end, "today": date.today(), "employee_id": self.employee_combo.currentData(),
                "limit": PAGE_SIZE, "offset": self._offset, "sort": self.sort_combo.currentData()}

    def _period_changed(self):
        custom = self.period_combo.currentData() == "custom"
        self.from_edit.setVisible(custom)
        self.to_edit.setVisible(custom)
        self._filters_changed()

    def _filters_changed(self, *_args):
        if self._building:
            return
        self._offset = 0
        self.refresh()

    def _sort_changed(self):
        if not self._building:
            self._offset = 0
            self.refresh()

    def _page(self, step):
        self._offset = max(0, self._offset + step * PAGE_SIZE)
        self.refresh()

    def refresh(self):
        """Load the report for the current filters (called when the page is opened)."""
        if self.reports is None:
            return
        self._generation += 1
        self._show_notice("Loading…")
        loader = ReportLoader(self.reports, self._generation, self._params(), self._list_employees, self)
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_failed)
        loader.finished.connect(loader.deleteLater)
        self._loader = loader
        loader.start()

    def _list_employees(self):
        try:
            return list(self.db.get_all_employees())
        except Exception:
            return []

    def _show_notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _on_failed(self, generation, message):
        if generation == self._generation:
            self._show_notice(message)

    def _on_loaded(self, generation, payload):
        if generation != self._generation:
            return                                   # the filters changed meanwhile
        self._show_notice("")
        self._fill_employees(payload.get("employees") or [])
        self._bundle = {"overview": payload["overview"], "employee": payload["employee"], "trends": payload["trends"],
                        "scope": self.employee_combo.currentText(), "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "ranking": []}
        self._render(self._bundle)

    def _fill_employees(self, employees):
        names = [(e["full_name"], e["id"]) for e in employees]
        if names == self._employees:
            return
        self._building = True
        keep = self.employee_combo.currentData()
        self.employee_combo.clear()
        self.employee_combo.addItem("Whole team", None)
        for name, user_id in names:
            self.employee_combo.addItem(name, user_id)
        index = self.employee_combo.findData(keep)
        self.employee_combo.setCurrentIndex(max(index, 0))
        self._employees = names
        self._building = False

    def _open_employee(self, row, _column):
        item = self.table.item(row, 0)
        index = self.employee_combo.findData(item.data(Qt.UserRole)) if item else -1
        if index >= 0:
            self.employee_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------ #
    #  Drawing
    # ------------------------------------------------------------------ #
    def _render(self, bundle):
        employee_mode = bundle["employee"] is not None
        report = bundle["employee"] or bundle["overview"]
        for card, (title, value, delta, tone) in zip(self.kpi_cards, report_export.kpi_cards(bundle)):
            card.set_content(title, value, delta, tone)
        self.table_card.setVisible(not employee_mode)
        self.attendance_card.setVisible(not employee_mode)
        if employee_mode:
            self._render_employee(report)
        else:
            self._render_team(report, bundle["trends"])
        slices = [(a["name"], a["seconds"], f"{a['share']:g}% · {hours_text(a['seconds'] / 3600)}") for a in report["apps"]]
        self.apps_chart.set_slices(slices, center=hours_text(sum(a["seconds"] for a in report["apps"]) / 3600) if slices else "")

    def _render_team(self, report, trends):
        points = trends["points"]
        labels = [point_label(p["start"]) for p in points]
        self.trend_chart.set_series(labels, [p["focus_pct"] if p["tracked_seconds"] else None for p in points],
                                    name="Team focus")
        self.hours_chart.set_rows(labels, [(p["focus_seconds"] / 3600, p["distraction_seconds"] / 3600,
                                            p["away_seconds"] / 3600) for p in points])
        page = report["ranking"]
        rows = page["items"]
        self.ranking_title.setText("Focus by employee")
        self.ranking_chart.set_rows([(r["full_name"], r["focus_pct"], f"{r['focus_pct']:g}%" if r["tracked_seconds"] else "no data")
                                     for r in rows])
        attendance = report["attendance"]
        self.attendance_chart.set_rows([point_label(a["day"]) for a in attendance],
                                       [(a["present"], max(a["total"] - a["present"], 0)) for a in attendance],
                                       names=("Present", "Absent"), keys=("focus", "away"), unit="")
        self._fill_table(rows, page)

    def _render_employee(self, report):
        daily = report["daily"]
        labels = [point_label(p["start"]) for p in daily]
        self.trend_chart.set_series(
            labels, [p["focus_pct"] if p["tracked_seconds"] else None for p in daily],
            compare=[p["team_focus_pct"] or None for p in daily], name=report["user"]["full_name"])
        self.hours_chart.set_rows(labels, [(p["focus_seconds"] / 3600, p["distraction_seconds"] / 3600,
                                            p["away_seconds"] / 3600) for p in daily])
        mine, team = report["totals"], report["team_average"]
        self.ranking_title.setText("Compared with the team")
        self.ranking_chart.set_rows([
            ("Focus", mine["focus_pct"], f"{mine['focus_pct']:g}% (team {team['focus_pct']:g}%)"),
            ("Distracted", mine["distraction_pct"], f"{mine['distraction_pct']:g}% (team {team['distraction_pct']:g}%)"),
            ("Away", mine["away_pct"], f"{mine['away_pct']:g}% (team {team['away_pct']:g}%)")])

    def _fill_table(self, rows, page):
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = [r["full_name"], f"{r['focus_pct']:g}%", f"{r['distraction_pct']:g}%", f"{r['away_pct']:g}%",
                     hours_text(r["hours_worked"]), str(r["days_present"]), f"{r['tasks_done']}/{r['tasks_total']}",
                     "—" if r["vs_team_pp"] is None else f"{r['vs_team_pp']:+g} pts"]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.UserRole, r["id"])
                if column:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.setFixedHeight(self.table.horizontalHeader().height() + theme.TABLE_ROW_HEIGHT * max(len(rows), 1) + 6)
        first = page["offset"] + 1 if rows else 0
        self.page_label.setText(f"{first}–{page['offset'] + len(rows)} of {page['total']}")
        self.prev_button.setEnabled(page["offset"] > 0)
        self.next_button.setEnabled(page["offset"] + PAGE_SIZE < page["total"])

    # ------------------------------------------------------------------ #
    #  Export
    # ------------------------------------------------------------------ #
    def _export(self, kind):
        if self._bundle is None or self.reports is None:
            return
        params = self._params()
        default = f"report-{params['start']}-{params['end']}.{kind}"
        title, pattern = ("Export CSV", "CSV file (*.csv)") if kind == "csv" else ("Export PDF", "PDF file (*.pdf)")
        path, _ = QFileDialog.getSaveFileName(self, title, default, pattern)
        if not path:
            return
        if self._bundle["employee"] is not None:                      # one employee: nothing more to fetch
            self._write(kind, path, [])
            return
        self._show_notice("Preparing the export…")
        fetcher = RankingFetcher(self.reports, params, self)
        fetcher.done.connect(lambda rows, k=kind, p=path: self._write(k, p, rows))
        fetcher.failed.connect(lambda message: self._show_notice("Export failed: " + message))
        fetcher.finished.connect(fetcher.deleteLater)
        self._fetcher = fetcher
        fetcher.start()

    def _write(self, kind, path, rows):
        bundle = dict(self._bundle, ranking=rows)
        try:
            if kind == "csv":
                report_export.write_csv(path, bundle)
            else:
                report_export.write_pdf(path, bundle, {
                    "trend": self.trend_chart, "hours": self.hours_chart, "apps": self.apps_chart,
                    "ranking": self.ranking_chart})
        except Exception as error:                  # a failed export must never take the window down
            logger.warning("export failed", exc_info=True)
            self._show_notice("")
            QMessageBox.warning(self, "Export", f"Could not create the file: {error}")
            return
        self._show_notice(f"Saved {path}")
