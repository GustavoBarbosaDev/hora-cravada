import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.branches.schemas import BranchIn, BranchPatch
from app.core.errors import ConflictError, NotFoundError
from app.db.errors import FOREIGN_KEY_VIOLATION, sqlstate
from app.tenants.models import Branch


async def list_branches(session: AsyncSession) -> list[Branch]:
    return list(await session.scalars(select(Branch).order_by(Branch.name, Branch.id)))


async def get_branch(session: AsyncSession, branch_id: uuid.UUID) -> Branch:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise NotFoundError("Filial não encontrada.")
    return branch


async def create_branch(session: AsyncSession, tenant_id: uuid.UUID, data: BranchIn) -> Branch:
    branch = Branch(tenant_id=tenant_id, **data.model_dump())
    session.add(branch)
    await session.flush()
    return branch


async def update_branch(session: AsyncSession, branch_id: uuid.UUID, data: BranchPatch) -> Branch:
    branch = await get_branch(session, branch_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(branch, field, value)
    await session.flush()
    return branch


async def delete_branch(session: AsyncSession, branch_id: uuid.UUID) -> None:
    branch = await get_branch(session, branch_id)
    try:
        await session.delete(branch)
        await session.flush()
    except IntegrityError as exc:
        if sqlstate(exc) != FOREIGN_KEY_VIOLATION:
            raise
        raise ConflictError("A filial ainda tem recursos vinculados.") from exc
