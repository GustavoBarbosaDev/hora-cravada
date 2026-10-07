import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.conftest import Databases


@pytest.fixture
async def app_conn(migrated_database: Databases) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(migrated_database.app_url)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


@pytest.fixture
async def two_tenants(migrated_database: Databases) -> tuple[uuid.UUID, uuid.UUID]:
    """Dois tenants, cada um com um usuário e uma filial, criados pelo role dono."""
    engine = create_async_engine(migrated_database.admin_url)
    ids = (uuid.uuid4(), uuid.uuid4())
    async with engine.begin() as conn:
        for tenant_id in ids:
            slug = f"t-{tenant_id.hex[:12]}"
            await conn.execute(
                text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :slug)"),
                {"id": tenant_id, "slug": slug},
            )
            await conn.execute(
                text(
                    "INSERT INTO users (tenant_id, email, password_hash, role) "
                    "VALUES (:t, :email, 'x', 'owner')"
                ),
                {"t": tenant_id, "email": f"dono@{slug}.com.br"},
            )
            await conn.execute(
                text(
                    "INSERT INTO branches (tenant_id, name, timezone) VALUES (:t, 'Centro', 'UTC')"
                ),
                {"t": tenant_id},
            )
    await engine.dispose()
    return ids


async def use_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


async def test_unfiltered_query_returns_only_rows_of_the_current_tenant(
    app_conn: AsyncConnection, two_tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_a, _ = two_tenants
    await use_tenant(app_conn, tenant_a)

    users = await app_conn.execute(text("SELECT tenant_id FROM users"))
    branches = await app_conn.execute(text("SELECT tenant_id FROM branches"))

    assert {row[0] for row in users} == {tenant_a}
    assert {row[0] for row in branches} == {tenant_a}


async def test_query_without_tenant_context_returns_no_rows(
    app_conn: AsyncConnection, two_tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    result = await app_conn.execute(text("SELECT count(*) FROM users"))

    assert result.scalar_one() == 0


async def test_context_does_not_leak_past_the_end_of_the_transaction(
    app_conn: AsyncConnection, two_tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    await use_tenant(app_conn, two_tenants[0])
    await app_conn.commit()

    result = await app_conn.execute(text("SELECT count(*) FROM users"))

    assert result.scalar_one() == 0


async def test_update_and_delete_cannot_touch_another_tenants_rows(
    app_conn: AsyncConnection, two_tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_a, tenant_b = two_tenants
    await use_tenant(app_conn, tenant_a)

    updated = await app_conn.execute(
        text("UPDATE users SET role = 'professional' WHERE tenant_id = :t"), {"t": tenant_b}
    )
    deleted = await app_conn.execute(
        text("DELETE FROM branches WHERE tenant_id = :t"), {"t": tenant_b}
    )

    assert updated.rowcount == 0
    assert deleted.rowcount == 0


async def test_insert_for_another_tenant_is_rejected(
    app_conn: AsyncConnection, two_tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_a, tenant_b = two_tenants
    await use_tenant(app_conn, tenant_a)

    with pytest.raises(DBAPIError, match="row-level security"):
        await app_conn.execute(
            text("INSERT INTO branches (tenant_id, name, timezone) VALUES (:t, 'Invasora', 'UTC')"),
            {"t": tenant_b},
        )


async def test_app_role_cannot_bypass_row_level_security(app_conn: AsyncConnection) -> None:
    row = (
        await app_conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()

    assert tuple(row) == (False, False)


async def test_every_table_with_tenant_id_forces_row_level_security(
    migrated_database: Databases,
) -> None:
    engine = create_async_engine(migrated_database.admin_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
        )
        tables = {row[0]: tuple(row[1:]) for row in rows}
    await engine.dispose()

    assert tables, "nenhuma tabela com tenant_id encontrada"
    assert all(flags == (True, True, True) for flags in tables.values()), tables


async def test_concurrent_connections_keep_separate_tenant_contexts(
    migrated_database: Databases, two_tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    engine = create_async_engine(migrated_database.app_url)

    async def visible_tenants(tenant_id: uuid.UUID) -> set[uuid.UUID]:
        async with engine.connect() as conn:
            await use_tenant(conn, tenant_id)
            await asyncio.sleep(0.05)
            return {row[0] for row in await conn.execute(text("SELECT tenant_id FROM users"))}

    first, second = await asyncio.gather(
        visible_tenants(two_tenants[0]), visible_tenants(two_tenants[1])
    )
    await engine.dispose()

    assert first == {two_tenants[0]}
    assert second == {two_tenants[1]}
