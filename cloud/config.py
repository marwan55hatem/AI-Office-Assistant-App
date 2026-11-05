"""Where the server is. Set OFFICE_API_URL to override (e.g. a staging server)."""
import os

DEFAULT_API_URL = "http://localhost:8000"


def api_url() -> str:
    return os.environ.get("OFFICE_API_URL", DEFAULT_API_URL).rstrip("/")


def use_local_database() -> bool:
    """OFFICE_BACKEND=local runs against the old single-PC SQLite file (development only)."""
    return os.environ.get("OFFICE_BACKEND", "").lower() == "local"
