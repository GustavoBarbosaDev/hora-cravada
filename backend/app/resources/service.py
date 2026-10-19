import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.branches.service import get_branch
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.db.errors import FOREIGN_KEY_VIOLATION, sqlstate
from app.resources.models import Resource
from app.resources.schemas import ResourceIn, ResourcePatch
from app.tenants.models import Branch


async def list_resources(
    session: AsyncSession, *, kind: str | None = None, branch_id: uuid.UUID | None = None
) -> list[Resource]:
    query = select(Resource).order_by(Resource.name, Resource.id)
    if kind is not None:
        query = query.where(Resource.kind == kind)
    if branch_id is not None:
        query = query.where(Resource.branch_id == branch_id)
    return list(await session.scalars(query))


async def get_resource(session: AsyncSession, resource_id: uuid.UUID) -> Resource:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise NotFoundError("Recurso não encontrado.")
    return resource


async def require_branch(session: AsyncSession, branch_id: uuid.UUID) -> Branch:
    try:
        return await get_branch(session, branch_id)
    except NotFoundError:
        raise UnprocessableError("Filial não encontrada.", details={"field": "branch_id"}) from None


async def create_resource(
    session: AsyncSession, tenant_id: uuid.UUID, data: ResourceIn
) -> Resource:
    await require_branch(session, data.branch_id)
    resource = Resource(tenant_id=tenant_id, **data.model_dump())
    session.add(resource)
    await session.flush()
    return resource


async def update_resource(
    session: AsyncSession, resource_id: uuid.UUID, data: ResourcePatch
) -> Resource:
    resource = await get_resource(session, resource_id)
    changes = data.model_dump(exclude_unset=True)
    if "branch_id" in changes:
        await require_branch(session, changes["branch_id"])
    for field, value in changes.items():
        setattr(resource, field, value)
    await session.flush()
    return resource


async def delete_resource(session: AsyncSession, resource_id: uuid.UUID) -> None:
    resource = await get_resource(session, resource_id)
    try:
        await session.delete(resource)
        await session.flush()
    except IntegrityError as exc:
        if sqlstate(exc) != FOREIGN_KEY_VIOLATION:
            raise
        raise ConflictError("O recurso tem reservas; desative-o em vez de apagar.") from exc
