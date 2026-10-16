import datetime
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.slots.router import utc_now
from tests.helpers import owner_headers, signup
from tests.integration.test_availability import add_rule
from tests.integration.test_branches_and_resources import create_resource, default_branch_id
from tests.integration.test_services import create_service

MONDAY = "2026-11-02"
TUESDAY = "2026-11-03"


@pytest.fixture(autouse=True)
def fixed_clock(app: FastAPI) -> Iterator[None]:
    now = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
    app.dependency_overrides[utc_now] = lambda: now
    yield
    app.dependency_overrides.pop(utc_now, None)


async def link(
    client: AsyncClient, headers: dict[str, str], service: dict[str, Any], *ids: str
) -> None:
    response = await client.put(
        f"/services/{service['id']}/resources", headers=headers, json={"resource_ids": list(ids)}
    )
    assert response.status_code == 200, response.text


async def create_resource_in(
    client: AsyncClient, headers: dict[str, str], branch_id: str, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/resources",
        headers=headers,
        json={"branch_id": branch_id, "kind": "barbeiro", "name": "Rogério Teixeira", **overrides},
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def get_slots(client: AsyncClient, slug: str, service_id: str, **params: Any) -> Any:
    return await client.get(
        f"/public/{slug}/slots",
        params={"service_id": service_id, "date_from": MONDAY, "date_to": MONDAY, **params},
    )


def local_starts(body: dict[str, Any], offset_hours: int = -3) -> list[str]:
    zone = datetime.timezone(datetime.timedelta(hours=offset_hours))
    return [
        datetime.datetime.fromisoformat(slot["start"]).astimezone(zone).strftime("%H:%M")
        for slot in body["slots"]
    ]


async def barbershop(
    client: AsyncClient,
) -> tuple[Any, dict[str, str], dict[str, Any], dict[str, Any]]:
    company, headers = await owner_headers(client)
    barber = await create_resource(client, headers)
    service = await create_service(client, headers, duration_min=30, buffer_after_min=5)
    await link(client, headers, service, barber["id"])
    await add_rule(client, headers, barber["id"], weekday=0, start="09:00", end="12:00")
    await add_rule(client, headers, barber["id"], weekday=0, start="13:00", end="19:00")
    return company, headers, barber, service


async def test_public_slots_skip_the_lunch_break_and_use_the_branch_timezone(
    client: AsyncClient,
) -> None:
    company, headers, barber, service = await barbershop(client)

    response = await get_slots(client, company.slug, service["id"], step_min=30)
    body = response.json()

    assert response.status_code == 200
    assert body["timezone"] == "America/Sao_Paulo"
    assert body["duration_min"] == 30
    assert local_starts(body) == [
        "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
        *[f"{h}:{m}" for h in range(13, 19) for m in ("00", "30")],
    ]  # fmt: skip
    first = body["slots"][0]
    assert first["start"].startswith("2026-11-02T12:00:00")
    assert first["end"].startswith("2026-11-02T12:30:00")
    assert first["resource_ids"] == [barber["id"]]


async def test_slots_need_no_authentication(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    response = await client.get(
        f"/public/{company.slug}/slots",
        params={"service_id": service["id"], "date_from": MONDAY, "date_to": MONDAY},
    )

    assert response.status_code == 200


async def test_company_wide_holiday_removes_the_day(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    await client.post(
        "/availability-exceptions",
        headers=headers,
        json={"date": MONDAY, "kind": "closed", "reason": "Feriado"},
    )

    response = await get_slots(client, company.slug, service["id"], date_to=TUESDAY)

    assert response.json()["slots"] == []


async def test_special_opening_replaces_the_weekly_hours(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    await client.post(
        "/availability-exceptions",
        headers=headers,
        json={
            "resource_id": barber["id"],
            "date": MONDAY,
            "kind": "open",
            "start": "10:00",
            "end": "11:00",
        },
    )

    response = await get_slots(client, company.slug, service["id"], step_min=30)

    assert local_starts(response.json()) == ["10:00", "10:30"]


async def test_range_spans_several_days(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    await add_rule(client, headers, barber["id"], weekday=1, start="08:00", end="09:00")

    response = await get_slots(client, company.slug, service["id"], date_to=TUESDAY, step_min=30)

    days = {slot["start"][:10] for slot in response.json()["slots"]}
    assert days == {MONDAY, TUESDAY}


async def test_slots_in_the_past_are_not_offered(client: AsyncClient, app: FastAPI) -> None:
    company, _, _, service = await barbershop(client)
    now = datetime.datetime(2026, 11, 2, 14, 10, tzinfo=datetime.UTC)  # 11:10 em São Paulo
    app.dependency_overrides[utc_now] = lambda: now

    response = await get_slots(client, company.slug, service["id"], step_min=30)

    assert local_starts(response.json())[0] == "11:30"


async def test_branch_timezone_decides_the_utc_instant(client: AsyncClient) -> None:
    company, headers = await owner_headers(client)
    branch = await client.post(
        "/branches", headers=headers, json={"name": "Nova York", "timezone": "America/New_York"}
    )
    resource = await create_resource_in(client, headers, branch.json()["id"])
    service = await create_service(client, headers)
    await link(client, headers, service, resource["id"])
    await add_rule(client, headers, resource["id"], weekday=0, start="09:00", end="10:00")

    response = await get_slots(client, company.slug, service["id"])

    assert response.json()["timezone"] == "America/New_York"
    assert response.json()["slots"][0]["start"].startswith("2026-11-02T14:00:00")


async def test_service_offered_in_two_branches_requires_branch_id(client: AsyncClient) -> None:
    company, headers = await owner_headers(client)
    main = await default_branch_id(client, headers)
    other = (
        await client.post(
            "/branches", headers=headers, json={"name": "Savassi", "timezone": "America/Sao_Paulo"}
        )
    ).json()["id"]
    first = await create_resource_in(client, headers, main, name="Rogério Teixeira")
    second = await create_resource_in(client, headers, other, name="Anderson Lopes")
    service = await create_service(client, headers)
    await link(client, headers, service, first["id"], second["id"])
    for resource in (first, second):
        await add_rule(client, headers, resource["id"], weekday=0, start="09:00", end="10:00")

    ambiguous = await get_slots(client, company.slug, service["id"])
    chosen = await get_slots(client, company.slug, service["id"], branch_id=other)

    assert ambiguous.status_code == 422
    assert chosen.status_code == 200
    assert {r for s in chosen.json()["slots"] for r in s["resource_ids"]} == {second["id"]}
    assert chosen.json()["branch_id"] == other


async def test_resource_filter_narrows_the_slots_to_one_professional(
    client: AsyncClient,
) -> None:
    company, headers, rogerio, service = await barbershop(client)
    anderson = await create_resource(client, headers, name="Anderson Lopes")
    await link(client, headers, service, rogerio["id"], anderson["id"])
    await add_rule(client, headers, anderson["id"], weekday=0, start="09:00", end="10:00")

    everyone = await get_slots(client, company.slug, service["id"], step_min=30)
    only_anderson = await get_slots(
        client, company.slug, service["id"], resource_id=anderson["id"], step_min=30
    )

    assert everyone.json()["slots"][0]["resource_ids"] == [anderson["id"], rogerio["id"]]
    assert local_starts(only_anderson.json()) == ["09:00", "09:30"]
    assert {r for s in only_anderson.json()["slots"] for r in s["resource_ids"]} == {anderson["id"]}


async def test_resource_that_does_not_perform_the_service_is_not_found(
    client: AsyncClient,
) -> None:
    company, headers, _, service = await barbershop(client)
    other = await create_resource(client, headers, name="Mateus Ribeiro")

    response = await get_slots(client, company.slug, service["id"], resource_id=other["id"])

    assert response.status_code == 404


async def test_inactive_resource_is_not_offered(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    await client.patch(f"/resources/{barber['id']}", headers=headers, json={"active": False})

    response = await get_slots(client, company.slug, service["id"])

    assert response.status_code == 404


async def test_inactive_service_is_not_found(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    await client.patch(f"/services/{service['id']}", headers=headers, json={"active": False})

    response = await get_slots(client, company.slug, service["id"])

    assert response.status_code == 404


async def test_unknown_company_and_unknown_service_are_not_found(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    no_company = await get_slots(client, "nao-existe", service["id"])
    no_service = await get_slots(client, company.slug, str(uuid.uuid4()))

    assert (no_company.status_code, no_service.status_code) == (404, 404)


async def test_a_company_cannot_query_the_service_of_another(client: AsyncClient) -> None:
    _, _, _, service = await barbershop(client)
    stranger = await signup(client)

    response = await get_slots(client, stranger.slug, service["id"])

    assert response.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": TUESDAY, "date_to": MONDAY},
        {"date_from": "2026-11-01", "date_to": "2026-12-02"},
        {"step_min": 7},
        {"date_from": "02/11/2026"},
    ],
)
async def test_invalid_query_is_rejected(client: AsyncClient, params: dict[str, Any]) -> None:
    company, _, _, service = await barbershop(client)

    response = await get_slots(client, company.slug, service["id"], **params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_thirty_one_days_is_the_longest_period_accepted(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    response = await get_slots(
        client, company.slug, service["id"], date_from="2026-11-01", date_to="2026-12-01"
    )

    assert response.status_code == 200


async def test_service_without_anyone_to_perform_it_is_not_found(client: AsyncClient) -> None:
    company, headers = await owner_headers(client)
    service = await create_service(client, headers)

    response = await get_slots(client, company.slug, service["id"])

    assert response.status_code == 404


async def clinic(
    client: AsyncClient,
) -> tuple[Any, dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    company, headers = await owner_headers(client)
    doctor = await create_resource(client, headers, kind="medico", name="Dra. Helena Moraes")
    rooms = [
        await create_resource(client, headers, kind="sala", name=f"Consultório {n}") for n in (1, 2)
    ]
    service = await create_service(
        client,
        headers,
        name="Consulta",
        duration_min=60,
        buffer_after_min=0,
        required_resource_kinds=["sala"],
    )
    await link(client, headers, service, doctor["id"])
    await add_rule(client, headers, doctor["id"], weekday=0, start="08:00", end="10:00")
    return company, headers, service, rooms


async def test_service_that_needs_a_room_has_no_slot_while_no_room_is_open(
    client: AsyncClient,
) -> None:
    company, _, service, _ = await clinic(client)

    response = await get_slots(client, company.slug, service["id"], step_min=60)

    assert response.status_code == 200
    assert response.json()["slots"] == []


async def test_service_that_needs_a_room_follows_the_room_hours(client: AsyncClient) -> None:
    company, headers, service, rooms = await clinic(client)
    await add_rule(client, headers, rooms[0]["id"], weekday=0, start="09:00", end="12:00")

    response = await get_slots(client, company.slug, service["id"], step_min=60)

    assert local_starts(response.json()) == ["09:00"]


async def test_closing_one_of_two_rooms_keeps_the_slots(client: AsyncClient) -> None:
    company, headers, service, rooms = await clinic(client)
    for room in rooms:
        await add_rule(client, headers, room["id"], weekday=0, start="08:00", end="12:00")
    await client.post(
        "/availability-exceptions",
        headers=headers,
        json={"resource_id": rooms[0]["id"], "date": MONDAY, "kind": "closed"},
    )

    response = await get_slots(client, company.slug, service["id"], step_min=60)

    assert local_starts(response.json()) == ["08:00", "09:00"]


async def test_closing_every_room_removes_the_slots(client: AsyncClient) -> None:
    company, headers, service, rooms = await clinic(client)
    for room in rooms:
        await add_rule(client, headers, room["id"], weekday=0, start="08:00", end="12:00")
        await client.post(
            "/availability-exceptions",
            headers=headers,
            json={"resource_id": room["id"], "date": MONDAY, "kind": "closed"},
        )

    response = await get_slots(client, company.slug, service["id"], step_min=60)

    assert response.json()["slots"] == []


async def test_rooms_of_another_branch_do_not_count(client: AsyncClient) -> None:
    company, headers, service, _ = await clinic(client)
    other = await client.post(
        "/branches", headers=headers, json={"name": "Savassi", "timezone": "America/Sao_Paulo"}
    )
    elsewhere = await create_resource_in(
        client, headers, other.json()["id"], kind="sala", name="Sala Savassi"
    )
    await add_rule(client, headers, elsewhere["id"], weekday=0, start="08:00", end="12:00")

    response = await get_slots(client, company.slug, service["id"], step_min=60)

    assert response.json()["slots"] == []


async def test_another_company_rooms_and_holidays_do_not_leak(client: AsyncClient) -> None:
    company, headers, service, rooms = await clinic(client)
    _, other_headers = await owner_headers(client)
    stray_room = await create_resource(client, other_headers, kind="sala", name="Sala alheia")
    await add_rule(client, other_headers, stray_room["id"], weekday=0, start="08:00", end="12:00")
    await client.post(
        "/availability-exceptions",
        headers=other_headers,
        json={"date": MONDAY, "kind": "closed"},
    )

    without_own_room = await get_slots(client, company.slug, service["id"], step_min=60)
    await add_rule(client, headers, rooms[0]["id"], weekday=0, start="08:00", end="12:00")
    with_own_room = await get_slots(client, company.slug, service["id"], step_min=60)

    assert without_own_room.json()["slots"] == []
    assert local_starts(with_own_room.json()) == ["08:00", "09:00"]
