"""create app role

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

import re

from alembic import op
from sqlalchemy.engine import make_url

from app.config import get_settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def app_role() -> tuple[str, str]:
    settings = get_settings()
    app_url = make_url(settings.database_url)
    owner_url = make_url(settings.migration_database_url)
    if not app_url.username or not IDENTIFIER.match(app_url.username):
        raise RuntimeError("DATABASE_URL precisa ter um usuário simples (a-z, 0-9, _).")
    if app_url.username == owner_url.username:
        raise RuntimeError("DATABASE_URL e MIGRATION_DATABASE_URL não podem usar o mesmo role.")
    return app_url.username, app_url.password or ""


def upgrade() -> None:
    role, password = app_role()
    quoted_password = "'" + password.replace("'", "''") + "'"
    # O role é do cluster, não do banco: pode já existir (banco de testes, volume antigo).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD {quoted_password}
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    # Tabelas criadas pelas próximas migrations já nascem acessíveis ao role da aplicação.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )


def downgrade() -> None:
    role, _ = app_role()
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {role}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
