import uuid
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


async def get_transaction(request: Request) -> AsyncIterator[AsyncSession]:
    """Uma transação por requisição: confirma ao final e desfaz se a rota falhar.

    O contexto de tenant vale só dentro da transação. Quem confirmar antes do fim
    (por exemplo, para persistir algo e ainda assim responder com erro) perde o contexto.
    """
    async with request.app.state.sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    # set_config(..., true) equivale a SET LOCAL e aceita parâmetro, ao contrário do SET.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
