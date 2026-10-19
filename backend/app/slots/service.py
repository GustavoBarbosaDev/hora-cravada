import datetime
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.availability.models import AvailabilityException, AvailabilityRule
from app.bookings.models import BookingResource
from app.core.errors import NotFoundError, UnprocessableError
from app.resources.models import Resource
from app.services.models import ResourceService, Service
from app.slots.engine import (
    ExceptionWindow,
    Interval,
    Policy,
    Schedule,
    ServiceTiming,
    Slot,
    compute_slots,
)
from app.slots.schemas import SlotOut, SlotPolicySettings, SlotQuery, SlotsOut
from app.tenants.models import Branch, Tenant


async def load_busy(
    session: AsyncSession,
    resource_ids: list[uuid.UUID],
    start: datetime.datetime,
    end: datetime.datetime,
) -> dict[uuid.UUID, dict[int, list[Interval]]]:
    """Intervalos ocupados por recurso e vaga entre `start` e `end` (UTC), com os buffers."""
    busy: dict[uuid.UUID, dict[int, list[Interval]]] = defaultdict(lambda: defaultdict(list))
    rows = await session.execute(
        select(
            BookingResource.resource_id,
            BookingResource.seat,
            BookingResource.busy_start,
            BookingResource.busy_end,
        ).where(
            BookingResource.resource_id.in_(resource_ids),
            BookingResource.active.is_(True),
            BookingResource.busy_start < end,
            BookingResource.busy_end > start,
        )
    )
    for resource_id, seat, busy_start, busy_end in rows:
        busy[resource_id][seat].append((busy_start, busy_end))
    return busy


@dataclass(frozen=True)
class SlotPlan:
    """Resultado do motor com o contexto que as reservas também precisam."""

    tenant: Tenant
    branch: Branch
    service: Service
    slots: list[Slot]
    resources: dict[uuid.UUID, Resource]


async def find_slots(
    session: AsyncSession, tenant: Tenant, query: SlotQuery, now: datetime.datetime
) -> SlotsOut:
    plan = await plan_slots(session, tenant, query, now)
    return SlotsOut(
        branch_id=plan.branch.id,
        timezone=plan.branch.timezone,
        service_id=plan.service.id,
        duration_min=plan.service.duration_min,
        slots=[
            SlotOut(
                start=slot.start,
                end=slot.end,
                resource_ids=[assignment[0] for assignment in slot.assignments],
            )
            for slot in plan.slots
        ],
    )


async def plan_slots(
    session: AsyncSession, tenant: Tenant, query: SlotQuery, now: datetime.datetime
) -> SlotPlan:
    service = await session.get(Service, query.service_id)
    if service is None or not service.active:
        raise NotFoundError("Serviço não encontrado.")

    performers = await _performers(session, service.id, query)
    branch = await _single_branch(session, performers, query)
    tz = ZoneInfo(branch.timezone)

    days = [
        query.date_from + datetime.timedelta(days=offset)
        for offset in range((query.date_to - query.date_from).days + 1)
    ]
    required = await _required_resources(session, service, branch)
    resources = [*performers, *(r for group in required.values() for r in group)]

    window_start = _local_midnight(days[0], tz)
    window_end = _local_midnight(days[-1] + datetime.timedelta(days=1), tz)
    schedules = await _schedules(session, resources, days, window_start, window_end)

    settings = SlotPolicySettings.from_tenant(tenant.settings)
    slots = compute_slots(
        performers=[schedules[r.id] for r in performers],
        required={kind: [schedules[r.id] for r in group] for kind, group in required.items()},
        service=ServiceTiming(
            duration_min=service.duration_min,
            buffer_before_min=service.buffer_before_min,
            buffer_after_min=service.buffer_after_min,
        ),
        days=days,
        tz=tz,
        policy=Policy(
            step_min=query.step_min,
            min_notice=datetime.timedelta(minutes=settings.min_notice_min),
            max_advance=datetime.timedelta(days=settings.max_advance_days),
        ),
        now=now,
    )
    return SlotPlan(
        tenant=tenant,
        branch=branch,
        service=service,
        slots=slots,
        resources={r.id: r for r in resources},
    )


def _local_midnight(day: datetime.date, tz: ZoneInfo) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(datetime.UTC)


async def _performers(
    session: AsyncSession, service_id: uuid.UUID, query: SlotQuery
) -> list[Resource]:
    statement = (
        select(Resource)
        .join(ResourceService, ResourceService.resource_id == Resource.id)
        .where(ResourceService.service_id == service_id, Resource.active.is_(True))
        .order_by(Resource.name, Resource.id)
    )
    if query.branch_id is not None:
        statement = statement.where(Resource.branch_id == query.branch_id)
    if query.resource_id is not None:
        statement = statement.where(Resource.id == query.resource_id)
    performers = list(await session.scalars(statement))
    if query.resource_id is not None and not performers:
        raise NotFoundError("Esse recurso não executa o serviço.")
    return performers


async def _single_branch(
    session: AsyncSession, performers: list[Resource], query: SlotQuery
) -> Branch:
    branch_ids = {r.branch_id for r in performers}
    if query.branch_id is not None:
        branch_ids.add(query.branch_id)
    if len(branch_ids) > 1:
        raise UnprocessableError(
            "O serviço é atendido em mais de uma filial; informe branch_id.",
            details={"field": "branch_id"},
        )
    if not branch_ids:
        # Serviço sem ninguém que o execute: não há de qual filial falar.
        raise NotFoundError("Nenhuma filial atende esse serviço.")
    branch = await session.get(Branch, next(iter(branch_ids)))
    if branch is None:
        raise NotFoundError("Filial não encontrada.")
    return branch


async def _required_resources(
    session: AsyncSession, service: Service, branch: Branch
) -> dict[str, list[Resource]]:
    required: dict[str, list[Resource]] = {kind: [] for kind in service.required_resource_kinds}
    if not required:
        return required
    rows = await session.scalars(
        select(Resource)
        .where(
            Resource.branch_id == branch.id,
            Resource.active.is_(True),
            Resource.kind.in_(required),
        )
        .order_by(Resource.name, Resource.id)
    )
    for resource in rows:
        required[resource.kind].append(resource)
    return required


async def _schedules(
    session: AsyncSession,
    resources: list[Resource],
    days: list[datetime.date],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> dict[uuid.UUID, Schedule]:
    ids = list({r.id for r in resources})
    weekly: dict[uuid.UUID, dict[int, list[tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for rule in await session.scalars(
        select(AvailabilityRule).where(AvailabilityRule.resource_id.in_(ids))
    ):
        weekly[rule.resource_id][rule.weekday].append((rule.start_minute, rule.end_minute))

    exceptions: dict[uuid.UUID, dict[datetime.date, list[ExceptionWindow]]] = {
        resource_id: defaultdict(list) for resource_id in ids
    }
    rows = await session.scalars(
        select(AvailabilityException).where(
            AvailabilityException.date.between(days[0], days[-1]),
            or_(
                AvailabilityException.resource_id.in_(ids),
                AvailabilityException.resource_id.is_(None),
            ),
        )
    )
    for item in rows:
        window = ExceptionWindow(
            cast(Literal["closed", "open"], item.kind), item.start_minute, item.end_minute
        )
        # Exceção sem recurso vale para todos.
        targets = ids if item.resource_id is None else [item.resource_id]
        for resource_id in targets:
            exceptions[resource_id][item.date].append(window)

    busy = await load_busy(session, ids, window_start, window_end)
    capacity = {r.id: r.capacity for r in resources}
    return {
        resource_id: Schedule(
            resource_id=resource_id,
            weekly=weekly[resource_id],
            exceptions=exceptions[resource_id],
            capacity=capacity[resource_id],
            busy=busy[resource_id][1] if resource_id in busy else [],
            busy_by_seat=[
                intervals
                for seat, intervals in busy[resource_id].items()
                if seat <= capacity[resource_id]
            ]
            if resource_id in busy
            else [],
        )
        for resource_id in ids
    }
