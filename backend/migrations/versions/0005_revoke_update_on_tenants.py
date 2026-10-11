"""revoke update on tenants from the app role

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""

import re

from alembic import op
from sqlalchemy.engine import make_url

from app.config import get_settings

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def app_role() -> str:
    role = make_url(get_settings().database_url).username
    if not role or not IDENTIFIER.match(role):
        raise RuntimeError("DATABASE_URL precisa ter um usuário simples (a-z, 0-9, _).")
    return role


def upgrade() -> None:
    # `tenants` não tem RLS, então um UPDATE do role da aplicação alcançaria qualquer empresa.
    # Nenhuma rota edita tenants hoje; quando "editar empresa" existir (fase 10), conceder
    # UPDATE só nas colunas necessárias e filtrar por `principal.tenant_id`.
    op.execute(f"REVOKE UPDATE ON tenants FROM {app_role()}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE ON tenants TO {app_role()}")
