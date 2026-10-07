# Hora Cravada

Plataforma de agendamento multi-tenant. O núcleo (recursos, serviços, disponibilidade e reservas) é genérico e se adapta a barbearias, clínicas e locação de salas por configuração. O ponto central é impedir conflito de horários sob concorrência: a garantia fica no banco, com uma exclusion constraint do PostgreSQL.

O projeto está em desenvolvimento. Hoje existem a fundação (API, migrations, worker, frontend mínimo, CI) e o isolamento entre empresas: cadastro de tenant, login com JWT e refresh rotativo, papéis e Row Level Security.

## Requisitos

- Docker com Docker Compose v2 (`docker compose`)
- make

## Como subir

```sh
make up
```

Serviços:

| Serviço | Endereço |
|---|---|
| API | http://localhost:8000 (`/health`, `/docs`) |
| Frontend | http://localhost:3000 |
| PostgreSQL | localhost:5432 (banco `hora_cravada`; `hora` é o dono e roda as migrations, `hora_app` é o role da API) |
| Redis | localhost:6379 |

As migrations rodam sozinhas quando a API sobe. Para rodar manualmente: `make migrate`.

## Comandos

| Comando | O que faz |
|---|---|
| `make up` | Sobe todos os serviços em segundo plano |
| `make down` | Derruba os serviços |
| `make test` | Roda a suíte de testes do backend |
| `make lint` | ruff, mypy, ESLint e Prettier |
| `make migrate` | Aplica as migrations |

## Estrutura

- `backend/`: FastAPI, SQLAlchemy 2 async, Alembic, worker ARQ
- `frontend/`: Next.js (App Router)
- `docs/`: arquitetura (modelo de tenant), decisões e backlog
