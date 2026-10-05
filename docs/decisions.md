# Decisões

## Migrations rodam na subida da API em desenvolvimento

Contexto: `make up && make test` precisa funcionar numa máquina limpa.
Decisão: o comando do serviço `api` no compose executa `alembic upgrade head` antes do uvicorn.
Alternativa descartada: serviço separado de migração, mais cerimônia para um ambiente de desenvolvimento.

## Banco de testes separado no mesmo Postgres do compose

Contexto: os testes de migration derrubam e recriam extensões.
Decisão: `docker/postgres/init-test-db.sql` cria o banco `hora_cravada_test` junto com o principal; os testes usam `TEST_DATABASE_URL`, e sem ela sobem um Postgres via testcontainers.
Alternativa descartada: usar sempre testcontainers, que exigiria acesso ao socket do Docker de dentro do container da API.

## Alvo `make seed` fica para a fase 2

Contexto: o plano lista `seed` entre os alvos da fase 0, mas os dados de seed dependem das tabelas de recursos e serviços.
Decisão: o alvo é criado junto com o seed, na fase 2, para não existir um comando que falha.
Alternativa descartada: alvo vazio agora.

## Frontend mínimo na fase 0

Contexto: o compose precisa de um serviço `frontend`, mas Tailwind e shadcn/ui só têm uso a partir da fase 7.
Decisão: Next.js com TypeScript, ESLint e Prettier apenas; as demais dependências entram quando forem usadas.
Alternativa descartada: instalar o conjunto completo de UI antecipadamente.
