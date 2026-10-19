"""Where the application finds its files -- in development and when installed.

Two kinds of location:

* **read-only, shipped with the app** (code, models, icons): ``BUNDLE_DIR``.  In a
  PyInstaller build that is ``sys._MEIPASS`` (the ``_internal`` folder next to the exe);
  in development it is the project folder.
* **writable, per Windows user** (database, logs): ``USER_DATA_DIR``.  Installed
  under ``C:\\Program Files`` the app may not write next to itself, so a frozen build
  uses ``%LOCALAPPDATA%\\OfficeAssistant``; development keeps using ``<project>/data``.

Both can be overridden with the environment variables ``OFFICE_MODELS_DIR`` and
``OFFICE_DATA_DIR`` (handy for tests and for a portable copy).
"""

import os
import sys

APP_NAME = "OfficeAssistant"
FROZEN = bool(getattr(sys, "frozen", False))

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = getattr(sys, "_MEIPASS", PROJECT_ROOT)

MODELS_DIR = os.environ.get("OFFICE_MODELS_DIR") or os.path.join(BUNDLE_DIR, "models")
HF_MODELS_DIR = os.path.join(MODELS_DIR, "hf")          # BART + MarianMT copies (tools/fetch_models.py)
ASSETS_DIR = os.path.join(BUNDLE_DIR, "assets")
APP_ICON = os.path.join(ASSETS_DIR, "icons", "app.ico")


def _user_data_dir():
    override = os.environ.get("OFFICE_DATA_DIR")
    if override:
        return override
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    return os.path.join(PROJECT_ROOT, "data")


USER_DATA_DIR = _user_data_dir()
LOG_DIR = os.path.join(USER_DATA_DIR, "logs")


def hf_model(repo_id):
    """``(name_or_path, local_only)`` for a Hugging Face model.

    The local copy in ``models/hf/<name>`` wins when it exists (the installed app is
    offline); otherwise the hub id is returned and transformers uses its own cache.
    """
    local = os.path.join(HF_MODELS_DIR, repo_id.split("/")[-1])
    if os.path.isfile(os.path.join(local, "config.json")):
        return local, True
    return repo_id, False
