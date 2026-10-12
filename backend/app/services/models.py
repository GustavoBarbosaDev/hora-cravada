import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.tenants.models import UUID_DEFAULT


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_services_tenant_id_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    duration_min: Mapped[int] = mapped_column(Integer)
    buffer_before_min: Mapped[int] = mapped_column(Integer, server_default="0")
    buffer_after_min: Mapped[int] = mapped_column(Integer, server_default="0")
    price_cents: Mapped[int] = mapped_column(Integer, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    required_resource_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )


class ResourceService(Base):
    __tablename__ = "resource_services"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resources.tenant_id", "resources.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "service_id"], ["services.tenant_id", "services.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, index=True)
