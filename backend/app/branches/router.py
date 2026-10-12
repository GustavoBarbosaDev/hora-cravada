import uuid

from fastapi import APIRouter, Response

from app.auth.deps import CurrentPrincipal, OwnerPrincipal, TenantSession
from app.branches import service
from app.branches.schemas import BranchIn, BranchOut, BranchPatch

router = APIRouter(prefix="/branches", tags=["branches"])


@router.get("")
async def list_branches(_: CurrentPrincipal, session: TenantSession) -> list[BranchOut]:
    return [BranchOut.model_validate(branch) for branch in await service.list_branches(session)]


@router.post("", status_code=201)
async def create_branch(
    data: BranchIn, principal: OwnerPrincipal, session: TenantSession
) -> BranchOut:
    return BranchOut.model_validate(await service.create_branch(session, principal.tenant_id, data))


@router.patch("/{branch_id}")
async def update_branch(
    branch_id: uuid.UUID, data: BranchPatch, _: OwnerPrincipal, session: TenantSession
) -> BranchOut:
    return BranchOut.model_validate(await service.update_branch(session, branch_id, data))


@router.delete("/{branch_id}", status_code=204)
async def delete_branch(
    branch_id: uuid.UUID, _: OwnerPrincipal, session: TenantSession
) -> Response:
    await service.delete_branch(session, branch_id)
    return Response(status_code=204)
