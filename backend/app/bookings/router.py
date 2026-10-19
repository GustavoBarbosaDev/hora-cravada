import datetime
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime

from app.auth.deps import FrontDeskPrincipal, TenantSession
from app.bookings import service
from app.bookings.schemas import BookingIn, BookingOut, PublicBookingOut
from app.slots.router import utc_now
from app.tenants.deps import PublicSession
from app.tenants.service import get_tenant_by_slug

public_router = APIRouter(prefix="/public/{slug}", tags=["public"])
router = APIRouter(prefix="/bookings", tags=["bookings"])


@public_router.post("/bookings", status_code=201)
async def create_booking(
    slug: str,
    data: BookingIn,
    session: PublicSession,
    now: Annotated[datetime.datetime, Depends(utc_now)],
) -> PublicBookingOut:
    tenant = await get_tenant_by_slug(session, slug)
    return await service.create_booking(session, tenant, data, now)


@router.get("")
async def list_bookings(
    _: FrontDeskPrincipal,
    session: TenantSession,
    date_from: AwareDatetime | None = None,
    date_to: AwareDatetime | None = None,
    resource_id: uuid.UUID | None = None,
    status: Literal["confirmed", "cancelled"] | None = None,
) -> list[BookingOut]:
    return await service.list_bookings(
        session, date_from=date_from, date_to=date_to, resource_id=resource_id, status=status
    )


@router.get("/{booking_id}")
async def get_booking(
    booking_id: uuid.UUID, _: FrontDeskPrincipal, session: TenantSession
) -> BookingOut:
    return await service.get_booking(session, booking_id)


@router.post("/{booking_id}/cancel")
async def cancel_booking(
    booking_id: uuid.UUID,
    _: FrontDeskPrincipal,
    session: TenantSession,
    now: Annotated[datetime.datetime, Depends(utc_now)],
) -> BookingOut:
    return await service.cancel_booking(session, booking_id, now)
