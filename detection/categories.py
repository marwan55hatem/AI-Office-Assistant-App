"""Names shared by the detection code, the session counters and the screens.

Two small vocabularies, kept in one place so that a typo cannot silently create a
third state:

* what the *screen* shows (:data:`SCREEN_CATEGORIES`) -- decided from the window title;
* what a session second *counts as* (:data:`SESSION_STATES`) -- focus, distraction or away.
  These are also the ``event_type`` values stored in the ``events`` table.
"""

# What the active window is (see ``ScreenMonitor.classify``).
SCREEN_PRODUCTIVE = "productive"
SCREEN_NEUTRAL = "neutral"
SCREEN_DISTRACTION = "distraction"
SCREEN_IDLE = "idle"
SCREEN_CATEGORIES = (SCREEN_PRODUCTIVE, SCREEN_NEUTRAL, SCREEN_DISTRACTION, SCREEN_IDLE)

# What one second of a session counts as (see ``SessionState.tick``).
FOCUS = "focus"
DISTRACTION = "distraction"
AWAY = "away"
SESSION_STATES = (FOCUS, DISTRACTION, AWAY)
