"""Manager reports: the numbers behind the charts.

Definitions (also shown in the app):

* **focus / distracted / away %** -- each timer's share of the *tracked* time (the sum of
  the three timers over all sessions in the range).
* **hours worked** -- time present at the desk: focus + distracted (away time is not work).
* **days are the employees' local calendar days** (``sessions.local_date``).
* **period change ("week-over-week")** -- the range is compared with the preceding range
  of the same length (7 days -> the 7 days before). Percentage metrics change in
  percentage points, hours in percent.
* **task completion rate** -- of the tasks created in the range for the employees, the
  share that is done.
* **attendance** -- an employee is present on a day if they recorded at least one session.
* **most-used apps** -- seconds spent in each application while at the desk (focus and
  distracted time); only the application's display name is stored, never window titles.

Only active employees are included. Everything is scoped to one company.
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import SessionApp, Task, User, WorkSession

MAX_DAYS = 366


class RangeError(ValueError):
    pass


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self):
        if self.end < self.start:
            raise RangeError("The end date is before the start date")
        if self.days > MAX_DAYS:
            raise RangeError(f"A report can cover at most {MAX_DAYS} days")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "DateRange":
        return DateRange(self.start - timedelta(days=self.days), self.start - timedelta(days=1))


def pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def hours(seconds: float) -> float:
    return round(seconds / 3600.0, 2)


# ---------------------------------------------------------------- queries
def employees(session: Session, company_id: uuid.UUID, only: uuid.UUID | None = None) -> list[User]:
    statement = select(User).where(User.company_id == company_id, User.role == "employee", User.status == "active")
    if only is not None:
        statement = statement.where(User.id == only)
    return list(session.scalars(statement.order_by(User.full_name, User.id)))


def per_user_sums(session: Session, company_id: uuid.UUID, user_ids: list, rng: DateRange) -> dict:
    """``{user_id: row}`` with focus/distraction/away seconds, sessions and days present."""
    if not user_ids:
        return {}
    rows = session.execute(
        select(WorkSession.user_id,
               func.coalesce(func.sum(WorkSession.focus_seconds), 0).label("focus"),
               func.coalesce(func.sum(WorkSession.distraction_seconds), 0).label("distraction"),
               func.coalesce(func.sum(WorkSession.away_seconds), 0).label("away"),
               func.count().label("sessions"),
               func.count(func.distinct(WorkSession.local_date)).label("days"))
        .where(WorkSession.company_id == company_id, WorkSession.user_id.in_(user_ids),
               WorkSession.local_date >= rng.start, WorkSession.local_date <= rng.end)
        .group_by(WorkSession.user_id))
    return {row.user_id: row for row in rows}


def per_day(session: Session, company_id: uuid.UUID, user_ids: list, rng: DateRange) -> dict:
    """``{day: row}`` with the three timers, session count and distinct people present."""
    if not user_ids:
        return {}
    rows = session.execute(
        select(WorkSession.local_date.label("day"),
               func.coalesce(func.sum(WorkSession.focus_seconds), 0).label("focus"),
               func.coalesce(func.sum(WorkSession.distraction_seconds), 0).label("distraction"),
               func.coalesce(func.sum(WorkSession.away_seconds), 0).label("away"),
               func.count().label("sessions"),
               func.count(func.distinct(WorkSession.user_id)).label("present"))
        .where(WorkSession.company_id == company_id, WorkSession.user_id.in_(user_ids),
               WorkSession.local_date >= rng.start, WorkSession.local_date <= rng.end)
        .group_by(WorkSession.local_date))
    return {row.day: row for row in rows}


def task_sums(session: Session, company_id: uuid.UUID, user_ids: list, rng: DateRange) -> dict:
    """``{user_id: (total, done)}`` of the tasks created in the range."""
    if not user_ids:
        return {}
    rows = session.execute(
        select(Task.user_id, func.count().label("total"),
               func.count().filter(Task.is_done.is_(True)).label("done"))
        .where(Task.company_id == company_id, Task.user_id.in_(user_ids),
               cast(Task.created_at, Date) >= rng.start, cast(Task.created_at, Date) <= rng.end)
        .group_by(Task.user_id))
    return {row.user_id: (row.total, row.done) for row in rows}


def overdue_open_tasks(session: Session, company_id: uuid.UUID, user_ids: list, today: date) -> int:
    if not user_ids:
        return 0
    return session.scalar(
        select(func.count()).where(Task.company_id == company_id, Task.user_id.in_(user_ids),
                                   Task.is_done.is_(False), Task.deadline_date.is_not(None),
                                   Task.deadline_date < today)) or 0


def app_usage(session: Session, company_id: uuid.UUID, user_ids: list, rng: DateRange, limit: int = 10) -> list[dict]:
    if not user_ids:
        return []
    rows = session.execute(
        select(SessionApp.app_name, SessionApp.category, func.sum(SessionApp.seconds).label("seconds"))
        .join(WorkSession, (WorkSession.company_id == SessionApp.company_id) & (WorkSession.id == SessionApp.session_id))
        .where(SessionApp.company_id == company_id, SessionApp.user_id.in_(user_ids),
               WorkSession.local_date >= rng.start, WorkSession.local_date <= rng.end)
        .group_by(SessionApp.app_name, SessionApp.category)).all()
    merged: dict[str, dict] = {}
    for name, category, seconds in rows:
        entry = merged.setdefault(name, {"name": name, "seconds": 0, "by_category": defaultdict(int)})
        entry["seconds"] += int(seconds)
        entry["by_category"][category] += int(seconds)
    total = sum(e["seconds"] for e in merged.values())
    ordered = sorted(merged.values(), key=lambda e: (-e["seconds"], e["name"].lower()))
    return [{"name": e["name"], "category": max(e["by_category"], key=e["by_category"].get),
             "seconds": e["seconds"], "share": pct(e["seconds"], total)} for e in ordered[:limit]]


# ---------------------------------------------------------------- building blocks
def totals_from(rows) -> dict:
    focus = sum(int(r.focus) for r in rows)
    distraction = sum(int(r.distraction) for r in rows)
    away = sum(int(r.away) for r in rows)
    tracked = focus + distraction + away
    return {
        "focus_seconds": focus, "distraction_seconds": distraction, "away_seconds": away,
        "tracked_seconds": tracked, "sessions": sum(int(r.sessions) for r in rows),
        "focus_pct": pct(focus, tracked), "distraction_pct": pct(distraction, tracked), "away_pct": pct(away, tracked),
        "hours_worked": hours(focus + distraction),
    }


def task_summary(sums: dict) -> dict:
    total = sum(t for t, _ in sums.values())
    done = sum(d for _, d in sums.values())
    return {"total": total, "done": done, "completion_rate": pct(done, total)}


def change(current: dict, previous: dict, tasks_now: dict, tasks_before: dict) -> dict:
    """Period-over-period change: percentage points for shares, percent for hours."""
    def points(now, before, comparable):
        return round(now - before, 1) if comparable else None

    # a share is only comparable when both periods have tracked time (0 % of nothing is no data)
    shares = current["tracked_seconds"] > 0 and previous["tracked_seconds"] > 0
    before_hours = previous["hours_worked"]
    return {
        "focus_pct": points(current["focus_pct"], previous["focus_pct"], shares),
        "distraction_pct": points(current["distraction_pct"], previous["distraction_pct"], shares),
        "away_pct": points(current["away_pct"], previous["away_pct"], shares),
        "hours_worked_pct": round(100.0 * (current["hours_worked"] - before_hours) / before_hours, 1)
        if before_hours else None,
        "task_completion_rate": points(tasks_now["completion_rate"], tasks_before["completion_rate"],
                                       tasks_now["total"] > 0 and tasks_before["total"] > 0),
    }


def attendance_series(day_rows: dict, rng: DateRange, total_employees: int) -> list[dict]:
    out = []
    for offset in range(rng.days):
        day = rng.start + timedelta(days=offset)
        present = int(day_rows[day].present) if day in day_rows else 0
        out.append({"day": day, "present": present, "total": total_employees, "rate": pct(present, total_employees)})
    return out


def trend_points(day_rows: dict, rng: DateRange, bucket: str) -> list[dict]:
    """Daily or weekly (Monday-based, clipped to the range) points; empty days are zeros."""
    buckets: dict[date, dict] = {}
    for offset in range(rng.days):
        day = rng.start + timedelta(days=offset)
        key = day if bucket == "day" else max(day - timedelta(days=day.weekday()), rng.start)
        entry = buckets.setdefault(key, {"start": key, "focus": 0, "distraction": 0, "away": 0, "sessions": 0,
                                         "present_days": 0, "peak_present": 0})
        row = day_rows.get(day)
        if row is not None:
            entry["focus"] += int(row.focus)
            entry["distraction"] += int(row.distraction)
            entry["away"] += int(row.away)
            entry["sessions"] += int(row.sessions)
            entry["present_days"] += int(row.present)
            entry["peak_present"] = max(entry["peak_present"], int(row.present))
    points = []
    for key in sorted(buckets):
        e = buckets[key]
        tracked = e["focus"] + e["distraction"] + e["away"]
        points.append({
            "start": key, "focus_seconds": e["focus"], "distraction_seconds": e["distraction"],
            "away_seconds": e["away"], "tracked_seconds": tracked, "sessions": e["sessions"],
            "focus_pct": pct(e["focus"], tracked), "distraction_pct": pct(e["distraction"], tracked),
            "away_pct": pct(e["away"], tracked), "hours_worked": hours(e["focus"] + e["distraction"]),
            "present_people_days": e["present_days"],
        })
    return points


def ranking_rows(staff: list[User], sums: dict, tasks: dict, team_focus_pct: float) -> list[dict]:
    rows = []
    for user in staff:
        s = sums.get(user.id)
        focus, distraction, away = (int(s.focus), int(s.distraction), int(s.away)) if s else (0, 0, 0)
        tracked = focus + distraction + away
        total_tasks, done_tasks = tasks.get(user.id, (0, 0))
        rows.append({
            "id": user.id, "full_name": user.full_name, "focus_seconds": focus, "distraction_seconds": distraction,
            "away_seconds": away, "tracked_seconds": tracked, "sessions": int(s.sessions) if s else 0,
            "days_present": int(s.days) if s else 0, "hours_worked": hours(focus + distraction),
            "focus_pct": pct(focus, tracked), "distraction_pct": pct(distraction, tracked),
            "away_pct": pct(away, tracked), "tasks_total": total_tasks, "tasks_done": done_tasks,
            "completion_rate": pct(done_tasks, total_tasks),
            "vs_team_pp": round(pct(focus, tracked) - team_focus_pct, 1) if tracked else None,
        })
    return rows


SORTS = {
    "focus_pct": lambda r: (-(r["tracked_seconds"] > 0), -r["focus_pct"], r["full_name"].lower()),
    "hours": lambda r: (-r["hours_worked"], r["full_name"].lower()),
    "name": lambda r: (r["full_name"].lower(),),
    "distraction_pct": lambda r: (-(r["tracked_seconds"] > 0), -r["distraction_pct"], r["full_name"].lower()),
    "tasks": lambda r: (-r["completion_rate"], -r["tasks_total"], r["full_name"].lower()),
}


# ---------------------------------------------------------------- the three reports
def overview(session: Session, company_id: uuid.UUID, rng: DateRange, today: date, *, limit: int, offset: int,
             sort: str) -> dict:
    staff = employees(session, company_id)
    ids = [u.id for u in staff]
    previous = rng.previous()
    sums, before = per_user_sums(session, company_id, ids, rng), per_user_sums(session, company_id, ids, previous)
    current = totals_from(sums.values())
    prior = totals_from(before.values())
    tasks_now = task_summary(task_sums(session, company_id, ids, rng))
    tasks_before = task_summary(task_sums(session, company_id, ids, previous))
    tasks_now["overdue_open"] = overdue_open_tasks(session, company_id, ids, today)
    rows = ranking_rows(staff, sums, task_sums(session, company_id, ids, rng), current["focus_pct"])
    rows.sort(key=SORTS[sort])
    attendance = attendance_series(per_day(session, company_id, ids, rng), rng, len(staff))
    present_days = sum(a["present"] for a in attendance)
    return {
        "range": {"start": rng.start, "end": rng.end, "days": rng.days},
        "previous_range": {"start": previous.start, "end": previous.end, "days": previous.days},
        "employees_total": len(staff),
        "totals": current, "previous": prior,
        "change": change(current, prior, tasks_now, tasks_before),
        "tasks": tasks_now, "previous_tasks": tasks_before,
        "attendance": attendance,
        "attendance_rate": pct(present_days, len(staff) * rng.days),
        "apps": app_usage(session, company_id, ids, rng),
        "team_average": {
            "focus_pct": current["focus_pct"], "distraction_pct": current["distraction_pct"],
            "away_pct": current["away_pct"],
            "hours_per_employee": round(current["hours_worked"] / len(staff), 2) if staff else 0.0,
        },
        "ranking": {"total": len(rows), "limit": limit, "offset": offset, "items": rows[offset:offset + limit]},
    }


def trends(session: Session, company_id: uuid.UUID, rng: DateRange, bucket: str, only: uuid.UUID | None) -> dict:
    staff = employees(session, company_id, only)
    ids = [u.id for u in staff]
    return {"range": {"start": rng.start, "end": rng.end, "days": rng.days}, "bucket": bucket,
            "user_id": only, "points": trend_points(per_day(session, company_id, ids, rng), rng, bucket)}


def employee_report(session: Session, company_id: uuid.UUID, user: User, rng: DateRange, today: date) -> dict:
    team = employees(session, company_id)
    team_ids = [u.id for u in team]
    previous = rng.previous()
    mine = per_user_sums(session, company_id, [user.id], rng)
    mine_before = per_user_sums(session, company_id, [user.id], previous)
    team_sums = per_user_sums(session, company_id, team_ids, rng)
    current, prior = totals_from(mine.values()), totals_from(mine_before.values())
    team_totals = totals_from(team_sums.values())
    tasks_now = task_summary(task_sums(session, company_id, [user.id], rng))
    tasks_before = task_summary(task_sums(session, company_id, [user.id], previous))
    tasks_now["overdue_open"] = overdue_open_tasks(session, company_id, [user.id], today)
    team_task_rate = task_summary(task_sums(session, company_id, team_ids, rng))["completion_rate"]
    row = ranking_rows([user], mine, task_sums(session, company_id, [user.id], rng), team_totals["focus_pct"])[0]
    # rank among the employees who tracked time, by focus share
    ranked = sorted((u for u in team if u.id in team_sums and int(team_sums[u.id].focus + team_sums[u.id].distraction
                                                                   + team_sums[u.id].away) > 0),
                    key=lambda u: -pct(int(team_sums[u.id].focus), int(team_sums[u.id].focus
                                       + team_sums[u.id].distraction + team_sums[u.id].away)))
    position = next((i + 1 for i, u in enumerate(ranked) if u.id == user.id), None)
    days = per_day(session, company_id, [user.id], rng)
    team_days = per_day(session, company_id, team_ids, rng)
    daily = trend_points(days, rng, "day")
    team_daily = trend_points(team_days, rng, "day")
    for mine_point, team_point in zip(daily, team_daily):
        mine_point["team_focus_pct"] = team_point["focus_pct"]
    attendance = [{"day": rng.start + timedelta(days=i),
                   "present": (rng.start + timedelta(days=i)) in days,
                   "tracked_seconds": int(days[rng.start + timedelta(days=i)].focus
                                          + days[rng.start + timedelta(days=i)].distraction
                                          + days[rng.start + timedelta(days=i)].away)
                   if (rng.start + timedelta(days=i)) in days else 0} for i in range(rng.days)]
    return {
        "user": {"id": user.id, "full_name": user.full_name, "email": user.email},
        "range": {"start": rng.start, "end": rng.end, "days": rng.days},
        "previous_range": {"start": previous.start, "end": previous.end, "days": previous.days},
        "totals": current, "previous": prior, "change": change(current, prior, tasks_now, tasks_before),
        "tasks": tasks_now, "previous_tasks": tasks_before,
        "summary": row,
        "team_average": {
            "focus_pct": team_totals["focus_pct"], "distraction_pct": team_totals["distraction_pct"],
            "away_pct": team_totals["away_pct"], "completion_rate": team_task_rate,
            "hours_per_employee": round(team_totals["hours_worked"] / len(team), 2) if team else 0.0,
        },
        "vs_team": {
            "focus_pp": round(current["focus_pct"] - team_totals["focus_pct"], 1),
            "distraction_pp": round(current["distraction_pct"] - team_totals["distraction_pct"], 1),
            "hours": round(current["hours_worked"] - (team_totals["hours_worked"] / len(team) if team else 0), 2),
            "completion_pp": round(tasks_now["completion_rate"] - team_task_rate, 1),
        },
        "rank": {"position": position, "of": len(ranked)},
        "daily": daily, "attendance": attendance,
        "days_present": row["days_present"],
        "apps": app_usage(session, company_id, [user.id], rng),
    }
