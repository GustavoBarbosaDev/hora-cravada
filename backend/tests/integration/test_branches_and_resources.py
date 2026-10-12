import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import PASSWORD, add_user, bearer, login, owner_headers, signup


async def default_branch_id(client: AsyncClient, headers: dict[str, str]) -> str:
    branches = (await client.get("/branches", headers=headers)).json()
    assert len(branches) == 1
    branch_id: str = branches[0]["id"]
    return branch_id


async def create_resource(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    body = {
        "branch_id": await default_branch_id(client, headers),
        "kind": "barbeiro",
        "name": "Rogério Teixeira",
        **overrides,
    }
    response = await client.post("/resources", headers=headers, json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_signup_creates_a_default_branch_with_the_company_timezone(
    client: AsyncClient,
) -> None:
    company = await signup(client)
    headers = bearer(await login(client, company))

    branches = (await client.get("/branches", headers=headers)).json()

    assert [(b["name"], b["timezone"]) for b in branches] == [("Principal", "America/Sao_Paulo")]


async def test_branch_can_be_created_updated_and_deleted(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)

    created = await client.post(
        "/branches",
        headers=headers,
        json={"name": "Savassi", "timezone": "America/Fortaleza", "address": "Rua Pernambuco, 100"},
    )
    branch_id = created.json()["id"]
    updated = await client.patch(
        f"/branches/{branch_id}", headers=headers, json={"name": "Funcionários", "address": None}
    )
    deleted = await client.delete(f"/branches/{branch_id}", headers=headers)

    assert created.status_code == 201
    assert updated.json()["name"] == "Funcionários"
    assert updated.json()["address"] is None
    assert updated.json()["timezone"] == "America/Fortaleza"
    assert deleted.status_code == 204
    assert len((await client.get("/branches", headers=headers)).json()) == 1


@pytest.mark.parametrize("value", ["Mars/Olympus", "localtime", "", "../etc/passwd", "sao paulo"])
async def test_branch_timezone_must_be_an_iana_name(client: AsyncClient, value: str) -> None:
    _, headers = await owner_headers(client)

    response = await client.post(
        "/branches", headers=headers, json={"name": "Filial", "timezone": value}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_branch_patch_validates_the_timezone(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    branch_id = await default_branch_id(client, headers)

    response = await client.patch(
        f"/branches/{branch_id}", headers=headers, json={"timezone": "Mars/Olympus"}
    )

    assert response.status_code == 422


async def test_signup_rejects_a_timezone_that_is_not_iana(client: AsyncClient) -> None:
    response = await client.post(
        "/tenants",
        json={
            "tenant_name": "Clínica Vida Plena",
            "slug": f"t-{uuid.uuid4().hex[:12]}",
            "timezone": "localtime",
            "owner_email": "direcao@vidaplena.med.br",
            "owner_password": PASSWORD,
        },
    )

    assert response.status_code == 422


async def test_branch_patch_rejects_null_on_required_fields(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    branch_id = await default_branch_id(client, headers)

    response = await client.patch(f"/branches/{branch_id}", headers=headers, json={"name": None})

    assert response.status_code == 422


async def test_branch_with_resources_cannot_be_deleted(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    response = await client.delete(f"/branches/{resource['branch_id']}", headers=headers)

    assert response.status_code == 409


async def test_resource_crud(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    created = await create_resource(
        client, headers, kind="sala", name="Sala Mauá", capacity=8, attributes={"projetor": True}
    )
    resource_id = created["id"]

    patched = await client.patch(
        f"/resources/{resource_id}", headers=headers, json={"capacity": 10, "active": False}
    )
    fetched = await client.get(f"/resources/{resource_id}", headers=headers)
    deleted = await client.delete(f"/resources/{resource_id}", headers=headers)
    missing = await client.get(f"/resources/{resource_id}", headers=headers)

    assert created["capacity"] == 8
    assert created["active"] is True
    assert patched.json()["capacity"] == 10
    assert patched.json()["name"] == "Sala Mauá"
    assert fetched.json()["active"] is False
    assert deleted.status_code == 204
    assert missing.status_code == 404


async def test_resource_list_filters_by_kind(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    await create_resource(client, headers, kind="medico", name="Dra. Helena Moraes")
    await create_resource(client, headers, kind="sala", name="Consultório 1")

    rooms = await client.get("/resources", headers=headers, params={"kind": "sala"})

    assert [r["name"] for r in rooms.json()] == ["Consultório 1"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"capacity": 0},
        {"capacity": -2},
        {"kind": "Barbeiro"},
        {"kind": "com espaço"},
        {"name": ""},
        {"attributes": {"nota": "x" * 5000}},
    ],
)
async def test_invalid_resource_is_rejected(client: AsyncClient, overrides: dict[str, Any]) -> None:
    _, headers = await owner_headers(client)
    body = {"branch_id": await default_branch_id(client, headers), "kind": "sala", "name": "Sala"}

    response = await client.post("/resources", headers=headers, json={**body, **overrides})

    assert response.status_code == 422


async def test_resource_cannot_use_a_branch_from_another_tenant(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    foreign_branch = await default_branch_id(client, other_headers)

    created = await client.post(
        "/resources",
        headers=headers,
        json={"branch_id": foreign_branch, "kind": "sala", "name": "Sala"},
    )
    own = await create_resource(client, headers)
    moved = await client.patch(
        f"/resources/{own['id']}", headers=headers, json={"branch_id": foreign_branch}
    )

    assert created.status_code == 422
    assert moved.status_code == 422


async def test_tenant_cannot_read_change_or_delete_resources_of_another(
    client: AsyncClient,
) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    resource = await create_resource(client, other_headers)
    url = f"/resources/{resource['id']}"

    assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.patch(url, headers=headers, json={"name": "Invasor"})).status_code == 404
    assert (await client.delete(url, headers=headers)).status_code == 404
    assert (await client.get("/resources", headers=headers)).json() == []
    assert (await client.get(url, headers=other_headers)).json()["name"] == resource["name"]


@pytest.mark.parametrize("role", ["reception", "professional"])
async def test_staff_can_read_but_not_write_the_catalog(client: AsyncClient, role: str) -> None:
    company, owner = await owner_headers(client)
    resource = await create_resource(client, owner)
    staff = bearer(await login(client, company, await add_user(client, owner, role)))

    listed = await client.get("/resources", headers=staff)
    created = await client.post(
        "/resources",
        headers=staff,
        json={"branch_id": resource["branch_id"], "kind": "sala", "name": "Sala"},
    )
    patched = await client.patch(f"/resources/{resource['id']}", headers=staff, json={"name": "x"})
    deleted = await client.delete(f"/resources/{resource['id']}", headers=staff)

    assert listed.status_code == 200
    assert (created.status_code, patched.status_code, deleted.status_code) == (403, 403, 403)
