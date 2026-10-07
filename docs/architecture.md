# Arquitetura

## Multi-tenancy

Todas as empresas (tenants) compartilham o mesmo banco e as mesmas tabelas. O isolamento é garantido pelo PostgreSQL com Row Level Security, não por filtros escritos na aplicação: uma consulta sem `WHERE tenant_id = ...` continua devolvendo só os dados do tenant atual.

### Dois roles de banco

| Role | Uso | Observação |
|---|---|---|
| `hora` (dono) | migrations | cria tabelas e policies; nunca usado pela API |
| `hora_app` | API e worker | `NOSUPERUSER NOBYPASSRLS`; só `SELECT/INSERT/UPDATE/DELETE` |

A migration `0002` cria `hora_app` com base em `DATABASE_URL` e configura os privilégios padrão para as tabelas futuras. As migrations conectam com `MIGRATION_DATABASE_URL`.

### Contexto de tenant

Cada requisição roda em uma única transação (`get_transaction`, em `app/db/session.py`). Antes de qualquer consulta de negócio, `set_tenant` executa `set_config('app.tenant_id', '<uuid>', true)`, equivalente a `SET LOCAL`: o valor vale só até o fim da transação e nunca vaza para a próxima requisição que reaproveitar a conexão do pool.

O tenant vem de dois lugares:

- **Painel:** do access token (`tid`), pela dependência `TenantSession` (`app/auth/deps.py`).
- **Área pública:** do slug na URL, pela dependência `PublicSession` (`app/tenants/deps.py`).

Login, cadastro e refresh resolvem o tenant por conta própria (slug no corpo, ou prefixo do refresh token) e chamam `set_tenant` antes de tocar nas tabelas de negócio.

### Policy padrão

`app/db/rls.py` expõe `enable_tenant_rls(tabela)`, usada nas migrations. Ela liga RLS, força a policy também para o dono da tabela (`FORCE`) e cria:

```sql
CREATE POLICY tenant_isolation ON <tabela>
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

Sem contexto, o predicado é NULL e nenhuma linha é visível nem gravável. O `WITH CHECK` impede inserir ou mover linhas para outro tenant.

A tabela `tenants` é a exceção: não tem `tenant_id` e não usa RLS, porque o slug é resolvido antes de existir contexto. O role da aplicação não pode apagar tenants.

Um teste (`test_every_table_with_tenant_id_forces_row_level_security`) percorre o catálogo e falha se alguma tabela com `tenant_id` aparecer sem RLS ativa, forçada e com policy. Tabelas novas entram nessa verificação sem alteração no teste.

## Autenticação

- Senhas com argon2id.
- Access token JWT (HS256), 15 minutos, com `sub`, `tid` e `role`. Validado só pela assinatura.
- Refresh token opaco, de uso único, guardado como SHA-256. O formato é `<tenant_id>.<segredo>`. Reapresentar um token já usado revoga toda a família de tokens daquela sessão.
- `POST /auth/login` recebe o slug da empresa, porque o e-mail só é único dentro de um tenant.

## Papéis

`owner`, `reception` e `professional`. A dependência `require_roles(...)` devolve 403 quando o papel do token não está na lista. Em 401 e 403 o formato de erro é o mesmo das demais respostas (ver `app/core/errors.py`).
