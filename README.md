# Hora Cravada

Plataforma de agendamento multi-tenant. O núcleo (recursos, serviços, disponibilidade e reservas) é genérico e se adapta a barbearias, clínicas e locação de salas por configuração. O ponto central é impedir conflito de horários sob concorrência: a garantia fica no banco, com uma exclusion constraint do PostgreSQL.

O projeto está em desenvolvimento. Hoje existe apenas a fundação: API com `/health`, migrations, worker, frontend mínimo e pipeline de CI.

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
| PostgreSQL | localhost:5432 (usuário `hora`, banco `hora_cravada`) |
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
- `docs/`: decisões e, nas próximas fases, arquitetura e concorrência
