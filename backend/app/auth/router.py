from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.deps import CurrentPrincipal, OwnerPrincipal, TenantSession
from app.auth.models import Role, User
from app.auth.schemas import (
    CreateUserRequest,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserOut,
)
from app.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.db.session import get_transaction

router = APIRouter(tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, role=Role(user.role), active=user.active)


@router.post("/auth/login")
async def login(
    data: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_transaction)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPair:
    return await service.login(session, data.tenant_slug, data.email, data.password, settings)


@router.post("/auth/refresh")
async def refresh(
    data: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_transaction)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPair:
    return await service.refresh(session, data.refresh_token, settings)


@router.post("/auth/logout", status_code=204)
async def logout(
    data: RefreshRequest, session: Annotated[AsyncSession, Depends(get_transaction)]
) -> Response:
    await service.logout(session, data.refresh_token)
    return Response(status_code=204)


@router.get("/auth/me")
async def me(principal: CurrentPrincipal, session: TenantSession) -> UserOut:
    user = await session.get(User, principal.user_id)
    if user is None or not user.active:
        raise UnauthorizedError("Autenticação necessária.")
    return user_out(user)


@router.get("/users")
async def list_users(_: OwnerPrincipal, session: TenantSession) -> list[UserOut]:
    return [user_out(user) for user in await service.list_users(session)]


@router.post("/users", status_code=201)
async def create_user(
    data: CreateUserRequest, principal: OwnerPrincipal, session: TenantSession
) -> UserOut:
    return user_out(await service.create_user(session, principal.tenant_id, data))
