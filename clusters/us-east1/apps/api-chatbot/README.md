# Chatbot interno e worker de resumos

Preencha a imagem ARM64 por digest em `deployment.yaml` e os IDs em
`bitwarden-secret.yaml` antes de provisionar. A imagem deve iniciar a API
FastAPI (`src.main:app`) em `0.0.0.0:8000`, incluindo suas dependências.
O bootstrap recusa placeholders e instala o token Bitwarden neste namespace.
Os valores dos secrets não são escritos no Git nem no estado Terraform.

Os nomes de ambiente correspondem ao contrato atual de `AI_Multi-Agent`:
OpenAI/Gemini/Groq/Hugging Face, JWT, PostgreSQL somente leitura, MongoDB,
Qdrant e Redis. A imagem v0.2.0 usa OpenAI para resumos/títulos e Gemini para
embeddings. Preencha `REPLACE_WITH_CHATBOT_OPENAI_API_KEY_SECRET_ID` com o ID
do secret `OPENAI_API_KEY` no Bitwarden antes de integrar/aplicar: o bootstrap
recusa o placeholder e aguarda essa chave na sincronização do Secret. Nunca
coloque o valor da chave no manifest. O machine account precisa acessar esse ID.
MongoDB, Qdrant e PostgreSQL permanecem externos ao ciclo de recriação do
cluster. `redis-temp.yaml` fornece o Redis temporário já usado no laboratório;
ele não tem persistência. API e worker devem usar o mesmo `REDIS_URL`.

O Deployment `api-chatbot` executa dois containers com a mesma imagem ARM64:
`api-chatbot` inicia Uvicorn, e `summary-worker` inicia
`python -m src.memory.worker.run_summary_worker`. O segundo consome Redis
Streams, publica a outbox MongoDB, reconcilia jobs e gera/indexa os resumos no
Qdrant. Os dois recebem o mesmo Secret `chatbot-external`, incluindo a chave
OpenAI ausente no mapeamento anterior. O worker não precisa de Service ou porta
HTTP. As publicações do chatbot devem atualizar os dois digests juntos.

O worker acrescenta request de 100m CPU/512Mi memória e limite de 1 CPU/1Gi.
Compartilha a réplica e o ciclo de vida do Pod com a API. Durante RollingUpdate
podem existir dois workers: IDs únicos de consumidor e leases do serviço
coordenam os jobs; não se presume execução exatamente uma vez. SIGTERM é
entregue diretamente ao Python; jobs interrompidos são retomados pelos leases.

O worker não fornece health endpoint, portanto não recebe probes HTTP/TCP da
API. Um processo Running não prova que os jobs estão sendo concluídos. Confira
os logs e teste o encerramento de uma conversa autenticada, verificando que o
job termina e o resumo fica disponível:

```bash
kubectl rollout status deployment/api-chatbot -n api-chatbot --timeout=10m
kubectl logs -n api-chatbot deployment/api-chatbot -c summary-worker --tail=100 -f
kubectl logs -n api-chatbot deployment/api-chatbot -c api-chatbot --tail=100 -f
```

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
