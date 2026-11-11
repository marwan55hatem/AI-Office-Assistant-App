"""Where the server is.

Order: the OFFICE_API_URL environment variable (testing, a staging server), then the address the
installer was built with (``server_url.txt`` next to the bundled files, written by
``packaging/build.ps1 -ApiUrl``), then the local development server.
"""
import os

from app_paths import BUNDLE_DIR

DEFAULT_API_URL = "http://localhost:8000"
SERVER_URL_FILE = os.path.join(BUNDLE_DIR, "server_url.txt")


def _built_in_url():
    try:
        with open(SERVER_URL_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def api_url() -> str:
    return (os.environ.get("OFFICE_API_URL") or _built_in_url() or DEFAULT_API_URL).rstrip("/")


def use_local_database() -> bool:
    """OFFICE_BACKEND=local runs against the old single-PC SQLite file (development only)."""
    return os.environ.get("OFFICE_BACKEND", "").lower() == "local"
