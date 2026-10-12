import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.availability.models import AvailabilityException, AvailabilityRule
from app.availability.schemas import (
    ExceptionIn,
    ExceptionOut,
    RuleIn,
    RuleOut,
    to_clock,
    to_minutes,
)
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.db.errors import EXCLUSION_VIOLATION, sqlstate
from app.resources.service import get_resource


def rule_out(rule: AvailabilityRule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        resource_id=rule.resource_id,
        weekday=rule.weekday,
        start=to_clock(rule.start_minute),
        end=to_clock(rule.end_minute),
    )


def exception_out(item: AvailabilityException) -> ExceptionOut:
    return ExceptionOut(
        id=item.id,
        resource_id=item.resource_id,
        date=item.date,
        kind=item.kind,
        start=None if item.start_minute is None else to_clock(item.start_minute),
        end=None if item.end_minute is None else to_clock(item.end_minute),
        reason=item.reason,
    )


async def list_rules(session: AsyncSession, resource_id: uuid.UUID) -> list[AvailabilityRule]:
    await get_resource(session, resource_id)
    rules = await session.scalars(
        select(AvailabilityRule)
        .where(AvailabilityRule.resource_id == resource_id)
        .order_by(AvailabilityRule.weekday, AvailabilityRule.start_minute)
    )
    return list(rules)


async def create_rule(
    session: AsyncSession, tenant_id: uuid.UUID, resource_id: uuid.UUID, data: RuleIn
) -> AvailabilityRule:
    await get_resource(session, resource_id)
    rule = AvailabilityRule(
        tenant_id=tenant_id,
        resource_id=resource_id,
        weekday=data.weekday,
        start_minute=to_minutes(data.start),
        end_minute=to_minutes(data.end),
    )
    session.add(rule)
    try:
        await session.flush()
    except IntegrityError as exc:
        # A garantia é a exclusion constraint; checar antes na aplicação deixaria uma janela
        # para duas requisições simultâneas passarem.
        if sqlstate(exc) != EXCLUSION_VIOLATION:
            raise
        raise ConflictError("Esse intervalo se sobrepõe a outro do mesmo dia.") from exc
    return rule


async def delete_rule(session: AsyncSession, rule_id: uuid.UUID) -> None:
    rule = await session.get(AvailabilityRule, rule_id)
    if rule is None:
        raise NotFoundError("Regra não encontrada.")
    await session.delete(rule)
    await session.flush()


async def list_exceptions(
    session: AsyncSession,
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    resource_id: uuid.UUID | None = None,
) -> list[AvailabilityException]:
    query = select(AvailabilityException).order_by(
        AvailabilityException.date, AvailabilityException.start_minute, AvailabilityException.id
    )
    if date_from is not None:
        query = query.where(AvailabilityException.date >= date_from)
    if date_to is not None:
        query = query.where(AvailabilityException.date <= date_to)
    if resource_id is not None:
        query = query.where(AvailabilityException.resource_id == resource_id)
    return list(await session.scalars(query))


async def create_exception(
    session: AsyncSession, tenant_id: uuid.UUID, data: ExceptionIn
) -> AvailabilityException:
    if data.resource_id is not None:
        try:
            await get_resource(session, data.resource_id)
        except NotFoundError:
            raise UnprocessableError(
                "Recurso não encontrado.", details={"field": "resource_id"}
            ) from None
    item = AvailabilityException(
        tenant_id=tenant_id,
        resource_id=data.resource_id,
        date=data.date,
        kind=data.kind,
        start_minute=None if data.start is None else to_minutes(data.start),
        end_minute=None if data.end is None else to_minutes(data.end),
        reason=data.reason,
    )
    session.add(item)
    await session.flush()
    return item


async def delete_exception(session: AsyncSession, exception_id: uuid.UUID) -> None:
    item = await session.get(AvailabilityException, exception_id)
    if item is None:
        raise NotFoundError("Exceção não encontrada.")
    await session.delete(item)
    await session.flush()
