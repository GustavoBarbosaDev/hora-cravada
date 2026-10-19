"""create customers, bookings and booking resources

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.rls import disable_tenant_rls, enable_tenant_rls

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UUID_PK = sa.text("gen_random_uuid()")


def tenant_fk(
    table: str, column: str, ref: str, ondelete: str | None = None
) -> sa.ForeignKeyConstraint:
    # Mesma razão da 0006: a FK composta com tenant_id impede apontar para linha de outro tenant.
    # Sem ondelete, apagar o que já tem reserva falha; o caminho normal passa a ser desativar.
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{ref}.tenant_id", f"{ref}.id"],
        name=f"fk_{table}_tenant_id_{ref}",
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "phone", name="uq_customers_tenant_id_phone"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_customers_tenant_id_tenants", ondelete="CASCADE"
        ),
    )
    enable_tenant_rls("customers")

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("buffer_before_min", sa.Integer(), nullable=False),
        sa.Column("buffer_after_min", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="confirmed", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_bookings"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_bookings_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_bookings_tenant_id_tenants", ondelete="CASCADE"
        ),
        tenant_fk("bookings", "branch_id", "branches"),
        tenant_fk("bookings", "service_id", "services"),
        tenant_fk("bookings", "customer_id", "customers"),
        sa.CheckConstraint("end_at > start_at", name="ck_bookings_interval"),
        sa.CheckConstraint("status IN ('confirmed', 'cancelled')", name="ck_bookings_status"),
        sa.CheckConstraint(
            "buffer_before_min >= 0 AND buffer_after_min >= 0", name="ck_bookings_buffers"
        ),
    )
    op.create_index("ix_bookings_tenant_id_start_at", "bookings", ["tenant_id", "start_at"])
    enable_tenant_rls("bookings")

    op.create_table(
        "booking_resources",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("busy_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("busy_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("booking_id", "resource_id", name="pk_booking_resources"),
        tenant_fk("booking_resources", "booking_id", "bookings", ondelete="CASCADE"),
        tenant_fk("booking_resources", "resource_id", "resources"),
        sa.CheckConstraint("seat >= 1", name="ck_booking_resources_seat"),
        sa.CheckConstraint("busy_end > busy_start", name="ck_booking_resources_interval"),
    )
    op.create_index(
        "ix_booking_resources_resource_id_busy_start",
        "booking_resources",
        ["resource_id", "busy_start"],
    )
    # Duas reservas ativas não ocupam a mesma vaga do mesmo recurso ao mesmo tempo. Encostar é
    # permitido ([início, fim)). Reserva cancelada sai da restrição por `active`.
    op.execute(
        "ALTER TABLE booking_resources ADD CONSTRAINT booking_resources_no_overlap "
        "EXCLUDE USING gist (resource_id WITH =, seat WITH =, "
        "tstzrange(busy_start, busy_end) WITH &&) WHERE (active)"
    )
    enable_tenant_rls("booking_resources")


def downgrade() -> None:
    for table in ("booking_resources", "bookings", "customers"):
        disable_tenant_rls(table)
        op.drop_table(table)
