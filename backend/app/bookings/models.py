import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.tenants.models import UUID_DEFAULT

CONFIRMED = "confirmed"
CANCELLED = "cancelled"


class Customer(Base):
    """Cliente final. Não tem login: é identificado pelo telefone dentro da empresa."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
        UniqueConstraint("tenant_id", "phone", name="uq_customers_tenant_id_phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Booking(Base):
    """Reserva. Duração e buffers são copiados do serviço: mudar o serviço depois não altera o
    que já foi reservado."""

    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_bookings_tenant_id_id"),
        Index("ix_bookings_tenant_id_start_at", "tenant_id", "start_at"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "branch_id"], ["branches.tenant_id", "branches.id"]),
        ForeignKeyConstraint(["tenant_id", "service_id"], ["services.tenant_id", "services.id"]),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        CheckConstraint("end_at > start_at", name="interval"),
        CheckConstraint("status IN ('confirmed', 'cancelled')", name="status"),
        CheckConstraint("buffer_before_min >= 0 AND buffer_after_min >= 0", name="buffers"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    buffer_before_min: Mapped[int] = mapped_column(Integer)
    buffer_after_min: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=CONFIRMED)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class BookingResource(Base):
    """Recurso ocupado por uma reserva, de `busy_start` a `busy_end` (com os buffers).

    `seat` numera a vaga do recurso (1 até a capacidade). A exclusion constraint impede dois
    registros ativos na mesma vaga com intervalos sobrepostos; é ela que garante a ausência de
    conflito sob concorrência, não uma checagem na aplicação.
    """

    __tablename__ = "booking_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "booking_id"],
            ["bookings.tenant_id", "bookings.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["tenant_id", "resource_id"], ["resources.tenant_id", "resources.id"]),
        CheckConstraint("seat >= 1", name="seat"),
        CheckConstraint("busy_end > busy_start", name="interval"),
        Index("ix_booking_resources_resource_id_busy_start", "resource_id", "busy_start"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seat: Mapped[int] = mapped_column(SmallInteger)
    busy_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    busy_end: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
