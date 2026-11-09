"""Behaviour shared by the manager and the employee shell (sidebar + stacked pages)."""

import logging

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from ui.connection_banner import ConnectionBanner

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

    #: pages that still work without the server (the session records into the outbox)
    WORKS_OFFLINE = ("session", "ai_helper", "settings")

    def _content_with_banner(self):
        """The page stack with the offline banner above it."""
        self.connection_banner = ConnectionBanner()
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.connection_banner)
        column.addWidget(self.stack, 1)
        return content

    def set_online(self, online):
        """Show or hide the offline banner and grey out the pages that need the server."""
        banner = getattr(self, "connection_banner", None)
        if banner is not None:
            banner.set_online(online)
        for key in self._page_index:
            if key not in self.WORKS_OFFLINE:
                self.sidebar.set_item_enabled(key, online, "needs a connection")

    def _refresh_calendar_badge(self):
        """Show how many events today (created or invited) on the Calendar item, and how many
        meeting requests wait for this user on the Meetings item."""
        if self.db is None or self.user.get("id") is None:
            return
        try:
            count = len(self.db.get_today_events(self.user["id"]))
            waiting = self.db.count_meeting_requests_waiting() if "meetings" in self._page_index else 0
        except Exception:
            logger.warning("Updating the badges failed", exc_info=True)
            return
        self.sidebar.set_badge("calendar", count)
        if "meetings" in self._page_index:
            self.sidebar.set_badge("meetings", waiting)
