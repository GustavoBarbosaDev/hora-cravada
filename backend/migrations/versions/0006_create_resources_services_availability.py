"""create resources, services and availability

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.rls import disable_tenant_rls, enable_tenant_rls

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UUID_PK = sa.text("gen_random_uuid()")


def tenant_fk(
    table: str, column: str, ref: str, ondelete: str | None = "CASCADE"
) -> sa.ForeignKeyConstraint:
    # FK composta com tenant_id: o RLS só confere a linha que está sendo gravada, e a checagem
    # de FK ignora o RLS. Sem tenant_id na chave, um id de outro tenant seria aceito.
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{ref}.tenant_id", f"{ref}.id"],
        name=f"fk_{table}_tenant_id_{ref}",
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.create_unique_constraint("uq_branches_tenant_id_id", "branches", ["tenant_id", "id"])

    op.create_table(
        "resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resources"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_resources_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_resources_tenant_id_tenants", ondelete="CASCADE"
        ),
        tenant_fk("resources", "branch_id", "branches", ondelete=None),
        sa.CheckConstraint("capacity >= 1", name="ck_resources_capacity"),
    )
    op.create_index("ix_resources_tenant_id_branch_id", "resources", ["tenant_id", "branch_id"])
    enable_tenant_rls("resources")

    op.create_table(
        "services",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("buffer_before_min", sa.Integer(), server_default="0", nullable=False),
        sa.Column("buffer_after_min", sa.Integer(), server_default="0", nullable=False),
        sa.Column("price_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "required_resource_kinds",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_services_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_services_tenant_id_tenants", ondelete="CASCADE"
        ),
        sa.CheckConstraint("duration_min > 0", name="ck_services_duration"),
        sa.CheckConstraint(
            "buffer_before_min >= 0 AND buffer_after_min >= 0", name="ck_services_buffers"
        ),
        sa.CheckConstraint("price_cents >= 0", name="ck_services_price"),
    )
    op.create_index("ix_services_tenant_id", "services", ["tenant_id"])
    enable_tenant_rls("services")

    op.create_table(
        "resource_services",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("resource_id", "service_id", name="pk_resource_services"),
        tenant_fk("resource_services", "resource_id", "resources"),
        tenant_fk("resource_services", "service_id", "services"),
    )
    op.create_index("ix_resource_services_service_id", "resource_services", ["service_id"])
    enable_tenant_rls("resource_services")

    op.create_table(
        "availability_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=False),
        sa.Column("end_minute", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_availability_rules"),
        tenant_fk("availability_rules", "resource_id", "resources"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_availability_rules_weekday"),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute",
            name="ck_availability_rules_interval",
        ),
    )
    # Intervalos [início, fim) do mesmo recurso e dia não se sobrepõem; encostar é permitido.
    op.execute(
        "ALTER TABLE availability_rules ADD CONSTRAINT availability_rules_no_overlap "
        "EXCLUDE USING gist (resource_id WITH =, weekday WITH =, "
        "int4range(start_minute, end_minute) WITH &&)"
    )
    enable_tenant_rls("availability_rules")

    op.create_table(
        "availability_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=True),
        sa.Column("end_minute", sa.SmallInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_availability_exceptions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_availability_exceptions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        tenant_fk("availability_exceptions", "resource_id", "resources"),
        sa.CheckConstraint("kind IN ('closed', 'open')", name="ck_availability_exceptions_kind"),
        sa.CheckConstraint(
            "(kind = 'closed' AND start_minute IS NULL AND end_minute IS NULL) OR "
            "(start_minute IS NOT NULL AND end_minute IS NOT NULL "
            "AND start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute)",
            name="ck_availability_exceptions_interval",
        ),
    )
    op.create_index(
        "ix_availability_exceptions_tenant_id_date",
        "availability_exceptions",
        ["tenant_id", "date"],
    )
    enable_tenant_rls("availability_exceptions")

    op.create_check_constraint(
        "ck_users_resource_only_for_professional",
        "users",
        "resource_id IS NULL OR role = 'professional'",
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT fk_users_tenant_id_resources "
        "FOREIGN KEY (tenant_id, resource_id) REFERENCES resources (tenant_id, id) "
        "ON DELETE SET NULL (resource_id)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_tenant_id_resources", "users", type_="foreignkey")
    op.drop_constraint("ck_users_resource_only_for_professional", "users", type_="check")
    for table in (
        "availability_exceptions",
        "availability_rules",
        "resource_services",
        "services",
        "resources",
    ):
        disable_tenant_rls(table)
        op.drop_table(table)
    op.drop_constraint("uq_branches_tenant_id_id", "branches", type_="unique")
