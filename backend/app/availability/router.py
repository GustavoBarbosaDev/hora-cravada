import datetime
import uuid

from fastapi import APIRouter, Response

from app.auth.deps import CurrentPrincipal, OwnerPrincipal, TenantSession
from app.availability import service
from app.availability.schemas import ExceptionIn, ExceptionOut, RuleIn, RuleOut

router = APIRouter(tags=["availability"])


@router.get("/resources/{resource_id}/availability-rules")
async def list_rules(
    resource_id: uuid.UUID, _: CurrentPrincipal, session: TenantSession
) -> list[RuleOut]:
    return [service.rule_out(rule) for rule in await service.list_rules(session, resource_id)]


@router.post("/resources/{resource_id}/availability-rules", status_code=201)
async def create_rule(
    resource_id: uuid.UUID, data: RuleIn, principal: OwnerPrincipal, session: TenantSession
) -> RuleOut:
    rule = await service.create_rule(session, principal.tenant_id, resource_id, data)
    return service.rule_out(rule)


@router.delete("/availability-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, _: OwnerPrincipal, session: TenantSession) -> Response:
    await service.delete_rule(session, rule_id)
    return Response(status_code=204)


@router.get("/availability-exceptions")
async def list_exceptions(
    _: CurrentPrincipal,
    session: TenantSession,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    resource_id: uuid.UUID | None = None,
) -> list[ExceptionOut]:
    items = await service.list_exceptions(
        session, date_from=date_from, date_to=date_to, resource_id=resource_id
    )
    return [service.exception_out(item) for item in items]


@router.post("/availability-exceptions", status_code=201)
async def create_exception(
    data: ExceptionIn, principal: OwnerPrincipal, session: TenantSession
) -> ExceptionOut:
    return service.exception_out(await service.create_exception(session, principal.tenant_id, data))


@router.delete("/availability-exceptions/{exception_id}", status_code=204)
async def delete_exception(
    exception_id: uuid.UUID, _: OwnerPrincipal, session: TenantSession
) -> Response:
    await service.delete_exception(session, exception_id)
    return Response(status_code=204)
