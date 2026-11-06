"""The server's reports as the Reports page uses them (see backend/app/services/reports.py).

Every call can raise ``cloud.api.Offline`` / ``ApiError`` / ``SessionExpired``; the page
decides what to tell the user. Calls are safe to make from a worker thread.
"""
from datetime import date

PAGE_LIMIT = 200          # the server's maximum page size


def _day(value) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


class ReportsApi:
    def __init__(self, api):
        self.api = api

    def overview(self, start, end, today=None, limit=20, offset=0, sort="focus_pct") -> dict:
        return self.api.get("/reports/overview", start=_day(start), end=_day(end), today=_day(today or end),
                            limit=limit, offset=offset, sort=sort)

    def trends(self, start, end, bucket="day", user_id=None) -> dict:
        return self.api.get("/reports/trends", start=_day(start), end=_day(end), bucket=bucket, user_id=user_id)

    def employee(self, user_id, start, end, today=None) -> dict:
        return self.api.get(f"/reports/employee/{user_id}", start=_day(start), end=_day(end), today=_day(today or end))

    def whole_ranking(self, start, end, today=None, sort="focus_pct") -> list:
        """Every employee's row (all pages), for the CSV and PDF."""
        rows, offset = [], 0
        while True:
            page = self.overview(start, end, today, limit=PAGE_LIMIT, offset=offset, sort=sort)["ranking"]
            rows += page["items"]
            offset += PAGE_LIMIT
            if offset >= page["total"]:
                return rows
