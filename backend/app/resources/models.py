import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.tenants.models import UUID_DEFAULT


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_resources_tenant_id_id"),
        Index("ix_resources_tenant_id_branch_id", "tenant_id", "branch_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"]),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    capacity: Mapped[int] = mapped_column(Integer, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
