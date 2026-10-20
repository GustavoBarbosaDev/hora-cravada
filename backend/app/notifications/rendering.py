import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.notifications.models import BOOKING_CANCELLED, BOOKING_CONFIRMED, BOOKING_RESCHEDULED

WEEKDAYS = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]
MONTHS = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]

SUBJECTS = {
    BOOKING_CONFIRMED: "Reserva confirmada em {tenant_name}",
    BOOKING_CANCELLED: "Reserva cancelada em {tenant_name}",
    BOOKING_RESCHEDULED: "Reserva remarcada em {tenant_name}",
}


def local_datetime(value: str, timezone: str) -> str:
    moment = datetime.datetime.fromisoformat(value).astimezone(ZoneInfo(timezone))
    return (
        f"{WEEKDAYS[moment.weekday()]}, {moment.day} de {MONTHS[moment.month - 1]} de "
        f"{moment.year}, às {moment:%H:%M}"
    )


def brl(cents: int) -> str:
    reais, centavos = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
    undefined=StrictUndefined,
)
_env.filters["local_datetime"] = local_datetime
_env.filters["brl"] = brl


def render_email(
    kind: str, event_id: str, recipient: str, payload: dict[str, Any], sender: str
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = SUBJECTS[kind].format(**payload)
    message["From"] = formataddr((payload["tenant_name"], sender))
    message["To"] = recipient
    # Fixo por evento: se o mesmo evento for enviado de novo depois de uma queda, o cliente
    # recebe duas mensagens com o mesmo Message-ID, que os clientes de e-mail costumam agrupar.
    message["Message-ID"] = f"<{event_id}@{sender.rpartition('@')[2]}>"
    message.set_content(_env.get_template(f"{kind}.txt.j2").render(**payload))
    message.add_alternative(_env.get_template(f"{kind}.html.j2").render(**payload), subtype="html")
    return message
