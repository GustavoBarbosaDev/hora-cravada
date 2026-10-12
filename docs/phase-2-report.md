# Relatório técnico: fase 2 (recursos, serviços e disponibilidade)

## Escopo

Cadastro de tudo que o motor de slots (fase 3) precisa: filiais com fuso validado, recursos, serviços, vínculo recurso-serviço, regras semanais de atendimento e exceções. Nenhum cálculo de horários livre e nenhuma reserva foi implementado. O modelo está descrito em [architecture.md](architecture.md); aqui ficam o que foi entregue, a referência da API e como verificar.

## Resultado

| Item | Estado |
|---|---|
| CRUD de recursos (`kind`, capacidade, atributos JSON) | Feito |
| CRUD de serviços (duração, buffers, preço, `required_resource_kinds`) | Feito |
| Vínculo recurso-serviço | Feito (`PUT /services/{id}/resources`) |
| Regras semanais com vários intervalos por dia | Feito |
| Exceções por recurso ou para a empresa toda (folga, feriado, horário especial) | Feito |
| Validação: fim maior que início, sem sobreposição na mesma regra | Feito; sobreposição garantida por exclusion constraint |
| Fuso por filial validado contra a base IANA | Feito |
| CRUD de filiais e filial padrão no cadastro da empresa | Feito (pendência da fase 1) |
| FK de `users.resource_id` para `resources` e vínculo do profissional | Feito (pendência da fase 1) |
| `make seed` com três empresas | Feito |
| Teste de concorrência em `tests/concurrency/` | Feito (regras sobrepostas simultâneas) |
| `services.custom_fields_schema` | Adiado para a fase 11 (ver [decisions.md](decisions.md)) |

## Banco de dados

Migration `0006`. Todas as tabelas novas têm `tenant_id` e RLS com `FORCE`; o teste de catálogo da fase 1 as cobre sem alteração.

| Tabela | Chaves e constraints principais |
|---|---|
| `resources` | `UNIQUE (tenant_id, id)`; FK composta `(tenant_id, branch_id)` para `branches`; `capacity >= 1`; índice `(tenant_id, branch_id)` |
| `services` | `UNIQUE (tenant_id, id)`; `duration_min > 0`; buffers e preço `>= 0`; `required_resource_kinds text[]` |
| `resource_services` | PK `(resource_id, service_id)`; FKs compostas para `resources` e `services` com cascade; índice em `service_id` |
| `availability_rules` | `weekday 0..6`; `0 <= start < end <= 1440`; `EXCLUDE USING gist` contra sobreposição por recurso e dia |
| `availability_exceptions` | `kind IN ('closed','open')`; início e fim juntos ou nenhum; `open` sempre com horário; índice `(tenant_id, date)` |
| `users` | nova FK composta `(tenant_id, resource_id)` com `ON DELETE SET NULL (resource_id)`; `CHECK` de que só `professional` tem recurso |
| `branches` | novo `UNIQUE (tenant_id, id)`, alvo das FKs compostas |

`branches` é referenciada sem `ON DELETE`, então apagar uma filial com recursos é recusado, e apagar o tenant (role dono) continua funcionando porque a remoção em cascata acontece no mesmo comando.

## Backend

### Módulos novos

| Módulo | Responsabilidade |
|---|---|
| `app/branches/` | rotas e serviço de filiais (o modelo `Branch` continua em `app/tenants/models.py`) |
| `app/resources/` | recursos |
| `app/services/` | serviços e vínculo com recursos |
| `app/availability/` | regras semanais e exceções; conversão entre `"HH:MM"` e minutos |
| `app/core/timezones.py` | tipo `Timezone`, validado contra a lista do `tzdata` |
| `app/core/schemas.py` | `PatchModel`: `PATCH` em que `null` só vale nos campos anuláveis |
| `app/db/errors.py` | `sqlstate()` e os códigos de violação tratados |
| `app/seed.py` | dados de exemplo (`make seed`) |

### Referência da API

Leitura (`GET`) para qualquer papel autenticado; escrita só para `owner`. Todas as rotas são do painel (token de acesso).

| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET /branches`, `POST /branches` | `name`, `timezone`, `address?` | lista; 201 |
| `PATCH /branches/{id}`, `DELETE /branches/{id}` | campos opcionais | filial; 204; 409 se tem recursos |
| `GET /resources?kind&branch_id`, `GET /resources/{id}` | | recursos |
| `POST /resources` | `branch_id`, `kind`, `name`, `capacity` (1), `attributes` ({}) | 201 |
| `PATCH /resources/{id}`, `DELETE /resources/{id}` | campos opcionais, incluindo `active` | recurso; 204 |
| `GET /services`, `GET /services/{id}` | | serviços |
| `POST /services` | `name`, `duration_min`, `buffer_before_min` (0), `buffer_after_min` (0), `price_cents` (0), `required_resource_kinds` ([]) | 201 |
| `PATCH /services/{id}`, `DELETE /services/{id}` | campos opcionais, incluindo `active` | serviço; 204 |
| `GET /services/{id}/resources` | | `{resource_ids}` |
| `PUT /services/{id}/resources` | `{resource_ids}` (substitui o conjunto) | `{resource_ids}`; 422 se algum não existe |
| `GET /resources/{id}/availability-rules` | | regras por dia e início |
| `POST /resources/{id}/availability-rules` | `weekday` (0 = segunda), `start`, `end` (`"HH:MM"`, fim até `"24:00"`) | 201; 409 se sobrepõe |
| `DELETE /availability-rules/{id}` | | 204 |
| `GET /availability-exceptions?date_from&date_to&resource_id` | | exceções por data |
| `POST /availability-exceptions` | `resource_id?`, `date`, `kind`, `start?`, `end?`, `reason?` | 201 |
| `DELETE /availability-exceptions/{id}` | | 204 |
| `POST /users` | passou a aceitar `resource_id` (só para `professional`) | `UserOut` agora inclui `resource_id` |

Recurso ou filial de outro tenant, em corpo de requisição, devolve 422 (referência inexistente do ponto de vista de quem chama); em caminho de URL, 404. O formato de erro é o mesmo das fases anteriores.

### Limites de entrada

`kind` e itens de `required_resource_kinds`: minúsculas, números e hífens, até 40 caracteres. Nomes até 120. Capacidade 1 a 1000. Duração 1 a 1440 minutos; buffers 0 a 1440. `attributes` até 4096 bytes serializados. No máximo 10 tipos exigidos por serviço e 200 recursos por vínculo.

## Correções feitas no caminho

- O fuso do cadastro de empresa era validado com `ZoneInfo`, que aceita `localtime` e a lista `available_timezones()` também a inclui. Agora usa a lista do pacote `tzdata` (nova dependência explícita), nos dois lugares.
- `test_production_refuses_the_development_jwt_secret` falhava sempre que `JWT_SECRET` estava definido no ambiente, como no compose (`make test`). O teste agora passa o segredo de desenvolvimento explicitamente.
- Os modelos SQLAlchemy de `users` e `branches` divergiam das migrations (nomes de constraints). Foram alinhados; `alembic check` passa a reportar "No new upgrade operations detected".

## Testes

165 testes no backend, todos passando (ruff, ruff format e mypy sem erros); a suíte foi executada 3 vezes seguidas sem falha intermitente.

| Arquivo | Comportamento coberto |
|---|---|
| `tests/integration/test_branches_and_resources.py` | filial padrão no cadastro; CRUD de filiais e recursos; fuso inválido (`localtime`, `Mars/Olympus`, caminhos); `null` em campo obrigatório; filial com recursos não é apagada; validações de recurso; filial de outro tenant; isolamento entre tenants; escrita negada a recepção e profissional |
| `tests/integration/test_services.py` | CRUD; tipos exigidos sem duplicata; validações; substituição do conjunto de recursos; recursos inexistentes ou de outro tenant; vínculo some ao apagar recurso ou serviço; isolamento; escrita negada |
| `tests/integration/test_availability.py` | pausa de almoço; intervalos encostados; sobreposições (cinco formas); mesmo horário em outro dia ou recurso; fim às 24:00; formatos inválidos; exclusão libera o intervalo; isolamento; exceções (feriado, folga, parcial, abertura especial), validações, filtros e exclusão |
| `tests/integration/test_professional_link.py` | profissional vinculado a recurso; recepção não pode; recurso de outro tenant; recurso apagado desvincula |
| `tests/integration/test_catalog_schema.py` | direto no banco, como `hora_app`: FK composta recusa filial, recurso e serviço de outro tenant (inclusive em `users`); `CHECK` de profissional; exclusion constraint sem passar pela aplicação; exceções inconsistentes; dono apaga tenant com catálogo completo; filial com recursos é restrita |
| `tests/concurrency/test_availability_rules.py` | 8 regras sobrepostas simultâneas: uma vence, sete recebem 409, e uma fica gravada |
| `tests/integration/test_seed.py` | seed idempotente; cada empresa com catálogo completo, vínculos, horários e feriados; profissional vinculado ao recurso |
| `tests/integration/test_migrations.py` | tabelas novas sobem e descem; downgrade para `0005` preserva `users` e `branches` |

## Verificação realizada

Mesmo ambiente da fase 1 (sem Docker Compose v2): Postgres 16 e Redis 7 em contêineres avulsos, imagem do backend reconstruída com a nova dependência.

- `pytest`: 165 passando, 3 execuções seguidas; `ruff check`, `ruff format --check`, `mypy app tests`: sem erros.
- `alembic upgrade head` até a `0006` e `alembic check` sem diferenças entre modelos e banco.
- `python -m app.seed` duas vezes: cria as três empresas e na segunda não faz nada.
- Smoke da API com uvicorn: login do dono da clínica seeded, `GET /resources`, `GET /health` e `/openapi.json`.
- CI: ainda não rodou sobre os commits das fases 1 e 2 (não enviados ao remoto).
- Não executado: `make up && make test` (falta o plugin Compose v2 na máquina) e os hooks do pre-commit.

## Limitações conhecidas

Detalhes em [backlog.md](backlog.md). As que afetam o uso:

- Exceções com semântica definida (`open` substitui, `closed` subtrai) mas ainda sem consumidor; o motor de slots da fase 3 é quem a aplica, e os testes dele devem cobrir a combinação.
- Listagens sem paginação.
- Vínculo de usuário com recurso só na criação.
- Corrida entre apagar um registro e referenciá-lo termina em 500 em vez de 409.
- Apagar recurso ou serviço é definitivo; passa a ser restrito quando as reservas existirem (fase 4).
