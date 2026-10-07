import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken, User
from app.auth.schemas import CreateUserRequest, TokenPair
from app.config import Settings
from app.core.errors import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import (
    Principal,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    tenant_of_refresh_token,
    verify_password,
)
from app.db.session import set_tenant
from app.tenants.service import get_tenant_by_slug

INVALID_CREDENTIALS = "E-mail ou senha incorretos."


async def issue_tokens(
    session: AsyncSession, user: User, settings: Settings, family_id: uuid.UUID | None = None
) -> TokenPair:
    refresh_token = new_refresh_token(user.tenant_id)
    session.add(
        RefreshToken(
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await session.flush()
    access_token = create_access_token(Principal(user.id, user.tenant_id, user.role), settings)
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


async def login(
    session: AsyncSession, tenant_slug: str, email: str, password: str, settings: Settings
) -> TokenPair:
    try:
        tenant = await get_tenant_by_slug(session, tenant_slug)
    except NotFoundError:
        # Mesma resposta de uma senha errada, para não revelar quais empresas existem.
        await asyncio.to_thread(verify_password, None, password)
        raise UnauthorizedError(INVALID_CREDENTIALS) from None

    await set_tenant(session, tenant.id)
    user = await session.scalar(select(User).where(User.email == email))
    valid = await asyncio.to_thread(verify_password, user.password_hash if user else None, password)
    if user is None or not valid or not user.active:
        raise UnauthorizedError(INVALID_CREDENTIALS)
    return await issue_tokens(session, user, settings)


async def refresh(session: AsyncSession, token: str, settings: Settings) -> TokenPair:
    await set_tenant(session, tenant_of_refresh_token(token))
    stored = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise UnauthorizedError("Refresh token inválido ou expirado.")

    if stored.used_at is not None:
        # Um token já rotacionado voltou a ser apresentado: alguém o copiou. Derruba a família
        # inteira e confirma a revogação antes de responder com erro.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == stored.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        raise UnauthorizedError("Refresh token inválido ou expirado.")

    user = await session.get(User, stored.user_id)
    if user is None or not user.active:
        raise UnauthorizedError("Refresh token inválido ou expirado.")

    stored.used_at = now
    return await issue_tokens(session, user, settings, family_id=stored.family_id)


async def logout(session: AsyncSession, token: str) -> None:
    await set_tenant(session, tenant_of_refresh_token(token))
    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(token))
    )
    if stored is None:
        return
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == stored.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def create_user(session: AsyncSession, tenant_id: uuid.UUID, data: CreateUserRequest) -> User:
    password_hash = await asyncio.to_thread(hash_password, data.password)
    user = User(
        tenant_id=tenant_id,
        email=data.email,
        password_hash=password_hash,
        role=data.role,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "Já existe um usuário com esse e-mail.", details={"field": "email"}
        ) from exc
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.scalars(select(User).order_by(User.email))
    return list(result)
