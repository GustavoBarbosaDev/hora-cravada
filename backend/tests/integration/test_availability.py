from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import add_user, bearer, login, owner_headers
from tests.integration.test_branches_and_resources import create_resource


async def add_rule(
    client: AsyncClient, headers: dict[str, str], resource_id: str, **body: Any
) -> Any:
    return await client.post(
        f"/resources/{resource_id}/availability-rules",
        headers=headers,
        json={"weekday": 1, "start": "09:00", "end": "12:00", **body},
    )


async def test_a_day_can_have_several_intervals_for_a_lunch_break(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    morning = await add_rule(client, headers, resource["id"], start="09:00", end="12:00")
    afternoon = await add_rule(client, headers, resource["id"], start="13:00", end="19:00")
    listed = await client.get(f"/resources/{resource['id']}/availability-rules", headers=headers)

    assert (morning.status_code, afternoon.status_code) == (201, 201)
    assert [(r["weekday"], r["start"], r["end"]) for r in listed.json()] == [
        (1, "09:00", "12:00"),
        (1, "13:00", "19:00"),
    ]


async def test_adjacent_intervals_are_allowed(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    await add_rule(client, headers, resource["id"], start="09:00", end="12:00")

    response = await add_rule(client, headers, resource["id"], start="12:00", end="14:00")

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("11:00", "13:00"),
        ("08:00", "09:30"),
        ("09:00", "12:00"),
        ("10:00", "11:00"),
        ("08:00", "13:00"),
    ],
)
async def test_overlapping_interval_on_the_same_day_is_rejected(
    client: AsyncClient, start: str, end: str
) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    await add_rule(client, headers, resource["id"], start="09:00", end="12:00")

    response = await add_rule(client, headers, resource["id"], start=start, end=end)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_same_hours_are_allowed_on_other_days_and_other_resources(
    client: AsyncClient,
) -> None:
    _, headers = await owner_headers(client)
    first = await create_resource(client, headers, name="Rogério Teixeira")
    second = await create_resource(client, headers, name="Anderson Lopes")
    await add_rule(client, headers, first["id"])

    other_day = await add_rule(client, headers, first["id"], weekday=2)
    other_resource = await add_rule(client, headers, second["id"])

    assert (other_day.status_code, other_resource.status_code) == (201, 201)


async def test_interval_can_end_at_midnight(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    response = await add_rule(client, headers, resource["id"], start="18:00", end="24:00")

    assert response.status_code == 201
    assert response.json()["end"] == "24:00"


@pytest.mark.parametrize(
    "body",
    [
        {"start": "12:00", "end": "12:00"},
        {"start": "13:00", "end": "12:00"},
        {"start": "9:00", "end": "12:00"},
        {"start": "09:00", "end": "24:01"},
        {"start": "09:60", "end": "12:00"},
        {"start": "24:00", "end": "24:00"},
        {"weekday": 7},
        {"weekday": -1},
    ],
)
async def test_invalid_rule_is_rejected(client: AsyncClient, body: dict[str, Any]) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    response = await add_rule(client, headers, resource["id"], **body)

    assert response.status_code == 422


async def test_deleting_a_rule_frees_the_interval(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    rule = (await add_rule(client, headers, resource["id"])).json()

    deleted = await client.delete(f"/availability-rules/{rule['id']}", headers=headers)
    again = await add_rule(client, headers, resource["id"])

    assert deleted.status_code == 204
    assert again.status_code == 201


async def test_deleting_a_resource_removes_its_rules(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    rule = (await add_rule(client, headers, resource["id"])).json()

    await client.delete(f"/resources/{resource['id']}", headers=headers)

    response = await client.delete(f"/availability-rules/{rule['id']}", headers=headers)
    assert response.status_code == 404


async def test_tenant_cannot_see_or_change_rules_of_another(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    resource = await create_resource(client, other_headers)
    rule = (await add_rule(client, other_headers, resource["id"])).json()

    listed = await client.get(f"/resources/{resource['id']}/availability-rules", headers=headers)
    created = await add_rule(client, headers, resource["id"], weekday=3)
    deleted = await client.delete(f"/availability-rules/{rule['id']}", headers=headers)

    assert (listed.status_code, created.status_code, deleted.status_code) == (404, 404, 404)


@pytest.mark.parametrize("role", ["reception", "professional"])
async def test_staff_can_read_but_not_change_availability(client: AsyncClient, role: str) -> None:
    company, owner = await owner_headers(client)
    resource = await create_resource(client, owner)
    rule = (await add_rule(client, owner, resource["id"])).json()
    staff = bearer(await login(client, company, await add_user(client, owner, role)))

    listed = await client.get(f"/resources/{resource['id']}/availability-rules", headers=staff)
    created = await add_rule(client, staff, resource["id"], weekday=4)
    deleted = await client.delete(f"/availability-rules/{rule['id']}", headers=staff)
    exceptions = await client.get("/availability-exceptions", headers=staff)
    new_exception = await client.post(
        "/availability-exceptions",
        headers=staff,
        json={"date": "2026-12-25", "kind": "closed"},
    )

    assert (listed.status_code, exceptions.status_code) == (200, 200)
    assert (created.status_code, deleted.status_code, new_exception.status_code) == (403,) * 3


async def add_exception(client: AsyncClient, headers: dict[str, str], **body: Any) -> Any:
    return await client.post(
        "/availability-exceptions",
        headers=headers,
        json={"date": "2026-12-25", "kind": "closed", **body},
    )


async def test_holiday_closes_the_whole_tenant(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)

    response = await add_exception(client, headers, reason="Natal")

    assert response.status_code == 201
    assert response.json() | {"id": None} == {
        "id": None,
        "resource_id": None,
        "date": "2026-12-25",
        "kind": "closed",
        "start": None,
        "end": None,
        "reason": "Natal",
    }


async def test_day_off_and_special_hours_target_one_resource(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)

    day_off = await add_exception(client, headers, resource_id=resource["id"], reason="Folga")
    partial = await add_exception(
        client, headers, resource_id=resource["id"], date="2026-12-26", start="12:00", end="14:00"
    )
    special = await add_exception(
        client,
        headers,
        resource_id=resource["id"],
        date="2026-12-24",
        kind="open",
        start="09:00",
        end="14:00",
    )

    assert (day_off.status_code, partial.status_code, special.status_code) == (201, 201, 201)
    assert special.json()["kind"] == "open"
    assert partial.json()["start"] == "12:00"


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "open"},
        {"kind": "open", "start": "09:00"},
        {"kind": "closed", "start": "09:00"},
        {"kind": "closed", "end": "09:00"},
        {"kind": "open", "start": "14:00", "end": "09:00"},
        {"kind": "folga"},
        {"date": "25/12/2026"},
        {"reason": ""},
    ],
)
async def test_invalid_exception_is_rejected(client: AsyncClient, body: dict[str, Any]) -> None:
    _, headers = await owner_headers(client)

    response = await add_exception(client, headers, **body)

    assert response.status_code == 422


async def test_exceptions_can_be_filtered_by_period_and_resource(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    await add_exception(client, headers, date="2026-12-25", reason="Natal")
    await add_exception(client, headers, date="2027-01-01", reason="Ano Novo")
    await add_exception(client, headers, date="2026-12-31", resource_id=resource["id"])

    december = await client.get(
        "/availability-exceptions",
        headers=headers,
        params={"date_from": "2026-12-01", "date_to": "2026-12-31"},
    )
    of_resource = await client.get(
        "/availability-exceptions", headers=headers, params={"resource_id": resource["id"]}
    )

    assert [e["date"] for e in december.json()] == ["2026-12-25", "2026-12-31"]
    assert [e["date"] for e in of_resource.json()] == ["2026-12-31"]


async def test_exception_cannot_target_a_resource_of_another_tenant(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    foreign = await create_resource(client, other_headers)

    response = await add_exception(client, headers, resource_id=foreign["id"])

    assert response.status_code == 422


async def test_exception_can_be_deleted_only_by_its_own_tenant(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    _, other_headers = await owner_headers(client)
    created = (await add_exception(client, headers)).json()
    url = f"/availability-exceptions/{created['id']}"

    foreign = await client.delete(url, headers=other_headers)
    own = await client.delete(url, headers=headers)
    again = await client.delete(url, headers=headers)

    assert (foreign.status_code, own.status_code, again.status_code) == (404, 204, 404)
