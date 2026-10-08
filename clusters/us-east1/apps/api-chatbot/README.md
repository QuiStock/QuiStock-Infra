# Chatbot interno — estrutura para preenchimento

Preencha a imagem ARM64 por digest em `deployment.yaml` e os IDs em
`bitwarden-secret.yaml` antes de provisionar. A imagem deve iniciar a API
FastAPI (`src.main:app`) em `0.0.0.0:8000`, incluindo suas dependências.
O bootstrap recusa placeholders e instala o token Bitwarden neste namespace.
Os valores dos secrets não são escritos no Git nem no estado Terraform.

Os nomes de ambiente correspondem ao contrato atual de `AI_Multi-Agent`:
Gemini/Groq/Hugging Face, JWT, PostgreSQL somente leitura, MongoDB, Qdrant e Redis.
Esses serviços de dados permanecem externos ao ciclo de recriação do cluster.
Não criamos Deployments de bancos, Redis ou workers. Funcionalidades que exigem
um worker de resumos continuam dependentes de um processo externo.

`/health` verifica dependências externas e serve apenas para readiness.
Startup/liveness usam TCP para não reiniciar a API quando um provedor estiver
indisponível. `AUTH_BYPASS_LOCAL_TESTS=false` permanece explícito.

Endereços disponíveis para a integração a ser implementada nas aplicações:

| Chamador | Destino |
| --- | --- |
| Core → chatbot | `http://api-chatbot.api-chatbot.svc.cluster.local/api/v1/...` |
| Chatbot → Core | `http://api-core.api-core.svc.cluster.local/...` |

O Service é ClusterIP e o proxy público não contém rota para o chatbot. Isso
evita publicação direta, mas não restringe quais Pods internos podem chamá-lo.

**A conectividade Kubernetes não implementa a integração de negócio.** A Core
atual responde ao chat localmente e ainda não chama esta API. O chatbot atual
valida JWT com `JWT_SECRET`, enquanto Auth/Core usam RSA/JWKS; não reutilize
uma chave RSA como segredo HMAC. Antes do teste funcional, implemente um
contrato de autenticação compatível e as chamadas HTTP nos repositórios das APIs.
