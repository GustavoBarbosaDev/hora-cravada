import datetime
import json
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db.session import build_engine
from app.slots.router import utc_now
from tests.helpers import add_user, bearer, login, owner_headers
from tests.integration.test_availability import add_rule
from tests.integration.test_branches_and_resources import create_resource, default_branch_id
from tests.integration.test_services import create_service
from tests.integration.test_slots_api import (  # noqa: F401  (fixed_clock é autouse)
    MONDAY,
    barbershop,
    fixed_clock,
    get_slots,
    link,
    local_starts,
)

CUSTOMER = {"name": "Marina Lopes", "phone": "(31) 99999-1234", "email": "marina@exemplo.com.br"}


def at(hour: int, minute: int = 0) -> str:
    """Horário local de São Paulo na segunda-feira de teste, em ISO com fuso."""
    return f"{MONDAY}T{hour:02d}:{minute:02d}:00-03:00"


async def book(
    client: AsyncClient, slug: str, service: dict[str, Any], start: str, **overrides: Any
) -> Any:
    return await client.post(
        f"/public/{slug}/bookings",
        json={"service_id": service["id"], "start": start, "customer": CUSTOMER, **overrides},
    )


async def test_public_booking_needs_no_login_and_returns_the_reserved_slot(
    client: AsyncClient,
) -> None:
    company, _, barber, service = await barbershop(client)

    response = await book(client, company.slug, service, at(9), notes="Degradê")

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "confirmed"
    assert body["resource_ids"] == [barber["id"]]
    assert body["start"].startswith("2026-11-02T12:00:00")
    assert body["end"].startswith("2026-11-02T12:30:00")
    assert "customer" not in body


async def test_a_booked_slot_and_its_buffer_leave_the_availability(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)
    before = local_starts((await get_slots(client, company.slug, service["id"])).json())

    await book(client, company.slug, service, at(9))
    after = local_starts((await get_slots(client, company.slug, service["id"])).json())

    # Corte de 30 min com 5 de limpeza: ocupa até 09:35, então 09:30 some e 09:45 continua.
    assert {"09:00", "09:15", "09:30"} <= set(before)
    assert not {"09:00", "09:15", "09:30"} & set(after)
    assert "09:45" in after


async def test_the_same_slot_cannot_be_booked_twice(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    first = await book(client, company.slug, service, at(10))
    second = await book(client, company.slug, service, at(10))
    overlapping = await book(client, company.slug, service, at(10, 15))

    assert first.status_code == 201
    assert second.status_code == 409
    assert overlapping.status_code == 409


async def test_a_time_the_availability_never_offered_is_refused(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    lunch = await book(client, company.slug, service, at(12, 30))
    night = await book(client, company.slug, service, at(22))
    past = await book(client, company.slug, service, "2026-09-01T09:00:00-03:00")

    assert [r.status_code for r in (lunch, night, past)] == [409, 409, 409]


async def test_the_start_must_carry_a_timezone(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    response = await book(client, company.slug, service, f"{MONDAY}T09:00:00")

    assert response.status_code == 422


async def test_the_start_can_be_sent_in_any_offset(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    response = await book(client, company.slug, service, f"{MONDAY}T12:00:00Z")

    assert response.status_code == 201
    assert response.json()["start"].startswith("2026-11-02T12:00:00")


@pytest.mark.parametrize(
    "customer",
    [
        {"name": "", "phone": "31999991234"},
        {"name": "Marina", "phone": "abc"},
        {"name": "Marina", "phone": "123"},
        {"name": "Marina", "phone": "31999991234", "email": "não é e-mail"},
    ],
)
async def test_invalid_customer_data_is_refused(
    client: AsyncClient, customer: dict[str, str]
) -> None:
    company, _, _, service = await barbershop(client)

    response = await book(client, company.slug, service, at(9), customer=customer)

    assert response.status_code == 422


async def test_unknown_company_or_service_is_not_found(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)

    no_company = await book(client, "nao-existe", service, at(9))
    no_service = await book(
        client, company.slug, {"id": "00000000-0000-0000-0000-000000000000"}, at(9)
    )

    assert no_company.status_code == 404
    assert no_service.status_code == 404


async def test_a_customer_is_reused_by_phone_without_being_rewritten(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))

    await book(
        client,
        company.slug,
        service,
        at(10),
        customer={"name": "Outra Pessoa", "phone": "+55 (31) 99999-1234"},
    )
    await book(
        client,
        company.slug,
        service,
        at(11),
        customer={"name": "Marina de novo", "phone": "31 99999 1234"},
    )

    rows = (await client.get("/bookings", headers=headers)).json()
    assert len(rows) == 3
    # "+55..." tem outro formato e vira outro cliente; os dois sem "+" são o mesmo.
    assert len({row["customer"]["id"] for row in rows}) == 2
    assert {row["customer"]["name"] for row in rows} == {"Marina Lopes", "Outra Pessoa"}


async def test_staff_can_list_filter_read_and_cancel_bookings(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    first = (await book(client, company.slug, service, at(9))).json()
    second = (await book(client, company.slug, service, at(10))).json()

    listed = (await client.get("/bookings", headers=headers)).json()
    one = await client.get(f"/bookings/{first['id']}", headers=headers)
    cancelled = await client.post(f"/bookings/{second['id']}/cancel", headers=headers)
    again = await client.post(f"/bookings/{second['id']}/cancel", headers=headers)
    only_active = (await client.get("/bookings?status=confirmed", headers=headers)).json()
    by_resource = (
        await client.get(f"/bookings?resource_id={barber['id']}", headers=headers)
    ).json()
    window = (
        await client.get(
            "/bookings",
            params={"date_from": f"{MONDAY}T12:40:00Z", "date_to": f"{MONDAY}T14:00:00Z"},
            headers=headers,
        )
    ).json()

    assert [b["id"] for b in listed] == [first["id"], second["id"]]
    assert one.json()["customer"]["phone"] == "31999991234"
    assert one.json()["price_cents"] == 4500
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None
    assert again.status_code == 200
    assert [b["id"] for b in only_active] == [first["id"]]
    assert len(by_resource) == 2
    assert [b["id"] for b in window] == [second["id"]]


async def test_cancelling_frees_the_slot_again(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(9))).json()

    await client.post(f"/bookings/{booking['id']}/cancel", headers=headers)
    again = await book(client, company.slug, service, at(9))

    assert again.status_code == 201
    slots = local_starts((await get_slots(client, company.slug, service["id"])).json())
    assert "09:00" not in slots


async def test_booking_endpoints_require_front_desk_roles(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(9))).json()
    reception = bearer(await login(client, company, await add_user(client, headers, "reception")))
    professional = bearer(
        await login(client, company, await add_user(client, headers, "professional", barber["id"]))
    )

    anonymous = await client.get("/bookings")
    forbidden = await client.get("/bookings", headers=professional)
    allowed = await client.post(f"/bookings/{booking['id']}/cancel", headers=reception)

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403
    assert allowed.status_code == 200


async def test_bookings_are_isolated_between_companies(client: AsyncClient) -> None:
    company, _, _, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(9))).json()
    _, other_headers = await owner_headers(client)

    listed = await client.get("/bookings", headers=other_headers)
    read = await client.get(f"/bookings/{booking['id']}", headers=other_headers)
    cancelled = await client.post(f"/bookings/{booking['id']}/cancel", headers=other_headers)

    assert listed.json() == []
    assert read.status_code == 404
    assert cancelled.status_code == 404


async def test_a_service_from_another_company_cannot_be_booked(client: AsyncClient) -> None:
    _, _, _, service = await barbershop(client)
    other, _, _, _ = await barbershop(client)

    response = await book(client, other.slug, service, at(9))

    assert response.status_code == 404


async def test_resource_and_service_with_bookings_cannot_be_deleted(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    await book(client, company.slug, service, at(9))

    resource = await client.delete(f"/resources/{barber['id']}", headers=headers)
    catalog = await client.delete(f"/services/{service['id']}", headers=headers)
    deactivated = await client.patch(
        f"/resources/{barber['id']}", headers=headers, json={"active": False}
    )

    assert resource.status_code == 409
    assert catalog.status_code == 409
    assert deactivated.status_code == 200


async def test_a_booking_keeps_the_service_terms_it_was_made_with(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(9))).json()

    await client.patch(
        f"/services/{service['id']}", headers=headers, json={"duration_min": 60, "price_cents": 9}
    )
    stored = (await client.get(f"/bookings/{booking['id']}", headers=headers)).json()

    assert stored["price_cents"] == 4500
    assert stored["end"] == booking["end"]


async def test_a_room_with_capacity_takes_that_many_simultaneous_bookings(
    client: AsyncClient,
) -> None:
    company, headers = await owner_headers(client)
    room = await create_resource(client, headers, kind="sala", name="Sala Mauá", capacity=3)
    service = await create_service(client, headers, duration_min=60, buffer_after_min=0)
    await link(client, headers, service, room["id"])
    await add_rule(client, headers, room["id"], weekday=0, start="09:00", end="12:00")

    results = [
        (
            await book(
                client,
                company.slug,
                service,
                at(9),
                customer={**CUSTOMER, "phone": f"3199999000{n}"},
            )
        ).status_code
        for n in range(4)
    ]
    slots = local_starts((await get_slots(client, company.slug, service["id"])).json())
    next_hour = await book(client, company.slug, service, at(10))

    assert results == [201, 201, 201, 409]
    assert "09:00" not in slots
    assert "09:30" not in slots
    assert "10:00" in slots
    assert next_hour.status_code == 201

    first = (await client.get("/bookings", headers=headers)).json()[0]
    await client.post(f"/bookings/{first['id']}/cancel", headers=headers)
    assert (await book(client, company.slug, service, at(9))).status_code == 201


async def test_a_service_that_needs_a_room_reserves_the_executor_and_the_room(
    client: AsyncClient,
) -> None:
    company, headers = await owner_headers(client)
    branch_id = await default_branch_id(client, headers)
    doctor = await create_resource(client, headers, kind="medico", name="Dra. Helena")
    room = await create_resource(client, headers, kind="sala", name="Consultório 1")
    consult = await create_service(
        client,
        headers,
        name="Consulta",
        duration_min=60,
        buffer_after_min=0,
        required_resource_kinds=["sala"],
    )
    await link(client, headers, consult, doctor["id"])
    for resource in (doctor, room):
        await add_rule(client, headers, resource["id"], weekday=0, start="09:00", end="12:00")
    other_doctor = await create_resource(client, headers, kind="medico", name="Dr. Igor")
    await link(client, headers, consult, doctor["id"], other_doctor["id"])
    await add_rule(client, headers, other_doctor["id"], weekday=0, start="09:00", end="12:00")

    first = await book(client, company.slug, consult, at(9), branch_id=branch_id)
    # Há outro médico livre, mas só uma sala: o segundo pedido no mesmo horário não cabe.
    second = await book(
        client,
        company.slug,
        consult,
        at(9),
        customer={**CUSTOMER, "phone": "31988880000"},
    )

    assert first.status_code == 201
    assert sorted(first.json()["resource_ids"]) == sorted([doctor["id"], room["id"]])
    assert second.status_code == 409
    assert (await book(client, company.slug, consult, at(10))).status_code == 201


async def test_booking_a_specific_executor_leaves_the_others_free(client: AsyncClient) -> None:
    company, headers, barber, service = await barbershop(client)
    second = await create_resource(client, headers, name="Zeca Prado")
    await link(client, headers, service, barber["id"], second["id"])
    await add_rule(client, headers, second["id"], weekday=0, start="09:00", end="12:00")

    one = await book(client, company.slug, service, at(9), resource_id=barber["id"])
    same = await book(client, company.slug, service, at(9), resource_id=barber["id"])
    other = await book(client, company.slug, service, at(9), resource_id=second["id"])

    assert [r.status_code for r in (one, same, other)] == [201, 409, 201]
    assert other.json()["resource_ids"] == [second["id"]]


async def test_minimum_notice_applies_to_bookings(client: AsyncClient, app: FastAPI) -> None:
    company, _, _, service = await barbershop(client)
    # 08:30 em São Paulo; com 60 minutos de antecedência, o primeiro início possível é 09:30.
    app.dependency_overrides[utc_now] = lambda: datetime.datetime(
        2026, 11, 2, 11, 30, tzinfo=datetime.UTC
    )
    engine = build_engine(get_settings().migration_database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET settings = CAST(:settings AS jsonb) WHERE slug = :slug"),
            {"settings": json.dumps({"slots": {"min_notice_min": 60}}), "slug": company.slug},
        )
    await engine.dispose()

    too_soon = await book(client, company.slug, service, at(9))
    fine = await book(client, company.slug, service, at(10))

    assert too_soon.status_code == 409
    assert fine.status_code == 201
