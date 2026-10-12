import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, UnprocessableError
from app.resources.models import Resource
from app.services.models import ResourceService, Service
from app.services.schemas import ServiceIn, ServicePatch


async def list_services(session: AsyncSession) -> list[Service]:
    return list(await session.scalars(select(Service).order_by(Service.name, Service.id)))


async def get_service(session: AsyncSession, service_id: uuid.UUID) -> Service:
    service = await session.get(Service, service_id)
    if service is None:
        raise NotFoundError("Serviço não encontrado.")
    return service


async def create_service(session: AsyncSession, tenant_id: uuid.UUID, data: ServiceIn) -> Service:
    service = Service(tenant_id=tenant_id, **data.model_dump())
    session.add(service)
    await session.flush()
    return service


async def update_service(
    session: AsyncSession, service_id: uuid.UUID, data: ServicePatch
) -> Service:
    service = await get_service(session, service_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(service, field, value)
    await session.flush()
    return service


async def delete_service(session: AsyncSession, service_id: uuid.UUID) -> None:
    await session.delete(await get_service(session, service_id))
    await session.flush()


async def list_service_resources(session: AsyncSession, service_id: uuid.UUID) -> list[uuid.UUID]:
    await get_service(session, service_id)
    rows = await session.scalars(
        select(ResourceService.resource_id)
        .where(ResourceService.service_id == service_id)
        .order_by(ResourceService.resource_id)
    )
    return list(rows)


async def set_service_resources(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    service_id: uuid.UUID,
    resource_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Substitui o conjunto de recursos que executam o serviço."""
    # O lock serializa substituições concorrentes do mesmo serviço (apagar e reinserir).
    locked = await session.scalar(
        select(Service.id).where(Service.id == service_id).with_for_update()
    )
    if locked is None:
        raise NotFoundError("Serviço não encontrado.")
    wanted = set(resource_ids)
    found = set(await session.scalars(select(Resource.id).where(Resource.id.in_(wanted))))
    if found != wanted:
        raise UnprocessableError(
            "Há recursos que não existem.",
            details={"field": "resource_ids", "unknown": sorted(str(i) for i in wanted - found)},
        )
    await session.execute(delete(ResourceService).where(ResourceService.service_id == service_id))
    session.add_all(
        ResourceService(tenant_id=tenant_id, resource_id=rid, service_id=service_id)
        for rid in wanted
    )
    await session.flush()
    return sorted(wanted)
