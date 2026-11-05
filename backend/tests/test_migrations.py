"""The migrations build the whole schema from an empty database and match the models."""
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.db.models import TENANT_TABLES, Base
from tests.conftest import BACKEND, OWNER_URL

SCRATCH_DB = "office_migration_test"


def _config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["url"] = url
    return config


def test_upgrade_from_empty_downgrade_and_upgrade_again():
    admin = create_engine(OWNER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {SCRATCH_DB}"))
    url = make_url(OWNER_URL).set(database=SCRATCH_DB).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        command.upgrade(_config(url), "head")
        tables = set(inspect(engine).get_table_names())
        assert set(TENANT_TABLES) | {"companies"} <= tables
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            assert diff == [], f"models and migrations differ: {diff}"
            policies = connection.execute(text("SELECT count(*) FROM pg_policies")).scalar()
            forced = connection.execute(text(
                "SELECT count(*) FROM pg_class WHERE relforcerowsecurity AND relkind = 'r'")).scalar()
        assert policies == forced == len(TENANT_TABLES) + 1

        command.downgrade(_config(url), "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(_config(url), "head")
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)"))
        admin.dispose()
