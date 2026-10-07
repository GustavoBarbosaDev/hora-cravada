# Backlog

Itens fora do escopo da fase em que apareceram.

- Mailpit no compose entra com as notificações (fase 5).
- Limite de tentativas de login por IP e por e-mail (fase 14, endurecimento).
- CRUD de filiais e criação da filial padrão no cadastro do tenant (fase 2, junto com recursos).
- Chave estrangeira de `users.resource_id` para `resources` (fase 2).
- Edição e desativação de usuários, troca de senha e recuperação de senha (fase 10).
- Limpeza periódica de refresh tokens expirados (fase 14).
- Refresh duplicado (duas abas ou retry de rede com o mesmo token) revoga a família e desloga o usuário. Definir janela de tolerância de alguns segundos ou lock entre abas antes do frontend de login (fases 7 e 10).
- `tenants` não tem RLS: o `hora_app` pode dar UPDATE em qualquer empresa. Ao criar "editar empresa" (fase 10), filtrar explicitamente por `id = principal.tenant_id` e cobrir com teste de que outro tenant não é alterado.
- Resposta 500 de exceção não tratada sai sem o header `x-request-id` (o `ServerErrorMiddleware` fica fora do middleware da aplicação); o corpo já leva o `request_id`.
- Confirmar na fase 2 que `Branch`, `Tenant.segment`, `Tenant.settings` e `PublicSession` passam a ser usados, e remover o que sobrar; `tests/concurrency` ainda só tem `.gitkeep`.
- Testes: corrida real de dois refreshes simultâneos e usuário desativado com access token ainda válido (janela de 15 minutos assumida).
- Dockerfile roda como root e instala dependências de dev; separar imagem de produção (fase 14).
