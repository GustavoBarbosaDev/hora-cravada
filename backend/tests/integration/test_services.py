from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import add_user, bearer, login, owner_headers
from tests.integration.test_branches_and_resources import create_resource

CORTE = {
    "name": "Corte",
    "duration_min": 30,
    "buffer_after_min": 5,
    "price_cents": 4500,
}


async def create_service(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post("/services", headers=headers, json={**CORTE, **overrides})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_service_crud(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    created = await create_service(client, headers, required_resource_kinds=["sala", "medico"])
    url = f"/services/{created['id']}"

    patched = await client.patch(url, headers=headers, json={"duration_min": 45, "active": False})
    listed = await client.get("/services", headers=headers)
    deleted = await client.delete(url, headers=headers)
    missing = await client.get(url, headers=headers)

    assert created["buffer_before_min"] == 0
    assert created["required_resource_kinds"] == ["medico", "sala"]
    assert patched.json()["duration_min"] == 45
    assert patched.json()["name"] == "Corte"
    assert patched.json()["active"] is False
    assert [s["id"] for s in listed.json()] == [created["id"]]
    assert deleted.status_code == 204
    assert missing.status_code == 404


async def test_duplicate_resource_kinds_are_collapsed(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)

    created = await create_service(client, headers, required_resource_kinds=["sala", "sala"])

    assert created["required_resource_kinds"] == ["sala"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_min": 0},
        {"duration_min": 1441},
        {"buffer_before_min": -1},
        {"buffer_after_min": -5},
        {"price_cents": -1},
        {"name": ""},
        {"required_resource_kinds": ["Sala Grande"]},
    ],
)
async def test_invalid_service_is_rejected(client: AsyncClient, overrides: dict[str, Any]) -> None:
    _, headers = await owner_headers(client)

    response = await client.post("/services", headers=headers, json={**CORTE, **overrides})

    assert response.status_code == 422


async def test_service_patch_rejects_null_on_required_fields(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    service = await create_service(client, headers)

    response = await client.patch(
        f"/services/{service['id']}", headers=headers, json={"duration_min": None}
    )

    assert response.status_code == 422


async def test_resources_that_perform_a_service_can_be_replaced(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    service = await create_service(client, headers)
    rogerio = await create_resource(client, headers, name="Rogério Teixeira")
    anderson = await create_resource(client, headers, name="Anderson Lopes")
    url = f"/services/{service['id']}/resources"

    first = await client.put(url, headers=headers, json={"resource_ids": [rogerio["id"]]})
    second = await client.put(
        url, headers=headers, json={"resource_ids": [anderson["id"], rogerio["id"]]}
    )
    third = await client.put(url, headers=headers, json={"resource_ids": [anderson["id"]]})
    listed = await client.get(url, headers=headers)
    cleared = await client.put(url, headers=headers, json={"resource_ids": []})

    assert first.json()["resource_ids"] == [rogerio["id"]]
    assert sorted(second.json()["resource_ids"]) == sorted([anderson["id"], rogerio["id"]])
    assert listed.json()["resource_ids"] == [anderson["id"]]
    assert third.status_code == 200
    assert cleared.json()["resource_ids"] == []


async def test_service_cannot_be_linked_to_unknown_or_foreign_resources(
    client: AsyncClient,
) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    service = await create_service(client, headers)
    own = await create_resource(client, headers)
    foreign = await create_resource(client, other_headers)
    url = f"/services/{service['id']}/resources"
    await client.put(url, headers=headers, json={"resource_ids": [own["id"]]})

    response = await client.put(
        url, headers=headers, json={"resource_ids": [own["id"], foreign["id"]]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown"] == [foreign["id"]]
    assert (await client.get(url, headers=headers)).json()["resource_ids"] == [own["id"]]


async def test_deleting_a_resource_or_service_drops_the_link(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    kept = await create_service(client, headers)
    gone = await create_service(client, headers, name="Barba")
    resource = await create_resource(client, headers)
    for service in (kept, gone):
        await client.put(
            f"/services/{service['id']}/resources",
            headers=headers,
            json={"resource_ids": [resource["id"]]},
        )

    await client.delete(f"/services/{gone['id']}", headers=headers)
    await client.delete(f"/resources/{resource['id']}", headers=headers)

    links = await client.get(f"/services/{kept['id']}/resources", headers=headers)
    assert links.json()["resource_ids"] == []


async def test_tenant_cannot_read_change_or_link_services_of_another(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    service = await create_service(client, other_headers)
    url = f"/services/{service['id']}"

    assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.patch(url, headers=headers, json={"name": "x"})).status_code == 404
    assert (await client.delete(url, headers=headers)).status_code == 404
    assert (await client.get(f"{url}/resources", headers=headers)).status_code == 404
    assert (
        await client.put(f"{url}/resources", headers=headers, json={"resource_ids": []})
    ).status_code == 404
    assert (await client.get("/services", headers=headers)).json() == []


@pytest.mark.parametrize("role", ["reception", "professional"])
async def test_staff_cannot_change_services(client: AsyncClient, role: str) -> None:
    company, owner = await owner_headers(client)
    service = await create_service(client, owner)
    staff = bearer(await login(client, company, await add_user(client, owner, role)))

    listed = await client.get("/services", headers=staff)
    created = await client.post("/services", headers=staff, json=CORTE)
    patched = await client.patch(f"/services/{service['id']}", headers=staff, json={"name": "x"})
    linked = await client.put(
        f"/services/{service['id']}/resources", headers=staff, json={"resource_ids": []}
    )

    assert listed.status_code == 200
    assert (created.status_code, patched.status_code, linked.status_code) == (403, 403, 403)
