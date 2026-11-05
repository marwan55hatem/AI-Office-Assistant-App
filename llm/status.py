"""What to tell the user about the online AI model (chat header badge and Settings)."""

from typing import Tuple

OFF = "off"
OFFLINE = "missing"          # the badge styles reuse the old state names
READY = "ready"
LOADING = "loading"


def snapshot(enabled: bool, loading: bool = False, service=None) -> Tuple[str, str]:
    """``(state, text)`` for the header badge.  ``enabled`` is the on/off setting."""
    if not enabled:
        return OFF, "AI model: off — answers come from your own data only"
    if service is not None and not service.available():
        return OFFLINE, "AI model: offline — needs a connection"
    if loading:
        return LOADING, "AI model: connecting…"
    return READY, "AI model: online"
