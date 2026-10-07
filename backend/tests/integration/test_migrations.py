import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import build_engine
from tests.conftest import Databases


def query_names(url: str, sql: str) -> set[str]:
    async def query() -> set[str]:
        engine = build_engine(url)
        async with engine.connect() as conn:
            names = {row[0] for row in await conn.execute(text(sql))}
        await engine.dispose()
        return names

    return asyncio.run(query())


def test_migrations_install_and_remove_required_extensions(use_database: Databases) -> None:
    config = Config("alembic.ini")
    sql = "SELECT extname FROM pg_extension"

    command.upgrade(config, "head")
    assert {"btree_gist", "pgcrypto"} <= query_names(use_database.admin_url, sql)

    command.downgrade(config, "base")
    assert not {"btree_gist", "pgcrypto"} & query_names(use_database.admin_url, sql)

    command.upgrade(config, "head")


def test_migrations_create_and_drop_tenant_tables(use_database: Databases) -> None:
    config = Config("alembic.ini")
    sql = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    expected = {"tenants", "branches", "users", "refresh_tokens"}

    command.upgrade(config, "head")
    assert expected <= query_names(use_database.admin_url, sql)

    command.downgrade(config, "0001")
    assert not expected & query_names(use_database.admin_url, sql)
