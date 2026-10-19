"""User preferences that are not about looks (the theme lives in ``ui.theme``).

Stored with ``QSettings`` next to the theme.  Currently one switch: whether the AI
Chat may use the local language model for general questions.
"""

import logging

from PyQt5.QtCore import QSettings

from ui import theme

logger = logging.getLogger(__name__)

AI_MODEL_KEY = "ai/use_model"


def _settings():
    return QSettings(theme.SETTINGS_ORGANISATION, theme.SETTINGS_APPLICATION)


def use_ai_model():
    """The user's choice (default: on)."""
    try:
        value = _settings().value(AI_MODEL_KEY, True)
    except Exception:
        return True
    return str(value).lower() not in ("false", "0", "no", "off")


def set_use_ai_model(enabled):
    """Remember the Settings switch for the AI model."""
    try:
        settings = _settings()
        settings.setValue(AI_MODEL_KEY, bool(enabled))
        settings.sync()
    except Exception:
        logger.warning("Could not save the AI model preference", exc_info=True)


def forced_off():
    """True when the model is switched off from outside (environment OFFICE_LLM=0)."""
    from chat.config import LLM_ENABLED

    return not LLM_ENABLED


def model_enabled():
    """Is the language model allowed right now?  (Preference AND not forced off.)"""
    return use_ai_model() and not forced_off()
