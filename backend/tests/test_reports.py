"""Phase 4: report metrics with seeded data, permissions, pagination, caching and app usage.

The scenario (all days are the employees' local days; TODAY = the test's today):

  employees  Anna, Ben, Cleo (active) -- Dana (pending) and Eve (disabled) must never count
  range      the last 7 days  [TODAY-6 .. TODAY];  the previous range is [TODAY-13 .. TODAY-7]

  Anna  TODAY    focus 3600  distraction 600   away 300     apps Code 3000 / Chrome 900 / YouTube 600
        TODAY-1  focus 7200
        TODAY-8  focus 1800  distraction 1800                (previous range) app Old 999
  Ben   TODAY    focus 1800  distraction 1800                apps Chrome 1200
  Cleo  nothing in the range
  Eve   TODAY    focus 99999                                 (disabled: excluded)

  tasks  Anna: a1 (done), a2 (open, deadline yesterday)   Ben: b1 (done)
         Cleo: old (created 10 days ago, open)            (previous range)
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.services import report_cache as cache_module
from app.services.report_cache import ReportCache, report_cache
from tests.conftest import add_active_employee, auth, register

TODAY = date.today()
RANGE = {"start": str(TODAY - timedelta(days=6)), "end": str(TODAY), "today": str(TODAY)}


def _sync(client, who, day, focus=0, distraction=0, away=0, apps=(), session_id=None):
    session = {"id": str(session_id or uuid.uuid4()), "local_date": str(day), "started_at": datetime.now(UTC).isoformat(),
               "focus_seconds": focus, "distraction_seconds": distraction, "away_seconds": away,
               "apps": [{"name": n, "category": c, "seconds": s} for n, c, s in apps]}
    response = client.post("/sessions/sync", json={"sessions": [session]}, headers=auth(who))
    assert response.status_code == 200, response.text
    return session["id"]


@pytest.fixture
def team(client, owner_engine):
    manager = register(client)
    anna, anna_id = add_active_employee(client, manager, "anna@acme-corp.com", "Anna")
    ben, ben_id = add_active_employee(client, manager, "ben@acme-corp.com", "Ben")
    cleo, cleo_id = add_active_employee(client, manager, "cleo@acme-corp.com", "Cleo")
    eve, eve_id = add_active_employee(client, manager, "eve@acme-corp.com", "Eve")
    client.post("/auth/join", json={"full_name": "Dana", "email": "dana@acme-corp.com", "password": "correct horse battery",
                                    "company_code": client.get("/company", headers=auth(manager)).json()["join_code"]})

    _sync(client, anna, TODAY, 3600, 600, 300, [("Code", "productive", 3000), ("Chrome", "neutral", 900),
                                                 ("YouTube", "distraction", 600)])
    _sync(client, anna, TODAY - timedelta(days=1), 7200)
    _sync(client, anna, TODAY - timedelta(days=8), 1800, 1800, 0, [("Old", "neutral", 999)])
    _sync(client, ben, TODAY, 1800, 1800, 0, [("Chrome", "neutral", 1200)])
    _sync(client, eve, TODAY, 99999)
    client.patch(f"/users/{eve_id}/status", json={"status": "disabled"}, headers=auth(manager))

    headers = auth(manager)
    a1 = client.post("/tasks", json={"title": "a1", "user_id": anna_id}, headers=headers).json()["id"]
    client.post("/tasks", json={"title": "a2", "user_id": anna_id, "deadline_date": str(TODAY - timedelta(days=1))},
                headers=headers)
    b1 = client.post("/tasks", json={"title": "b1", "user_id": ben_id}, headers=headers).json()["id"]
    client.post("/tasks", json={"title": "old", "user_id": cleo_id}, headers=headers)
    client.post(f"/tasks/{a1}/toggle", headers=headers)
    client.post(f"/tasks/{b1}/toggle", headers=headers)
    with owner_engine.begin() as connection:
        connection.execute(text("UPDATE tasks SET created_at = now() - interval '10 days' WHERE title = 'old'"))
    report_cache.clear()
    return {"manager": manager, "anna": anna, "ben": ben, "cleo": cleo, "ids": {"anna": anna_id, "ben": ben_id,
            "cleo": cleo_id, "eve": eve_id}}


def _overview(client, team, **extra):
    response = client.get("/reports/overview", params={**RANGE, **extra}, headers=auth(team["manager"]))
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- overview: totals and shares
def test_totals_percentages_and_hours(client, team):
    totals = _overview(client, team)["totals"]
    assert (totals["focus_seconds"], totals["distraction_seconds"], totals["away_seconds"]) == (12600, 2400, 300)
    assert totals["tracked_seconds"] == 15300 and totals["sessions"] == 3
    assert totals["focus_pct"] == 82.4 and totals["distraction_pct"] == 15.7 and totals["away_pct"] == 2.0
    assert totals["hours_worked"] == 4.17                       # (12600 + 2400) / 3600: focus + distracted


def test_only_active_employees_count(client, team):
    data = _overview(client, team)
    assert data["employees_total"] == 3
    assert {row["full_name"] for row in data["ranking"]["items"]} == {"Anna", "Ben", "Cleo"}   # not Dana, not Eve
    assert data["totals"]["focus_seconds"] == 12600                                            # Eve's 99999 is not in it


def test_the_range_is_inclusive_and_local_days(client, team):
    only_today = client.get("/reports/overview", params={"start": str(TODAY), "end": str(TODAY), "today": str(TODAY)},
                            headers=auth(team["manager"])).json()
    assert only_today["totals"]["focus_seconds"] == 5400 and only_today["range"]["days"] == 1
    yesterday = client.get("/reports/overview", params={"start": str(TODAY - timedelta(days=1)),
                                                        "end": str(TODAY - timedelta(days=1)), "today": str(TODAY)},
                           headers=auth(team["manager"])).json()
    assert yesterday["totals"]["focus_seconds"] == 7200


# ---------------------------------------------------------------- week over week
def test_change_against_the_previous_period(client, team):
    data = _overview(client, team)
    assert data["previous_range"] == {"start": str(TODAY - timedelta(days=13)), "end": str(TODAY - timedelta(days=7)),
                                      "days": 7}
    assert data["previous"]["focus_pct"] == 50.0 and data["previous"]["hours_worked"] == 1.0
    change = data["change"]
    assert change["focus_pct"] == 32.4                           # 82.4 - 50.0 points
    assert change["distraction_pct"] == round(15.7 - 50.0, 1)
    assert change["hours_worked_pct"] == 317.0                   # 4.17 h against 1.0 h
    assert change["task_completion_rate"] == 66.7                # 66.7 % against 0 %


def test_change_is_empty_when_there_was_no_previous_work(client, team):
    data = client.get("/reports/overview", params={"start": str(TODAY - timedelta(days=60)),
                                                   "end": str(TODAY - timedelta(days=30)), "today": str(TODAY)},
                      headers=auth(team["manager"])).json()
    assert data["totals"]["tracked_seconds"] == 0 and data["totals"]["focus_pct"] == 0.0
    assert data["change"] == {"focus_pct": None, "distraction_pct": None, "away_pct": None,
                              "hours_worked_pct": None, "task_completion_rate": None}   # nothing to compare


def test_no_change_is_shown_when_one_side_has_no_data(client, team):
    """The first range with data has nothing before it; the range after a quiet one has nothing to compare with."""
    long_ago = client.get("/reports/overview", params={"start": str(TODAY - timedelta(days=27)),
                                                       "end": str(TODAY - timedelta(days=21)), "today": str(TODAY)},
                          headers=auth(team["manager"])).json()
    assert long_ago["change"]["focus_pct"] is None and long_ago["change"]["task_completion_rate"] is None
    ben = client.get(f"/reports/employee/{team['ids']['ben']}", params=RANGE, headers=auth(team["manager"])).json()
    assert ben["previous"]["tracked_seconds"] == 0                # Ben only worked in the current range
    assert ben["change"]["focus_pct"] is None and ben["change"]["distraction_pct"] is None
    assert ben["change"]["hours_worked_pct"] is None              # no earlier hours either
    assert ben["change"]["task_completion_rate"] is None          # no tasks in the previous range


# ---------------------------------------------------------------- tasks
def test_task_completion_rate_and_overdue(client, team):
    data = _overview(client, team)
    assert data["tasks"] == {"total": 3, "done": 2, "completion_rate": 66.7, "overdue_open": 1}
    assert data["previous_tasks"] == {"total": 1, "done": 0, "completion_rate": 0.0}


# ---------------------------------------------------------------- attendance
def test_attendance_by_day(client, team):
    data = _overview(client, team)
    days = {a["day"]: a for a in data["attendance"]}
    assert len(data["attendance"]) == 7
    assert days[str(TODAY)] == {"day": str(TODAY), "present": 2, "total": 3, "rate": 66.7}
    assert days[str(TODAY - timedelta(days=1))]["present"] == 1 and days[str(TODAY - timedelta(days=1))]["rate"] == 33.3
    assert days[str(TODAY - timedelta(days=3))]["present"] == 0
    assert data["attendance_rate"] == 14.3                       # 3 present-days of 3 people x 7 days


# ---------------------------------------------------------------- most-used apps
def test_most_used_apps_count_only_the_range_and_merge_users(client, team):
    apps = _overview(client, team)["apps"]
    assert [(a["name"], a["seconds"]) for a in apps] == [("Code", 3000), ("Chrome", 2100), ("YouTube", 600)]
    assert [a["share"] for a in apps] == [52.6, 36.8, 10.5]
    assert [a["category"] for a in apps] == ["productive", "neutral", "distraction"]
    assert "Old" not in {a["name"] for a in apps}                # that session is in the previous range


def test_app_seconds_only_grow_and_repeated_names_do_not_break_sync(client, team):
    session = _sync(client, team["ben"], TODAY - timedelta(days=2), 600, apps=[("Slack", "neutral", 500)])
    _sync(client, team["ben"], TODAY - timedelta(days=2), 600, apps=[("Slack", "neutral", 200)], session_id=session)
    twice = {"id": session, "local_date": str(TODAY - timedelta(days=2)), "started_at": datetime.now(UTC).isoformat(),
             "apps": [{"name": "Slack", "category": "neutral", "seconds": 450}, {"name": "Slack", "category": "neutral",
                                                                                "seconds": 700}]}
    assert client.post("/sessions/sync", json={"sessions": [twice]}, headers=auth(team["ben"])).status_code == 200
    report_cache.clear()
    slack = next(a for a in _overview(client, team)["apps"] if a["name"] == "Slack")
    assert slack["seconds"] == 700                              # the highest value ever reported


def test_app_input_is_validated_and_other_users_sessions_are_not_touched(client, team):
    base = {"id": str(uuid.uuid4()), "local_date": str(TODAY), "started_at": datetime.now(UTC).isoformat()}
    for bad in ({"name": "x", "category": "weird", "seconds": 1}, {"name": "a\x00b", "category": "neutral", "seconds": 1},
                {"name": "x" * 81, "category": "neutral", "seconds": 1}, {"name": "x", "category": "neutral", "seconds": -1},
                {"name": "x", "category": "neutral", "seconds": 1, "title": "Secret document.docx"}):
        assert client.post("/sessions/sync", json={"sessions": [{**base, "apps": [bad]}]},
                           headers=auth(team["ben"])).status_code == 422
    anna_session = client.get("/sessions", params={"user_id": team["ids"]["anna"]}, headers=auth(team["manager"])).json()[0]["id"]
    client.post("/sessions/sync", json={"sessions": [{**base, "id": anna_session,
                                                      "apps": [{"name": "Hijack", "category": "neutral", "seconds": 5}]}]},
                headers=auth(team["ben"]))
    report_cache.clear()
    assert "Hijack" not in {a["name"] for a in _overview(client, team)["apps"]}


# ---------------------------------------------------------------- ranking, sorting, pagination
def test_ranking_and_vs_team(client, team):
    rows = _overview(client, team)["ranking"]["items"]
    assert [r["full_name"] for r in rows] == ["Anna", "Ben", "Cleo"]       # by focus share; no data last
    anna, ben, cleo = rows
    assert (anna["focus_pct"], anna["hours_worked"], anna["days_present"], anna["sessions"]) == (92.3, 3.17, 2, 2)
    assert anna["vs_team_pp"] == 9.9 and ben["vs_team_pp"] == -32.4 and cleo["vs_team_pp"] is None
    assert (anna["tasks_total"], anna["tasks_done"], anna["completion_rate"]) == (2, 1, 50.0)
    assert (cleo["tracked_seconds"], cleo["focus_pct"], cleo["tasks_total"]) == (0, 0.0, 0)   # Cleo's task is old


def test_sorting_and_pagination(client, team):
    names = lambda **kw: [r["full_name"] for r in _overview(client, team, **kw)["ranking"]["items"]]    # noqa: E731
    assert names(sort="name") == ["Anna", "Ben", "Cleo"]
    assert names(sort="hours") == ["Anna", "Ben", "Cleo"]
    assert names(sort="distraction_pct")[0] == "Ben"                       # 50 % against Anna's 5.1 %
    assert names(sort="tasks")[0] == "Ben"                                 # 100 % completion
    page = _overview(client, team, limit=2, offset=0)["ranking"]
    assert page["total"] == 3 and [r["full_name"] for r in page["items"]] == ["Anna", "Ben"]
    assert [r["full_name"] for r in _overview(client, team, limit=2, offset=2)["ranking"]["items"]] == ["Cleo"]
    assert _overview(client, team, limit=2, offset=9)["ranking"]["items"] == []


def test_team_average(client, team):
    average = _overview(client, team)["team_average"]
    assert average["focus_pct"] == 82.4 and average["hours_per_employee"] == 1.39      # 4.17 h over 3 employees


# ---------------------------------------------------------------- trends
def test_daily_trend_fills_empty_days(client, team):
    points = client.get("/reports/trends", params={**RANGE, "bucket": "day"}, headers=auth(team["manager"])).json()["points"]
    assert len(points) == 7 and points[-1]["start"] == str(TODAY)
    today, yesterday, quiet = points[-1], points[-2], points[0]
    assert (today["focus_seconds"], today["distraction_seconds"], today["away_seconds"]) == (5400, 2400, 300)
    assert today["focus_pct"] == 66.7 and today["present_people_days"] == 2 and today["sessions"] == 2
    assert yesterday["focus_pct"] == 100.0 and yesterday["hours_worked"] == 2.0
    assert quiet["tracked_seconds"] == 0 and quiet["focus_pct"] == 0.0


def test_weekly_trend_buckets_start_on_mondays_and_add_up(client, team):
    points = client.get("/reports/trends", params={"start": str(TODAY - timedelta(days=20)), "end": str(TODAY),
                                                   "bucket": "week"}, headers=auth(team["manager"])).json()["points"]
    starts = [date.fromisoformat(p["start"]) for p in points]
    assert all(s.weekday() == 0 for s in starts[1:]) and starts[0] == TODAY - timedelta(days=20)
    assert sum(p["focus_seconds"] for p in points) == 12600 + 1800          # includes TODAY-8 (Anna's earlier session)
    assert starts == sorted(starts) and len(set(starts)) == len(starts)


def test_trend_for_one_employee(client, team):
    data = client.get("/reports/trends", params={**RANGE, "user_id": team["ids"]["ben"]},
                      headers=auth(team["manager"])).json()
    assert data["user_id"] == team["ids"]["ben"] and data["points"][-1]["focus_seconds"] == 1800
    assert sum(p["focus_seconds"] for p in data["points"]) == 1800


# ---------------------------------------------------------------- employee report
def test_employee_report_compares_with_the_team(client, team):
    response = client.get(f"/reports/employee/{team['ids']['anna']}", params=RANGE, headers=auth(team["manager"]))
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["user"]["full_name"] == "Anna"
    assert report["totals"]["focus_pct"] == 92.3 and report["totals"]["hours_worked"] == 3.17
    assert report["previous"]["focus_pct"] == 50.0 and report["change"]["focus_pct"] == 42.3
    assert report["vs_team"] == {"focus_pp": 9.9, "distraction_pp": round(5.1 - 15.7, 1), "hours": round(3.17 - 4.17 / 3, 2),
                                 "completion_pp": round(50.0 - 66.7, 1)}
    assert report["rank"] == {"position": 1, "of": 2}                       # Cleo tracked nothing: not ranked
    assert report["days_present"] == 2 and sum(1 for d in report["attendance"] if d["present"]) == 2
    assert report["daily"][-1]["team_focus_pct"] == 66.7 and report["daily"][-1]["focus_pct"] == 80.0
    assert [(a["name"], a["seconds"]) for a in report["apps"]] == [("Code", 3000), ("Chrome", 900), ("YouTube", 600)]
    assert report["tasks"]["overdue_open"] == 1 and report["team_average"]["completion_rate"] == 66.7


def test_an_employee_without_data_gets_a_complete_empty_report(client, team):
    report = client.get(f"/reports/employee/{team['ids']['cleo']}", params=RANGE, headers=auth(team["manager"])).json()
    assert report["totals"]["tracked_seconds"] == 0 and report["rank"] == {"position": None, "of": 2}
    assert report["apps"] == [] and len(report["daily"]) == 7 and report["days_present"] == 0


# ---------------------------------------------------------------- permissions and validation
def test_who_may_see_which_report(client, team):
    ben, manager = auth(team["ben"]), auth(team["manager"])
    assert client.get("/reports/overview", params=RANGE, headers=ben).status_code == 403
    assert client.get("/reports/trends", params=RANGE, headers=ben).status_code == 403
    assert client.get("/reports/trends", params={**RANGE, "user_id": team["ids"]["ben"]}, headers=ben).status_code == 200
    assert client.get(f"/reports/employee/{team['ids']['ben']}", params=RANGE, headers=ben).status_code == 200
    assert client.get(f"/reports/employee/{team['ids']['anna']}", params=RANGE, headers=ben).status_code == 404
    assert client.get("/reports/trends", params={**RANGE, "user_id": team["ids"]["anna"]}, headers=ben).status_code == 404
    me = client.get("/auth/me", headers=manager).json()["user"]["id"]
    assert client.get(f"/reports/employee/{me}", params=RANGE, headers=manager).status_code == 404      # a manager is no employee
    assert client.get(f"/reports/employee/{team['ids']['eve']}", params=RANGE, headers=manager).status_code == 404
    assert client.get("/reports/overview", params=RANGE).status_code == 401


def test_dates_are_validated(client, team):
    manager = auth(team["manager"])
    assert client.get("/reports/overview", params={"start": "2026-02-01", "end": "2026-01-01"}, headers=manager).status_code == 422
    assert client.get("/reports/overview", params={"start": "2024-01-01", "end": "2026-01-01"}, headers=manager).status_code == 422
    assert client.get("/reports/overview", params={"start": "2026-01-01"}, headers=manager).status_code == 422
    assert client.get("/reports/overview", params={"start": "nope", "end": "2026-01-01"}, headers=manager).status_code == 422
    assert client.get("/reports/overview", params={**RANGE, "sort": "salary"}, headers=manager).status_code == 422
    assert client.get("/reports/overview", params={**RANGE, "limit": 0}, headers=manager).status_code == 422
    one_year = client.get("/reports/overview", params={"start": str(TODAY - timedelta(days=365)), "end": str(TODAY)},
                          headers=manager)
    assert one_year.status_code == 200 and one_year.json()["range"]["days"] == 366


def test_a_company_without_employees_gets_zeros(client):
    manager = register(client, company="Solo", email="solo@solo-corp.com")
    data = client.get("/reports/overview", params=RANGE, headers=auth(manager)).json()
    assert data["employees_total"] == 0 and data["totals"]["tracked_seconds"] == 0
    assert data["ranking"]["items"] == [] and data["attendance_rate"] == 0.0 and data["team_average"]["hours_per_employee"] == 0.0


# ---------------------------------------------------------------- the cache
def test_repeated_reports_come_from_the_cache_until_something_changes(client, team):
    manager = auth(team["manager"])
    report_cache.clear()
    first = client.get("/reports/overview", params=RANGE, headers=manager).json()
    second = client.get("/reports/overview", params=RANGE, headers=manager).json()
    assert second == first and report_cache.hits == 1 and report_cache.misses == 1
    client.get("/reports/overview", params={**RANGE, "limit": 5}, headers=manager)     # other parameters: its own entry
    assert report_cache.misses == 2
    # a task change invalidates the company's cached reports
    client.post("/tasks", json={"title": "new", "user_id": team["ids"]["ben"]}, headers=manager)
    third = client.get("/reports/overview", params=RANGE, headers=manager).json()
    assert third["tasks"]["total"] == first["tasks"]["total"] + 1
    # so does approving or disabling a person
    client.patch(f"/users/{team['ids']['cleo']}/status", json={"status": "disabled"}, headers=manager)
    assert client.get("/reports/overview", params=RANGE, headers=manager).json()["employees_total"] == 2


def test_cache_entries_are_per_company_and_expire():
    clock = {"now": 100.0}
    cache = ReportCache(ttl=30.0, max_entries=2, clock=lambda: clock["now"])
    a, b = uuid.uuid4(), uuid.uuid4()
    cache.set(a, "k", {"v": 1})
    assert cache.get(a, "k") == {"v": 1} and cache.get(b, "k") is None          # another company: never a hit
    clock["now"] = 131.0
    assert cache.get(a, "k") is None                                             # expired
    cache.set(a, "k", 1)
    cache.invalidate(a)
    assert cache.get(a, "k") is None
    cache.set(a, "1", 1), cache.set(a, "2", 2), cache.set(a, "3", 3)
    assert cache.get(a, "1") is None and cache.get(a, "3") == 3                  # the oldest entry was dropped


def test_the_cache_key_never_mixes_roles(client, team):
    """An employee's own-report request must not be served from a manager's cached entry or vice versa."""
    ben_id = team["ids"]["ben"]
    as_manager = client.get(f"/reports/employee/{ben_id}", params=RANGE, headers=auth(team["manager"])).json()
    as_ben = client.get(f"/reports/employee/{ben_id}", params=RANGE, headers=auth(team["ben"])).json()
    assert as_manager == as_ben                                                  # same numbers, each authorised on its own
    assert client.get(f"/reports/employee/{team['ids']['anna']}", params=RANGE, headers=auth(team["ben"])).status_code == 404


def test_the_cache_module_is_the_one_the_routes_use():
    assert cache_module.report_cache is report_cache
