"""Prove a backup can be restored: compare every table of a restored copy with the source.

    SOURCE_URL=postgresql+psycopg://...   # the database the dump was taken from
    RESTORED_URL=postgresql+psycopg://... # a scratch database the dump was restored into
    python scripts/restore_check.py

Prints one line per table (rows in source / rows in copy) and exits 1 on any difference.
Run it after `pg_restore` into a scratch database (docs/PRODUCTION.md, "Backups and restore").
"""
import os
import sys

from sqlalchemy import create_engine, text

TABLES_SQL = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"


def counts(url: str) -> dict:
    engine = create_engine(url)
    with engine.connect() as connection:
        tables = [row[0] for row in connection.execute(text(TABLES_SQL))]
        result = {t: connection.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in tables}
        result["(alembic version)"] = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    return result


def main() -> int:
    source, restored = counts(os.environ["SOURCE_URL"]), counts(os.environ["RESTORED_URL"])
    bad = 0
    for table in sorted(set(source) | set(restored)):
        same = source.get(table) == restored.get(table)
        bad += not same
        print(f"{'ok  ' if same else 'DIFF'} {table:28} {source.get(table)!s:>8} {restored.get(table)!s:>8}")
    print("restore check:", "PASSED" if not bad else f"FAILED ({bad} tables differ)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
