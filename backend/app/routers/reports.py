"""/reports: overview, trends and per-employee reports for managers.

Managers see the whole company; an employee may ask only for their own report
(``/reports/employee/{own id}``). The days are the employees' local calendar days; the
caller passes ``today`` so the server never guesses a time zone. Heavy results are
cached for a short time (see ``app.services.report_cache``).
"""
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import CurrentManager, CurrentUser
from app.routers.common import target_user
from app.services import reports
from app.services.report_cache import report_cache

router = APIRouter(prefix="/reports", tags=["reports"])


def _range(start: date, end: date) -> reports.DateRange:
    try:
        return reports.DateRange(start, end)
    except reports.RangeError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


def _cached(principal, key, compute):
    cached = report_cache.get(principal.company_id, key)
    if cached is not None:
        return cached
    value = compute()
    report_cache.set(principal.company_id, key, value)
    return value


@router.get("/overview")
def overview(principal: CurrentManager, start: date = Query(...), end: date = Query(...),
             today: date | None = None, limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0),
             sort: Literal["focus_pct", "hours", "name", "distraction_pct", "tasks"] = "focus_pct"):
    rng = _range(start, end)
    today = today or end
    return _cached(principal, ("overview", rng.start, rng.end, today, limit, offset, sort),
                   lambda: reports.overview(principal.session, principal.company_id, rng, today,
                                            limit=limit, offset=offset, sort=sort))


@router.get("/trends")
def trends(principal: CurrentUser, start: date = Query(...), end: date = Query(...),
           bucket: Literal["day", "week"] = "day", user_id: uuid.UUID | None = None):
    rng = _range(start, end)
    if user_id is None and not principal.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can see the whole company")
    only = target_user(principal, user_id).id if user_id is not None else None
    return _cached(principal, ("trends", rng.start, rng.end, bucket, only),
                   lambda: reports.trends(principal.session, principal.company_id, rng, bucket, only))


@router.get("/employee/{user_id}")
def employee_report(user_id: uuid.UUID, principal: CurrentUser, start: date = Query(...), end: date = Query(...),
                    today: date | None = None):
    rng = _range(start, end)
    user = target_user(principal, user_id)
    if user.role != "employee" or user.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    today = today or end
    return _cached(principal, ("employee", user.id, rng.start, rng.end, today),
                   lambda: reports.employee_report(principal.session, principal.company_id, user, rng, today))
