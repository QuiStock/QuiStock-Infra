# Chatbot interno e worker de resumos

O Deployment usa duas imagens ARM64 da mesma revisão aprovada:
`ghcr.io/quistock/ai-multi-agent` (API na porta 8000) e
`ghcr.io/quistock/ai-multi-agent-worker` (worker sem porta HTTP).
Digests diferentes são esperados. O publisher atualiza os dois containers
por nome; a primeira troca do repositório worker exige revisão explícita.

API e worker compartilham `chatbot-config` e `chatbot-external`.
OpenAI fornece chat, resumos e títulos; Gemini fornece embeddings.
Groq e Hugging Face não são mais requisitos de bootstrap. A API valida o
JWT RS256 encaminhado pela Core usando o JWKS interno da Auth, issuer,
audience e expiração. A chave privada RSA da Auth não é enviada à IA.
`AUTH_BYPASS_LOCAL_TESTS=false` permanece explícito em produção.

MongoDB, PostgreSQL e Qdrant são externos ao ciclo de vida do cluster.
PostgreSQL usa credencial própria somente leitura. IA usa `MONGODB_DB`;
Auth usa `MONGODB_DATABASE`. Os valores dos secrets não ficam no Git/state.

O Redis temporário tem probes, mas não persistência. O valor existente de
`REDIS_URL` é preservado; para usar o Redis interno, configure
`redis://redis.api-chatbot.svc.cluster.local:6379/0` no Bitwarden.
API e worker precisam compartilhar Redis, MongoDB e nomes das coleções.
Jobs/outbox duráveis ficam no MongoDB. Relay e reconciliação já executam
no worker; não criar um CronJob duplicado.

O worker compartilha escala e ciclo de vida do Pod da API. Durante rollout
podem existir dois workers: IDs de consumidor e leases coordenam os jobs,
sem garantia de execução exatamente uma vez. Ele não tem probe HTTP.
Running não comprova progresso: conferir logs, backlog e resumo concluído.

```bash
kubectl rollout status deployment/api-chatbot -n api-chatbot --timeout=10m
kubectl logs -n api-chatbot deployment/api-chatbot -c summary-worker --tail=100
kubectl logs -n api-chatbot deployment/api-chatbot -c api-chatbot --tail=100
```

`/health` é readiness para SQL, MongoDB, Redis, Qdrant, Gemini e OpenAI.
Startup/liveness usam TCP para não reiniciar por falha de dependências.
O Service é ClusterIP; Core recebe
`AI_API_BASE_URL=http://api-chatbot.api-chatbot.svc.cluster.local`, sem path
de conversas. O proxy público encaminha `/api/chat` à Core e não expõe
IA/observabilidade diretamente.

Coleções/índices exigem provisionamento avulso e dimensão de embedding
verificada. Use `lab.py memory` primeiro sem `--apply`. Não executar apply
indiscriminadamente sobre dados existentes; esse comando não ingere FAQ.
Consulte o [runbook](../../../../docs/learner-lab-atualizacao-runtime.md).

## Runtime atual e Observe

A API usa `PORT=8000`. O frontend Observe é uma aplicação separada em `/observe/`; o proxy mantém o prefixo nativo `/api/v1/observability` para preservar o cookie. O bootstrap injeta a origem HTTPS atual e os dois itens adicionais de Secrets Manager pelos UUIDs da configuração local. O worker não recebe esses dois segredos.

Os Jobs operacionais usam `python -m src.ops.memory` e `python -m src.ops.faq`, com check por padrão e apply explícito. Veja [teste atômico](../../../../docs/teste-aws-passo-a-passo.md).
