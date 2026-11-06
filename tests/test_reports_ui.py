"""Phase 4 desktop side: the charts, the CSV/PDF export and the Reports page (with a fake server)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRectF  # noqa: E402
from PyQt5.QtGui import QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from cloud.api import Offline  # noqa: E402
from cloud.reports_api import ReportsApi  # noqa: E402
from ui import report_export  # noqa: E402
from ui.charts import (DonutChart, HBarChart, LineChart, StackedBarChart, hours_text,  # noqa: E402
                       nice_ceiling)
from ui.reports_screen import PAGE_SIZE, ReportsScreen, period_range  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def paints(chart, qapp):
    chart.resize(600, 300)
    image = QImage(600, 300, QImage.Format_ARGB32)
    painter = QPainter(image)
    chart.paint_to(painter, QRectF(0, 0, 600, 300))
    painter.end()
    return image


# ---------------------------------------------------------------- charts
def test_nice_ceiling_and_hours_text():
    assert nice_ceiling(0) > 0 and nice_ceiling(7.3) >= 7.3 and nice_ceiling(98) >= 98
    assert hours_text(32.3667) == "32h 22m" and hours_text(0) == "0m"


def test_every_chart_paints_when_empty_and_filled(qapp):
    line, stack, bars, donut = LineChart(), StackedBarChart(), HBarChart(), DonutChart()
    for chart in (line, stack, bars, donut):
        assert not chart.has_data()
        paints(chart, qapp)                                          # the empty state must not raise
    line.set_series(["a", "b", "c"], [80.0, None, 60.0], compare=[70.0, 70.0, None])
    stack.set_rows(["a", "b"], [(5, 1, 0.5), (0, 0, 0)])
    bars.set_rows([("Anna", 80.0, "80%"), ("Ben", 0.0, "no data")])
    donut.set_slices([("Word", 3600, "60%"), ("Chrome", 2400, "40%")], center="1h")
    for chart in (line, stack, bars, donut):
        assert chart.has_data()
        paints(chart, qapp)


def test_a_line_with_only_gaps_has_no_data(qapp):
    line = LineChart()
    line.set_series(["a", "b"], [None, None])
    assert not line.has_data()
    paints(line, qapp)


# ---------------------------------------------------------------- export
def totals(focus=80.0, hours=10.0):
    return {"focus_pct": focus, "distraction_pct": 15.0, "away_pct": 5.0, "hours_worked": hours, "sessions": 4,
            "tracked_seconds": 40000, "focus_seconds": 28800, "distraction_seconds": 5400, "away_seconds": 1800}


def team_report(names=("Anna", "=cmd|' /C calc'!A0", "+SUM(1)")):
    items = [{"id": f"u{i}", "full_name": n, "focus_pct": 80.0 - i, "distraction_pct": 15.0, "away_pct": 5.0,
              "hours_worked": 8.0, "focus_seconds": 20000, "distraction_seconds": 4000, "away_seconds": 1000,
              "tracked_seconds": 25000, "days_present": 5, "sessions": 5, "tasks_done": 2, "tasks_total": 3,
              "completion_rate": 66.7, "vs_team_pp": None if i == 0 else 1.5} for i, n in enumerate(names)]
    return {"range": {"start": "2026-11-01", "end": "2026-11-07", "days": 7},
            "previous_range": {"start": "2026-10-25", "end": "2026-10-31", "days": 7},
            "totals": totals(), "previous": totals(78.0, 9.0),
            "change": {"focus_pct": 2.0, "distraction_pct": -1.0, "away_pct": None, "hours_worked_pct": 11.1,
                       "task_completion_rate": None},
            "tasks": {"completion_rate": 66.7, "done": 2, "total": 3},
            "previous_tasks": {"completion_rate": 0.0, "done": 0, "total": 0},
            "attendance_rate": 71.4, "employees_total": 3,
            "attendance": [{"day": "2026-11-02", "present": 2, "total": 3, "rate": 66.7}],
            "apps": [{"name": "=Evil", "category": "distraction", "seconds": 3600, "share": 100.0}],
            "ranking": {"items": items, "total": len(items), "offset": 0, "limit": PAGE_SIZE}}


def bundle_for(report, rows=None):
    return {"overview": report, "employee": None,
            "trends": {"bucket": "day", "points": [{"start": "2026-11-02", "focus_pct": 80.0, "distraction_pct": 15.0,
                                                    "away_pct": 5.0, "hours_worked": 8.0, "tracked_seconds": 28800,
                                                    "focus_seconds": 23000, "distraction_seconds": 4000,
                                                    "away_seconds": 1800, "sessions": 2}]},
            "scope": "Whole team", "generated": "2026-11-07 09:00", "ranking": rows or []}


def test_safe_cell_blocks_formulas():
    for bad in ("=1+1", "+1", "-1", "@x"):
        assert report_export.safe_cell(bad).startswith("'")
    assert report_export.safe_cell("Anna") == "Anna" and report_export.safe_cell(5) == 5


def test_csv_has_every_section_and_no_live_formulas(tmp_path):
    report = team_report()
    path = tmp_path / "r.csv"
    report_export.write_csv(str(path), bundle_for(report, report["ranking"]["items"]))
    text = path.read_text(encoding="utf-8-sig")
    for section in ("Summary", "Employees", "Trend (day)", "Attendance by day", "Most-used apps"):
        assert section in text
    assert "Anna" in text and "'=cmd" in text and "'+SUM" in text and "'=Evil" in text
    assert "\n=cmd" not in text and ",=cmd" not in text


def test_kpi_cards_say_when_there_is_nothing_to_compare():
    cards = {title: (delta, tone) for title, _v, delta, tone in report_export.kpi_cards(bundle_for(team_report()))}
    assert cards["Focus"] == ("▲ 2 pts", "good")
    assert cards["Distracted"] == ("▼ 1 pts", "good")                # less distraction is good
    assert cards["Away"] == ("no earlier data", "muted")
    assert cards["Task completion"] == ("no earlier data", "muted")


def test_pdf_is_a_real_document(tmp_path, qapp):
    page = ReportsScreen()
    page._render(bundle_for(team_report()) | {"ranking": []})
    path = tmp_path / "r.pdf"
    pages = report_export.write_pdf(str(path), bundle_for(team_report(), team_report()["ranking"]["items"]), {
        "trend": page.trend_chart, "hours": page.hours_chart, "apps": page.apps_chart})
    assert pages >= 1 and path.read_bytes().startswith(b"%PDF")


# ---------------------------------------------------------------- the page
class FakeReports:
    def __init__(self, employees=25, fail=None):
        self.names = [f"Emp {i:02d}" for i in range(employees)]
        self.fail, self.calls = fail, []

    def overview(self, start, end, today=None, limit=20, offset=0, sort="focus_pct"):
        self.calls.append(("overview", offset, sort))
        if self.fail:
            raise self.fail
        report = team_report(self.names[offset:offset + limit])
        report["ranking"].update(total=len(self.names), offset=offset, limit=limit)
        return report

    def trends(self, start, end, bucket="day", user_id=None):
        return bundle_for(team_report())["trends"]

    def employee(self, user_id, start, end, today=None):
        self.calls.append(("employee", user_id))
        report = team_report()
        daily = [{"start": "2026-11-02", "focus_pct": 83.0, "distraction_pct": 10.0, "away_pct": 7.0,
                  "tracked_seconds": 3600, "focus_seconds": 3000, "distraction_seconds": 400, "away_seconds": 200,
                  "hours_worked": 1.0, "sessions": 1, "team_focus_pct": 72.0}]
        report.update(user={"id": user_id, "full_name": "Emp 00"}, daily=daily, team_average=totals(72.0),
                      attendance=[{"day": "2026-11-02", "present": True, "tracked_seconds": 3600}])
        return report


class FakeDb:
    def __init__(self, reports):
        self.reports = reports

    def get_all_employees(self):
        return [{"id": f"u{i}", "full_name": n} for i, n in enumerate(self.reports.names)]


def wait(qapp, condition, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def open_page(qapp, **kwargs):
    fake = FakeReports(**kwargs)
    page = ReportsScreen(db=FakeDb(fake))
    page.refresh()
    return page, fake


def test_the_page_fills_kpis_charts_and_the_first_page_of_employees(qapp):
    page, _fake = open_page(qapp)
    assert wait(qapp, lambda: page.kpi_cards[0].value.text() != "—")
    assert page.table.rowCount() == PAGE_SIZE and "of 25" in page.page_label.text()
    assert not page.prev_button.isEnabled() and page.next_button.isEnabled()
    assert page.trend_chart.has_data() and page.apps_chart.has_data()


def test_paging_and_sorting_ask_the_server(qapp):
    page, fake = open_page(qapp)
    assert wait(qapp, lambda: page.table.rowCount() == PAGE_SIZE)
    page.next_button.click()
    assert wait(qapp, lambda: ("overview", PAGE_SIZE, "focus_pct") in fake.calls and page.prev_button.isEnabled())
    page.sort_combo.setCurrentIndex(page.sort_combo.findData("name"))
    assert wait(qapp, lambda: ("overview", 0, "name") in fake.calls)       # sorting starts again from page one


def test_drilling_into_one_employee_compares_with_the_team(qapp):
    page, _fake = open_page(qapp)
    assert wait(qapp, lambda: page.table.rowCount() == PAGE_SIZE)
    page.table.cellDoubleClicked.emit(0, 0)
    assert wait(qapp, lambda: page.ranking_title.text() == "Compared with the team")
    assert page.table_card.isHidden() and page.trend_chart.compare is not None


def test_an_offline_server_shows_a_message_not_a_crash(qapp):
    page, _fake = open_page(qapp, fail=Offline("down"))
    assert wait(qapp, lambda: "No connection" in page.notice.text())


def test_a_page_without_a_server_does_nothing(qapp):
    page = ReportsScreen()
    page.refresh()                                                   # no reports client: stays idle
    assert page.table.rowCount() == 0


def test_period_ranges():
    from datetime import date
    today = date(2026, 11, 6)
    assert period_range("7d", today) == (date(2026, 10, 31), today)
    assert period_range("30d", today)[0] == date(2026, 10, 8)


def test_reports_api_builds_the_requests():
    seen = []

    class Api:
        def get(self, path, **params):
            seen.append((path, params))
            return {"ranking": {"items": [{"id": 1}], "total": 1}}

    from datetime import date
    api = ReportsApi(Api())
    api.employee("u1", date(2026, 11, 1), date(2026, 11, 7))
    api.trends(date(2026, 11, 1), date(2026, 11, 7), "week")
    assert seen[0][0] == "/reports/employee/u1" and seen[0][1]["start"] == "2026-11-01"
    assert seen[1][1]["bucket"] == "week"
    assert api.whole_ranking(date(2026, 11, 1), date(2026, 11, 7)) == [{"id": 1}]
