import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.deps import TenantSession
from app.config import Settings
from app.core.security import Principal, create_access_token, verify_password
from app.main import create_app
from app.tenants.deps import PublicSession
from tests.conftest import JWT_SECRET, Databases

PASSWORD = "senha-forte-123"


@dataclass
class Company:
    slug: str
    owner_email: str
    owner_id: str
    tenant_id: str


@pytest.fixture
def app(migrated_database: Databases) -> FastAPI:
    app = create_app()

    @app.get("/public/{slug}/user-count")
    async def user_count(session: PublicSession) -> dict[str, int]:
        total = await session.scalar(text("SELECT count(*) FROM users"))
        return {"users": total or 0}

    @app.get("/panel/user-count")
    async def panel_user_count(session: TenantSession) -> dict[str, int]:
        total = await session.scalar(text("SELECT count(*) FROM users"))
        return {"users": total or 0}

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def signup(client: AsyncClient, name: str = "Barbearia do Seu Zé") -> Company:
    slug = f"t-{uuid.uuid4().hex[:12]}"
    email = f"dono@{slug}.com.br"
    response = await client.post(
        "/tenants",
        json={
            "tenant_name": name,
            "slug": slug,
            "owner_email": email,
            "owner_password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Company(slug, email, body["owner_id"], body["tenant"]["id"])


async def login(client: AsyncClient, company: Company, email: str | None = None) -> dict[str, str]:
    response = await client.post(
        "/auth/login",
        json={
            "tenant_slug": company.slug,
            "email": email or company.owner_email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    tokens: dict[str, str] = response.json()
    return tokens


def bearer(tokens: dict[str, str]) -> dict[str, str]:
    return {"authorization": f"Bearer {tokens['access_token']}"}


async def test_signup_creates_tenant_with_an_owner_who_can_log_in(client: AsyncClient) -> None:
    company = await signup(client)

    tokens = await login(client, company)
    me = await client.get("/auth/me", headers=bearer(tokens))

    assert me.status_code == 200
    assert me.json()["id"] == company.owner_id
    assert me.json()["role"] == "owner"


async def test_signup_with_taken_slug_is_rejected(client: AsyncClient) -> None:
    company = await signup(client)

    response = await client.post(
        "/tenants",
        json={
            "tenant_name": "Outra",
            "slug": company.slug,
            "owner_email": "outro@exemplo.com.br",
            "owner_password": PASSWORD,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize("slug", ["ab", "Barbearia", "com espaco", "-inicio", "fim-", "a--b"])
async def test_signup_rejects_malformed_slug(client: AsyncClient, slug: str) -> None:
    response = await client.post(
        "/tenants",
        json={
            "tenant_name": "Barbearia",
            "slug": slug,
            "owner_email": "dono@exemplo.com.br",
            "owner_password": PASSWORD,
        },
    )

    assert response.status_code == 422


async def test_login_with_wrong_password_or_unknown_company_gets_the_same_error(
    client: AsyncClient,
) -> None:
    company = await signup(client)

    wrong_password = await client.post(
        "/auth/login",
        json={"tenant_slug": company.slug, "email": company.owner_email, "password": "errada-123"},
    )
    unknown_company = await client.post(
        "/auth/login",
        json={"tenant_slug": "nao-existe", "email": company.owner_email, "password": PASSWORD},
    )

    assert wrong_password.status_code == unknown_company.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_company.json()["error"]["message"]


async def test_credentials_of_one_tenant_do_not_work_in_another(client: AsyncClient) -> None:
    first = await signup(client)
    second = await signup(client)

    response = await client.post(
        "/auth/login",
        json={"tenant_slug": second.slug, "email": first.owner_email, "password": PASSWORD},
    )

    assert response.status_code == 401


async def test_same_email_can_exist_in_two_tenants(client: AsyncClient) -> None:
    first = await signup(client)
    second = await signup(client)
    owner = await login(client, first)
    shared = "recepcao@exemplo.com.br"

    created = await client.post(
        "/users",
        json={"email": shared, "password": PASSWORD, "role": "reception"},
        headers=bearer(owner),
    )
    other_owner = await login(client, second)
    created_elsewhere = await client.post(
        "/users",
        json={"email": shared, "password": PASSWORD, "role": "reception"},
        headers=bearer(other_owner),
    )

    assert created.status_code == created_elsewhere.status_code == 201


async def test_request_without_or_with_invalid_token_is_unauthorized(client: AsyncClient) -> None:
    missing = await client.get("/auth/me")
    garbage = await client.get("/auth/me", headers={"authorization": "Bearer lixo"})

    assert missing.status_code == garbage.status_code == 401


async def test_expired_access_token_is_unauthorized(client: AsyncClient) -> None:
    company = await signup(client)
    expired = create_access_token(
        Principal(uuid.UUID(company.owner_id), uuid.UUID(company.tenant_id), "owner"),
        Settings(jwt_secret=JWT_SECRET, access_token_ttl_minutes=-1),
    )

    response = await client.get("/auth/me", headers={"authorization": f"Bearer {expired}"})

    assert response.status_code == 401


async def test_refresh_returns_a_new_pair_and_retires_the_old_token(client: AsyncClient) -> None:
    tokens = await login(client, await signup(client))

    rotated = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]
    me = await client.get("/auth/me", headers=bearer(rotated.json()))
    assert me.status_code == 200


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(
    client: AsyncClient,
) -> None:
    tokens = await login(client, await signup(client))
    rotated = (
        await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).json()

    replay = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    legitimate = await client.post(
        "/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )

    assert replay.status_code == 401
    assert legitimate.status_code == 401


async def test_two_simultaneous_refreshes_of_one_token_let_only_one_through(
    client: AsyncClient,
) -> None:
    tokens = await login(client, await signup(client))
    body = {"refresh_token": tokens["refresh_token"]}

    first, second = await asyncio.gather(
        client.post("/auth/refresh", json=body), client.post("/auth/refresh", json=body)
    )

    assert sorted([first.status_code, second.status_code]) == [200, 401]
    winner = first if first.status_code == 200 else second
    # O perdedor foi tratado como reutilização: a família inteira está revogada.
    after = await client.post(
        "/auth/refresh", json={"refresh_token": winner.json()["refresh_token"]}
    )
    assert after.status_code == 401


async def test_logout_revokes_the_refresh_token(client: AsyncClient) -> None:
    tokens = await login(client, await signup(client))

    logout = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    after = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert logout.status_code == 204
    assert after.status_code == 401


async def test_refresh_token_of_a_deactivated_user_is_rejected(
    client: AsyncClient, migrated_database: Databases
) -> None:
    company = await signup(client)
    tokens = await login(client, company)
    engine = create_async_engine(migrated_database.admin_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET active = false WHERE id = :id"), {"id": company.owner_id}
        )
    await engine.dispose()

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 401


async def test_deactivated_user_is_rejected_by_me_even_with_a_valid_access_token(
    client: AsyncClient, migrated_database: Databases
) -> None:
    company = await signup(client)
    tokens = await login(client, company)
    engine = create_async_engine(migrated_database.admin_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET active = false WHERE id = :id"), {"id": company.owner_id}
        )
    await engine.dispose()

    response = await client.get("/auth/me", headers=bearer(tokens))

    assert response.status_code == 401


async def test_owner_creates_users_and_lists_only_their_own_tenant(client: AsyncClient) -> None:
    mine = await signup(client)
    other = await signup(client)
    owner = await login(client, mine)

    created = await client.post(
        "/users",
        json={"email": "bruna@exemplo.com.br", "password": PASSWORD, "role": "professional"},
        headers=bearer(owner),
    )
    listed = await client.get("/users", headers=bearer(owner))

    assert created.status_code == 201
    emails = {user["email"] for user in listed.json()}
    assert emails == {mine.owner_email, "bruna@exemplo.com.br"}
    assert other.owner_email not in emails


async def test_creating_a_user_with_a_taken_email_is_rejected(client: AsyncClient) -> None:
    company = await signup(client)
    owner = await login(client, company)

    response = await client.post(
        "/users",
        json={"email": company.owner_email, "password": PASSWORD, "role": "reception"},
        headers=bearer(owner),
    )

    assert response.status_code == 409


@pytest.mark.parametrize("role", ["professional", "reception"])
async def test_non_owner_cannot_reach_owner_routes(client: AsyncClient, role: str) -> None:
    company = await signup(client)
    owner = await login(client, company)
    email = f"{role}@exemplo.com.br"
    await client.post(
        "/users",
        json={"email": email, "password": PASSWORD, "role": role},
        headers=bearer(owner),
    )
    staff = await login(client, company, email)

    listing = await client.get("/users", headers=bearer(staff))
    creation = await client.post(
        "/users",
        json={"email": "novo@exemplo.com.br", "password": PASSWORD, "role": "owner"},
        headers=bearer(staff),
    )

    assert listing.status_code == creation.status_code == 403
    assert listing.json()["error"]["code"] == "forbidden"


async def test_panel_session_only_sees_the_tenant_from_the_token(client: AsyncClient) -> None:
    first = await signup(client)
    await signup(client)
    owner = await login(client, first)

    response = await client.get("/panel/user-count", headers=bearer(owner))

    assert response.json() == {"users": 1}


async def test_public_session_resolves_the_tenant_from_the_slug(client: AsyncClient) -> None:
    company = await signup(client)

    response = await client.get(f"/public/{company.slug}/user-count")

    assert response.json() == {"users": 1}


async def test_public_session_with_unknown_slug_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/public/nao-existe/user-count")

    assert response.status_code == 404


async def test_oversized_login_and_refresh_bodies_are_rejected_before_hashing(
    client: AsyncClient,
) -> None:
    company = await signup(client)

    login_response = await client.post(
        "/auth/login",
        json={"tenant_slug": company.slug, "email": company.owner_email, "password": "x" * 129},
    )
    refresh_response = await client.post("/auth/refresh", json={"refresh_token": "x" * 513})
    logout_response = await client.post("/auth/logout", json={"refresh_token": "x" * 513})

    assert login_response.status_code == 422
    assert refresh_response.status_code == 422
    assert logout_response.status_code == 422


async def test_password_verification_does_not_block_the_event_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = await signup(client)

    def slow_verify(password_hash: str | None, password: str) -> bool:
        time.sleep(0.3)
        return verify_password(password_hash, password)

    monkeypatch.setattr("app.auth.service.verify_password", slow_verify)
    longest_gap = 0.0
    running = True

    async def ticker() -> None:
        nonlocal longest_gap
        last = time.perf_counter()
        while running:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            longest_gap = max(longest_gap, now - last)
            last = now

    task = asyncio.create_task(ticker())
    await login(client, company)
    running = False
    await task

    # Rodando no event loop, o hash de 0,3 s deixaria o ticker parado por todo esse tempo.
    assert longest_gap < 0.15
