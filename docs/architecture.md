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

A tabela `tenants` é a exceção: não tem `tenant_id` e não usa RLS, porque o slug é resolvido antes de existir contexto. O role da aplicação lê e insere, mas não atualiza nem apaga tenants (migrations `0003` e `0005`).

Um teste (`test_every_table_with_tenant_id_forces_row_level_security`) percorre o catálogo e falha se alguma tabela com `tenant_id` aparecer sem RLS ativa, forçada e com policy. Tabelas novas entram nessa verificação sem alteração no teste.

## Autenticação

- Senhas com argon2id.
- Access token JWT (HS256), 15 minutos, com `sub`, `tid` e `role`. Validado só pela assinatura.
- Refresh token opaco, de uso único, guardado como SHA-256. O formato é `<tenant_id>.<segredo>`. Reapresentar um token já usado revoga toda a família de tokens daquela sessão.
- `POST /auth/login` recebe o slug da empresa, porque o e-mail só é único dentro de um tenant.

## Papéis

`owner`, `reception` e `professional`. A dependência `require_roles(...)` devolve 403 quando o papel do token não está na lista. Em 401 e 403 o formato de erro é o mesmo das demais respostas (ver `app/core/errors.py`).

## Catálogo e disponibilidade

Recursos, serviços e horários são o que o motor de slots (fase 3) lê para calcular a agenda.

| Tabela | Conteúdo |
|---|---|
| `resources` | quem ou o que é reservado: `kind` (identificador livre, como `barbeiro`, `medico`, `sala`), capacidade, atributos em JSON, filial |
| `services` | duração, buffers antes e depois, preço em centavos, `required_resource_kinds` (tipos de recurso que precisam estar livres além de quem executa) |
| `resource_services` | quais recursos executam cada serviço |
| `availability_rules` | intervalos semanais por recurso; vários por dia para pausas |
| `availability_exceptions` | folgas, feriados e horários especiais, por recurso ou para a empresa toda |

### Chaves estrangeiras compostas

Toda referência entre tabelas de negócio inclui `tenant_id` (por exemplo, `(tenant_id, resource_id)` apontando para `resources (tenant_id, id)`). O RLS só confere a linha que está sendo gravada; a checagem de FK do PostgreSQL ignora o RLS. Com uma FK simples, um dono poderia vincular um serviço seu a um recurso de outra empresa se soubesse o id. Com a FK composta, o banco recusa. Por isso `branches`, `resources` e `services` têm `UNIQUE (tenant_id, id)`.

### Horários

- `weekday` segue `date.weekday()`: 0 é segunda-feira, 6 é domingo.
- Horários são minutos desde a meia-noite local da filial, no intervalo `[início, fim)`, de 0 a 1440. A API usa `"HH:MM"` e aceita `"24:00"` como fim. O tipo `time` do PostgreSQL e do Python não representa 24:00, e uma sala que abre até a meia-noite é comum.
- Intervalos encostados (`09:00-12:00` e `12:00-14:00`) são permitidos.
- Datas de exceção são datas locais da filial. O fuso da filial (`branches.timezone`) é validado contra a lista do pacote `tzdata`. A conversão para UTC é responsabilidade do motor de slots.

### Sobreposição de regras

A garantia de que dois intervalos do mesmo recurso e dia não se sobrepõem é uma exclusion constraint, não uma checagem na aplicação:

```sql
EXCLUDE USING gist (resource_id WITH =, weekday WITH =, int4range(start_minute, end_minute) WITH &&)
```

Duas requisições simultâneas passariam juntas por uma checagem na aplicação; o banco serializa. A violação (`23P01`) vira `409`. Há um teste de concorrência em `tests/concurrency/`.

### Como as exceções se combinam com as regras (contrato para a fase 3)

Para um recurso e uma data local:

1. Se existe alguma exceção `open` aplicável (do recurso ou da empresa), as janelas `open` substituem as regras semanais daquela data.
2. Sem `open`, valem as regras semanais do dia da semana.
3. Exceções `closed` removem o que sobrou, mesmo de uma janela `open`: sem horário, o dia inteiro; com horário, só aquele intervalo.

Exceção com `resource_id` nulo vale para todos os recursos da empresa.

### Papéis

Qualquer usuário autenticado lê filiais, recursos, serviços e horários (o painel precisa deles para qualquer perfil). Só o `owner` cria, altera e remove.

