import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import DependencyUnavailableError, register_error_handlers
from app.core.logging import configure_logging
from app.db.session import build_engine, build_sessionmaker, get_session

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = build_engine(get_settings().database_url)
    app.state.sessionmaker = build_sessionmaker(engine)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Hora Cravada", lifespan=lifespan)
    register_error_handlers(app)

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                duration_ms=elapsed_ms,
            )
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health")
    async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
        try:
            await session.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            raise DependencyUnavailableError("Banco de dados indisponível.") from exc
        return {"status": "ok"}

    return app


app = create_app()
