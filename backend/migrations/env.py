import asyncio

from alembic import context
from sqlalchemy.engine import Connection

import app.auth.models  # noqa: F401
import app.tenants.models  # noqa: F401
from app.config import get_settings
from app.db.base import Base
from app.db.session import build_engine

config = context.config
target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = build_engine(get_settings().migration_database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise SystemExit("Migrations offline não são suportadas.")
run_migrations_online()
