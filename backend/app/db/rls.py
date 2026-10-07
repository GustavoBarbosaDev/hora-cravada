from alembic import op

# NULLIF evita o erro de cast quando a variável foi definida e depois zerada pelo fim da transação;
# sem tenant, o predicado vira NULL e nenhuma linha passa.
TENANT_PREDICATE = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def enable_tenant_rls(table: str) -> None:
    """Liga RLS (inclusive para o dono da tabela) com a policy padrão de isolamento por tenant."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def disable_tenant_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
