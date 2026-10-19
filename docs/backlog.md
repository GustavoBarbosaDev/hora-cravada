# Backlog

Itens fora do escopo da fase em que apareceram.

- Mailpit no compose entra com as notificações (fase 5).
- Limite de tentativas de login por IP e por e-mail (fase 14, endurecimento).
- Edição e desativação de usuários, troca de senha e recuperação de senha (fase 10).
- Limpeza periódica de refresh tokens expirados (fase 14).
- Refresh duplicado (duas abas ou retry de rede com o mesmo token) revoga a família e desloga o usuário. Definir janela de tolerância de alguns segundos ou lock entre abas antes do frontend de login (fases 7 e 10).
- Dockerfile roda como root e instala dependências de dev; separar imagem de produção (fase 14).
- Ao criar "editar empresa" (fase 10): a migration `0005` revogou `UPDATE` em `tenants` do `hora_app`. Conceder `UPDATE` só nas colunas necessárias, filtrar por `id = principal.tenant_id` e cobrir com teste de que outro tenant não é alterado.
- `Tenant.segment` e `Tenant.settings` não têm leitura nem escrita ainda; entram com os templates de segmento (fase 11) e as configurações de hold e cancelamento (fases 6 e 8). `PublicSession` só é exercitada em testes até o endpoint público de slots (fase 3).
- Vincular ou trocar o recurso de um usuário já criado (hoje só na criação, em `POST /users`) junto da edição de usuários (fase 10).
- Listagens de filiais, recursos, serviços e exceções não paginam. Paginar ou limitar por período se algum tenant passar de algumas centenas de registros.
- Remover um recurso ou serviço enquanto outra requisição o referencia (vínculo, filial) pode terminar em 500 por violação de FK na corrida. Traduzir para 409 se aparecer em uso real.
- Trocar o fuso de uma filial não revisa reservas futuras. As reservas são instantes UTC e não mudam; o que muda é o horário local que o cliente vê. Definir se bloqueia a troca com reservas futuras ou avisa a recepção (fase 10).
- `services.custom_fields_schema` entra na fase 11 (ver decisões).
- Cache em Redis dos slots (ver decisão na fase 4: contador de versão por empresa). Fazer quando houver medição de carga e Redis nos testes.
- Reduzir `resources.capacity` com reservas futuras nas vagas removidas: as reservas continuam valendo, mas as vagas acima da nova capacidade deixam de contar no motor. Avisar ou bloquear na edição (fase 10).
- Rota para o dono editar `settings["slots"]` (antecedência mínima e máxima) junto de "editar empresa" (fase 10).
- Não há rota pública para listar serviços, recursos e filiais da empresa; entra com a página de agendamento (fase 7).
- Reserva pública sem cancelamento pelo cliente: não há token nem link para ele cancelar ou remarcar (fase 8). A resposta de criação ainda não devolve segredo algum.
- A rota pública de criação não tem limite de taxa nem proteção contra abuso (reservas falsas); entra com o endurecimento (fase 14).
- Cliente identificado só pelo telefone, sem verificação: quem digita um número alheio cria reservas no nome dele. Confirmação por código ou link entra com as notificações (fase 5).
- Reservas feitas pelo painel (recepção marcando para o cliente, encaixes) ainda não existem; só a rota pública cria.
- `GET /bookings` não pagina. Limitar por período obrigatório quando houver volume (fase 7 ou 10).
- Vagas de recursos com capacidade alta (centenas) são tentadas no máximo 5 por reserva em caso de corrida; em disputa extrema o cliente recebe 409 mesmo havendo vaga.
