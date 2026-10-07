from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_transaction
from app.tenants import service
from app.tenants.schemas import SignupRequest, SignupResponse, TenantOut

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", status_code=201)
async def signup(
    data: SignupRequest, session: Annotated[AsyncSession, Depends(get_transaction)]
) -> SignupResponse:
    tenant, owner = await service.signup(session, data)
    return SignupResponse(
        tenant=TenantOut(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            timezone_default=tenant.timezone_default,
        ),
        owner_id=owner.id,
    )
