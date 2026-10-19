"""Employee workspace: collapsible sidebar + (Session | To Do | AI Helper).

:class:`EmployeeScreen` is the shell that owns the sidebar and a page stack;
:class:`SessionPage` holds the camera view, the session counters and the
START/STOP session logic that used to live directly on the screen.  The session
widgets are still reachable as ``page.camera_label``, ``page.focus_value_lbl``
and friends, and the shell forwards ``stop_session_if_running`` so quitting the
application still closes an open session.
"""


import logging
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.calendar_screen import CalendarScreen
from ui.shell import ShellNavigationMixin
from ui.sidebar import Sidebar

from detection.camera_thread import CameraThread
from detection.categories import SCREEN_DISTRACTION, SCREEN_IDLE, SCREEN_NEUTRAL, SCREEN_PRODUCTIVE
from detection.screen_monitor import WHATSAPP_DISTRACTION_THRESHOLD_SECONDS
from detection.screen_thread import ScreenThread
from detection.session import SessionState

logger = logging.getLogger(__name__)

CAMERA_IDLE_TEXT = "\U0001F4F7\n\nCamera Preview\n(activates when session starts)"
CAMERA_LIVE_TEXT = "\U0001F4F7\n\nCamera starting…\n(waiting for the first frame)"

PERSON_IDLE_TEXT = "🧑  Person"
PHONE_IDLE_TEXT = "\U0001F4F1  Phone"
INPUT_IDLE_TEXT = "\u23F8\uFE0F  Idle"
SCREEN_IDLE_TEXT = "\U0001F5A5\uFE0F  Screen"

#: How each screen category is shown: ``(badge text, name of the colour in ui.theme)``.
#: The colour is looked up by name when it is used, so a theme switch is honoured.
#: A new category is a new row here -- no ``if/elif`` to extend.
SCREEN_BADGES = {
    SCREEN_PRODUCTIVE: ("\uD83D\uDFE2  Screen: Productive", "SUCCESS"),
    SCREEN_DISTRACTION: ("\uD83D\uDFE1  Screen: Distracted", "WARNING"),
    SCREEN_IDLE: (SCREEN_IDLE_TEXT, "TEXT_MUTED"),
    SCREEN_NEUTRAL: ("\u26AA  Screen: Neutral", "TEXT_MUTED"),
}
CAMERA_ERROR_TEXT = "\u26A0  Camera unavailable"

STAT_BOX_HEIGHT = 92
SCREEN_BAR_WIDTH = 150

EMPLOYEE_ITEMS = [
    ("item", "session", "⏱️", "Session"),
    ("item", "calendar", "\U0001F4C5", "Calendar"),
    ("item", "todo", "\U0001F4CB", "To Do"),
    ("item", "ai_helper", "\U0001F916", "AI Helper"),
    ("item", "ai_chat", "\U0001F4AC", "AI Chat"),
    ("item", "settings", "⚙️", "Settings"),
    ("separator",),
]


class SessionPage(QWidget):
    """Camera + counters + START/STOP session (the previous main screen)."""

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 2, "full_name": "Marwan Hatem"}
        self.db = db
        self.full_name = self.user.get("full_name", "Employee")

        # Session state
        self.session_active = False
        self.session_state = None
        self.session_id = None

        # Worker threads
        self.camera_thread = None
        self.screen_thread = None
        self._stray_threads = []  # keeps threads alive that outlive stop()

        # Latest values for the UI
        self._last_frame = None

        # Mirrors of the session counters (kept for direct readers)
        self.focus_seconds = 0
        self.distraction_seconds = 0
        self.away_seconds = 0

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        self._build_ui()
        self._update_stats_ui()

        # Make sure a session is closed and the threads are stopped when the
        # application quits (the window manager does not call our slots).
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop_session_if_running)

    def refresh(self):
        """No database content on this page; kept so the shell can call it."""

    def _build_ui(self):
        # The shell's sidebar replaces the old top navbar and bottom nav, so the
        # page is just the camera column plus the statistics card.
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addLayout(self._build_content(), 1)


    def _build_content(self):
        content = QHBoxLayout()
        content.setContentsMargins(theme.SP_6, theme.SP_5, theme.SP_6, theme.SP_4)
        content.setSpacing(theme.SP_5)
        content.addWidget(self._build_left_column(), 6)
        content.addWidget(self._build_right_column(), 4)
        return content


    def _build_left_column(self):
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_3)

        camera_box = QFrame()
        camera_box.setObjectName("CameraBox")
        camera_box.setMinimumHeight(500)
        theme.apply_card_shadow(camera_box)

        camera_layout = QVBoxLayout(camera_box)
        camera_layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)

        self.camera_label = QLabel(CAMERA_IDLE_TEXT)
        self.camera_label.setObjectName("CameraPlaceholder")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setMinimumSize(200, 150)
        camera_layout.addWidget(self.camera_label)

        layout.addWidget(camera_box, 1)

        # One pill per signal: icon + short label + coloured status dot.
        pills = QHBoxLayout()
        pills.setSpacing(theme.SP_2)

        self.person_pill, self.person_badge, self.person_dot = self._make_pill(
            "🧑", "Person", "Live result of the YOLO person detection"
        )
        self.phone_pill, self.phone_badge, self.phone_dot = self._make_pill(
            "📱", "Phone", "Live result of the YOLO phone detection"
        )
        self.idle_pill, self.idle_badge, self.idle_dot = self._make_pill(
            "⏸️", "Idle", "No keyboard or mouse input for a while"
        )
        self.screen_pill, self.screen_pill_badge, self.screen_pill_dot = self._make_pill(
            "🖥️", "Screen", "Classification of the focused window"
        )
        for pill in (self.person_pill, self.phone_pill, self.idle_pill,
                     self.screen_pill):
            pills.addWidget(pill, 1)

        layout.addLayout(pills)

        return column


    def _make_pill(self, icon, label, tooltip):
        """Build a 28px status pill; returns ``(pill, text label, dot)``."""
        pill = QFrame()
        pill.setObjectName("PillBox")
        pill.setFixedHeight(40)
        pill.setToolTip(tooltip)

        row = QHBoxLayout(pill)
        row.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
        row.setSpacing(6)

        dot = QFrame()
        dot.setObjectName("Dot")
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            "background-color: %s; border: none; border-radius: 4px;" % theme.TEXT_MUTED
        )
        row.addWidget(dot)

        text = QLabel(f"{icon}  {label}")
        text.setObjectName("MutedLabel")
        # let the pill shrink instead of forcing the page wider than the window
        text.setMinimumWidth(1)
        row.addWidget(text)
        row.addStretch(1)

        # Keep them together so _set_badge() can recolour the dot.
        text.dot = dot
        return pill, text, dot


    def _build_right_column(self):
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumWidth(390)
        card.setMaximumWidth(440)
        theme.apply_card_shadow(card)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_5)
        card_layout.setSpacing(theme.SP_3)

        # The statistics scroll (six boxes plus the screen panel are taller than
        # a short window); the session button stays pinned below so it is always
        # reachable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ScrollContent")

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_2)

        self._add_timer(layout)
        self._add_time_totals(layout)
        self._add_active_app(layout)
        self._add_screen_bars(layout)

        layout.addStretch(1)

        scroll.setWidget(content)
        card_layout.addWidget(scroll, 1)

        self.session_button = QPushButton("▶   START SESSION")
        self.session_button.setObjectName("PrimaryButton")
        self.session_button.setMinimumHeight(60)
        self.session_button.setStyleSheet("font-size: 18px;")
        self.session_button.setCursor(Qt.PointingHandCursor)
        self.session_button.clicked.connect(self._toggle_session)
        card_layout.addWidget(self.session_button)

        footer = QLabel("🔒  All data stored locally on this device")
        footer.setObjectName("MutedLabel")
        footer.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(footer)

        return card

    def _add_timer(self, layout):
        """The big session timer with its caption."""
        caption = QLabel("SESSION TIMER")
        caption.setObjectName("StatLabel")
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)

        self.timer_label = QLabel("00 : 00 : 00")
        self.timer_label.setObjectName("TimerDisplay")
        self.timer_label.setAlignment(Qt.AlignCenter)
        timer_font = self.timer_label.font()
        timer_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.timer_label.setFont(timer_font)
        layout.addWidget(self.timer_label)

        layout.addSpacing(theme.SP_2)

    def _add_time_totals(self, layout):
        """The three stat boxes: time worked, distracted and away."""
        self.focus_value_lbl = self._add_stat_box(
            layout, "🟢  Time Worked", "00 : 00 : 00"
        )
        self.distraction_time_lbl = self._add_stat_box(
            layout, "🟡  Time Distracted", "00 : 00 : 00"
        )
        self.away_value_lbl = self._add_stat_box(
            layout, "🔴  Time Away", "00 : 00 : 00"
        )

        layout.addSpacing(theme.SP_2)

    def _add_active_app(self, layout):
        """The focused window's title and its classification pill."""
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        app_caption = QLabel("🖥️  ACTIVE APPLICATION")
        app_caption.setObjectName("SectionHeaderSmall")
        layout.addWidget(app_caption)

        self.active_app_label = QLabel("—")
        self.active_app_label.setObjectName("AppTitle")
        self.active_app_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.active_app_label.setWordWrap(True)
        self.active_app_label.setMaximumHeight(48)  # about two lines
        layout.addWidget(self.active_app_label)

        # `screen_badge` stays the classification pill in the right column; the
        # camera row has its own "Screen" pill that mirrors it.
        self.screen_badge = QLabel(SCREEN_IDLE_TEXT)
        self.screen_badge.setObjectName("PillMuted")
        self.screen_badge.setAlignment(Qt.AlignCenter)
        self.screen_badge.setToolTip("Classification of the focused window")
        layout.addWidget(self.screen_badge)

        layout.addSpacing(theme.SP_2)

    def _add_screen_bars(self, layout):
        """The three bars that split screen time into worked / distracted / idle."""
        self.screen_productive_lbl, self.screen_productive_bar = self._add_screen_bar(
            layout, "🟢  Worked", theme.SUCCESS
        )
        self.screen_distracted_lbl, self.screen_distracted_bar = self._add_screen_bar(
            layout, "🔴  Distr.", theme.DANGER
        )
        self.screen_idle_lbl, self.screen_idle_bar = self._add_screen_bar(
            layout, "⚪  Idle", theme.TEXT_MUTED
        )


    def _add_stat_box(self, parent_layout, title, value):
        """Add one compact "title ... value" stat box and return its value label."""
        box = QFrame()
        box.setObjectName("StatBox")
        box.setFixedHeight(STAT_BOX_HEIGHT)

        row = QHBoxLayout(box)
        row.setContentsMargins(theme.SP_4, 6, theme.SP_4, 6)
        row.setSpacing(theme.SP_2)

        title_label = QLabel(title)
        title_label.setObjectName("StatLabel")
        row.addWidget(title_label)
        row.addStretch(1)

        value_label = QLabel(value)
        value_label.setObjectName("StatNumber")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(value_label)

        parent_layout.addWidget(box)
        return value_label

    def _add_screen_bar(self, parent_layout, title, colour):
        """Add a "label -- proportional bar -- value" row.

        Returns ``(value_label, fill)`` so the caller can update both; the fill's
        width is the share of the tracked screen time.
        """
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(theme.SP_2)

        title_label = QLabel(title)
        title_label.setObjectName("FeedText")
        title_label.setFixedWidth(92)
        row.addWidget(title_label)

        track = QFrame()
        track.setObjectName("BarTrack")
        track.setFixedSize(SCREEN_BAR_WIDTH, 8)
        fill = QFrame(track)
        fill.setObjectName("BarFill")
        fill.setStyleSheet(
            "background-color: %s; border: none; border-radius: 4px;" % colour
        )
        fill.setGeometry(0, 0, 0, 8)
        row.addWidget(track)

        value_label = QLabel("00 : 00 : 00")
        value_label.setObjectName("SecondaryLabel")
        row.addWidget(value_label)
        row.addStretch(1)

        parent_layout.addWidget(holder)
        return value_label, fill


    @staticmethod
    def _badge_qss(color_hex):
        """Build the inline style for one badge state.

        ``ui/theme.py`` owns the application stylesheet and defines only the two
        static badge variants, so the coloured variants needed at runtime are
        generated here from the same palette constants.
        """
        color = QColor(color_hex)
        red, green, blue = color.red(), color.green(), color.blue()
        return (
            f"background-color: rgba({red}, {green}, {blue}, 40);"
            f" color: {color_hex};"
            f" border: 1px solid rgba({red}, {green}, {blue}, 130);"
            " border-radius: 8px; padding: 8px 14px;"
            f" font-size: {theme.SMALL_SIZE}px; font-weight: 600;"
        )


    def _set_badge(self, badge, text, color_hex):
        """Update one status indicator (coloured text, plus its pill dot).

        Labels that live inside a status pill carry a ``dot`` reference; those
        only recolour their text and the dot so the pill itself stays intact.
        Standalone badges (the screen classification in the stats card) keep the
        full coloured background.
        """
        badge.setText(text)
        dot = getattr(badge, "dot", None)
        if dot is None:
            badge.setStyleSheet(self._badge_qss(color_hex))
            return
        badge.setStyleSheet(
            "background: transparent; color: %s; font-size: %dpx; font-weight: 600;"
            % (color_hex, theme.SMALL_SIZE)
        )
        dot.setStyleSheet(
            "background-color: %s; border: none; border-radius: 4px;" % color_hex
        )


    def _reset_badges(self):
        self._set_badge(self.person_badge, PERSON_IDLE_TEXT, theme.TEXT_MUTED)
        self._set_badge(self.phone_badge, PHONE_IDLE_TEXT, theme.TEXT_MUTED)
        self._set_badge(self.idle_badge, INPUT_IDLE_TEXT, theme.TEXT_MUTED)
        self._set_badge(self.screen_pill_badge, SCREEN_IDLE_TEXT, theme.TEXT_MUTED)
        self._set_badge(self.screen_badge, SCREEN_IDLE_TEXT, theme.TEXT_MUTED)
        self.active_app_label.setText("—")
        for fill in (self.screen_productive_bar, self.screen_distracted_bar,
                     self.screen_idle_bar):
            fill.setFixedWidth(0)


    @staticmethod
    def _fmt_hms(seconds):
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return "%02d : %02d : %02d" % (hours, minutes, secs)


    def _toggle_session(self):
        if self.session_active:
            self._stop_session()
        else:
            self._start_session()


    def _start_session(self):
        if self.session_active:
            return
        self.session_active = True

        user_id = self.user.get("id")
        if self.db is not None and user_id is not None:
            try:
                self.session_id = self.db.create_session(user_id)
            except Exception:
                logger.warning("Could not create session", exc_info=True)
                self.session_id = None
        else:
            self.session_id = -1  # demo without a database

        # A brand-new SessionState every time: camera_ready / camera_failed are
        # False by default, so no state leaks in from a previous session.  Its
        # ``_last_state`` also starts as None, so the first tick logs no event.
        self.session_state = SessionState(self.session_id, user_id)
        self._last_frame = None

        self._update_stats_ui()
        self._reset_badges()

        self.session_button.setText("⏹   STOP SESSION")
        self.session_button.setObjectName("DangerButton")
        theme.repolish(self.session_button)

        self.camera_label.clear()
        self.camera_label.setText(CAMERA_LIVE_TEXT)
        self.camera_label.setObjectName("CameraPlaceholder")
        theme.repolish(self.camera_label)

        self.camera_thread = CameraThread(camera_index=0)
        self.camera_thread.frame_ready.connect(self._on_frame)
        self.camera_thread.detection_update.connect(self._on_detection)
        self.camera_thread.error.connect(self._on_camera_error)
        self.camera_thread.start()

        self.screen_thread = ScreenThread()
        self.screen_thread.screen_update.connect(self._on_screen)
        self.screen_thread.idle_update.connect(self._on_idle)
        self.screen_thread.start()

        self.timer.start()


    def _stop_worker(self, thread):
        """Stop one worker thread and dispose of it safely."""
        if thread is None:
            return
        thread.stop()
        if thread.isRunning():
            # The current inference outlived the grace period: keep a reference
            # (never destroy a running QThread) and delete it when it finishes.
            self._stray_threads.append(thread)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(
                lambda t=thread: self._stray_threads.remove(t)
                if t in self._stray_threads
                else None
            )
        else:
            thread.deleteLater()


    def _stop_session(self):
        if not self.session_active:
            return
        self.session_active = False
        self.timer.stop()

        camera_thread, self.camera_thread = self.camera_thread, None
        screen_thread, self.screen_thread = self.screen_thread, None
        self._stop_worker(camera_thread)
        self._stop_worker(screen_thread)

        state = self.session_state
        if (
            self.db is not None
            and state is not None
            and self.session_id
            and self.session_id > 0
        ):
            try:
                self.db.end_session(
                    self.session_id,
                    state.focus_seconds,
                    state.away_seconds,
                    distraction_seconds=state.distraction_seconds,
                    screen_productive=state.screen_productive,
                    screen_distracted=state.screen_distracted,
                    screen_idle=state.screen_idle,
                )
            except Exception:
                logger.warning("Could not save session", exc_info=True)

        # Dropping the state also stops late queued signals from repainting.
        self.session_state = None
        self.session_id = None

        self.session_button.setText("▶   START SESSION")
        self.session_button.setObjectName("")
        theme.repolish(self.session_button)

        self._last_frame = None
        self.camera_label.clear()
        self.camera_label.setText(CAMERA_IDLE_TEXT)
        self.camera_label.setObjectName("CameraPlaceholder")
        theme.repolish(self.camera_label)

        self._reset_badges()
        self._update_stats_ui()


    def stop_session_if_running(self):
        """Close the session (and stop the threads) before this screen goes away."""
        if self.session_active:
            self._stop_session()
        if self.timer.isActive():
            self.timer.stop()


    def _on_frame(self, frame):
        if self.session_state is None or frame is None:
            return

        import cv2
        from PyQt5.QtGui import QImage, QPainter, QPainterPath, QPixmap

        self._last_frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data, width, height, channels * width, QImage.Format_RGB888
        )
        pixmap = QPixmap.fromImage(image).scaled(
            self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # Round the frame's corners to match the CameraBox radius.
        rounded = QPixmap(pixmap.size())
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), 16, 16)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()

        self.camera_label.setPixmap(rounded)


    def _on_detection(self, person, phone):
        if self.session_state is None:
            return
        self.session_state.person = person
        self.session_state.phone = phone
        # First detection of the session: the model is loaded, so the tick loop
        # may start counting seconds.
        self.session_state.camera_ready = True

        if person:
            self._set_badge(self.person_badge, "✓  Person Detected", theme.SUCCESS)
        else:
            self._set_badge(self.person_badge, "✗  Not Detected", theme.DANGER)

        if phone:
            self._set_badge(self.phone_badge, "📱  Phone Detected", theme.WARNING)
        else:
            self._set_badge(self.phone_badge, PHONE_IDLE_TEXT, theme.TEXT_MUTED)


    def _on_camera_error(self, message):
        if self.session_state is not None:
            # No camera for this session: mark it failed *and* ready so the tick
            # loop resumes and the screen/idle rules keep counting seconds.
            self.session_state.camera_failed = True
            self.session_state.camera_ready = True
        if not self.session_active:
            return

        self.camera_label.clear()
        self.camera_label.setText(f"⚠️  Camera error:\n{message}")
        self.camera_label.setObjectName("CameraPlaceholder")
        theme.repolish(self.camera_label)
        self._set_badge(self.person_badge, CAMERA_ERROR_TEXT, theme.DANGER)

        QMessageBox.warning(self, "Camera", message)


    def _on_idle(self, is_idle, idle_secs):
        """Keyboard/mouse idleness reported by the screen thread."""
        if self.session_state is None:
            return

        self.session_state.input_idle = is_idle
        self.session_state.idle_seconds = idle_secs

        if is_idle:
            self._set_badge(self.idle_badge, f"⏸️  Idle {idle_secs}s", theme.WARNING)
        else:
            self._set_badge(self.idle_badge, INPUT_IDLE_TEXT, theme.TEXT_MUTED)


    def _on_screen(self, title, category, whatsapp_elapsed=0):
        if self.session_state is None:
            return
        self.session_state.screen_title = title
        self.session_state.screen_category = category

        short = (title[:60] + "…") if len(title) > 60 else (title or "—")
        self.active_app_label.setText(short)

        # WhatsApp is neutral until it has been focused for the threshold; show
        # the remaining seconds so the user can see it coming.
        if category == SCREEN_NEUTRAL and "whatsapp" in (title or "").lower():
            remaining = max(
                0, WHATSAPP_DISTRACTION_THRESHOLD_SECONDS - int(whatsapp_elapsed)
            )
            self._set_screen_badges(f"🟡  WhatsApp — distracted in {remaining}s", theme.WARNING)
            return

        text, colour_name = SCREEN_BADGES.get(category, SCREEN_BADGES[SCREEN_NEUTRAL])
        self._set_screen_badges(text, getattr(theme, colour_name))

    def _set_screen_badges(self, text, colour):
        """Show ``text`` on both screen badges (the card and the pill)."""
        self._set_badge(self.screen_badge, text, colour)
        self._set_badge(self.screen_pill_badge, text, colour)


    def _tick(self):
        if self.session_state is None:
            return

        if self.session_state.camera_failed:
            # Without a camera every second would count as "away", which would
            # make the screen monitoring useless.  Treat the employee as present
            # so the screen classification drives the counters instead.
            self.session_state.person = True
            self.session_state.phone = False

        self.session_state.tick()
        self._update_stats_ui()


    def _update_stats_ui(self):
        state = self.session_state

        focus = state.focus_seconds if state else 0
        distraction = state.distraction_seconds if state else 0
        away = state.away_seconds if state else 0
        screen_productive = state.screen_productive if state else 0
        screen_distracted = state.screen_distracted if state else 0
        screen_idle = state.screen_idle if state else 0

        # The session timer is the whole session: focus + distraction + away.
        self.timer_label.setText(self._fmt_hms(focus + distraction + away))
        self.focus_value_lbl.setText(self._fmt_hms(focus))
        self.distraction_time_lbl.setText(self._fmt_hms(distraction))
        self.away_value_lbl.setText(self._fmt_hms(away))
        self.screen_productive_lbl.setText(self._fmt_hms(screen_productive))
        self.screen_distracted_lbl.setText(self._fmt_hms(screen_distracted))
        self.screen_idle_lbl.setText(self._fmt_hms(screen_idle))

        # Bars show each bucket's share of the tracked screen time (cosmetic).
        tracked = screen_productive + screen_distracted + screen_idle
        for fill, seconds in (
            (self.screen_productive_bar, screen_productive),
            (self.screen_distracted_bar, screen_distracted),
            (self.screen_idle_bar, screen_idle),
        ):
            width = int(SCREEN_BAR_WIDTH * seconds / tracked) if tracked else 0
            fill.setFixedWidth(max(0, min(SCREEN_BAR_WIDTH, width)))

        # Mirrored for callers that read the counters straight off the screen.
        self.focus_seconds = focus
        self.distraction_seconds = distraction
        self.away_seconds = away

        if state is not None and getattr(state, "last_tick_counted", False):
            self._log_transitions(state)


    def _log_transitions(self, state):
        """Write one event per state *change* (never one per tick).

        ``SessionState`` owns the tri-state (focus / distraction / away) and
        reports a change only when it actually differs from the previous tick --
        the very first tick is never logged.
        """
        if self.db is not None and self.session_id and self.session_id > 0:
            try:
                new_state = state.take_state_change()
                if new_state is not None:
                    self.db.log_event(self.session_id, new_state)
            except Exception:
                logger.warning("log_event failed", exc_info=True)




class EmployeeScreen(ShellNavigationMixin, QWidget):
    """Employee workspace shell: sidebar on the left, page stack on the right."""

    logout_requested = pyqtSignal()
    open_todo = pyqtSignal()
    open_ai_helper = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 2, "full_name": "Marwan Hatem"}
        self.db = db
        self.full_name = self.user.get("full_name", "Employee")

        self.sidebar = Sidebar(user=self.user, items=EMPLOYEE_ITEMS)
        self.sidebar.navigate.connect(self._navigate)
        self.sidebar.logout_requested.connect(self.logout_requested)

        from ui.ai_chat_screen import AIChatScreen
        from ui.ai_helper_screen import AIHelperScreen
        from ui.settings_screen import SettingsScreen
        from ui.todo_screen import TodoScreen

        self.session_page = SessionPage(user=self.user, db=self.db)
        self.todo_page = TodoScreen(user=self.user, db=self.db)
        self.ai_helper_page = AIHelperScreen(user=self.user, db=self.db)
        self.ai_chat_page = AIChatScreen(user=self.user, db=self.db)
        self.settings_page = SettingsScreen(user=self.user, db=self.db)
        self.settings_page.profile_updated.connect(self._on_profile_updated)
        self.calendar_page = CalendarScreen(user=self.user, db=self.db)

        self.stack = QStackedWidget()
        self._page_index = {}
        for key, page in (
            ("session", self.session_page),
            ("calendar", self.calendar_page),
            ("todo", self.todo_page),
            ("ai_helper", self.ai_helper_page),
            ("ai_chat", self.ai_chat_page),
            ("settings", self.settings_page),
        ):
            self._page_index[key] = self.stack.addWidget(page)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(self.stack, 1)

        # Calendar badge: today's event count, refreshed every 30 s.
        self.badge_timer = QTimer(self)
        self.badge_timer.setInterval(30000)
        self.badge_timer.timeout.connect(self._refresh_calendar_badge)
        self.badge_timer.start()
        self.calendar_page.changed.connect(self._refresh_calendar_badge)
        self._refresh_calendar_badge()

        self._navigate("session")

    # ------------------------------------------------------------------ #
    #  Navigation
    # ------------------------------------------------------------------ #
    def _on_profile_updated(self, full_name, _username):
        """The Settings page saved a new name: show it in the sidebar."""
        self.full_name = full_name
        self.sidebar.set_user(full_name)

    # ------------------------------------------------------------------ #
    #  Session passthroughs (the previous single-screen API)
    # ------------------------------------------------------------------ #
    def stop_session_if_running(self):
        """Stop the running session, if any (called before the screen is replaced)."""
        return self.session_page.stop_session_if_running()

    @property
    def session_button(self):
        """Alias of ``session_page.session_button`` (kept from the single-screen API)."""
        return self.session_page.session_button

    @property
    def session_active(self):
        """Alias of ``session_page.session_active`` (kept from the single-screen API)."""
        return self.session_page.session_active

    @property
    def session_state(self):
        """Alias of ``session_page.session_state`` (kept from the single-screen API)."""
        return self.session_page.session_state

    @property
    def session_id(self):
        """Alias of ``session_page.session_id`` (kept from the single-screen API)."""
        return self.session_page.session_id

    @property
    def camera_label(self):
        """Alias of ``session_page.camera_label`` (kept from the single-screen API)."""
        return self.session_page.camera_label

    @property
    def focus_value_lbl(self):
        """Alias of ``session_page.focus_value_lbl`` (kept from the single-screen API)."""
        return self.session_page.focus_value_lbl

    @property
    def away_value_lbl(self):
        """Alias of ``session_page.away_value_lbl`` (kept from the single-screen API)."""
        return self.session_page.away_value_lbl

    @property
    def distraction_time_lbl(self):
        """Alias of ``session_page.distraction_time_lbl`` (kept from the single-screen API)."""
        return self.session_page.distraction_time_lbl

    @property
    def timer_label(self):
        """Alias of ``session_page.timer_label`` (kept from the single-screen API)."""
        return self.session_page.timer_label

    @property
    def focus_seconds(self):
        """Alias of ``session_page.focus_seconds`` (kept from the single-screen API)."""
        return self.session_page.focus_seconds

    @property
    def distraction_seconds(self):
        """Alias of ``session_page.distraction_seconds`` (kept from the single-screen API)."""
        return self.session_page.distraction_seconds

    @property
    def away_seconds(self):
        """Alias of ``session_page.away_seconds`` (kept from the single-screen API)."""
        return self.session_page.away_seconds
