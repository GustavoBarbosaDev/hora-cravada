"""create outbox events

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.rls import disable_tenant_rls, enable_tenant_rls

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_outbox_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "booking_id"],
            ["bookings.tenant_id", "bookings.id"],
            name="fk_outbox_events_tenant_id_bookings",
            ondelete="CASCADE",
        ),
        # Cancelar é idempotente e remarcar cria uma reserva nova, então um tipo de evento por
        # reserva basta; a restrição protege contra enfileirar o mesmo aviso duas vezes.
        sa.UniqueConstraint("booking_id", "kind", name="uq_outbox_events_booking_id_kind"),
        sa.CheckConstraint(
            "kind IN ('booking_confirmed', 'booking_cancelled', 'booking_rescheduled')",
            name="ck_outbox_events_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name="ck_outbox_events_status"
        ),
    )
    op.create_index(
        "ix_outbox_events_due",
        "outbox_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_outbox_events_tenant_id_status", "outbox_events", ["tenant_id", "status"])
    enable_tenant_rls("outbox_events")
    # O worker precisa enxergar os eventos de todas as empresas para escolher o próximo. Ele liga
    # esta variável só na transação que reivindica o evento; depois disso trabalha com o contexto
    # de tenant normal. Qualquer outro acesso continua restrito pela política de isolamento.
    op.execute(
        "CREATE POLICY outbox_worker ON outbox_events "
        "USING (current_setting('app.outbox_worker', true) = 'on') "
        "WITH CHECK (current_setting('app.outbox_worker', true) = 'on')"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS outbox_worker ON outbox_events")
    disable_tenant_rls("outbox_events")
    op.drop_table("outbox_events")
