"""Window-title classification and the WhatsApp time rule (no Windows API is touched)."""

from datetime import datetime, timedelta

import pytest

from detection import screen_monitor
from detection.categories import SCREEN_DISTRACTION, SCREEN_IDLE, SCREEN_NEUTRAL, SCREEN_PRODUCTIVE
from detection.screen_monitor import WHATSAPP_DISTRACTION_THRESHOLD_SECONDS, ScreenMonitor


@pytest.fixture
def monitor():
    return ScreenMonitor()


@pytest.mark.parametrize("title, expected", [
    ("main.py - Visual Studio Code", SCREEN_PRODUCTIVE),
    ("Quarterly report.docx - Word", SCREEN_PRODUCTIVE),
    ("Inbox - Gmail - Google Chrome", SCREEN_PRODUCTIVE),
    ("Netflix - Google Chrome", SCREEN_DISTRACTION),
    ("YouTube - Mozilla Firefox", SCREEN_DISTRACTION),
    ("Steam", SCREEN_DISTRACTION),
    ("Calculator", SCREEN_NEUTRAL),
    ("File Explorer", SCREEN_NEUTRAL),
    ("Some unknown program", SCREEN_NEUTRAL),
])
def test_classification_by_title(monitor, title, expected):
    assert monitor.classify(title) == expected


@pytest.mark.parametrize("title", ["", "   ", None])
def test_empty_title_is_idle(monitor, title):
    assert monitor.classify(title) == SCREEN_IDLE


def test_distraction_wins_when_a_title_matches_both_lists(monitor):
    assert monitor.classify("YouTube tutorial - Visual Studio Code docs") == SCREEN_DISTRACTION


def test_matching_ignores_case(monitor):
    assert monitor.classify("NETFLIX") == SCREEN_DISTRACTION
    assert monitor.classify("visual STUDIO code") == SCREEN_PRODUCTIVE


def test_whatsapp_is_not_listed_as_a_plain_keyword(monitor):
    """Plain classification says neutral; only the timed rule can make it a distraction."""
    assert monitor.classify("WhatsApp") == SCREEN_NEUTRAL


class _Clock:
    """A controllable ``datetime`` so the 90-second rule can be tested instantly."""

    def __init__(self):
        self.now_value = datetime(2026, 1, 1, 12, 0, 0)

    def now(self):
        return self.now_value

    def advance(self, seconds):
        self.now_value += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(screen_monitor, "datetime", clock)
    return clock


def sample(monitor, title):
    monitor.get_active_window_title = lambda: title
    return monitor.sample_with_timer()


def test_whatsapp_is_neutral_for_the_first_moments(monitor, clock):
    result = sample(monitor, "WhatsApp")
    assert result["category"] == SCREEN_NEUTRAL and result["whatsapp_elapsed"] == 0
    clock.advance(WHATSAPP_DISTRACTION_THRESHOLD_SECONDS - 1)
    assert sample(monitor, "WhatsApp")["category"] == SCREEN_NEUTRAL


def test_whatsapp_becomes_a_distraction_at_the_threshold(monitor, clock):
    sample(monitor, "WhatsApp")
    clock.advance(WHATSAPP_DISTRACTION_THRESHOLD_SECONDS)
    result = sample(monitor, "WhatsApp")
    assert result["category"] == SCREEN_DISTRACTION
    assert result["whatsapp_elapsed"] == WHATSAPP_DISTRACTION_THRESHOLD_SECONDS


def test_whatsapp_web_in_a_browser_counts_too(monitor, clock):
    sample(monitor, "(3) WhatsApp - Google Chrome")
    clock.advance(WHATSAPP_DISTRACTION_THRESHOLD_SECONDS + 5)
    assert sample(monitor, "(3) WhatsApp - Google Chrome")["category"] == SCREEN_DISTRACTION


def test_switching_away_resets_the_whatsapp_timer(monitor, clock):
    sample(monitor, "WhatsApp")
    clock.advance(80)
    sample(monitor, "main.py - Visual Studio Code")          # back to work
    clock.advance(30)
    result = sample(monitor, "WhatsApp")                       # a fresh start, not 110 s
    assert result["category"] == SCREEN_NEUTRAL and result["whatsapp_elapsed"] == 0


def test_sample_keeps_the_last_title_and_category(monitor, clock):
    sample(monitor, "Netflix")
    assert monitor.last_title == "Netflix" and monitor.last_category == SCREEN_DISTRACTION
