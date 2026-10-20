import asyncio
import datetime
from collections.abc import AsyncIterator
from email.message import EmailMessage
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db.session import build_engine, build_sessionmaker
from app.notifications.models import BOOKING_RESCHEDULED
from app.notifications.outbox import process_outbox
from tests.conftest import Databases
from tests.helpers import add_user, bearer, login, owner_headers
from tests.integration.test_bookings import CUSTOMER, at, book
from tests.integration.test_slots_api import (  # noqa: F401  (fixed_clock é autouse)
    barbershop,
    fixed_clock,
)

# O banco grava `next_attempt_at` com o relógio real; o do worker de teste fica adiante.
NOW = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)


class Outbox:
    """Mensagens que o worker de teste conseguiu entregar, com falha ou queda opcionais."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker
        self.delivered: list[EmailMessage] = []
        self.error: BaseException | None = None
        self.delay = 0.0

    async def send(self, message: EmailMessage) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        self.delivered.append(message)

    async def run(self, now: datetime.datetime = NOW, settings: Settings | None = None) -> int:
        return await process_outbox(
            self.sessionmaker, self.send, settings or get_settings(), lambda: now
        )


@pytest.fixture
async def outbox(migrated_database: Databases) -> AsyncIterator[Outbox]:
    # O banco é compartilhado entre testes: eventos que sobraram não podem ser entregues aqui.
    admin = create_async_engine(migrated_database.admin_url)
    async with admin.begin() as conn:
        await conn.execute(
            text("UPDATE outbox_events SET status = 'sent' WHERE status = 'pending'")
        )
    await admin.dispose()
    engine = build_engine(get_settings().database_url)
    yield Outbox(build_sessionmaker(engine))
    await engine.dispose()


async def events(
    client: AsyncClient, headers: dict[str, str], **params: str
) -> list[dict[str, Any]]:
    response = await client.get("/outbox-events", headers=headers, params=params)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


async def test_booking_and_its_confirmation_event_are_stored_together(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)

    response = await book(client, company.slug, service, at(9))

    [event] = await events(client, headers)
    assert response.status_code == 201
    assert event["kind"] == "booking_confirmed"
    assert event["booking_id"] == response.json()["id"]
    assert event["recipient"] == CUSTOMER["email"]
    assert (event["status"], event["attempts"]) == ("pending", 0)


async def test_a_refused_booking_leaves_no_event(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))

    refused = await book(client, company.slug, service, at(9))

    assert refused.status_code == 409
    assert len(await events(client, headers)) == 1


async def test_customer_without_email_gets_no_event(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)

    response = await book(
        client, company.slug, service, at(9), customer={"name": "Rui Alves", "phone": "31988887777"}
    )

    assert response.status_code == 201
    assert await events(client, headers) == []


async def test_cancelling_queues_one_cancellation_even_when_repeated(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(9))).json()

    await client.post(f"/bookings/{booking['id']}/cancel", headers=headers)
    await client.post(f"/bookings/{booking['id']}/cancel", headers=headers)

    kinds = sorted(e["kind"] for e in await events(client, headers))
    assert kinds == ["booking_cancelled", "booking_confirmed"]


async def test_worker_sends_the_email_and_marks_the_event_as_sent(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9), notes="Degradê")

    sent = await outbox.run()

    [message] = outbox.delivered
    [event] = await events(client, headers)
    body = message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert sent == 1
    assert message["To"] == CUSTOMER["email"]
    assert message["Subject"] == "Reserva confirmada em Barbearia do Seu Zé"
    assert "segunda-feira, 2 de novembro de 2026, às 09:00" in body
    assert "Degradê" in body
    assert (event["status"], event["attempts"], event["last_error"]) == ("sent", 1, None)
    assert event["sent_at"] is not None


async def test_cancellation_email_describes_the_booking_that_was_cancelled(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(14))).json()
    await client.post(f"/bookings/{booking['id']}/cancel", headers=headers)

    await outbox.run()

    subjects = sorted(m["Subject"] for m in outbox.delivered)
    assert subjects == [
        "Reserva cancelada em Barbearia do Seu Zé",
        "Reserva confirmada em Barbearia do Seu Zé",
    ]


async def test_rescheduled_event_is_rendered_and_sent(
    client: AsyncClient, outbox: Outbox, migrated_database: Databases
) -> None:
    company, headers, _, service = await barbershop(client)
    booking = (await book(client, company.slug, service, at(9))).json()
    await outbox.run()
    admin = create_async_engine(migrated_database.admin_url)
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO outbox_events (tenant_id, booking_id, kind, recipient, payload) "
                "SELECT tenant_id, booking_id, :kind, recipient, payload FROM outbox_events "
                "WHERE booking_id = :booking"
            ),
            {"kind": BOOKING_RESCHEDULED, "booking": booking["id"]},
        )
    await admin.dispose()

    await outbox.run()

    assert outbox.delivered[-1]["Subject"] == "Reserva remarcada em Barbearia do Seu Zé"


async def test_failed_delivery_keeps_the_event_for_a_later_attempt(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))
    outbox.error = ConnectionRefusedError("smtp fora do ar")

    sent = await outbox.run()
    same_moment = await outbox.run()
    outbox.error = None
    too_early = await outbox.run(NOW + datetime.timedelta(seconds=10))
    on_time = await outbox.run(NOW + datetime.timedelta(seconds=31))

    [event] = await events(client, headers)
    assert (sent, same_moment, too_early, on_time) == (0, 0, 0, 1)
    assert (event["status"], event["attempts"]) == ("sent", 2)


async def test_backoff_grows_with_each_failed_attempt(client: AsyncClient, outbox: Outbox) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))
    outbox.error = ConnectionRefusedError("smtp fora do ar")

    await outbox.run()
    [first] = await events(client, headers)
    await outbox.run(NOW + datetime.timedelta(seconds=31))
    [second] = await events(client, headers)

    assert first["last_error"] == "ConnectionRefusedError: smtp fora do ar"
    assert datetime.datetime.fromisoformat(first["next_attempt_at"]) == NOW + datetime.timedelta(
        seconds=30
    )
    assert datetime.datetime.fromisoformat(second["next_attempt_at"]) == (
        NOW + datetime.timedelta(seconds=31 + 60)
    )


async def test_event_that_runs_out_of_attempts_becomes_failed_and_visible(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))
    outbox.error = TimeoutError("sem resposta")
    settings = get_settings().model_copy(update={"outbox_max_attempts": 3})

    moment = NOW
    for _ in range(5):
        await outbox.run(moment, settings)
        moment += datetime.timedelta(hours=2)

    [failed] = await events(client, headers, status="failed")
    assert failed["attempts"] == 3
    assert failed["last_error"] == "TimeoutError: sem resposta"
    assert await events(client, headers, status="pending") == []


async def test_worker_crash_after_the_booking_does_not_lose_the_email(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))
    outbox.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await outbox.run()
    [after_crash] = await events(client, headers)
    outbox.error = None
    await outbox.run()

    [after_restart] = await events(client, headers)
    assert (after_crash["status"], after_crash["attempts"]) == ("pending", 0)
    assert after_restart["status"] == "sent"
    assert len(outbox.delivered) == 1


async def test_a_sent_event_is_not_sent_again(client: AsyncClient, outbox: Outbox) -> None:
    company, _, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))

    first = await outbox.run()
    second = await outbox.run(NOW + datetime.timedelta(days=1))

    assert (first, second) == (1, 0)
    assert len(outbox.delivered) == 1


async def test_two_workers_never_send_the_same_event_twice(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    for hour in range(9, 12):
        await book(client, company.slug, service, at(hour))
    outbox.delay = 0.05
    other = Outbox(outbox.sessionmaker)
    other.delay = 0.05

    sent = await asyncio.gather(outbox.run(), other.run())

    delivered = [*outbox.delivered, *other.delivered]
    assert sum(sent) == 3
    assert len({m["Message-ID"] for m in delivered}) == 3
    assert len(delivered) == 3
    assert {e["status"] for e in await events(client, headers)} == {"sent"}


async def test_events_are_isolated_between_companies(client: AsyncClient) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))
    _, other_headers = await owner_headers(client)

    assert len(await events(client, headers)) == 1
    assert await events(client, other_headers) == []


async def test_only_the_owner_can_list_events(client: AsyncClient) -> None:
    company, headers, _, _ = await barbershop(client)
    email = await add_user(client, headers, "reception")
    reception = bearer(await login(client, company, email))

    assert (await client.get("/outbox-events", headers=reception)).status_code == 403
    assert (await client.get("/outbox-events")).status_code == 401


async def test_tenant_requests_cannot_see_events_without_the_worker_flag(
    client: AsyncClient, outbox: Outbox
) -> None:
    company, headers, _, service = await barbershop(client)
    await book(client, company.slug, service, at(9))

    async with outbox.sessionmaker() as session:
        visible = (await session.execute(text("SELECT count(*) FROM outbox_events"))).scalar_one()
        await session.execute(text("SELECT set_config('app.outbox_worker', 'on', true)"))
        with_flag = (await session.execute(text("SELECT count(*) FROM outbox_events"))).scalar_one()

    assert visible == 0
    assert with_flag >= 1
