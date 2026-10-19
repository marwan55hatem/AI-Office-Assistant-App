"""What to tell the user about the language model, without importing PyTorch.

The chat screen shows this in its header and the Settings page shows it too.  The
model manager is only looked at if the app already imported it (it pulls in torch,
which is slow), so showing the status never makes the app start slower.
"""

import os
import sys
from typing import Tuple

from llm import config

OFF = "off"
MISSING = "missing"
IDLE = "idle"
LOADING = "loading"
READY = "ready"
SLOW = "slow"


def model_files_present() -> bool:
    """True when the downloaded model files are on disk."""
    return os.path.isfile(os.path.join(config.MODEL_DIR, "model.safetensors")) and \
        os.path.isfile(os.path.join(config.MODEL_DIR, "config.json"))


def snapshot(enabled: bool, loading: bool = False) -> Tuple[str, str]:
    """``(state, text)`` for the header badge.  ``enabled`` is the on/off setting."""
    if not enabled:
        return OFF, "AI model: off \u2014 answers come from your own data only"
    if not model_files_present():
        return MISSING, "AI model: not installed"
    module = sys.modules.get("llm.model_manager")
    manager = module.get_manager() if module is not None else None
    if loading:
        return LOADING, "AI model: loading\u2026"
    if manager is not None and manager.loaded:
        if manager.device == "cuda":
            return READY, "AI model: ready \u00b7 GPU"
        return SLOW, "AI model: slow mode \u00b7 CPU (not enough free GPU memory)"
    return IDLE, "AI model: loads on the first general question"
