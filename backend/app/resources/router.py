import uuid

from fastapi import APIRouter, Response

from app.auth.deps import CurrentPrincipal, OwnerPrincipal, TenantSession
from app.resources import service
from app.resources.schemas import ResourceIn, ResourceOut, ResourcePatch

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("")
async def list_resources(
    _: CurrentPrincipal,
    session: TenantSession,
    kind: str | None = None,
    branch_id: uuid.UUID | None = None,
) -> list[ResourceOut]:
    resources = await service.list_resources(session, kind=kind, branch_id=branch_id)
    return [ResourceOut.model_validate(resource) for resource in resources]


@router.get("/{resource_id}")
async def get_resource(
    resource_id: uuid.UUID, _: CurrentPrincipal, session: TenantSession
) -> ResourceOut:
    return ResourceOut.model_validate(await service.get_resource(session, resource_id))


@router.post("", status_code=201)
async def create_resource(
    data: ResourceIn, principal: OwnerPrincipal, session: TenantSession
) -> ResourceOut:
    return ResourceOut.model_validate(
        await service.create_resource(session, principal.tenant_id, data)
    )


@router.patch("/{resource_id}")
async def update_resource(
    resource_id: uuid.UUID, data: ResourcePatch, _: OwnerPrincipal, session: TenantSession
) -> ResourceOut:
    return ResourceOut.model_validate(await service.update_resource(session, resource_id, data))


@router.delete("/{resource_id}", status_code=204)
async def delete_resource(
    resource_id: uuid.UUID, _: OwnerPrincipal, session: TenantSession
) -> Response:
    await service.delete_resource(session, resource_id)
    return Response(status_code=204)
