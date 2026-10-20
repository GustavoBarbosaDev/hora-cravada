from typing import Any

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.core.logging import configure_logging
from app.db.session import build_engine, build_sessionmaker
from app.notifications.outbox import process_outbox, smtp_sender

logger = structlog.get_logger()

OUTBOX_POLL_SECONDS = set(range(0, 60, 10))


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["engine"] = build_engine(settings.database_url)
    ctx["sessionmaker"] = build_sessionmaker(ctx["engine"])
    ctx["send_email"] = smtp_sender(settings)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def ping(ctx: dict[str, Any]) -> str:
    logger.info("worker_ping")
    return "pong"


async def deliver_outbox(ctx: dict[str, Any]) -> int:
    return await process_outbox(ctx["sessionmaker"], ctx["send_email"], get_settings())


class WorkerSettings:
    functions = [ping, deliver_outbox]
    cron_jobs = [cron(deliver_outbox, second=OUTBOX_POLL_SECONDS, run_at_startup=True)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
