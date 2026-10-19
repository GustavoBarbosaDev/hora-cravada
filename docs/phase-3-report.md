# Relatório técnico: fase 3 (motor de slots)

## Escopo

Cálculo dos horários livres a partir do catálogo e da disponibilidade da fase 2, e o endpoint público que os expõe. Não há reservas ainda (fase 4): o motor já recebe os intervalos ocupados como entrada, e o carregamento deles está isolado em `load_busy`, que hoje devolve vazio. O modelo está em [architecture.md](architecture.md); aqui ficam o que foi entregue e como verificar.

## Resultado

| Item | Estado |
|---|---|
| Regras semanais expandidas em intervalos UTC pelo fuso da filial | Feito |
| Exceções (fechamento, abertura especial) | Feito, com a precedência definida na fase 2 |
| Subtrair reservas ativas, incluindo buffers | Feito no motor; `load_busy` vazio até a fase 4 |
| Slots por passo configurável, com duração e buffers conferidos | Feito (5, 10, 15, 20, 30 ou 60 min; padrão 15) |
| Serviço com vários tipos de recurso: só há slot se todos tiverem recurso livre | Feito; escolha pelo primeiro livre na ordem (nome, id) |
| Antecedência mínima e máxima | Feito, lida de `tenants.settings["slots"]` |
| `GET /public/{slug}/slots` | Feito |
| Cache em Redis por (empresa, serviço, dia) | Adiado para a fase 4 (ver [decisions.md](decisions.md)) |

## Código

| Arquivo | Responsabilidade |
|---|---|
| `app/slots/engine.py` | motor puro: união e subtração de intervalos, horário aberto do dia, conversão local para UTC, inícios livres por recurso, slots finais |
| `app/slots/service.py` | carrega executores, recursos exigidos, regras e exceções; resolve a filial; chama o motor |
| `app/slots/schemas.py` | parâmetros da consulta (período, passo), resposta e leitura da antecedência |
| `app/slots/router.py` | rota pública e a dependência `utc_now`, que os testes substituem |

Nenhuma migration: a fase usa as tabelas da anterior.

## API

`GET /public/{slug}/slots`, sem autenticação.

| Parâmetro | Obrigatório | Observação |
|---|---|---|
| `service_id` | sim | serviço ativo da empresa |
| `date_from`, `date_to` | sim | datas locais da filial, até 31 dias, inclusive |
| `branch_id` | quando o serviço tem executores em mais de uma filial | 422 sem ele |
| `resource_id` | não | restringe a um executor; 404 se ele não executa o serviço |
| `step_min` | não | 5, 10, 15, 20, 30 ou 60; padrão 15 |

Respostas: 200 com os slots (possivelmente vazios); 404 para empresa, serviço ou filial inexistente, serviço inativo, executor inválido ou serviço sem recurso ativo; 422 para período inválido, passo inválido ou filial ambígua. O formato do corpo está em [architecture.md](architecture.md).

## Testes

| Arquivo | Cobertura |
|---|---|
| `tests/unit/test_slot_engine.py` (52) | intervalos e exceções; pausa de almoço; buffers e reservas; meia-noite; horário de verão em Nova York e São Paulo; antecedência; vários recursos; todos os passos |
| `tests/unit/test_slot_settings.py` (8) | padrão, leitura e configuração inválida |
| `tests/integration/test_slots_api.py` (26) | pausa de almoço com fuso, feriado, abertura especial, período com vários dias, fuso por filial, filial ambígua, filtro por executor, recurso e serviço inativos, empresa e serviço inexistentes, isolamento entre empresas, validação da consulta, sala exigida (horário, fechamento de uma ou de todas, outra filial) |

Suíte completa: 251 testes passando, ruff, ruff format e mypy sem erros. Os testes unitários do motor rodam em menos de 0,1 s, sem banco.

## Verificação realizada

Mesmo ambiente das fases anteriores (sem Docker Compose v2): Postgres 16 em contêiner avulso e imagem do backend construída a partir do `Dockerfile`, com o código montado.

- `pytest` completo, `ruff check`, `ruff format --check` e `mypy app tests`.
- Não executado: `make up && make test`, os hooks do pre-commit e medição de cobertura (`pytest-cov` não faz parte das dependências).

## Limitações conhecidas

Detalhes em [backlog.md](backlog.md).

- Sem reservas, todo horário aberto aparece livre.
- Capacidade do recurso não entra no cálculo.
- A antecedência só pode ser alterada direto no banco; a rota de edição vem com a fase 10.
- Não há como a página pública listar serviços e profissionais; o `service_id` precisa ser conhecido.
- Num horário que não existe por causa do horário de verão, uma regra que começa ou termina nele é convertida pelo deslocamento anterior ao salto.
