# Relatório técnico: fase 0 (fundação)

## Escopo

Ambiente reproduzível e pipeline mínimo: API, banco, fila, worker, frontend, qualidade de código e CI. Nenhuma regra de negócio foi implementada nesta fase.

## Resultado

| Item | Estado |
|---|---|
| Estrutura de pastas, `pyproject.toml`, Makefile | Feito |
| `docker-compose.yml` (Postgres 16, Redis, api, worker, frontend) | Feito; sintaxe validada, stack completa não executada via `docker compose` |
| FastAPI com `/health` e configuração por ambiente | Feito |
| SQLAlchemy async, Alembic, migration das extensões | Feito |
| Logs JSON e formato único de erro | Feito |
| ruff, mypy, pre-commit | ruff e mypy verificados; pre-commit configurado, não executado |
| GitHub Actions | Escrito; ainda não executado (repositório sem remoto) |
| README inicial | Feito |

## Arquitetura entregue

### Backend (`backend/`)

- `app/config.py`: `Settings` (pydantic-settings) com `environment`, `log_level`, `database_url` e `redis_url`. `get_settings()` é cacheada; os testes limpam o cache ao trocar variáveis.
- `app/db/base.py`: `Base` declarativa com convenção de nomes para constraints, para que as migrations geradas sejam previsíveis.
- `app/db/session.py`: `build_engine`, `build_sessionmaker` e a dependência `get_session`. O engine é criado no `lifespan` e descartado no encerramento. O contexto de tenant (`SET LOCAL app.tenant_id`) entra na fase 1, neste mesmo módulo.
- `app/core/logging.py`: structlog com saída JSON. Logs de bibliotecas (uvicorn, SQLAlchemy, arq) passam pelo mesmo formatador via `ProcessorFormatter`. O log de acesso do uvicorn é desligado em favor do middleware da aplicação.
- `app/core/errors.py`: `AppError` (com `status_code` e `code` por subclasse) e `DependencyUnavailableError` (503). Handlers para `AppError`, `HTTPException`, erro de validação (422) e exceção não tratada (500, sem vazar a mensagem interna).
- `app/main.py`: `create_app()`, middleware que define `request_id` (aceita `x-request-id` ou gera um), registra cada requisição e devolve o cabeçalho na resposta. `GET /health` executa `SELECT 1` e responde 503 se o banco não responder.
- `app/worker/settings.py`: `WorkerSettings` do ARQ com a task `ping`, que existe para que o worker tenha ao menos uma função registrada e a fiação com o Redis seja testável.
- `migrations/`: Alembic assíncrono (`env.py` usa o mesmo engine da aplicação). Migration `0001` cria `btree_gist` e `pgcrypto`, com downgrade que as remove. Migrations offline não são suportadas.

### Formato de erro

Toda resposta de erro tem a mesma forma:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Dados inválidos.",
    "details": [{"field": "body.quantity", "message": "..."}],
    "request_id": "0ec65b178f234bfe83f43ad9f875a986"
  }
}
```

### Frontend (`frontend/`)

Next.js 15 (App Router) com TypeScript, ESLint e Prettier. Apenas layout e uma página inicial. Tailwind e shadcn/ui ficam para a fase 7.

### Infraestrutura

- `docker-compose.yml`: `db`, `redis`, `api`, `worker`, `frontend`, com healthchecks em Postgres e Redis e `depends_on` com `service_healthy`. O serviço `api` aplica `alembic upgrade head` antes de iniciar o uvicorn. O código é montado como volume para recarga em desenvolvimento.
- `docker/postgres/init-test-db.sql`: cria o banco `hora_cravada_test` na primeira inicialização do volume.
- `Makefile`: `up`, `down`, `test`, `lint`, `migrate`. O alvo `seed` fica para a fase 2.
- `.github/workflows/ci.yml`: job de backend (Postgres 16 e Redis como serviços; ruff, ruff format, mypy, pytest) e job de frontend (`npm ci`, lint, `tsc`).
- `.pre-commit-config.yaml`: hooks básicos, ruff, ruff-format e mypy.

## Testes

12 testes, todos passando.

| Arquivo | Comportamento coberto |
|---|---|
| `tests/unit/test_errors.py` | `AppError` usa seu status e mensagem; erro base devolve 500; rota inexistente devolve 404 no formato padrão; corpo inválido lista o campo com erro; exceção inesperada não vaza mensagem interna; `request_id` do cabeçalho aparece na resposta e no corpo do erro; logs saem como JSON |
| `tests/unit/test_worker.py` | a task `ping` responde e está registrada |
| `tests/integration/test_health.py` | `/health` responde 200 com banco no ar e 503 com banco inacessível |
| `tests/integration/test_migrations.py` | upgrade instala as extensões, downgrade as remove, novo upgrade funciona |

A fixture `database_url` usa `TEST_DATABASE_URL` quando definida (compose e CI) e, caso contrário, sobe um Postgres descartável com testcontainers.

## Verificação realizada

A máquina de desenvolvimento não tem o plugin `docker compose` v2 (o `docker-compose` v1 instalado está quebrado). Por isso a verificação foi feita com `docker run`, numa rede com contêineres de Postgres e Redis:

- ruff, ruff format e mypy: sem erros.
- pytest: 12 passando.
- API: migration aplicada na subida, `/health` devolvendo `{"status":"ok"}`, logs em JSON.
- Worker: `arq app.worker.settings.WorkerSettings` iniciou, conectou no Redis e registrou `ping`.
- Frontend: ESLint, Prettier e `tsc` sem erros; build da imagem concluído.
- `docker-compose.yml`: validado com `docker-compose config` (versão 1.29.2, em contêiner).

## Pendências para fechar o aceite

1. Executar `make up && make test` com Docker Compose v2.
2. Publicar o repositório e confirmar o workflow de CI verde.
3. Executar o pre-commit (`pre-commit install` e `pre-commit run --all-files`).

## Decisões

Registradas em [decisions.md](decisions.md):

- Migrations rodam na subida da API em desenvolvimento.
- Banco de testes separado no mesmo Postgres do compose.
- `make seed` adiado para a fase 2.
- Frontend mínimo na fase 0.

## Limitações conhecidas

- O `/health` verifica apenas o banco; Redis não faz parte do check.
- O usuário do banco usado pela aplicação ainda é o dono do schema. O role sem `BYPASSRLS` e a separação do role de migrations entram na fase 1.
- O Dockerfile do backend instala as dependências de desenvolvimento, pois a mesma imagem serve ao `make test`. Uma imagem de produção separada fica para a fase 14.
- As versões das dependências Python têm apenas limite inferior; não há lockfile no backend.
