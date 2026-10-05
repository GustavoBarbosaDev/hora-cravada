import os
from collections.abc import Iterator

import pytest

from app.config import get_settings


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Usa TEST_DATABASE_URL quando existe (CI, compose); senão sobe um Postgres descartável."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture
def use_database(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()
