import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import build_engine


def installed_extensions(url: str) -> set[str]:
    async def query() -> set[str]:
        engine = build_engine(url)
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT extname FROM pg_extension"))
            names = {row[0] for row in rows}
        await engine.dispose()
        return names

    return asyncio.run(query())


def test_migrations_install_and_remove_required_extensions(use_database: str) -> None:
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    assert {"btree_gist", "pgcrypto"} <= installed_extensions(use_database)

    command.downgrade(config, "base")
    assert not {"btree_gist", "pgcrypto"} & installed_extensions(use_database)

    command.upgrade(config, "head")
