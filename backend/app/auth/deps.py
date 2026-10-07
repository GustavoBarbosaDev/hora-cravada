from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import Principal, decode_access_token
from app.db.session import get_transaction, set_tenant

bearer = HTTPBearer(auto_error=False)


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if credentials is None:
        raise UnauthorizedError("Autenticação necessária.")
    return decode_access_token(credentials.credentials, settings)


def require_roles(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    allowed = {role.value for role in roles}

    async def check(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.role not in allowed:
            raise ForbiddenError("Seu perfil não tem acesso a este recurso.")
        return principal

    return check


async def get_tenant_session(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_transaction)],
) -> AsyncIterator[AsyncSession]:
    """Sessão do painel: o tenant vem do token e vale como `app.tenant_id` na transação."""
    await set_tenant(session, principal.tenant_id)
    yield session


TenantSession = Annotated[AsyncSession, Depends(get_tenant_session)]
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
OwnerPrincipal = Annotated[Principal, Depends(require_roles(Role.owner))]
