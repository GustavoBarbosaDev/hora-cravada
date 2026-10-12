import pytest
from httpx import AsyncClient

from app.seed import DEV_PASSWORD, SPECS, TenantSpec, seed
from tests.conftest import Databases
from tests.helpers import bearer


@pytest.fixture
async def seeded(migrated_database: Databases) -> list[str]:
    return await seed()


async def login_as(client: AsyncClient, slug: str, email: str) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"tenant_slug": slug, "email": email, "password": DEV_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return bearer(response.json())


async def test_seed_is_idempotent(seeded: list[str]) -> None:
    assert await seed() == []


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.slug)
async def test_each_seeded_company_has_a_complete_catalog(
    client: AsyncClient, seeded: list[str], spec: TenantSpec
) -> None:
    headers = await login_as(client, spec.slug, spec.owner_email)

    resources = (await client.get("/resources", headers=headers)).json()
    services = (await client.get("/services", headers=headers)).json()
    branches = (await client.get("/branches", headers=headers)).json()
    exceptions = (await client.get("/availability-exceptions", headers=headers)).json()

    assert {r["name"] for r in resources} == {name for name, *_ in spec.resources}
    assert {s["name"] for s in services} == {item.data.name for item in spec.services}
    assert [b["name"] for b in branches] == [spec.branch_name]
    assert len(exceptions) == len(spec.holidays)
    for item in spec.services:
        service_id = next(s["id"] for s in services if s["name"] == item.data.name)
        linked = (await client.get(f"/services/{service_id}/resources", headers=headers)).json()
        assert len(linked["resource_ids"]) == len(item.performed_by)
    for resource in resources:
        rules = await client.get(f"/resources/{resource['id']}/availability-rules", headers=headers)
        assert rules.json(), f"{resource['name']} ficou sem horários"


async def test_seeded_professional_is_linked_to_a_resource(
    client: AsyncClient, seeded: list[str]
) -> None:
    spec = SPECS[0]
    owner = await login_as(client, spec.slug, spec.owner_email)

    users = (await client.get("/users", headers=owner)).json()
    resources = {r["id"]: r["name"] for r in (await client.get("/resources", headers=owner)).json()}

    professional = next(u for u in users if u["role"] == "professional")
    assert resources[professional["resource_id"]] == "Rogério Teixeira"
