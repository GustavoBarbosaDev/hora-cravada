import datetime
import uuid
from itertools import islice

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bookings.models import CANCELLED, CONFIRMED, Booking, BookingResource, Customer
from app.bookings.schemas import BookingIn, BookingOut, CustomerOut, PublicBookingOut
from app.core.errors import ConflictError, NotFoundError
from app.db.errors import EXCLUSION_VIOLATION, sqlstate
from app.resources.models import Resource
from app.slots.schemas import SlotQuery
from app.slots.service import plan_slots
from app.tenants.models import Tenant

# A grade de 5 minutos contém a de qualquer passo aceito pelo endpoint de slots, então qualquer
# horário que a página ofereceu é um início válido aqui.
BOOKING_STEP_MIN = 5
# Vagas tentadas por recurso quando outra reserva ocupa a vaga escolhida entre a leitura e a
# gravação; com capacidade alta não vale percorrer todas.
SEAT_ATTEMPTS = 5


class _NoSeat(Exception):
    """Alguma vaga que o motor via livre foi ocupada por outra requisição."""


def _booking_out(booking: Booking, resource_ids: list[uuid.UUID], customer: Customer) -> BookingOut:
    return BookingOut(
        id=booking.id,
        service_id=booking.service_id,
        branch_id=booking.branch_id,
        resource_ids=resource_ids,
        start=booking.start_at,
        end=booking.end_at,
        status=booking.status,
        customer=CustomerOut.model_validate(customer),
        price_cents=booking.price_cents,
        notes=booking.notes,
        created_at=booking.created_at,
        cancelled_at=booking.cancelled_at,
    )


async def create_booking(
    session: AsyncSession, tenant: Tenant, data: BookingIn, now: datetime.datetime
) -> PublicBookingOut:
    start = data.start.astimezone(datetime.UTC)
    # O fuso é da filial, que só se conhece depois de achar o serviço; três dias em UTC cobrem
    # qualquer fuso para o dia local de `start`.
    day = start.date()
    query = SlotQuery(
        service_id=data.service_id,
        date_from=day - datetime.timedelta(days=1),
        date_to=day + datetime.timedelta(days=1),
        branch_id=data.branch_id,
        resource_id=data.resource_id,
        step_min=BOOKING_STEP_MIN,
    )
    # Valida contra o motor com os dados atuais: o horário precisa estar aberto, respeitar a
    # antecedência e ter recursos livres. É só uma triagem; quem decide é a constraint do banco.
    plan = await plan_slots(session, tenant, query, now)
    slot = next((s for s in plan.slots if s.start == start), None)
    if slot is None:
        raise ConflictError("Esse horário não está disponível.")

    service = plan.service
    busy_start = slot.start - datetime.timedelta(minutes=service.buffer_before_min)
    busy_end = slot.end + datetime.timedelta(minutes=service.buffer_after_min)

    await _lock_resources(session, {rid for assignment in slot.assignments for rid in assignment})
    customer = await _find_or_create_customer(session, tenant.id, data)
    for assignment in slot.assignments:
        booking = Booking(
            tenant_id=tenant.id,
            branch_id=plan.branch.id,
            service_id=service.id,
            customer_id=customer.id,
            start_at=slot.start,
            end_at=slot.end,
            buffer_before_min=service.buffer_before_min,
            buffer_after_min=service.buffer_after_min,
            price_cents=service.price_cents,
            notes=data.notes,
        )
        try:
            async with session.begin_nested():
                session.add(booking)
                await session.flush()
                for resource_id in sorted(assignment):
                    await _take_seat(
                        session,
                        tenant.id,
                        booking.id,
                        plan.resources[resource_id],
                        busy_start,
                        busy_end,
                    )
        except _NoSeat:
            continue
        return PublicBookingOut(
            id=booking.id,
            service_id=booking.service_id,
            branch_id=booking.branch_id,
            resource_ids=list(assignment),
            start=booking.start_at,
            end=booking.end_at,
            status=booking.status,
        )
    raise ConflictError("Esse horário acabou de ser ocupado.")


async def _lock_resources(session: AsyncSession, resource_ids: set[uuid.UUID]) -> None:
    """Serializa as reservas que disputam os mesmos recursos.

    A exclusion constraint já impede o conflito, mas duas inserções simultâneas de intervalos
    sobrepostos (não idênticos) esperam uma pela outra e o PostgreSQL derruba uma por deadlock.
    Travar os recursos numa ordem fixa evita isso; a constraint continua sendo a garantia final.
    `key_share` pede FOR NO KEY UPDATE, que não bloqueia a checagem das FKs de outras linhas.
    """
    await session.execute(
        select(Resource.id)
        .where(Resource.id.in_(resource_ids))
        .order_by(Resource.id)
        .with_for_update(key_share=True)
    )


async def _find_or_create_customer(
    session: AsyncSession, tenant_id: uuid.UUID, data: BookingIn
) -> Customer:
    # Um cliente já conhecido pelo telefone é reaproveitado sem alterar nome nem e-mail: a rota é
    # pública, e quem digita o número de outra pessoa não pode reescrever o cadastro dela.
    await session.execute(
        insert(Customer)
        .values(
            tenant_id=tenant_id,
            name=data.customer.name,
            phone=data.customer.phone,
            email=data.customer.email,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "phone"])
    )
    return await session.scalar(select(Customer).where(Customer.phone == data.customer.phone))  # type: ignore[return-value]


async def _take_seat(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    booking_id: uuid.UUID,
    resource: Resource,
    busy_start: datetime.datetime,
    busy_end: datetime.datetime,
) -> None:
    taken = set(
        await session.scalars(
            select(BookingResource.seat).where(
                BookingResource.resource_id == resource.id,
                BookingResource.active.is_(True),
                BookingResource.busy_start < busy_end,
                BookingResource.busy_end > busy_start,
            )
        )
    )
    free = (seat for seat in range(1, resource.capacity + 1) if seat not in taken)
    for seat in islice(free, SEAT_ATTEMPTS):
        try:
            async with session.begin_nested():
                session.add(
                    BookingResource(
                        tenant_id=tenant_id,
                        booking_id=booking_id,
                        resource_id=resource.id,
                        seat=seat,
                        busy_start=busy_start,
                        busy_end=busy_end,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            # Outra requisição ganhou a vaga entre a leitura e a gravação.
            if sqlstate(exc) != EXCLUSION_VIOLATION:
                raise
            continue
        return
    raise _NoSeat


async def list_bookings(
    session: AsyncSession,
    *,
    date_from: datetime.datetime | None,
    date_to: datetime.datetime | None,
    resource_id: uuid.UUID | None,
    status: str | None,
) -> list[BookingOut]:
    query = select(Booking, Customer).join(Customer, Customer.id == Booking.customer_id)
    if date_from is not None:
        query = query.where(Booking.end_at > date_from)
    if date_to is not None:
        query = query.where(Booking.start_at < date_to)
    if status is not None:
        query = query.where(Booking.status == status)
    if resource_id is not None:
        query = query.where(
            Booking.id.in_(
                select(BookingResource.booking_id).where(BookingResource.resource_id == resource_id)
            )
        )
    rows = (await session.execute(query.order_by(Booking.start_at, Booking.id))).all()
    resources = await _resource_ids(session, [booking.id for booking, _ in rows])
    return [_booking_out(b, resources.get(b.id, []), c) for b, c in rows]


async def get_booking(session: AsyncSession, booking_id: uuid.UUID) -> BookingOut:
    row = (
        await session.execute(
            select(Booking, Customer)
            .join(Customer, Customer.id == Booking.customer_id)
            .where(Booking.id == booking_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Reserva não encontrada.")
    booking, customer = row
    resources = await _resource_ids(session, [booking.id])
    return _booking_out(booking, resources.get(booking.id, []), customer)


async def cancel_booking(
    session: AsyncSession, booking_id: uuid.UUID, now: datetime.datetime
) -> BookingOut:
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update()
    )
    if booking is None:
        raise NotFoundError("Reserva não encontrada.")
    if booking.status == CONFIRMED:
        booking.status = CANCELLED
        booking.cancelled_at = now
        # Libera os recursos: a restrição do banco só olha registros ativos.
        await session.execute(
            update(BookingResource)
            .where(BookingResource.booking_id == booking.id)
            .values(active=False)
        )
        await session.flush()
    return await get_booking(session, booking_id)


async def _resource_ids(
    session: AsyncSession, booking_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    found: dict[uuid.UUID, list[uuid.UUID]] = {}
    if not booking_ids:
        return found
    rows = await session.execute(
        select(BookingResource.booking_id, BookingResource.resource_id)
        .where(BookingResource.booking_id.in_(booking_ids))
        .order_by(BookingResource.resource_id)
    )
    for booking_id, resource_id in rows:
        found.setdefault(booking_id, []).append(resource_id)
    return found
