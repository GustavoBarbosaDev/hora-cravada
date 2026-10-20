import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bookings.models import Booking, BookingResource, Customer
from app.notifications.models import OutboxEvent
from app.resources.models import Resource
from app.services.models import Service
from app.tenants.models import Branch, Tenant


async def enqueue_booking_event(session: AsyncSession, kind: str, booking_id: uuid.UUID) -> None:
    """Grava o aviso na transação da chamada, para que a reserva e o aviso valham juntos.

    Cliente sem e-mail não gera evento: não há para quem enviar.
    """
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise LookupError(f"Reserva {booking_id} não encontrada.")
    customer = await session.get(Customer, booking.customer_id)
    if customer is None or not customer.email:
        return
    service = await session.get(Service, booking.service_id)
    branch = await session.get(Branch, booking.branch_id)
    tenant = await session.get(Tenant, booking.tenant_id)
    resource_names = list(
        await session.scalars(
            select(Resource.name)
            .join(BookingResource, BookingResource.resource_id == Resource.id)
            .where(BookingResource.booking_id == booking.id)
            .order_by(Resource.name)
        )
    )
    assert service is not None and branch is not None and tenant is not None
    payload: dict[str, Any] = {
        "tenant_name": tenant.name,
        "customer_name": customer.name,
        "service_name": service.name,
        "branch_name": branch.name,
        "branch_address": branch.address,
        "timezone": branch.timezone,
        "start": booking.start_at.isoformat(),
        "end": booking.end_at.isoformat(),
        "resource_names": resource_names,
        "price_cents": booking.price_cents,
        "notes": booking.notes,
    }
    await session.execute(
        insert(OutboxEvent)
        .values(
            tenant_id=booking.tenant_id,
            booking_id=booking.id,
            kind=kind,
            recipient=customer.email,
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["booking_id", "kind"])
    )
