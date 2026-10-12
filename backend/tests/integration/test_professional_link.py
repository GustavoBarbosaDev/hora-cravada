import uuid

from httpx import AsyncClient

from tests.helpers import PASSWORD, owner_headers
from tests.integration.test_branches_and_resources import create_resource


def user_body(role: str, resource_id: str | None) -> dict[str, str | None]:
    return {
        "email": f"{role}-{uuid.uuid4().hex[:8]}@exemplo.com.br",
        "password": PASSWORD,
        "role": role,
        "resource_id": resource_id,
    }


async def test_professional_is_linked_to_a_resource(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    response = await client.post(
        "/users", headers=headers, json=user_body("professional", resource["id"])
    )

    assert response.status_code == 201
    assert response.json()["resource_id"] == resource["id"]


async def test_only_professionals_can_be_linked_to_a_resource(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    response = await client.post(
        "/users", headers=headers, json=user_body("reception", resource["id"])
    )

    assert response.status_code == 422


async def test_professional_cannot_be_linked_to_a_resource_of_another_tenant(
    client: AsyncClient,
) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    foreign = await create_resource(client, other_headers)

    response = await client.post(
        "/users", headers=headers, json=user_body("professional", foreign["id"])
    )

    assert response.status_code == 422


async def test_deleting_the_resource_unlinks_the_professional(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    created = await client.post(
        "/users", headers=headers, json=user_body("professional", resource["id"])
    )

    await client.delete(f"/resources/{resource['id']}", headers=headers)

    users = (await client.get("/users", headers=headers)).json()
    linked = next(u for u in users if u["id"] == created.json()["id"])
    assert linked["resource_id"] is None
    assert linked["role"] == "professional"
