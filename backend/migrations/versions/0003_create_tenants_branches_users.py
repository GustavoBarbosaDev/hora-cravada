"""create tenants, branches and users

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.rls import disable_tenant_rls, enable_tenant_rls

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("segment", sa.Text(), server_default="generic", nullable=False),
        sa.Column(
            "timezone_default", sa.Text(), server_default="America/Sao_Paulo", nullable=False
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    # A tabela de tenants não tem tenant_id: o slug é resolvido antes de existir contexto.
    # Quem precisa remover um tenant usa o role dono do schema.
    role = make_url(get_settings().database_url).username
    if not role or not IDENTIFIER.match(role):
        raise RuntimeError("DATABASE_URL precisa ter um usuário simples (a-z, 0-9, _).")
    op.execute(f"REVOKE DELETE ON tenants FROM {role}")

    op.create_table(
        "branches",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_branches"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_branches_tenant_id_tenants", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_branches_tenant_id", "branches", ["tenant_id"])
    enable_tenant_rls("branches")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_PK, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        # A FK para resources entra junto com a tabela, na fase 2.
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_users_tenant_id_tenants", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),
        sa.CheckConstraint("role IN ('owner', 'reception', 'professional')", name="ck_users_role"),
    )
    enable_tenant_rls("users")


def downgrade() -> None:
    disable_tenant_rls("users")
    op.drop_table("users")
    disable_tenant_rls("branches")
    op.drop_index("ix_branches_tenant_id", table_name="branches")
    op.drop_table("branches")
    op.drop_table("tenants")
