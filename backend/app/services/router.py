import uuid

from fastapi import APIRouter, Response

from app.auth.deps import CurrentPrincipal, OwnerPrincipal, TenantSession
from app.services import service
from app.services.schemas import ServiceIn, ServiceOut, ServicePatch, ServiceResources

router = APIRouter(prefix="/services", tags=["services"])


@router.get("")
async def list_services(_: CurrentPrincipal, session: TenantSession) -> list[ServiceOut]:
    return [ServiceOut.model_validate(item) for item in await service.list_services(session)]


@router.get("/{service_id}")
async def get_service(
    service_id: uuid.UUID, _: CurrentPrincipal, session: TenantSession
) -> ServiceOut:
    return ServiceOut.model_validate(await service.get_service(session, service_id))


@router.post("", status_code=201)
async def create_service(
    data: ServiceIn, principal: OwnerPrincipal, session: TenantSession
) -> ServiceOut:
    return ServiceOut.model_validate(
        await service.create_service(session, principal.tenant_id, data)
    )


@router.patch("/{service_id}")
async def update_service(
    service_id: uuid.UUID, data: ServicePatch, _: OwnerPrincipal, session: TenantSession
) -> ServiceOut:
    return ServiceOut.model_validate(await service.update_service(session, service_id, data))


@router.delete("/{service_id}", status_code=204)
async def delete_service(
    service_id: uuid.UUID, _: OwnerPrincipal, session: TenantSession
) -> Response:
    await service.delete_service(session, service_id)
    return Response(status_code=204)


@router.get("/{service_id}/resources")
async def list_service_resources(
    service_id: uuid.UUID, _: CurrentPrincipal, session: TenantSession
) -> ServiceResources:
    return ServiceResources(resource_ids=await service.list_service_resources(session, service_id))


@router.put("/{service_id}/resources")
async def set_service_resources(
    service_id: uuid.UUID, data: ServiceResources, principal: OwnerPrincipal, session: TenantSession
) -> ServiceResources:
    resource_ids = await service.set_service_resources(
        session, principal.tenant_id, service_id, data.resource_ids
    )
    return ServiceResources(resource_ids=resource_ids)
