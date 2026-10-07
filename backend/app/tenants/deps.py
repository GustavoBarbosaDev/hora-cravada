from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_transaction, set_tenant
from app.tenants.service import get_tenant_by_slug


async def get_public_session(
    slug: str, session: Annotated[AsyncSession, Depends(get_transaction)]
) -> AsyncIterator[AsyncSession]:
    """Sessão da área pública: o tenant vem do `slug` na URL, não de um token."""
    tenant = await get_tenant_by_slug(session, slug)
    await set_tenant(session, tenant.id)
    yield session


PublicSession = Annotated[AsyncSession, Depends(get_public_session)]
