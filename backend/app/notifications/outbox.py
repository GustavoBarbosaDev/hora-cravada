import datetime
from collections.abc import Awaitable, Callable
from email.message import EmailMessage

import aiosmtplib
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.notifications.models import FAILED, PENDING, SENT, OutboxEvent
from app.notifications.rendering import render_email

logger = structlog.get_logger()

Sender = Callable[[EmailMessage], Awaitable[None]]

BACKOFF_BASE = datetime.timedelta(seconds=30)
BACKOFF_CAP = datetime.timedelta(hours=1)
MAX_ERROR_LENGTH = 500


def retry_delay(attempts: int) -> datetime.timedelta:
    """Espera antes da próxima tentativa, dobrando a cada falha (30 s, 1 min, 2 min...)."""
    delay: datetime.timedelta = BACKOFF_BASE * 2 ** (attempts - 1)
    return min(delay, BACKOFF_CAP)


def smtp_sender(settings: Settings) -> Sender:
    async def send(message: EmailMessage) -> None:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=settings.smtp_starttls,
            timeout=15,
        )

    return send


async def process_outbox(
    sessionmaker: async_sessionmaker[AsyncSession],
    send: Sender,
    settings: Settings,
    now: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(datetime.UTC),
) -> int:
    """Entrega os eventos vencidos, até `outbox_batch_size`. Devolve quantos foram enviados."""
    sent = 0
    for _ in range(settings.outbox_batch_size):
        async with sessionmaker() as session, session.begin():
            outcome = await _deliver_next(session, send, settings, now())
        if outcome is None:
            break
        sent += outcome
    return sent


async def _deliver_next(
    session: AsyncSession, send: Sender, settings: Settings, now: datetime.datetime
) -> bool | None:
    """Trata um evento dentro da transação da sessão; `None` quando não há nenhum vencido.

    A linha fica travada durante o envio. SKIP LOCKED faz outro worker passar ao próximo evento
    em vez de esperar, e uma queda do processo desfaz a transação: o evento continua pendente e
    é reenviado. Isso garante entrega ao menos uma vez; o caso de queda entre o envio e o commit
    pode repetir a mensagem, que sai com o mesmo Message-ID.
    """
    await session.execute(text("SELECT set_config('app.outbox_worker', 'on', true)"))
    event = await session.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.status == PENDING, OutboxEvent.next_attempt_at <= now)
        .order_by(OutboxEvent.next_attempt_at, OutboxEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if event is None:
        return None
    try:
        message = render_email(
            event.kind, str(event.id), event.recipient, event.payload, settings.smtp_from
        )
        await send(message)
    except Exception as exc:
        event.attempts += 1
        event.last_error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        if event.attempts >= settings.outbox_max_attempts:
            event.status = FAILED
        else:
            event.next_attempt_at = now + retry_delay(event.attempts)
        logger.warning(
            "outbox_delivery_failed",
            event_id=str(event.id),
            kind=event.kind,
            attempts=event.attempts,
            status=event.status,
            error=event.last_error,
        )
        return False
    event.status = SENT
    event.attempts += 1
    event.sent_at = now
    event.last_error = None
    logger.info("outbox_delivered", event_id=str(event.id), kind=event.kind)
    return True
