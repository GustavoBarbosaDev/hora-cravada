import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.errors import EXCLUSION_VIOLATION, FOREIGN_KEY_VIOLATION, sqlstate
from tests.conftest import Databases

CHECK_VIOLATION = "23514"


@dataclass
class Company:
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    resource_id: uuid.UUID
    service_id: uuid.UUID


@pytest.fixture
async def companies(migrated_database: Databases) -> tuple[Company, Company]:
    """Duas empresas com filial, recurso e serviço, criadas pelo role dono."""
    engine = create_async_engine(migrated_database.admin_url)
    created = []
    async with engine.begin() as conn:
        for _ in range(2):
            ids = [uuid.uuid4() for _ in range(4)]
            company = Company(*ids)
            slug = f"t-{company.tenant_id.hex[:12]}"
            params = {"t": company.tenant_id, "b": company.branch_id, "r": company.resource_id}
            await conn.execute(
                text("INSERT INTO tenants (id, slug, name) VALUES (:t, :slug, :slug)"),
                {**params, "slug": slug},
            )
            await conn.execute(
                text(
                    "INSERT INTO branches (id, tenant_id, name, timezone)"
                    " VALUES (:b, :t, 'Centro', 'UTC')"
                ),
                params,
            )
            await conn.execute(
                text(
                    "INSERT INTO resources (id, tenant_id, branch_id, kind, name) "
                    "VALUES (:r, :t, :b, 'sala', 'Sala')"
                ),
                params,
            )
            await conn.execute(
                text(
                    "INSERT INTO services (id, tenant_id, name, duration_min) "
                    "VALUES (:s, :t, 'Aluguel', 60)"
                ),
                {**params, "s": company.service_id},
            )
            created.append(company)
    await engine.dispose()
    return created[0], created[1]


@pytest.fixture
async def conn(migrated_database: Databases) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(migrated_database.app_url)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def use_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


async def failure_code(conn: AsyncConnection, sql: str, params: dict[str, object]) -> str | None:
    with pytest.raises(DBAPIError) as raised:
        await conn.execute(text(sql), params)
    return sqlstate(raised.value)


async def test_resource_cannot_point_to_a_branch_of_another_tenant(
    conn: AsyncConnection, companies: tuple[Company, Company]
) -> None:
    mine, theirs = companies
    await use_tenant(conn, mine.tenant_id)

    code = await failure_code(
        conn,
        "INSERT INTO resources (tenant_id, branch_id, kind, name) VALUES (:t, :b, 'sala', 'X')",
        {"t": mine.tenant_id, "b": theirs.branch_id},
    )

    assert code == FOREIGN_KEY_VIOLATION


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO resource_services (tenant_id, resource_id, service_id) VALUES (:t, :r, :s)",
        "INSERT INTO availability_rules (tenant_id, resource_id, weekday, start_minute, end_minute)"
        " VALUES (:t, :r, 1, 540, 600)",
        "INSERT INTO availability_exceptions (tenant_id, resource_id, date, kind)"
        " VALUES (:t, :r, '2026-12-25', 'closed')",
    ],
)
async def test_children_cannot_point_to_a_resource_of_another_tenant(
    conn: AsyncConnection, companies: tuple[Company, Company], sql: str
) -> None:
    mine, theirs = companies
    await use_tenant(conn, mine.tenant_id)

    code = await failure_code(
        conn, sql, {"t": mine.tenant_id, "r": theirs.resource_id, "s": mine.service_id}
    )

    assert code == FOREIGN_KEY_VIOLATION


async def test_link_cannot_point_to_a_service_of_another_tenant(
    conn: AsyncConnection, companies: tuple[Company, Company]
) -> None:
    mine, theirs = companies
    await use_tenant(conn, mine.tenant_id)

    code = await failure_code(
        conn,
        "INSERT INTO resource_services (tenant_id, resource_id, service_id) VALUES (:t, :r, :s)",
        {"t": mine.tenant_id, "r": mine.resource_id, "s": theirs.service_id},
    )

    assert code == FOREIGN_KEY_VIOLATION


async def test_user_cannot_be_linked_to_a_resource_of_another_tenant(
    conn: AsyncConnection, companies: tuple[Company, Company]
) -> None:
    mine, theirs = companies
    await use_tenant(conn, mine.tenant_id)

    code = await failure_code(
        conn,
        "INSERT INTO users (tenant_id, email, password_hash, role, resource_id)"
        " VALUES (:t, 'a@b.com', 'x', 'professional', :r)",
        {"t": mine.tenant_id, "r": theirs.resource_id},
    )

    assert code == FOREIGN_KEY_VIOLATION


async def test_only_professionals_can_have_a_resource(
    conn: AsyncConnection, companies: tuple[Company, Company]
) -> None:
    mine, _ = companies
    await use_tenant(conn, mine.tenant_id)

    code = await failure_code(
        conn,
        "INSERT INTO users (tenant_id, email, password_hash, role, resource_id)"
        " VALUES (:t, 'a@b.com', 'x', 'reception', :r)",
        {"t": mine.tenant_id, "r": mine.resource_id},
    )

    assert code == CHECK_VIOLATION


async def test_database_rejects_overlapping_rules_without_the_application(
    conn: AsyncConnection, companies: tuple[Company, Company]
) -> None:
    mine, _ = companies
    await use_tenant(conn, mine.tenant_id)
    insert = (
        "INSERT INTO availability_rules (tenant_id, resource_id, weekday, start_minute, end_minute)"
        " VALUES (:t, :r, 1, :s, :e)"
    )
    params = {"t": mine.tenant_id, "r": mine.resource_id}
    await conn.execute(text(insert), {**params, "s": 540, "e": 720})

    adjacent = await conn.execute(text(insert), {**params, "s": 720, "e": 780})
    code = await failure_code(conn, insert, {**params, "s": 700, "e": 800})

    assert adjacent.rowcount == 1
    assert code == EXCLUSION_VIOLATION


@pytest.mark.parametrize(
    "values",
    [
        "'open', NULL, NULL",
        "'open', 540, NULL",
        "'closed', 540, NULL",
        "'closed', NULL, 600",
        "'closed', 600, 540",
        "'open', 540, 1441",
        "'folga', NULL, NULL",
    ],
)
async def test_database_rejects_inconsistent_exceptions(
    conn: AsyncConnection, companies: tuple[Company, Company], values: str
) -> None:
    mine, _ = companies
    await use_tenant(conn, mine.tenant_id)

    code = await failure_code(
        conn,
        "INSERT INTO availability_exceptions (tenant_id, date, kind, start_minute, end_minute)"
        f" VALUES (:t, '2026-12-25', {values})",
        {"t": mine.tenant_id},
    )

    assert code == CHECK_VIOLATION


async def test_owner_role_can_delete_a_tenant_with_all_its_catalog(
    migrated_database: Databases, companies: tuple[Company, Company]
) -> None:
    mine, theirs = companies
    engine = create_async_engine(migrated_database.admin_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO resource_services (tenant_id, resource_id, service_id)"
                " VALUES (:t, :r, :s)"
            ),
            {"t": mine.tenant_id, "r": mine.resource_id, "s": mine.service_id},
        )
        await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": mine.tenant_id})
        remaining = await conn.execute(
            text("SELECT count(*) FROM resources WHERE tenant_id = :t"), {"t": theirs.tenant_id}
        )
    await engine.dispose()

    assert remaining.scalar_one() == 1


async def test_deleting_a_branch_with_resources_is_restricted(
    conn: AsyncConnection, companies: tuple[Company, Company]
) -> None:
    mine, _ = companies
    await use_tenant(conn, mine.tenant_id)

    with pytest.raises(IntegrityError) as raised:
        await conn.execute(text("DELETE FROM branches WHERE id = :b"), {"b": mine.branch_id})

    assert sqlstate(raised.value) == FOREIGN_KEY_VIOLATION
