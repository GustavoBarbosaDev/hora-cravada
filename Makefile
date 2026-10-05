COMPOSE ?= docker compose

.PHONY: up down test lint migrate

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

test:
	$(COMPOSE) run --rm api pytest

lint:
	$(COMPOSE) run --rm api sh -c "ruff check . && ruff format --check . && mypy app tests"
	$(COMPOSE) run --rm frontend npm run lint

migrate:
	$(COMPOSE) run --rm api alembic upgrade head
