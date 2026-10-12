import datetime
import uuid

from sqlalchemy import Date, ForeignKey, ForeignKeyConstraint, Index, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.tenants.models import UUID_DEFAULT


class AvailabilityRule(Base):
    """Intervalo semanal recorrente. `weekday` segue `date.weekday()` (0 = segunda-feira) e os
    horários são minutos desde a meia-noite local da filial, no intervalo [início, fim)."""

    __tablename__ = "availability_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resources.tenant_id", "resources.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_minute: Mapped[int] = mapped_column(SmallInteger)
    end_minute: Mapped[int] = mapped_column(SmallInteger)


class AvailabilityException(Base):
    """Exceção para uma data local da filial. `resource_id` nulo vale para o tenant inteiro.

    `closed` sem horário fecha o dia todo; com horário, fecha só aquele intervalo. `open`
    sempre tem horário e define a janela aberta da data no lugar das regras semanais.
    """

    __tablename__ = "availability_exceptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resources.tenant_id", "resources.id"],
            ondelete="CASCADE",
        ),
        Index("ix_availability_exceptions_tenant_id_date", "tenant_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=UUID_DEFAULT
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    date: Mapped[datetime.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(Text)
    start_minute: Mapped[int | None] = mapped_column(SmallInteger)
    end_minute: Mapped[int | None] = mapped_column(SmallInteger)
    reason: Mapped[str | None] = mapped_column(Text)
