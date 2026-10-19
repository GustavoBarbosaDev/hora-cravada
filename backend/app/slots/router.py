import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.slots import service
from app.slots.schemas import SlotQuery, SlotsOut
from app.tenants.deps import PublicSession
from app.tenants.service import get_tenant_by_slug

router = APIRouter(prefix="/public/{slug}", tags=["public"])


def utc_now() -> datetime.datetime:
    """Relógio da API; os testes o substituem para fixar a data."""
    return datetime.datetime.now(datetime.UTC)


@router.get("/slots")
async def list_slots(
    slug: str,
    query: Annotated[SlotQuery, Query()],
    session: PublicSession,
    now: Annotated[datetime.datetime, Depends(utc_now)],
) -> SlotsOut:
    tenant = await get_tenant_by_slug(session, slug)
    return await service.find_slots(session, tenant, query, now)
