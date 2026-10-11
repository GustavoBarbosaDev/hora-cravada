# Backlog

Itens fora do escopo da fase em que apareceram.

- Mailpit no compose entra com as notificações (fase 5).
- Limite de tentativas de login por IP e por e-mail (fase 14, endurecimento).
- CRUD de filiais e criação da filial padrão no cadastro do tenant (fase 2, junto com recursos).
- Chave estrangeira de `users.resource_id` para `resources` (fase 2).
- Edição e desativação de usuários, troca de senha e recuperação de senha (fase 10).
- Limpeza periódica de refresh tokens expirados (fase 14).
- Refresh duplicado (duas abas ou retry de rede com o mesmo token) revoga a família e desloga o usuário. Definir janela de tolerância de alguns segundos ou lock entre abas antes do frontend de login (fases 7 e 10).
- Confirmar na fase 2 que `Branch`, `Tenant.segment`, `Tenant.settings` e `PublicSession` passam a ser usados, e remover o que sobrar; `tests/concurrency` ainda só tem `.gitkeep`.
- Dockerfile roda como root e instala dependências de dev; separar imagem de produção (fase 14).
- Ao criar "editar empresa" (fase 10): a migration `0005` revogou `UPDATE` em `tenants` do `hora_app`. Conceder `UPDATE` só nas colunas necessárias, filtrar por `id = principal.tenant_id` e cobrir com teste de que outro tenant não é alterado.
