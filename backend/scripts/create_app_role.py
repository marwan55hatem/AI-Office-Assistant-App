"""Create (or update) the database role the application connects as, and grant it access.

The role is deliberately NOT a superuser and has NO BYPASSRLS, so PostgreSQL
Row-Level Security applies to every query the application runs.

    MIGRATIONS_DATABASE_URL=... APP_ROLE_PASSWORD=... python scripts/create_app_role.py

Run it once per database (before or after `alembic upgrade head`; it is idempotent).
The password is read from the environment and never printed.
"""
import os
import sys

from sqlalchemy import create_engine, text

ROLE = os.environ.get("APP_ROLE_NAME", "office_app")

GRANTS = f"""
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {ROLE};
"""


def main() -> int:
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL")
    password = os.environ.get("APP_ROLE_PASSWORD")
    if not owner_url or not password:
        print("Set MIGRATIONS_DATABASE_URL and APP_ROLE_PASSWORD", file=sys.stderr)
        return 2
    if not ROLE.replace("_", "").isalnum():
        print("APP_ROLE_NAME may contain only letters, digits and _", file=sys.stderr)
        return 2
    engine = create_engine(owner_url)
    with engine.begin() as connection:
        exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}).first()
        verb = "ALTER" if exists else "CREATE"
        # the password goes through format(%L) on the server, so it is quoted safely
        statement = connection.execute(text(
            f"SELECT format('{verb} ROLE {ROLE} LOGIN PASSWORD %L "
            "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT', CAST(:pw AS text))"),
            {"pw": password}).scalar()
        connection.execute(text(statement))
        connection.execute(text(GRANTS))
        has_version = connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        if has_version:
            connection.execute(text(f"REVOKE ALL ON alembic_version FROM {ROLE}"))
    print(f"role {ROLE}: {'updated' if exists else 'created'}, privileges granted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
