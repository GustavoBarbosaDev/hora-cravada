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


## Motor de slots

`app/slots/engine.py` é uma função pura: não acessa banco nem relógio. Recebe a agenda de cada recurso (regras semanais, exceções por data e intervalos ocupados), o serviço, as datas locais e a política de antecedência, e devolve os inícios possíveis. `app/slots/service.py` carrega os dados, resolve a filial e chama o motor; `GET /public/{slug}/slots` expõe o resultado.

### Unidades

Regras e exceções ficam em minutos locais da filial. Tudo que é comparado com reservas ou com o relógio, e tudo que sai do motor, é instante em UTC. A conversão é `local_instant(dia, minuto, fuso)`; durações são somadas em UTC, então um serviço de 60 minutos dura 60 minutos mesmo num dia de 23 ou 25 horas.

### Cálculo

1. Para cada dia, o horário aberto do recurso sai das regras semanais e das exceções (precedência na seção anterior). Janelas que se encostam são unidas, inclusive entre dias: uma sala aberta até 24:00 e a partir de 00:00 permite um serviço atravessar a meia-noite.
2. Os inícios candidatos seguem uma grade de `step_min` minutos de tempo decorrido desde a meia-noite local. Num dia de 25 horas a hora repetida também tem slots.
3. O serviço (sem buffers) precisa caber inteiro numa janela aberta. Os buffers não precisam: ocupam o recurso, mas podem passar do fim do expediente.
4. O intervalo ocupado, de `início - buffer_antes` a `fim + buffer_depois`, não pode se sobrepor ao intervalo ocupado de nenhuma reserva do recurso (que também inclui os buffers dela). Reservas encostadas não bloqueiam. Recurso com capacidade maior que 1 tem uma vaga por unidade de capacidade e basta uma vaga livre no intervalo inteiro.
5. Serviço com `required_resource_kinds`: para cada tipo, precisa existir outro recurso da mesma filial livre no mesmo intervalo, com as mesmas regras de horário e buffers. Vale o primeiro livre na ordem recebida (nome, depois id), o que torna a escolha determinística.
6. Descartam-se inícios antes de `agora + antecedência mínima` e depois de `agora + antecedência máxima`.

### Filial e período

Um serviço atendido em mais de uma filial exige `branch_id` (422 sem ele), porque os horários só fazem sentido num fuso. O período tem no máximo 31 dias. Os passos aceitos são 5, 10, 15, 20, 30 e 60 minutos (padrão 15).

### Antecedência

Lida de `tenants.settings["slots"]`: `min_notice_min` (padrão 0) e `max_advance_days` (padrão 90). Valor ausente ou inválido cai no padrão. Ainda não há rota para editar essas configurações (fase 10).

### Resposta

```json
{
  "branch_id": "…",
  "timezone": "America/Sao_Paulo",
  "service_id": "…",
  "duration_min": 30,
  "slots": [{"start": "2026-11-02T12:00:00Z", "end": "2026-11-02T12:30:00Z", "resource_ids": ["…"]}]
}
```

`resource_ids` lista quem pode executar naquele horário. Serviço ou empresa inexistente, serviço inativo e serviço sem nenhum recurso ativo dão 404.

### Casos cobertos

| Caso | Teste |
|---|---|
| Pausa de almoço sem slots, e serviço que não atravessa a pausa | `test_day_with_a_lunch_break_has_no_slot_during_the_break`, `test_slot_cannot_straddle_the_lunch_break` |
| Regras encostadas funcionam como uma janela | `test_touching_rules_behave_as_one_continuous_window` |
| Serviço que ocupa a janela exata cabe; um minuto a mais não | `test_service_that_fills_the_window_exactly_fits`, `test_service_must_end_inside_the_window` |
| Buffer impede encaixe junto a uma reserva; reserva encostada não bloqueia | `test_buffer_blocks_a_start_that_would_touch_an_existing_booking`, `test_booking_adjacent_to_a_slot_does_not_block_it` |
| Buffer pode passar do fim do expediente | `test_buffers_do_not_need_to_fit_in_the_window` |
| Reserva que atravessa a meia-noite bloqueia o início do dia seguinte | `test_booking_crossing_midnight_blocks_the_start_of_the_next_day` |
| Serviço atravessa a meia-noite só se o recurso continua aberto | `test_service_can_cross_midnight_when_the_resource_stays_open`, `test_service_cannot_cross_midnight_when_the_resource_closes` |
| Horário de verão em `America/New_York`: dia de 23 e de 25 horas | `test_new_york_spring_forward_day_has_23_hours_of_slots`, `test_new_york_fall_back_day_has_25_hours_of_slots`, `test_service_duration_is_elapsed_time_across_the_fall_back` |
| Horário de verão histórico em `America/Sao_Paulo` (04/11/2018 e 16/02/2019) | `test_sao_paulo_historical_dst_start_has_23_hours`, `test_sao_paulo_historical_dst_end_has_25_hours` |
| Exceções: `open` substitui, `closed` subtrai, `closed` vence | `test_open_exception_replaces_the_weekly_rules`, `test_partial_closed_exception_removes_only_that_interval`, `test_closed_wins_over_open_on_the_same_date` |
| Dois recursos, só um livre | `test_service_with_two_resources_needs_both_free`, `test_only_one_of_two_rooms_free_still_makes_a_slot` |
| Todos os tipos exigidos precisam de recurso livre | `test_every_required_kind_must_have_a_free_resource` |
| Escolha determinística do recurso | `test_required_resources_are_picked_in_the_order_given` |
| Antecedência mínima e máxima, e horários passados | `test_minimum_notice_pushes_the_first_slot_forward`, `test_maximum_advance_cuts_the_far_end`, `test_slots_in_the_past_are_dropped` |
| Fuso da filial define o instante UTC | `test_branch_timezone_decides_the_utc_instant` (API) |
| Isolamento entre empresas | `test_a_company_cannot_query_the_service_of_another`, `test_another_company_rooms_and_holidays_do_not_leak` |

## Reservas

Três tabelas, todas com `tenant_id`, RLS e FK composta com o tenant:

| Tabela | Conteúdo |
|---|---|
| `customers` | cliente final, sem login; único por (empresa, telefone) |
| `bookings` | filial, serviço, cliente, início e fim em UTC, e uma cópia da duração, dos buffers e do preço do serviço; `status` `confirmed` ou `cancelled` |
| `booking_resources` | um registro por recurso ocupado: `seat` (vaga de 1 até a capacidade), `busy_start` e `busy_end` (já com os buffers) e `active` |

A garantia contra conflito é uma exclusion constraint, não código:

```sql
EXCLUDE USING gist (resource_id WITH =, seat WITH =, tstzrange(busy_start, busy_end) WITH &&) WHERE (active)
```

Cancelar marca `active = false`, o que tira o registro da restrição e libera o horário sem apagar o histórico. As FKs para recursos, serviços, filiais e clientes não têm `ON DELETE`: apagar algo com reserva dá 409 e o caminho é desativar.

### Criar uma reserva

`POST /public/{slug}/bookings`, sem login. Corpo: `service_id`, `start` (com fuso), `customer` (nome, telefone, e-mail opcional), e opcionalmente `branch_id`, `resource_id` e `notes`.

1. O motor de slots roda com a grade de 5 minutos (contém a grade de qualquer passo oferecido) e o `start` precisa ser um dos slots. Isso confere horário de funcionamento, exceções, antecedência e recursos livres. Se não for, 409.
2. Os recursos de todas as atribuições possíveis são travados numa ordem fixa (`FOR NO KEY UPDATE`). Sem isso, duas inserções simultâneas de intervalos sobrepostos mas diferentes esperam uma pela outra e o PostgreSQL derruba uma por deadlock.
3. O cliente é encontrado ou criado pelo telefone; um cliente existente não tem nome nem e-mail alterados por quem usa a rota pública.
4. Para cada atribuição, na ordem do motor, escolhe-se a primeira vaga livre de cada recurso e insere-se `booking_resources`. Se a constraint recusar (outra requisição ganhou), tenta-se a próxima vaga e depois a próxima atribuição. Esgotadas, 409.

Painel (perfis `owner` e `reception`): `GET /bookings` (filtros `date_from`, `date_to`, `resource_id`, `status`), `GET /bookings/{id}` e `POST /bookings/{id}/cancel`, que é idempotente.

### Casos cobertos

| Caso | Teste |
|---|---|
| Reserva pública sem login; o horário e o buffer saem da agenda | `test_public_booking_needs_no_login_and_returns_the_reserved_slot`, `test_a_booked_slot_and_its_buffer_leave_the_availability` |
| Mesmo horário duas vezes e horários sobrepostos | `test_the_same_slot_cannot_be_booked_twice` |
| Horário que a agenda nunca ofereceu | `test_a_time_the_availability_never_offered_is_refused`, `test_minimum_notice_applies_to_bookings` |
| Cancelar libera o horário | `test_cancelling_frees_the_slot_again` |
| Capacidade maior que 1 | `test_a_room_with_capacity_takes_that_many_simultaneous_bookings` |
| Serviço que exige sala ocupa executor e sala | `test_a_service_that_needs_a_room_reserves_the_executor_and_the_room` |
| Isolamento entre empresas e perfis | `test_bookings_are_isolated_between_companies`, `test_booking_endpoints_require_front_desk_roles` |
| Concorrência: um vencedor por horário, no máximo a capacidade por sala, nenhuma sobreposição com inícios diferentes | `tests/concurrency/test_bookings.py` |
| Capacidade no motor | `test_a_room_with_every_seat_taken_is_busy`, `test_a_seat_free_for_the_whole_interval_is_needed_not_just_free_at_each_instant` |

## Notificações (outbox)

`outbox_events` guarda o aviso a enviar. É gravado na mesma transação da reserva ou do cancelamento, então não existe reserva confirmada sem aviso pendente nem aviso de reserva que não aconteceu. O envio é feito à parte, por um worker ARQ.

| Campo | Conteúdo |
|---|---|
| `kind` | `booking_confirmed`, `booking_cancelled` ou `booking_rescheduled` |
| `payload` | cópia dos dados da reserva no momento do evento |
| `status` | `pending`, `sent` ou `failed` |
| `attempts`, `next_attempt_at`, `last_error` | controle das retentativas |

Único por (`booking_id`, `kind`).

Fluxo do worker (tarefa `deliver_outbox`, a cada 10 segundos): para cada evento vencido, uma transação com `set_config('app.outbox_worker', 'on')`, `SELECT ... FOR UPDATE SKIP LOCKED`, renderização do template Jinja2 (pt-BR, texto e HTML, data no fuso da filial), envio SMTP e atualização do estado. Falha soma uma tentativa e agenda a próxima com espera dobrando (30 s a 1 h); na sexta, o evento vira `failed`. Queda do processo desfaz a transação e o evento continua pendente.

SMTP por `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS` e `SMTP_FROM`. Em desenvolvimento, o Mailpit do compose recebe tudo (interface em http://localhost:8025).

`GET /outbox-events?status=` (perfil `owner`) lista os eventos da empresa.

### Casos cobertos

| Caso | Teste |
|---|---|
| Reserva e evento gravados juntos; recusa não deixa evento | `test_booking_and_its_confirmation_event_are_stored_together`, `test_a_refused_booking_leaves_no_event` |
| Sem e-mail, sem evento | `test_customer_without_email_gets_no_event` |
| Cancelar repetido enfileira um aviso | `test_cancelling_queues_one_cancellation_even_when_repeated` |
| Envio e conteúdo do e-mail | `test_worker_sends_the_email_and_marks_the_event_as_sent`, `tests/unit/test_email_rendering.py` |
| Falha mantém o evento; espera cresce; esgotado vira `failed` | `test_failed_delivery_keeps_the_event_for_a_later_attempt`, `test_backoff_grows_with_each_failed_attempt`, `test_event_that_runs_out_of_attempts_becomes_failed_and_visible` |
| Queda do worker e retomada | `test_worker_crash_after_the_booking_does_not_lose_the_email` |
| Sem reenvio; dois workers | `test_a_sent_event_is_not_sent_again`, `test_two_workers_never_send_the_same_event_twice` |
| Isolamento e perfis | `test_events_are_isolated_between_companies`, `test_only_the_owner_can_list_events`, `test_tenant_requests_cannot_see_events_without_the_worker_flag` |
