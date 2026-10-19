"""Behaviour shared by the manager and the employee shell (sidebar + stacked pages)."""

import logging

logger = logging.getLogger(__name__)


class ShellNavigationMixin:
    """Page switching and the calendar badge, for a shell that has ``self.sidebar``,
    ``self.stack``, ``self._page_index`` (key -> stack index), ``self.db`` and ``self.user``."""

    def _navigate(self, key):
        """Show the page registered under ``key`` and let it reload its data."""
        if key not in self._page_index:
            return
        self.stack.setCurrentIndex(self._page_index[key])
        self.sidebar.set_active(key)
        refresh = getattr(self.stack.currentWidget(), "refresh", None)
        if callable(refresh):
            refresh()

    def _refresh_calendar_badge(self):
        """Show how many events today (created or invited) on the Calendar item."""
        if self.db is None or self.user.get("id") is None:
            return
        try:
            count = len(self.db.get_today_events(self.user["id"]))
        except Exception:
            logger.warning("Updating the calendar badge failed", exc_info=True)
            return
        self.sidebar.set_badge("calendar", count)
