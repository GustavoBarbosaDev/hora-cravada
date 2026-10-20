from typing import Any

import pytest

from app.notifications.models import BOOKING_CANCELLED, BOOKING_CONFIRMED, BOOKING_RESCHEDULED
from app.notifications.outbox import BACKOFF_CAP, retry_delay
from app.notifications.rendering import brl, local_datetime, render_email

PAYLOAD: dict[str, Any] = {
    "tenant_name": "Barbearia do Seu Zé",
    "customer_name": "Marina Lopes",
    "service_name": "Corte masculino",
    "branch_name": "Centro",
    "branch_address": "Rua da Bahia, 120",
    "timezone": "America/Sao_Paulo",
    "start": "2026-11-02T12:00:00+00:00",
    "end": "2026-11-02T12:30:00+00:00",
    "resource_names": ["Carlos"],
    "price_cents": 4590,
    "notes": None,
}


def test_retry_delay_doubles_after_each_failure() -> None:
    assert [retry_delay(n).total_seconds() for n in (1, 2, 3, 4)] == [30, 60, 120, 240]


def test_retry_delay_stops_growing_at_the_cap() -> None:
    assert retry_delay(30) == BACKOFF_CAP


def test_price_is_formatted_in_reais() -> None:
    assert brl(4590) == "R$ 45,90"
    assert brl(5) == "R$ 0,05"
    assert brl(123456789) == "R$ 1.234.567,89"


def test_date_is_shown_in_the_branch_timezone() -> None:
    assert (
        local_datetime("2026-11-02T12:00:00+00:00", "America/Sao_Paulo")
        == "segunda-feira, 2 de novembro de 2026, às 09:00"
    )


@pytest.mark.parametrize(
    ("kind", "subject", "heading"),
    [
        (BOOKING_CONFIRMED, "Reserva confirmada em Barbearia do Seu Zé", "está confirmada"),
        (BOOKING_CANCELLED, "Reserva cancelada em Barbearia do Seu Zé", "foi cancelada"),
        (BOOKING_RESCHEDULED, "Reserva remarcada em Barbearia do Seu Zé", "foi remarcada"),
    ],
)
def test_each_event_kind_renders_subject_and_both_bodies(
    kind: str, subject: str, heading: str
) -> None:
    message = render_email(kind, "ev-1", "marina@exemplo.com.br", PAYLOAD, "agenda@zeapp.com.br")

    text = message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    html = message.get_body(("html",)).get_content()  # type: ignore[union-attr]
    assert message["Subject"] == subject
    assert message["To"] == "marina@exemplo.com.br"
    assert message["Message-ID"] == "<ev-1@zeapp.com.br>"
    assert heading in text
    for body in (text, html):
        assert "Marina Lopes" in body
        assert "segunda-feira, 2 de novembro de 2026, às 09:00" in body
        assert "R$ 45,90" in body
        assert "Rua da Bahia, 120" in body


def test_customer_input_is_escaped_in_html_and_left_alone_in_text() -> None:
    payload = {**PAYLOAD, "notes": "<script>alert(1)</script>"}

    message = render_email(
        BOOKING_CONFIRMED, "ev-1", "marina@exemplo.com.br", payload, "agenda@zeapp.com.br"
    )

    html = message.get_body(("html",)).get_content()  # type: ignore[union-attr]
    text = message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<script>" in text


def test_event_without_resources_or_address_omits_those_lines() -> None:
    payload = {**PAYLOAD, "resource_names": [], "branch_address": None}

    message = render_email(
        BOOKING_CONFIRMED, "ev-1", "marina@exemplo.com.br", payload, "agenda@zeapp.com.br"
    )

    text = message.get_body(("plain",)).get_content()  # type: ignore[union-attr]
    assert "Com:" not in text
    assert "Local: Centro\n" in text
