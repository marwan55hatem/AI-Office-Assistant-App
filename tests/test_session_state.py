"""The three session timers: exactly one counts each second, in a fixed priority order."""

import pytest

from detection.categories import (AWAY, DISTRACTION, FOCUS, SCREEN_DISTRACTION, SCREEN_IDLE,
                                  SCREEN_NEUTRAL, SCREEN_PRODUCTIVE)
from detection.session import SessionState


@pytest.fixture
def state():
    """A session whose camera is ready, with a person at the desk working in a neutral app."""
    s = SessionState(session_id=1, user_id=2)
    s.camera_ready = True
    s.person = True
    s.screen_category = SCREEN_NEUTRAL
    return s


def test_working_person_counts_as_focus(state):
    assert state.current_state() == FOCUS


def test_nobody_in_frame_is_away(state):
    state.person = False
    assert state.current_state() == AWAY


def test_phone_is_distraction(state):
    state.phone = True
    assert state.current_state() == DISTRACTION


def test_distracting_app_is_distraction(state):
    state.screen_category = SCREEN_DISTRACTION
    assert state.current_state() == DISTRACTION


def test_idle_screen_is_away(state):
    state.screen_category = SCREEN_IDLE
    assert state.current_state() == AWAY


def test_keyboard_idle_beats_everything(state):
    """Priority 1: asleep at the keyboard counts as away even with a face, a phone and a game."""
    state.input_idle = True
    state.phone = True
    state.screen_category = SCREEN_DISTRACTION
    assert state.current_state() == AWAY


def test_no_person_beats_phone_and_screen(state):
    """Priority 2: an empty chair is away, whatever else is detected."""
    state.person = False
    state.phone = True
    state.screen_category = SCREEN_DISTRACTION
    assert state.current_state() == AWAY


def test_phone_beats_screen_category(state):
    """Priority 3 over the screen rules: phone + productive app is still a distraction."""
    state.phone = True
    state.screen_category = SCREEN_PRODUCTIVE
    assert state.current_state() == DISTRACTION


@pytest.mark.parametrize("setup, expected", [
    ({}, FOCUS),
    ({"phone": True}, DISTRACTION),
    ({"person": False}, AWAY),
    ({"input_idle": True}, AWAY),
    ({"screen_category": SCREEN_DISTRACTION}, DISTRACTION),
])
def test_every_tick_adds_exactly_one_second_to_exactly_one_timer(state, setup, expected):
    for name, value in setup.items():
        setattr(state, name, value)
    before = (state.focus_seconds, state.distraction_seconds, state.away_seconds)
    state.tick()
    after = (state.focus_seconds, state.distraction_seconds, state.away_seconds)
    assert sum(after) - sum(before) == 1
    index = {FOCUS: 0, DISTRACTION: 1, AWAY: 2}[expected]
    assert after[index] - before[index] == 1
    assert state.last_tick_counted


def test_elapsed_is_the_sum_of_the_three_timers(state):
    for _ in range(5):
        state.tick()
    state.phone = True
    for _ in range(3):
        state.tick()
    state.person = False
    for _ in range(2):
        state.tick()
    assert (state.focus_seconds, state.distraction_seconds, state.away_seconds) == (5, 3, 2)
    assert state.elapsed_seconds == 10


def test_nothing_is_counted_while_the_camera_warms_up():
    s = SessionState(1, 2)               # camera_ready is False
    for _ in range(4):
        s.tick()
    assert s.elapsed_seconds == 0 and not s.last_tick_counted


def test_a_failed_camera_does_not_stall_the_timers():
    s = SessionState(1, 2)
    s.camera_failed = True
    s.person = True                      # the employee screen assumes presence when the camera is dead
    s.screen_category = SCREEN_NEUTRAL   # a fresh session starts 'idle', which would count as away
    s.tick()
    assert s.focus_seconds == 1


def test_screen_counters_follow_the_state(state):
    state.screen_category = SCREEN_PRODUCTIVE
    state.tick()
    state.screen_category = SCREEN_DISTRACTION
    state.tick()
    state.screen_category = SCREEN_IDLE
    state.tick()
    assert (state.screen_productive, state.screen_distracted, state.screen_idle) == (1, 1, 1)


def test_phone_distraction_is_not_counted_as_screen_distraction(state):
    state.phone = True
    state.screen_category = SCREEN_DISTRACTION
    state.tick()
    assert state.distraction_seconds == 1 and state.screen_distracted == 0


def test_state_changes_are_reported_once_and_never_on_the_first_tick(state):
    assert state.take_state_change() is None          # first look: nothing to log
    assert state.take_state_change() is None          # unchanged
    state.phone = True
    assert state.take_state_change() == DISTRACTION
    assert state.take_state_change() is None          # reported already
    state.phone = False
    assert state.take_state_change() == FOCUS
