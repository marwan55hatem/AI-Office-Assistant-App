"""Container entry point: bring the database up to date, then start the API.

1. ``alembic upgrade head`` as the database owner (``MIGRATIONS_DATABASE_URL``), when it is set;
2. create or update the restricted app role (``APP_ROLE_PASSWORD``), when it is set -- the API
   itself connects as that role (``DATABASE_URL``), so Row-Level Security applies to it;
3. start uvicorn on ``$PORT`` (hosts such as Render set it), trusting the host's proxy for the
   client address (rate limits) and the scheme.

Nothing secret is printed. A failed migration stops the start, so a half-migrated database is
never served.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.environ.get("MIGRATIONS_DATABASE_URL"):
        print("start: applying database migrations", flush=True)
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=HERE, check=True)
        if os.environ.get("APP_ROLE_PASSWORD"):
            subprocess.run([sys.executable, str(HERE / "scripts" / "create_app_role.py")], cwd=HERE, check=True)
    else:
        print("start: MIGRATIONS_DATABASE_URL not set, skipping migrations", flush=True)
    port = os.environ.get("PORT", "8000")
    os.execvp(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port,
                               "--proxy-headers", "--forwarded-allow-ips", os.environ.get("FORWARDED_ALLOW_IPS", "*"),
                               "--no-server-header"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
