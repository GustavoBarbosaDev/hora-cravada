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
- Trocar o fuso de uma filial não revisa reservas futuras; tratar na fase 4, quando existirem reservas.
- `services.custom_fields_schema` entra na fase 11 (ver decisões).
