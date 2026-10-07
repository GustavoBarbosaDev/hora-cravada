import asyncio
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

APP_ROLE = "hora_app"
APP_PASSWORD = "hora_app"
JWT_SECRET = "segredo-de-teste-com-tamanho-suficiente"


@dataclass(frozen=True)
class Databases:
    admin_url: str
    app_url: str


@pytest.fixture(scope="session")
def server_url() -> Iterator[str]:
    """Usa TEST_DATABASE_URL quando existe (CI, compose); senão sobe um Postgres descartável."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


def create_database(server_url: str) -> Databases:
    name = f"hc_{uuid.uuid4().hex[:12]}"

    async def run() -> None:
        engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
        await engine.dispose()

    asyncio.run(run())
    admin = make_url(server_url).set(database=name)
    app = admin.set(username=APP_ROLE, password=APP_PASSWORD)
    return Databases(
        admin.render_as_string(hide_password=False), app.render_as_string(hide_password=False)
    )


def migrate(databases: Databases, revision: str = "head") -> None:
    with pytest.MonkeyPatch.context() as patch:
        point_settings_at(patch, databases)
        command.upgrade(Config("alembic.ini"), revision)


def point_settings_at(patch: pytest.MonkeyPatch, databases: Databases) -> None:
    patch.setenv("MIGRATION_DATABASE_URL", databases.admin_url)
    patch.setenv("DATABASE_URL", databases.app_url)
    patch.setenv("JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()


@pytest.fixture
def use_database(server_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Databases]:
    """Banco novo e sem migrations, para os testes que controlam o schema."""
    databases = create_database(server_url)
    point_settings_at(monkeypatch, databases)
    yield databases
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def shared_database(server_url: str) -> Databases:
    databases = create_database(server_url)
    migrate(databases)
    return databases


@pytest.fixture
def migrated_database(
    shared_database: Databases, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Databases]:
    """Banco já migrado e compartilhado; cada teste cria os próprios tenants com slug único."""
    point_settings_at(monkeypatch, shared_database)
    yield shared_database
    get_settings.cache_clear()
