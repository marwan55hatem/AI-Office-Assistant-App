"""Per-session counters.

Pure in-memory state: it only counts, it never talks to the database or to the
UI.  ``EmployeeScreen`` owns the instance, feeds it the latest camera / screen
values through the worker-thread signals and calls :meth:`tick` once per second.

The session tracks exactly three *time* counters -- focus, distraction and away.
Every tick adds one second to exactly one of them, never to two:

    1. keyboard/mouse idle  -> away
    2. nobody in frame      -> away
    3. phone in frame       -> distraction
    4. distracting app      -> distraction
    5. screen idle          -> away
    6. otherwise            -> focus

``distractions`` (the old pickup *count*) is kept as an attribute so older code
still resolves it, but it is never incremented nor displayed any more.
"""

from typing import Optional

from detection.categories import (  # noqa: F401  (FOCUS / DISTRACTION / AWAY are re-exported)
    AWAY,
    DISTRACTION,
    FOCUS,
    SCREEN_DISTRACTION,
    SCREEN_IDLE,
    SCREEN_PRODUCTIVE,
)


class SessionState:
    """Time counters for one running session."""

    def __init__(self, session_id, user_id):
        self.session_id = session_id
        self.user_id = user_id

        # camera-derived
        self.person = False
        self.phone = False

        # screen-derived
        self.screen_title = ""
        self.screen_category = SCREEN_IDLE

        # input-derived (keyboard / mouse)
        self.input_idle = False
        self.idle_seconds = 0

        # camera availability: while the model warms up (or when it failed) the
        # absence of a detection must not be mistaken for "the user is away".
        self.camera_ready = False    # True once the first detection_update arrives
        self.camera_failed = False   # True if the camera thread reported an error

        # totals -- the three time counters
        self.focus_seconds = 0
        self.distraction_seconds = 0
        self.away_seconds = 0

        # legacy counter, kept for compatibility, never incremented
        self.distractions = 0

        # screen totals
        self.screen_productive = 0
        self.screen_distracted = 0
        self.screen_idle = 0

        # last state logged, so events are written on transitions only
        self._last_state = None

        # True only when the latest tick() actually incremented a timer.
        self.last_tick_counted = False

    @property
    def elapsed_seconds(self):
        """Wall-clock length of the session: every tick is one of the three."""
        return self.focus_seconds + self.distraction_seconds + self.away_seconds

    # ------------------------------------------------------------------ #
    #  Classification
    # ------------------------------------------------------------------ #
    def current_state(self) -> str:
        """Return 'focus', 'distraction' or 'away' for the present inputs."""
        if self.input_idle:
            # Asleep / away from the keyboard: the camera may still see a face,
            # but no work is happening.
            return AWAY
        if not self.person:
            return AWAY
        if self.phone:
            return DISTRACTION
        if self.screen_category == SCREEN_DISTRACTION:
            return DISTRACTION
        if self.screen_category == SCREEN_IDLE:
            return AWAY
        return FOCUS

    def tick(self) -> None:
        """Called once per second; adds one second to exactly one timer.

        While the camera is still warming up (loading YOLO takes a few seconds)
        no detection has arrived yet, so nothing is counted: otherwise every
        warm-up second would be recorded as "away".
        """
        self.last_tick_counted = False

        if not self.camera_ready and not self.camera_failed:
            # Camera still warming up - do not count this second yet.
            return

        state = self.current_state()

        if state == AWAY:
            self.away_seconds += 1
            if self.input_idle or self.screen_category == SCREEN_IDLE:
                self.screen_idle += 1
            self.last_tick_counted = True
            return

        if state == DISTRACTION:
            self.distraction_seconds += 1
            if self.screen_category == SCREEN_DISTRACTION and not self.phone:
                self.screen_distracted += 1
            self.last_tick_counted = True
            return

        self.focus_seconds += 1
        if self.screen_category == SCREEN_PRODUCTIVE:
            self.screen_productive += 1
        self.last_tick_counted = True

    def take_state_change(self) -> Optional[str]:
        """Return the new state when it differs from the last logged one.

        ``None`` means "nothing to log" -- either the state is unchanged or this
        is the very first tick (the spec: never log on the first tick).
        """
        state = self.current_state()
        previous, self._last_state = self._last_state, state
        if previous is None or previous == state:
            return None
        return state
