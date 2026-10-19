# Relatório técnico: fase 4 (reservas)

## Escopo

Criar e cancelar reservas sem conflito sob concorrência, ligar o motor de slots às reservas reais e aceitar recursos com capacidade maior que 1. O modelo está em [architecture.md](architecture.md); as decisões em [decisions.md](decisions.md).

## Resultado

| Item | Estado |
|---|---|
| Tabelas `customers`, `bookings`, `booking_resources` (migration 0007, com RLS e FK composta) | Feito |
| Exclusion constraint por (recurso, vaga, intervalo) só para registros ativos | Feito |
| `load_busy` lê as reservas; o slot some depois de reservar | Feito |
| `POST /public/{slug}/bookings`, sem login | Feito |
| Buffers gravados na reserva e protegidos pela constraint | Feito |
| Capacidade maior que 1 por vagas numeradas | Feito (ver decisão e consequência) |
| Serviço com recursos exigidos ocupa executor e sala juntos | Feito |
| Painel: listar, ler e cancelar (`owner` e `reception`) | Feito |
| Apagar recurso ou serviço com reserva dá 409 | Feito |
| Cache dos slots em Redis | Adiado, com o motivo nas decisões |

## Código

| Arquivo | Responsabilidade |
|---|---|
| `app/bookings/models.py` | `Customer`, `Booking`, `BookingResource` |
| `app/bookings/service.py` | validação contra o motor, trava de recursos, escolha de vaga, cancelamento |
| `app/bookings/router.py` | rota pública de criação e rotas do painel |
| `app/bookings/schemas.py` | corpo e respostas; telefone normalizado |
| `app/slots/service.py` | `plan_slots` (contexto reaproveitado pelas reservas) e `load_busy` real |
| `app/slots/engine.py` | `Schedule` com `capacity` e `busy_by_seat` |
| `migrations/versions/0007_create_bookings.py` | tabelas, índices, RLS e a constraint |

## API

| Rota | Acesso | Resposta |
|---|---|---|
| `POST /public/{slug}/bookings` | público | 201; 409 horário indisponível ou ocupado no instante; 404 empresa ou serviço; 422 dados inválidos ou filial ambígua |
| `GET /bookings` | `owner`, `reception` | lista, filtros `date_from`, `date_to`, `resource_id`, `status` |
| `GET /bookings/{id}` | idem | 404 se for de outra empresa |
| `POST /bookings/{id}/cancel` | idem | idempotente |

## Um problema encontrado

O teste de concorrência com inícios sobrepostos mas diferentes provocou deadlock do PostgreSQL na exclusion constraint, e a API devolveu 500. A correção é travar os recursos em ordem de id antes de inserir; detalhes em [decisions.md](decisions.md). O teste ficou para impedir regressão.

## Testes

Suíte completa: 280 testes passando (a contagem inclui parametrizações); `ruff check`, `ruff format --check` e `mypy app tests` sem erros. Os testes de concorrência foram repetidos 5 vezes seguidas sem falha.

Novos: `tests/integration/test_bookings.py` (20 funções, 23 casos com a parametrização), `tests/concurrency/test_bookings.py` (3) e 3 casos de capacidade em `tests/unit/test_slot_engine.py`.

Ambiente de verificação: o mesmo das fases anteriores, com Postgres 16 em contêiner avulso e a imagem do backend com o código montado. Não executado: `make up && make test`, hooks do pre-commit, cobertura.

## Limitações conhecidas

Detalhes em [backlog.md](backlog.md).

- Cliente identificado só pelo telefone, sem verificação, e sem limite de taxa na rota pública.
- O cliente não consegue cancelar nem remarcar sozinho.
- Só a rota pública cria reservas; recepção ainda não marca pelo painel.
- A regra de vagas é mais estrita que "no máximo N ao mesmo tempo" em casos de durações misturadas.
- Sem cache dos slots.
