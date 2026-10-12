import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UUID_DEFAULT = text("gen_random_uuid()")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    segment: Mapped[str] = mapped_column(Text, server_default="generic")
    timezone_default: Mapped[str] = mapped_column(Text, server_default="America/Sao_Paulo")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Branch(Base):
    __tablename__ = "branches"
    # Alvo das FKs compostas (tenant_id, branch_id) dos recursos.
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_branches_tenant_id_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
