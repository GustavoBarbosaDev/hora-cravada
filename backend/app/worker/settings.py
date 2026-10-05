from typing import Any

import structlog
from arq.connections import RedisSettings

from app.config import get_settings
from app.core.logging import configure_logging

logger = structlog.get_logger()


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)


async def ping(ctx: dict[str, Any]) -> str:
    logger.info("worker_ping")
    return "pong"


class WorkerSettings:
    functions = [ping]
    on_startup = on_startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
