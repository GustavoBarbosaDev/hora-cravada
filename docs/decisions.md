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

## Login recebe o slug da empresa

Contexto: o e-mail é único por tenant, não globalmente, então só o e-mail não identifica o usuário, e o RLS precisa do tenant antes de consultar `users`.
Decisão: `POST /auth/login` recebe `tenant_slug`, `email` e `password`. O refresh token carrega o tenant em um prefixo (`<tenant_id>.<segredo>`) pelo mesmo motivo.
Alternativa descartada: e-mail único global, que impediria a mesma pessoa de trabalhar em duas empresas.

## A tabela `tenants` não usa RLS

Contexto: o slug precisa ser resolvido antes de existir contexto de tenant (login, página pública, cadastro).
Decisão: `tenants` não tem `tenant_id` nem policy. O role da aplicação lê, insere e atualiza, mas não apaga. Remover um tenant exige o role dono.
Alternativa descartada: função `SECURITY DEFINER` para resolver o slug, mais código para proteger dados que a página pública já expõe (nome e slug).

## Policy tolera variável ausente ou vazia

Contexto: `current_setting('app.tenant_id')` sem o segundo argumento dá erro quando a variável nunca foi definida, e depois de um `SET LOCAL` a variável volta como texto vazio, que não converte para uuid.
Decisão: a policy usa `NULLIF(current_setting('app.tenant_id', true), '')::uuid`. Sem tenant, o predicado é NULL e nenhuma linha passa.
Alternativa descartada: o predicado do plano, que quebra a consulta com erro de cast em conexões reaproveitadas do pool.

## Role da aplicação criado pela migration

Contexto: o compose, o CI e os testes com testcontainers precisam do mesmo role sem repetir scripts de init (que também não rodam em volumes já existentes).
Decisão: a migration 0002 cria o role a partir de `DATABASE_URL` se ele não existir, e `ALTER DEFAULT PRIVILEGES` já concede acesso às tabelas das migrations seguintes. O downgrade remove os privilégios, mas não o role, que pertence ao cluster.
Alternativa descartada: criar o role em `docker/postgres/init-*.sql`.

## Refresh token rotativo com detecção de reutilização

Contexto: refresh tokens roubados são o risco principal de uma sessão longa.
Decisão: cada token só vale uma vez; apresentar de novo um token já usado revoga toda a família (`family_id`). O hash SHA-256 é guardado, nunca o token. Uma requisição duplicada legítima também derruba a sessão, o que é aceitável para o ganho de segurança.
Alternativa descartada: token fixo até expirar.

## Token de acesso sem consulta ao banco

Contexto: o painel faz muitas requisições por tela.
Decisão: o access token (15 minutos) carrega `sub`, `tid` e `role` e é validado só pela assinatura. Desativar um usuário vale no próximo refresh e em `/auth/me`.
Alternativa descartada: consultar o usuário em toda requisição.

## Gestão de usuários mínima na fase 1

Contexto: o teste de que o profissional não acessa rotas de dono precisa de uma rota de dono real e de usuários com outros papéis.
Decisão: `GET /users` e `POST /users`, só para `owner`. Edição, desativação e vínculo com `resource_id` ficam para o painel (fase 10) e para os recursos (fase 2).
Alternativa descartada: rotas fictícias só nos testes.

## `hora_app` não atualiza `tenants`

Contexto: `tenants` não tem RLS, então um UPDATE do role da aplicação alcançaria qualquer empresa, e nenhuma rota da fase 1 edita tenants.
Decisão: a migration `0005` revoga `UPDATE` de `hora_app` em `tenants`. A edição de empresa (fase 10) concede o privilégio por coluna e filtra pelo tenant do token.
Alternativa descartada: manter o privilégio e confiar em revisão de código para lembrar do filtro.

## Referências entre tabelas de negócio levam `tenant_id`

Contexto: o RLS valida só a linha gravada, e a checagem de FK ignora o RLS. Uma FK simples aceita o id de um recurso de outra empresa.
Decisão: FKs compostas `(tenant_id, x_id)` para `UNIQUE (tenant_id, id)` da tabela referenciada, inclusive `users.resource_id`. `ON DELETE SET NULL (resource_id)` em `users` mantém o `tenant_id` intacto.
Alternativa descartada: validar o tenant do id na aplicação, que protegeria só as rotas que lembrassem de fazê-lo.

## Horários guardados como minutos desde a meia-noite

Contexto: regras semanais precisam de fim de expediente às 24:00, que o tipo `time` não representa.
Decisão: `start_minute` e `end_minute` (smallint, 0 a 1440). A API continua em `"HH:MM"`.
Alternativa descartada: `time`, que limitaria o fim a 23:59.

## Sobreposição de regras decidida por exclusion constraint

Contexto: a validação "intervalos da mesma regra não se sobrepõem" precisa valer sob requisições simultâneas.
Decisão: `EXCLUDE USING gist` sobre `(resource_id, weekday, int4range(início, fim))`; a aplicação só traduz o erro `23P01` em `409`.
Alternativa descartada: consultar e inserir na aplicação, com janela de corrida.

## Exceções de disponibilidade: `open` substitui, `closed` subtrai

Contexto: "horário especial" e "folga" podem coexistir na mesma data e o plano não define a precedência.
Decisão: documentada em `architecture.md`; `open` substitui as regras semanais da data e `closed` remove o que sobrou, com `closed` vencendo.
Alternativa descartada: `open` somar às regras semanais, que impediria encurtar o expediente num dia especial.

## Leitura aberta a todos os papéis, escrita só do dono

Contexto: recepção e profissionais precisam ver recursos e serviços para operar a agenda; o plano só exige que profissional não acesse rotas de dono.
Decisão: `GET` com qualquer papel autenticado; `POST`, `PATCH`, `PUT` e `DELETE` só `owner`.
Alternativa descartada: restringir a leitura ao dono, o que obrigaria o painel a duplicar endpoints.

## Regras e exceções não têm edição

Contexto: são registros pequenos, sem relações dependentes.
Decisão: criar e apagar. Corrigir um horário é apagar e recriar.
Alternativa descartada: `PATCH`, que repetiria a validação de intervalo e o tratamento da constraint.

## Vínculo recurso-serviço por substituição do conjunto

Contexto: o painel envia a lista final de quem executa o serviço.
Decisão: `PUT /services/{id}/resources` troca o conjunto inteiro numa transação, com lock na linha do serviço para serializar chamadas simultâneas.
Alternativa descartada: um `POST` e um `DELETE` por vínculo, com mais chamadas e estados intermediários.

## Remoção definitiva de recursos e serviços por enquanto

Contexto: ainda não existem reservas.
Decisão: `DELETE` apaga o registro e leva horários e vínculos junto. Quando `booking_resources` existir (fase 4), a FK será restritiva e o caminho normal passa a ser desativar (`active = false`).
Alternativa descartada: só desativar agora, sem necessidade enquanto nada referencia os registros.

## Fuso horário validado pela lista do `tzdata`

Contexto: `ZoneInfo` aceita apelidos do sistema (`localtime`), e `available_timezones()` os lista; qualquer um passaria como fuso de filial.
Decisão: validar contra o arquivo `zones` do pacote `tzdata`, que passa a ser dependência explícita.
Alternativa descartada: `ZoneInfo(valor)` direto, que foi o que o cadastro de empresa fazia.

## `custom_fields_schema` fica para a fase 11

Contexto: a coluna aparece no modelo de referência de `services`, mas só o form builder da fase 11 a lê.
Decisão: não criar a coluna agora; a fase 11 a adiciona com a validação do schema.
Alternativa descartada: coluna JSONB sem validação nem uso.


## Grade de horários por tempo decorrido, não por relógio

Contexto: em dia de horário de verão o relógio local repete ou pula uma hora; uma grade por hora de relógio perde os slots da hora repetida ou inventa um na hora que não existe.
Decisão: os inícios candidatos são `meia-noite local + n × passo`, calculados em UTC. Os horários das regras continuam em minutos locais e são convertidos por `local_instant`; num horário inexistente vale o deslocamento anterior ao salto e, num repetido, a primeira ocorrência.
Alternativa descartada: grade em hora de relógio, que dá 24 slots por hora cheia em qualquer dia.

## Buffers ocupam o recurso, mas não precisam caber no expediente

Contexto: um corte de 30 minutos com 5 de limpeza depois, no último horário do dia, é uma situação comum.
Decisão: só o serviço precisa caber na janela aberta; `buffer_antes` e `buffer_depois` são conferidos contra reservas existentes.
Alternativa descartada: exigir os buffers dentro do expediente, o que removeria o último horário de todo dia.

## Janelas encostadas viram uma só

Contexto: duas regras `09:00-12:00` e `12:00-14:00` são permitidas e uma sala aberta até 24:00 continua aberta às 00:00.
Decisão: o motor une janelas que se encostam, também entre dias, antes de testar se o serviço cabe.
Alternativa descartada: tratar cada regra isoladamente, o que proibiria serviços que começam numa regra e terminam na seguinte sem pausa real.

## Filial obrigatória quando o serviço tem mais de uma

Contexto: o fuso é da filial e os recursos pertencem a uma filial; juntar horários de filiais diferentes numa lista só mistura fusos.
Decisão: `branch_id` é opcional quando só há uma filial com executores; com mais de uma, a resposta é 422. Recursos exigidos por tipo vêm sempre da mesma filial do executor.
Alternativa descartada: devolver os slots agrupados por filial, mais complexo para uma página de agendamento que pergunta a unidade antes.

## Cache em Redis fica para a fase 4

Contexto: o plano pede cache por (empresa, serviço, dia) invalidado quando uma reserva muda, mas ainda não existem reservas para invalidá-lo.
Decisão: não implementar o cache agora; `load_busy` é o ponto único que a fase 4 troca ao criar `bookings`, e a invalidação entra junto com a escrita de reservas.
Alternativa descartada: cache com TTL curto sem invalidação, que serviria horários já ocupados.

## Antecedência em `tenants.settings`

Contexto: o motor precisa de antecedência mínima e máxima, mas a edição de configurações só chega na fase 10.
Decisão: valores lidos de `settings["slots"]` (`min_notice_min`, `max_advance_days`) com padrão 0 e 90 dias; configuração inválida cai no padrão em vez de derrubar a agenda pública.
Alternativa descartada: constantes no código, que obrigariam uma migração de comportamento quando as configurações existirem.
