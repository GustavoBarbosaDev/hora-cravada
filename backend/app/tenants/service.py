import asyncio

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password
from app.db.session import set_tenant
from app.tenants.models import Tenant
from app.tenants.schemas import SignupRequest


async def get_tenant_by_slug(session: AsyncSession, slug: str) -> Tenant:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise NotFoundError("Empresa não encontrada.")
    return tenant


async def signup(session: AsyncSession, data: SignupRequest) -> tuple[Tenant, User]:
    tenant = Tenant(slug=data.slug, name=data.tenant_name, timezone_default=data.timezone)
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("Esse endereço já está em uso.", details={"field": "slug"}) from exc

    await set_tenant(session, tenant.id)
    password_hash = await asyncio.to_thread(hash_password, data.owner_password)
    owner = User(
        tenant_id=tenant.id,
        email=data.owner_email,
        password_hash=password_hash,
        role=Role.owner,
    )
    session.add(owner)
    await session.flush()
    return tenant, owner
