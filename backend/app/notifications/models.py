import datetime
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.tenants.models import UUID_DEFAULT

PENDING = "pending"
SENT = "sent"
FAILED = "failed"

BOOKING_CONFIRMED = "booking_confirmed"
BOOKING_CANCELLED = "booking_cancelled"
BOOKING_RESCHEDULED = "booking_rescheduled"


class OutboxEvent(Base):
    """Aviso a enviar, gravado na mesma transação da mudança que o originou.

    `payload` é uma cópia dos dados da reserva no momento do evento, para que o e-mail diga o que
    aconteceu mesmo que a reserva mude antes do envio.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("booking_id", "kind", name="uq_outbox_events_booking_id_kind"),
        ForeignKeyConstraint(
            ["tenant_id", "booking_id"], ["bookings.tenant_id", "bookings.id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "kind IN ('booking_confirmed', 'booking_cancelled', 'booking_rescheduled')",
            name="kind",
        ),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status"),
        Index(
            "ix_outbox_events_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_outbox_events_tenant_id_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default=PENDING)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
