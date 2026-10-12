"""Dados de exemplo para desenvolvimento: uma empresa de cada segmento.

Uso: `make seed`. Pode ser repetido; empresas que já existem são ignoradas.
"""

import asyncio
import datetime
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.models import Role
from app.auth.schemas import CreateUserRequest
from app.availability import service as availability_service
from app.availability.schemas import ExceptionIn, RuleIn
from app.branches import service as branch_service
from app.branches.schemas import BranchPatch
from app.config import get_settings
from app.db.session import build_engine, build_sessionmaker
from app.resources import service as resource_service
from app.resources.schemas import ResourceIn
from app.services import service as catalog_service
from app.services.schemas import ServiceIn
from app.tenants import service as tenant_service
from app.tenants.models import Tenant
from app.tenants.schemas import SignupRequest

DEV_PASSWORD = "senha-de-desenvolvimento"


@dataclass
class ServiceSpec:
    data: ServiceIn
    performed_by: list[str]


@dataclass
class TenantSpec:
    slug: str
    name: str
    timezone: str
    owner_email: str
    branch_name: str
    branch_address: str
    resources: list[tuple[str, str, int, dict[str, Any]]]  # (nome, tipo, capacidade, atributos)
    services: list[ServiceSpec]
    weekly_hours: dict[str, list[tuple[int, str, str]]]  # tipo -> (dia, início, fim)
    holidays: list[tuple[int, int, str]]  # (mês, dia, motivo)
    staff: list[tuple[str, Role, str | None]] = field(
        default_factory=list
    )  # (e-mail, papel, recurso)


def weekdays(days: range, *intervals: tuple[str, str]) -> list[tuple[int, str, str]]:
    return [(day, start, end) for day in days for start, end in intervals]


SPECS = [
    TenantSpec(
        slug="barbearia-seu-ze",
        name="Barbearia do Seu Zé",
        timezone="America/Sao_Paulo",
        owner_email="ze@barbeariaseuze.com.br",
        branch_name="Vila Madalena",
        branch_address="Rua Fradique Coutinho, 412, São Paulo",
        resources=[
            ("Rogério Teixeira", "barbeiro", 1, {}),
            ("Anderson Lopes", "barbeiro", 1, {}),
            ("Mateus Ribeiro", "barbeiro", 1, {}),
        ],
        services=[
            ServiceSpec(
                ServiceIn(name="Corte", duration_min=30, buffer_after_min=5, price_cents=4500),
                ["Rogério Teixeira", "Anderson Lopes", "Mateus Ribeiro"],
            ),
            ServiceSpec(
                ServiceIn(name="Barba", duration_min=20, buffer_after_min=5, price_cents=3000),
                ["Rogério Teixeira", "Anderson Lopes"],
            ),
            ServiceSpec(
                ServiceIn(
                    name="Corte e barba", duration_min=45, buffer_after_min=10, price_cents=6500
                ),
                ["Rogério Teixeira", "Mateus Ribeiro"],
            ),
        ],
        weekly_hours={
            "barbeiro": weekdays(range(1, 6), ("09:00", "12:00"), ("13:00", "19:00")),
        },
        holidays=[(12, 25, "Natal"), (1, 1, "Confraternização Universal")],
        staff=[
            ("camila@barbeariaseuze.com.br", Role.reception, None),
            ("rogerio@barbeariaseuze.com.br", Role.professional, "Rogério Teixeira"),
        ],
    ),
    TenantSpec(
        slug="clinica-vida-plena",
        name="Clínica Vida Plena",
        timezone="America/Sao_Paulo",
        owner_email="direcao@vidaplena.med.br",
        branch_name="Unidade Centro",
        branch_address="Av. Afonso Pena, 1500, Belo Horizonte",
        resources=[
            ("Dra. Helena Moraes", "medico", 1, {"especialidade": "Clínica geral"}),
            ("Dr. Paulo Nogueira", "medico", 1, {"especialidade": "Cardiologia"}),
            ("Consultório 1", "sala", 1, {}),
            ("Consultório 2", "sala", 1, {}),
        ],
        services=[
            ServiceSpec(
                ServiceIn(
                    name="Consulta clínica geral",
                    duration_min=40,
                    buffer_after_min=10,
                    price_cents=25000,
                    required_resource_kinds=["sala"],
                ),
                ["Dra. Helena Moraes"],
            ),
            ServiceSpec(
                ServiceIn(
                    name="Consulta cardiológica",
                    duration_min=50,
                    buffer_after_min=10,
                    price_cents=38000,
                    required_resource_kinds=["sala"],
                ),
                ["Dr. Paulo Nogueira"],
            ),
            ServiceSpec(
                ServiceIn(
                    name="Retorno",
                    duration_min=20,
                    price_cents=0,
                    required_resource_kinds=["sala"],
                ),
                ["Dra. Helena Moraes", "Dr. Paulo Nogueira"],
            ),
        ],
        weekly_hours={
            "medico": weekdays(range(0, 5), ("08:00", "12:00"), ("14:00", "18:00")),
            "sala": weekdays(range(0, 5), ("07:00", "19:00")),
        },
        holidays=[(12, 25, "Natal"), (1, 1, "Confraternização Universal")],
        staff=[
            ("recepcao@vidaplena.med.br", Role.reception, None),
            ("helena@vidaplena.med.br", Role.professional, "Dra. Helena Moraes"),
        ],
    ),
    TenantSpec(
        slug="coworking-ponte",
        name="Espaço Ponte",
        timezone="America/Recife",
        owner_email="contato@espacoponte.com.br",
        branch_name="Recife Antigo",
        branch_address="Rua do Bom Jesus, 203, Recife",
        resources=[
            ("Sala Mauá", "sala", 8, {"equipamentos": ["projetor", "quadro branco"]}),
            ("Sala Itaúna", "sala", 4, {"equipamentos": ["tv", "videoconferência"]}),
            ("Auditório", "sala", 40, {"equipamentos": ["projetor", "som", "microfones"]}),
        ],
        services=[
            ServiceSpec(
                ServiceIn(name="Reserva de 1 hora", duration_min=60, price_cents=12000),
                ["Sala Mauá", "Sala Itaúna", "Auditório"],
            ),
            ServiceSpec(
                ServiceIn(name="Meio período", duration_min=240, price_cents=40000),
                ["Sala Mauá", "Sala Itaúna", "Auditório"],
            ),
        ],
        weekly_hours={
            "sala": weekdays(range(0, 5), ("08:00", "22:00")) + [(5, "08:00", "14:00")],
        },
        holidays=[(12, 25, "Natal"), (1, 1, "Confraternização Universal")],
        staff=[("recepcao@espacoponte.com.br", Role.reception, None)],
    ),
]


def next_occurrence(month: int, day: int, today: datetime.date) -> datetime.date:
    candidate = datetime.date(today.year, month, day)
    return candidate if candidate >= today else datetime.date(today.year + 1, month, day)


async def seed_tenant(session: AsyncSession, spec: TenantSpec, today: datetime.date) -> None:
    tenant, owner = await tenant_service.signup(
        session,
        SignupRequest(
            tenant_name=spec.name,
            slug=spec.slug,
            timezone=spec.timezone,
            owner_email=spec.owner_email,
            owner_password=DEV_PASSWORD,
        ),
    )
    branch = (await branch_service.list_branches(session))[0]
    await branch_service.update_branch(
        session, branch.id, BranchPatch(name=spec.branch_name, address=spec.branch_address)
    )

    resources = {}
    for name, kind, capacity, attributes in spec.resources:
        resources[name] = await resource_service.create_resource(
            session,
            tenant.id,
            ResourceIn(
                branch_id=branch.id,
                kind=kind,
                name=name,
                capacity=capacity,
                attributes=attributes,
            ),
        )

    for item in spec.services:
        service = await catalog_service.create_service(session, tenant.id, item.data)
        await catalog_service.set_service_resources(
            session, tenant.id, service.id, [resources[name].id for name in item.performed_by]
        )

    for resource in resources.values():
        for weekday, start, end in spec.weekly_hours.get(resource.kind, []):
            await availability_service.create_rule(
                session, tenant.id, resource.id, RuleIn(weekday=weekday, start=start, end=end)
            )

    for month, day, reason in spec.holidays:
        await availability_service.create_exception(
            session,
            tenant.id,
            ExceptionIn(date=next_occurrence(month, day, today), kind="closed", reason=reason),
        )

    for email, role, resource_name in spec.staff:
        await auth_service.create_user(
            session,
            tenant.id,
            CreateUserRequest(
                email=email,
                password=DEV_PASSWORD,
                role=role,
                resource_id=resources[resource_name].id if resource_name else None,
            ),
        )


async def seed() -> list[str]:
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("O seed não roda em produção.")

    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    created = []
    for spec in SPECS:
        async with sessionmaker() as session, session.begin():
            if await session.scalar(select(Tenant.id).where(Tenant.slug == spec.slug)):
                continue
            await seed_tenant(session, spec, datetime.date.today())
            created.append(spec.slug)
    await engine.dispose()
    return created


def main() -> None:
    created = asyncio.run(seed())
    for slug in created:
        print(f"criada: {slug}")
    if not created:
        print("nada a fazer: as empresas de exemplo já existem")
    else:
        print(f"senha dos usuários de exemplo: {DEV_PASSWORD}")


if __name__ == "__main__":
    main()
