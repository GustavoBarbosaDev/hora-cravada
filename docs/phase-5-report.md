# Relatório técnico: fase 5 (notificações com outbox)

## Escopo

E-mail de confirmação, cancelamento e remarcação que não se perde. Modelo e fluxo em [architecture.md](architecture.md); decisões em [decisions.md](decisions.md).

## Resultado

| Item | Estado |
|---|---|
| Tabela `outbox_events` (migration 0008, RLS e política do worker) | Feito |
| Evento gravado na transação da reserva e do cancelamento | Feito |
| Worker ARQ com `FOR UPDATE SKIP LOCKED`, a cada 10 s | Feito |
| Retentativas com espera exponencial, limite e estado `failed` | Feito |
| `GET /outbox-events` para o dono | Feito |
| Templates Jinja2 em pt-BR (texto e HTML) para os três tipos | Feito |
| SMTP configurável e Mailpit no compose | Feito |
| Sem reenvio de evento já enviado | Feito (ao menos uma vez; ver decisão) |
| Emissor do evento de remarcação | Fase 8 |

## Código

| Arquivo | Responsabilidade |
|---|---|
| `app/notifications/events.py` | monta o payload e grava o evento |
| `app/notifications/outbox.py` | reivindicação, envio, retentativas e remetente SMTP |
| `app/notifications/rendering.py` | templates, formatação de data e preço, cabeçalhos |
| `app/notifications/router.py` | listagem para o dono |
| `app/worker/settings.py` | conexão do worker e tarefa periódica |
| `migrations/versions/0008_create_outbox_events.py` | tabela, índices e políticas |

## Um problema encontrado

O autoescape do Jinja estava ligado só para `*.html`, e os templates se chamam `*.html.j2`: as observações digitadas pelo cliente iam sem escape no HTML do e-mail. O teste de escape pegou; a configuração agora cobre `.html.j2`.

## Testes

Suíte completa: 305 passando; `ruff check`, `ruff format --check` e `mypy app tests` sem erros. Os testes de notificação e de concorrência foram repetidos 3 vezes sem falha. O envio SMTP real foi conferido uma vez contra um Mailpit avulso.

Ambiente: Postgres 16 e Redis em contêineres avulsos, imagem do backend com o código montado. Não executado: `make up && make test`, hooks do pre-commit, o worker ARQ contra o Redis (a tarefa é testada chamando `process_outbox` direto) e a derrubada real do processo do worker; a queda é simulada cancelando a tarefa no meio do envio.

## Limitações conhecidas

Detalhes em [backlog.md](backlog.md).

- Entrega ao menos uma vez: queda entre o envio e o commit pode repetir o e-mail.
- Evento `failed` só pode ser lido, não reenfileirado.
- Sem limpeza de eventos antigos.
