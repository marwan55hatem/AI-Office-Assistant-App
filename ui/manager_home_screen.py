"""Manager overview dashboard: KPIs, today's activity chart, feed and alerts."""

import logging
from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import icons, theme
from ui.widgets import clear_layout

logger = logging.getLogger(__name__)

MAX_BAR_WIDTH = 4000          # the chart fills the whole card
CHART_ROW_HEIGHT = 52
BAR_HEIGHT = 36
NAME_COLUMN_WIDTH = 220
TIME_COLUMN_WIDTH = 130

_fmt_hms = theme.fmt_hms

KPI_COLUMNS = 4
KPI_WIDE_WIDTH = 1000      # page width needed for a single row of four cards


class ActivityChart(QWidget):
    """Stacked focus / distracted / away bars, one per employee.

    Drawn with QPainter so the chart needs no extra dependency.  Every bar is
    scaled against the employee with the largest total, so the busiest person
    fills the full width.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.setMinimumHeight(CHART_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_rows(self, rows):
        """``rows``: [{full_name, focus_seconds, distraction_seconds, away_seconds}]."""
        self.rows = list(rows or [])
        self.setMinimumHeight(max(1, len(self.rows)) * CHART_ROW_HEIGHT + 8)
        self.update()

    def _bar_width(self):
        return max(120, min(MAX_BAR_WIDTH, self.width() - NAME_COLUMN_WIDTH - TIME_COLUMN_WIDTH))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = painter.font()
        font.setPixelSize(theme.BODY_SIZE)
        painter.setFont(font)

        if not self.rows:
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                self.rect().adjusted(4, 0, 0, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                "No activity yet today.",
            )
            painter.end()
            return

        largest = max(
            (row["focus_seconds"] + row["distraction_seconds"] + row["away_seconds"]
             for row in self.rows),
            default=0,
        )
        bar_width = self._bar_width()

        for index, row in enumerate(self.rows):
            top = index * CHART_ROW_HEIGHT + 4
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.drawText(
                4, top, NAME_COLUMN_WIDTH - 12, CHART_ROW_HEIGHT - 8,
                Qt.AlignVCenter | Qt.AlignLeft, row["full_name"],
            )

            total = (row["focus_seconds"] + row["distraction_seconds"]
                     + row["away_seconds"])
            if largest <= 0 or total <= 0:
                painter.setPen(QColor(theme.TEXT_MUTED))
                painter.drawText(
                    NAME_COLUMN_WIDTH, top, bar_width, CHART_ROW_HEIGHT - 8,
                    Qt.AlignVCenter | Qt.AlignLeft, "—",
                )
                continue

            scale = bar_width / float(largest)
            x = NAME_COLUMN_WIDTH
            for value, colour in (
                (row["focus_seconds"], theme.SUCCESS),
                (row["distraction_seconds"], theme.WARNING),
                (row["away_seconds"], theme.DANGER),
            ):
                segment = value * scale
                if segment <= 0:
                    continue
                path = QPainterPath()
                path.addRoundedRect(x, top + (CHART_ROW_HEIGHT - 8 - BAR_HEIGHT) / 2, segment, BAR_HEIGHT, 10, 10)
                painter.fillPath(path, QColor(colour))
                x += segment

            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                int(x) + 12, top, TIME_COLUMN_WIDTH - 16, CHART_ROW_HEIGHT - 8,
                Qt.AlignVCenter | Qt.AlignLeft, _fmt_hms(total),
            )

        painter.end()


class ManagerHomeScreen(QWidget):
    """Landing page for the manager: what the team is doing right now."""

    go_to_employees = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 1, "full_name": "Admin Manager"}
        self.db = db
        self.full_name = self.user.get("full_name", "Manager")
        self.employees = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_6)

        body.addLayout(self._build_greeting())
        body.addLayout(self._build_kpis())
        body.addWidget(self._build_chart_card())
        body.addLayout(self._build_bottom_row())
        body.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_greeting(self):
        column = QVBoxLayout()
        column.setSpacing(theme.SP_1)

        self.greeting_label = QLabel()
        self.greeting_label.setObjectName("H1")
        column.addWidget(self.greeting_label)

        subtitle = QLabel("Here's what's happening with your team today.")
        subtitle.setObjectName("LeadLabel")
        column.addWidget(subtitle)
        return column

    def _build_kpis(self):
        row = QGridLayout()
        row.setHorizontalSpacing(theme.SP_4)
        row.setVerticalSpacing(theme.SP_4)
        for column in range(KPI_COLUMNS):
            row.setColumnStretch(column, 1)
        self.kpi_grid = row
        self.kpi_cards = []
        self._kpi_columns = KPI_COLUMNS

        self.kpi_team = self._kpi_card(row, ("users", "Team size"), "Employees")
        self.kpi_active = self._kpi_card(row, ("check", "Currently active"), "Present")
        self.kpi_focus = self._kpi_card(row, ("clock", "Total focus time"), "Today")
        self.kpi_distracted = self._kpi_card(row, ("alert", "Total distracted time"), "Today")
        return row

    def _kpi_card(self, parent_layout, title, caption):
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumHeight(150)
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_4, theme.SP_5, theme.SP_4)
        layout.setSpacing(theme.SP_1)

        title_label = icons.IconLabel(title[0], title[1], "FeedText", size=18)
        layout.addWidget(title_label)

        value = QLabel("—")
        value.setObjectName("StatNumber")
        layout.addWidget(value)

        caption_label = QLabel(caption)
        caption_label.setObjectName("MutedLabel")
        layout.addWidget(caption_label)

        index = len(self.kpi_cards)
        self.kpi_cards.append(card)
        parent_layout.addWidget(card, index // KPI_COLUMNS, index % KPI_COLUMNS)
        return value

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_kpis()

    def _reflow_kpis(self):
        """Four cards in a row when there is room, a 2x2 block when narrow."""
        columns = KPI_COLUMNS if self.width() >= KPI_WIDE_WIDTH else 2
        if columns == self._kpi_columns:
            return
        self._kpi_columns = columns
        for index, card in enumerate(self.kpi_cards):
            self.kpi_grid.addWidget(card, index // columns, index % columns)
        for column in range(KPI_COLUMNS):
            self.kpi_grid.setColumnStretch(column, 1 if column < columns else 0)

    def _build_chart_card(self):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_3)

        header = icons.IconLabel("chart", "Today's Activity")
        layout.addWidget(header)

        legend = QHBoxLayout()
        legend.setSpacing(theme.SP_4)
        for text, colour in (("🟢 Focus", theme.SUCCESS),
                             ("🟡 Distracted", theme.WARNING),
                             ("🔴 Away", theme.DANGER)):
            item = QLabel(text)
            item.setStyleSheet(
                "color: %s; font-size: %dpx; background: transparent;"
                % (colour, theme.SMALL_SIZE + 1)
            )
            legend.addWidget(item)
        legend.addStretch(1)
        layout.addLayout(legend)

        self.chart = ActivityChart()
        layout.addWidget(self.chart)
        return card

    def _build_bottom_row(self):
        row = QHBoxLayout()
        row.setSpacing(theme.SP_5)
        row.addWidget(self._build_feed_card(), 1)
        row.addWidget(self._build_alerts_card(), 1)
        return row

    def _build_feed_card(self):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_2)

        header = icons.IconLabel("clock", "Recent Activity")
        layout.addWidget(header)

        self.feed_container = QVBoxLayout()
        self.feed_container.setSpacing(theme.SP_1)
        layout.addLayout(self.feed_container)
        layout.addStretch(1)
        return card

    def _build_alerts_card(self):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_2)

        header = icons.IconLabel("alert", "Alerts", tone="WARNING")
        layout.addWidget(header)

        self.alerts_container = QVBoxLayout()
        self.alerts_container.setSpacing(theme.SP_2)
        layout.addLayout(self.alerts_container)
        layout.addStretch(1)
        return card

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def refresh(self):
        """Reload every panel from the database (safe to call on a timer)."""
        self.greeting_label.setText(self._greeting())
        if self.db is None:
            return
        try:
            self.employees = self.db.get_employee_status_today()
            totals = self.db.get_today_totals()
            per_user = self.db.get_today_totals_per_user()
            events = self.db.get_recent_events(limit=10)
            pending = self.db.get_pending_users()
            absent = self.db.get_absent_employees(days=3)
            distracted = self.db.get_high_distraction_employees(3600)
        except Exception:  # pragma: no cover - defensive
            logger.warning("refresh failed", exc_info=True)
            return

        self._update_kpis(totals, pending)
        self.chart.set_rows(per_user)
        self._update_feed(events)
        self._update_alerts(pending, absent, distracted)

    def _greeting(self):
        hour = datetime.now().hour
        if 5 <= hour <= 11:
            part = "Good morning"
        elif 12 <= hour <= 17:
            part = "Good afternoon"
        else:
            part = "Good evening"
        first_name = str(self.full_name).split()[0] if str(self.full_name).strip() else "there"
        return f"{part}, {first_name}"

    def _update_kpis(self, totals, pending):
        self.kpi_team.setText(str(len(self.employees)))
        self.kpi_active.setText(str(self.db.get_active_session_count_today()))
        self.kpi_focus.setText(_fmt_hms(totals["focus_seconds"]))
        self.kpi_distracted.setText(_fmt_hms(totals["distraction_seconds"]))

    def _update_feed(self, events):
        clear_layout(self.feed_container)
        if not events:
            empty = QLabel("No activity yet.")
            empty.setObjectName("MutedLabel")
            self.feed_container.addWidget(empty)
            return

        colours = {
            "focus": theme.SUCCESS,
            "distraction": theme.WARNING,
            "away": theme.DANGER,
        }
        for event in events:
            row_widget = QWidget()
            row_widget.setMinimumHeight(36)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(theme.SP_2)

            dot = QFrame()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(
                "background-color: %s; border: none; border-radius: 5px;"
                % colours.get(event["event_type"], theme.TEXT_MUTED)
            )
            row.addWidget(dot)

            stamp = str(event["timestamp"] or "")
            time_part = stamp.split(" ")[-1][:5] if " " in stamp else stamp
            text = QLabel(
                f"{event['full_name']}  ·  {event['event_type']}  ·  {time_part}"
            )
            text.setObjectName("FeedText")
            row.addWidget(text, 1)
            self.feed_container.addWidget(row_widget)

    def _update_alerts(self, pending, absent, distracted):
        clear_layout(self.alerts_container)

        if pending:
            button = QLabel(f"🔔  {len(pending)} pending signup request"
                            f"{'s' if len(pending) != 1 else ''}")
            button.setObjectName("PillBadge")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip("Open the Employees page")
            button.mousePressEvent = (
                lambda _event: self.go_to_employees.emit()
            )
            self.alerts_container.addWidget(button, 0, Qt.AlignLeft)

        if absent:
            names = ", ".join(row["full_name"] for row in absent[:3])
            more = "" if len(absent) <= 3 else f" +{len(absent) - 3} more"
            label = QLabel(
                f"🔴  {len(absent)} employee(s) absent 3+ days — {names}{more}"
            )
            label.setObjectName("AlertText")
            label.setMinimumHeight(36)
            label.setWordWrap(True)
            self.alerts_container.addWidget(label)

        if distracted:
            names = ", ".join(row["full_name"] for row in distracted[:3])
            label = QLabel(
                f"🟡  {len(distracted)} employee(s) with >1h distraction today "
                f"— {names}"
            )
            label.setObjectName("AlertText")
            label.setMinimumHeight(36)
            label.setWordWrap(True)
            self.alerts_container.addWidget(label)

        if not pending and not absent and not distracted:
            clear = QLabel("✅  All clear")
            clear.setObjectName("PillDone")
            self.alerts_container.addWidget(clear, 0, Qt.AlignLeft)
