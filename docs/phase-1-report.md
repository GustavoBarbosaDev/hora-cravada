# Relatório técnico: fase 1 (tenants e autenticação)

## Escopo

Isolamento entre empresas no banco, cadastro de tenant, login com JWT e refresh rotativo, e controle por papéis. Nenhuma regra de agendamento foi implementada nesta fase. O modelo de isolamento está descrito em [architecture.md](architecture.md); aqui ficam o que foi entregue, a referência da API e como verificar.

## Resultado

| Item | Estado |
|---|---|
| Role `hora_app` (sem `BYPASSRLS`) separado do dono do schema | Feito (migration `0002`) |
| Tabelas `tenants`, `branches`, `users` e `refresh_tokens` | Feito (migrations `0003` e `0004`) |
| RLS com `FORCE` e policy `tenant_isolation` | Feito, com teste de catálogo que cobre tabelas futuras |
| Contexto de tenant por transação (`set_tenant`) | Feito |
| Cadastro de empresa, login, refresh, logout e `/auth/me` | Feito |
| Papéis `owner`, `reception`, `professional` com `require_roles` | Feito |
| `GET /users` e `POST /users` (só `owner`) | Feito |
| Validação do `JWT_SECRET` em produção | Feito |
| `UPDATE` em `tenants` revogado do `hora_app` | Feito (migration `0005`, pós-revisão) |
| Header `x-request-id` também nas respostas 500 | Feito (pós-revisão) |
| CRUD de filiais, recursos e demais telas | Fora do escopo (fase 2 em diante) |

## Banco de dados

### Roles

| Role | Variável | Uso |
|---|---|---|
| `hora` (dono) | `MIGRATION_DATABASE_URL` | migrations; nunca usado pela API |
| `hora_app` | `DATABASE_URL` | API e worker; `NOSUPERUSER NOBYPASSRLS`, só `SELECT/INSERT/UPDATE/DELETE` |

A migration `0002` cria o role a partir de `DATABASE_URL` se ele não existir, concede `USAGE` no schema e configura `ALTER DEFAULT PRIVILEGES` para que tabelas futuras já nasçam acessíveis. Ela recusa nomes de role fora de `[a-z0-9_]` e URLs em que app e migration usam o mesmo usuário. O downgrade revoga os privilégios, mas não remove o role (pertence ao cluster).

### Tabelas

| Tabela | RLS | Colunas principais | Constraints |
|---|---|---|---|
| `tenants` | não | `id`, `slug`, `name`, `segment` (`generic`), `timezone_default`, `settings` (JSONB), `created_at` | `slug` único; `UPDATE` (migration `0005`) e `DELETE` revogados de `hora_app` |
| `branches` | sim | `id`, `tenant_id`, `name`, `timezone`, `address` | FK `tenant_id` com cascade; índice em `tenant_id` |
| `users` | sim | `id`, `tenant_id`, `email`, `password_hash`, `role`, `resource_id`, `active` | `UNIQUE(tenant_id, email)`; `CHECK role IN (owner, reception, professional)` |
| `refresh_tokens` | sim | `id`, `tenant_id`, `user_id`, `family_id`, `token_hash`, `expires_at`, `used_at`, `revoked_at`, `created_at` | `token_hash` único; índice em `family_id`; FKs com cascade |

`users.resource_id` ainda não tem chave estrangeira; ela entra com a tabela `resources` na fase 2.

### RLS

`app/db/rls.py` expõe `enable_tenant_rls(tabela)` e `disable_tenant_rls(tabela)`, usadas nas migrations. A policy tolera a variável ausente ou vazia com `NULLIF(current_setting('app.tenant_id', true), '')::uuid`; sem contexto, nenhuma linha é visível nem gravável. Toda tabela nova com `tenant_id` deve chamar `enable_tenant_rls`, ou o teste de catálogo falha.

## Backend

### Módulos

| Módulo | Responsabilidade |
|---|---|
| `app/config.py` | `Settings`; novos campos `migration_database_url`, `jwt_secret`, `access_token_ttl_minutes` (15), `refresh_token_ttl_days` (30). Em `production`, recusa o segredo de desenvolvimento e segredos com menos de 32 bytes |
| `app/db/session.py` | `get_transaction` (uma transação por requisição, commit no fim, rollback em erro) e `set_tenant` (`set_config(..., true)`, equivalente a `SET LOCAL`) |
| `app/core/security.py` | argon2id, criação e validação do access token, geração e hash do refresh token, `Principal` |
| `app/auth/` | modelos `User` e `RefreshToken`, serviço, rotas, dependências (`TenantSession`, `CurrentPrincipal`, `OwnerPrincipal`, `require_roles`) |
| `app/tenants/` | modelos `Tenant` e `Branch`, cadastro, `PublicSession` (tenant pelo slug da URL) |

### Fluxo de uma requisição

1. **Painel:** o token é validado só pela assinatura; `TenantSession` abre a transação e chama `set_tenant` com o `tid`. O RLS filtra tudo a partir daí.
2. **Área pública:** `PublicSession` resolve o slug em `tenants` (sem RLS), chama `set_tenant` e entrega a sessão.
3. **Login, cadastro e refresh:** não têm token válido ainda; resolvem o tenant por conta própria (slug no corpo, ou prefixo do refresh token) antes de tocar nas tabelas de negócio.

Quem fizer `commit` antes do fim da requisição perde o contexto de tenant. Só o refresh com reutilização faz isso de propósito, para persistir a revogação antes de responder 401.

### Autenticação

- Senha: argon2id, calculada em `asyncio.to_thread` para não bloquear o event loop. Para usuário ou empresa inexistente, verifica contra um hash fixo, mantendo o tempo de resposta parecido e a mesma mensagem de erro.
- Access token: JWT HS256 com `sub`, `tid`, `role`, `iat`, `exp`; sem consulta ao banco.
- Refresh token: `<tenant_id>.<segredo>`, 256 bits de entropia, armazenado como SHA-256. Uso único: a rotação marca `used_at` e emite outro na mesma `family_id`. Reapresentar um token usado revoga a família inteira. `with_for_update` serializa refreshes concorrentes do mesmo token.
- Logout revoga a família do token informado e é idempotente.
- Limites de entrada: slug 3 a 40 caracteres em minúsculas e hífens; senha de 8 a 128 (cadastro) ou 1 a 128 (login); refresh token até 512; e-mail normalizado para minúsculas.

### Referência da API

| Método e rota | Acesso | Corpo | Resposta |
|---|---|---|---|
| `POST /tenants` | público | `tenant_name`, `slug`, `timezone` (padrão `America/Sao_Paulo`), `owner_email`, `owner_password` | 201 `{tenant, owner_id}`; 409 se o slug já existe; 422 para fuso desconhecido |
| `POST /auth/login` | público | `tenant_slug`, `email`, `password` | `{access_token, refresh_token, token_type, expires_in}`; 401 genérico |
| `POST /auth/refresh` | público | `refresh_token` | novo par de tokens; 401 se inválido, expirado, revogado ou reutilizado |
| `POST /auth/logout` | público | `refresh_token` | 204 |
| `GET /auth/me` | qualquer papel | — | `{id, email, role, active}`; 401 se o usuário foi desativado |
| `GET /users` | `owner` | — | usuários do tenant, por e-mail |
| `POST /users` | `owner` | `email`, `password`, `role` | 201 usuário; 409 se o e-mail já existe no tenant |

Erros seguem o formato único descrito no relatório da fase 0 (`error.code`, `message`, `details`, `request_id`). Sem token ou com token inválido: 401. Papel sem permissão: 403.

## Testes

63 testes no backend, todos passando (ruff, ruff format e mypy sem erros). A suíte rodou em contêineres avulsos de Postgres 16 e Redis 7 (ver "Verificação realizada"). O teste de corrida de refresh foi repetido 5 vezes sem falha.

| Arquivo | Comportamento coberto |
|---|---|
| `tests/integration/test_rls.py` | `hora_app` lê e insere em `tenants`, mas não atualiza nem apaga; consulta sem filtro devolve só o tenant atual; sem contexto, nenhuma linha; contexto não vaza após a transação; UPDATE e DELETE não alcançam outro tenant; INSERT para outro tenant é rejeitado; `hora_app` não ignora o RLS; toda tabela com `tenant_id` tem RLS ativa, forçada e com policy; conexões concorrentes mantêm contextos separados |
| `tests/integration/test_auth.py` | cadastro cria tenant e dono que consegue logar; slug repetido e malformado; mesma resposta para senha errada e empresa inexistente; credenciais não valem em outro tenant; mesmo e-mail em dois tenants; token ausente, inválido e expirado; rotação de refresh; reutilização revoga a família; dois refreshes simultâneos do mesmo token (um passa, um falha, família revogada); logout; usuário desativado (refresh e `/auth/me` com access token ainda válido); dono cria e lista só os usuários do seu tenant; e-mail repetido; papéis não-dono recebem 403; sessão do painel e pública resolvem o tenant certo; corpos gigantes rejeitados antes do hash; hash não bloqueia o event loop |
| `tests/unit/test_security.py` | hash e verificação de senha; round-trip do access token; token expirado ou assinado com outro segredo; refresh token com tenant e hash; tokens malformados; produção recusa segredo de desenvolvimento e curto, e aceita 32 bytes |
| `tests/integration/test_migrations.py` | upgrade e downgrade das extensões e das tabelas de tenant |
| `tests/unit/test_errors.py` | passou a cobrir o `x-request-id` na resposta 500 |

## Verificação realizada

A máquina não tem Docker Compose v2, então a verificação foi feita com `docker run` numa rede com Postgres 16 (com o `init-test-db.sql`) e Redis 7, usando a imagem do backend:

- `pytest`: 63 passando; `ruff check`, `ruff format --check` e `mypy app tests`: sem erros.
- Smoke da API: `alembic upgrade head` (até a `0005`), uvicorn no ar, `POST /tenants`, `POST /auth/login` e `GET /health` respondendo como esperado.
- pre-commit (end-of-file, trailing-whitespace, check-yaml, ruff, ruff-format): passando. O hook de mypy foi pulado nessa execução porque usa o Python do host; o mypy equivalente rodou acima.
- CI: o workflow já passou em `main` na fase 0 (run de 2026-10-05). Os commits da fase 1 ainda não foram enviados ao remoto, então o CI não rodou sobre eles.

## Decisões

Registradas em [decisions.md](decisions.md): login recebe o slug; `tenants` sem RLS; policy tolera variável ausente; role da aplicação criado pela migration; refresh rotativo com detecção de reutilização; access token sem consulta ao banco; gestão de usuários mínima; `hora_app` não atualiza `tenants`.

## Limitações conhecidas

Detalhes e fase de destino em [backlog.md](backlog.md). As que afetam a operação hoje:

- Refresh duplicado (duas abas ou retry de rede) derruba a sessão.
- Um usuário desativado continua com o access token válido até 15 minutos.
- `tenants` não tem RLS. O `hora_app` não atualiza nem apaga empresas; quando "editar empresa" existir (fase 10), será preciso conceder `UPDATE` nas colunas necessárias e filtrar por `principal.tenant_id`.
- Sem limite de tentativas de login (fase 14).

---

# Antes de começar a fase 2

## 1. Pendências herdadas da fase 0

- [x] Suíte, lint e smoke da API executados (via `docker run`, ver "Verificação realizada").
- [x] Hooks do pre-commit executados em todos os arquivos.
- [x] Repositório publicado; CI verde em `main` na fase 0.
- [ ] Instalar o plugin Docker Compose v2 e rodar `make up && make test` uma vez, para validar o `docker-compose.yml` de ponta a ponta.
- [ ] Enviar os commits da fase 1 ao remoto e confirmar o CI verde sobre eles.
- [ ] `pre-commit install` na máquina, para os hooks rodarem a cada commit.

## 2. Escopo da fase 2 já comprometido nos documentos

Itens que decisões e backlog atribuem à fase 2:

- [ ] Tabelas de recursos (e serviços, conforme o plano) com `tenant_id` e `enable_tenant_rls`.
- [ ] FK de `users.resource_id` para `resources`, e vínculo do usuário `professional` ao recurso.
- [ ] CRUD de filiais e criação da filial padrão no cadastro do tenant (`signup` hoje não cria filial).
- [ ] Alvo `make seed`, criado junto com o seed.
- [ ] Confirmar o uso de `Branch`, `Tenant.segment`, `Tenant.settings` e `PublicSession`; remover o que sobrar.
- [ ] Preencher `tests/concurrency` (hoje só `.gitkeep`), em especial se a fase 2 introduzir a exclusion constraint de reservas.

## 3. O que reutilizar

- Toda tabela nova: `tenant_id` + `enable_tenant_rls("tabela")` na migration; o teste de catálogo a cobre sem alteração.
- Rotas do painel: `TenantSession` e `require_roles(...)`.
- Rotas públicas por slug: `PublicSession`.
- Erros: subclasses de `AppError`; nunca `HTTPException` direta.
- Migrations rodam como `hora`; os privilégios de `hora_app` vêm do `ALTER DEFAULT PRIVILEGES` (revogar explicitamente o que não deve ser permitido, como foi feito com `DELETE` em `tenants`).

## 4. Pontos de atenção

- O plano original das fases não está no repositório; a lista da seção 2 foi extraída de `decisions.md` e `backlog.md`. Confirme contra o plano se houver itens adicionais.
- Refresh duplicado (duas abas ou retry) continua derrubando a sessão; é decisão de produto (janela de tolerância ou lock entre abas) a tomar antes do frontend de login.
- Se a fase 2 expuser a área pública de agendamento, aplicar o limite de tentativas e a janela de tolerância do refresh antes do frontend de login (fases 7 e 10), conforme o backlog.
