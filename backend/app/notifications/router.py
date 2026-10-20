from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.auth.deps import OwnerPrincipal, TenantSession
from app.notifications.models import OutboxEvent
from app.notifications.schemas import OutboxEventOut

router = APIRouter(prefix="/outbox-events", tags=["notifications"])


@router.get("")
async def list_outbox_events(
    _: OwnerPrincipal,
    session: TenantSession,
    status: Literal["pending", "sent", "failed"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[OutboxEventOut]:
    query = select(OutboxEvent).order_by(OutboxEvent.created_at.desc(), OutboxEvent.id).limit(limit)
    if status is not None:
        query = query.where(OutboxEvent.status == status)
    return [OutboxEventOut.model_validate(e) for e in await session.scalars(query)]
