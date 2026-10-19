import asyncio
import datetime
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.slots.router import utc_now
from tests.helpers import owner_headers
from tests.integration.test_availability import add_rule
from tests.integration.test_bookings import at, book
from tests.integration.test_branches_and_resources import create_resource
from tests.integration.test_services import create_service
from tests.integration.test_slots_api import link

REQUESTS = 10


@pytest.fixture(autouse=True)
def fixed_clock(app: FastAPI) -> Iterator[None]:
    now = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
    app.dependency_overrides[utc_now] = lambda: now
    yield
    app.dependency_overrides.pop(utc_now, None)


async def test_simultaneous_requests_for_one_slot_let_exactly_one_through(
    client: AsyncClient,
) -> None:
    company, headers = await owner_headers(client)
    barber = await create_resource(client, headers)
    service = await create_service(client, headers, duration_min=30, buffer_after_min=0)
    await link(client, headers, service, barber["id"])
    await add_rule(client, headers, barber["id"], weekday=0, start="09:00", end="12:00")

    responses = await asyncio.gather(
        *(
            book(
                client,
                company.slug,
                service,
                at(9),
                customer={"name": f"Cliente {n}", "phone": f"3199990{n:04d}"},
            )
            for n in range(REQUESTS)
        )
    )

    assert sorted(r.status_code for r in responses) == [201] + [409] * (REQUESTS - 1)
    stored = (await client.get("/bookings", headers=headers)).json()
    assert [b["status"] for b in stored] == ["confirmed"]


async def test_simultaneous_requests_never_exceed_the_room_capacity(client: AsyncClient) -> None:
    company, headers = await owner_headers(client)
    room = await create_resource(client, headers, kind="sala", name="Sala Mauá", capacity=3)
    service = await create_service(client, headers, duration_min=60, buffer_after_min=0)
    await link(client, headers, service, room["id"])
    await add_rule(client, headers, room["id"], weekday=0, start="09:00", end="12:00")

    responses = await asyncio.gather(
        *(
            book(
                client,
                company.slug,
                service,
                at(9),
                customer={"name": f"Cliente {n}", "phone": f"3199990{n:04d}"},
            )
            for n in range(REQUESTS)
        )
    )

    assert sorted(r.status_code for r in responses) == [201] * 3 + [409] * (REQUESTS - 3)


async def test_simultaneous_overlapping_starts_never_double_book(client: AsyncClient) -> None:
    company, headers = await owner_headers(client)
    barber = await create_resource(client, headers)
    service = await create_service(client, headers, duration_min=30, buffer_after_min=0)
    await link(client, headers, service, barber["id"])
    await add_rule(client, headers, barber["id"], weekday=0, start="09:00", end="12:00")
    starts = [at(9), at(9, 15), at(9, 30), at(9, 45), at(9, 5), at(9, 20)]

    responses = await asyncio.gather(
        *(
            book(
                client,
                company.slug,
                service,
                start,
                customer={"name": f"Cliente {n}", "phone": f"3199990{n:04d}"},
            )
            for n, start in enumerate(starts)
        )
    )

    booked = sorted(
        datetime.datetime.fromisoformat(b["start"])
        for b in (await client.get("/bookings?status=confirmed", headers=headers)).json()
    )
    assert len(booked) == sum(r.status_code == 201 for r in responses)
    for earlier, later in zip(booked, booked[1:], strict=False):
        assert later - earlier >= datetime.timedelta(minutes=30)
