# Atualizações de infraestrutura após mudanças nas aplicações

Investigação em 30/10/2026, pelo plugin GitHub, das branches `main` remotas. Este documento mapeia alterações; nenhum manifesto, segredo ou recurso de nuvem foi aplicado.

## Base e limites da análise

| Repositório | Commit da main consultada | Papel |
|---|---|---|
| [QuiStock-Infra](https://github.com/QuiStock/QuiStock-Infra/commit/13832a08a9cff16cdd1b1835aff65475888cbecd) | `13832a08a9cff16cdd1b1835aff65475888cbecd` | Estado desejado remoto |
| [DS_Auth](https://github.com/QuiStock/DS_Auth/commit/8b9b52f2053a38f132caa415f7d48c1166ef6623) | `8b9b52f2053a38f132caa415f7d48c1166ef6623` | Login, sessão e JWKS |
| [DS_Backend](https://github.com/QuiStock/DS_Backend/commit/edecdcfa40966326903c003ffdbc8de286aa2d4c) | `edecdcfa40966326903c003ffdbc8de286aa2d4c` | Core, ERP, migrações e proxy de chat |
| [AI_Multi-Agent](https://github.com/QuiStock/AI_Multi-Agent/commit/7f33892e0eb8fe1abe21418ddfd1376ff546df13) | `7f33892e0eb8fe1abe21418ddfd1376ff546df13` | API IA e worker |
| [quistock-dad](https://github.com/QuiStock/quistock-dad/commit/8d6a5f656f6d1085795626a9ccaceba2ce3fd3e7) | `8d6a5f656f6d1085795626a9ccaceba2ce3fd3e7` | Website que publica `web-frontend` |
| [Mobile](https://github.com/QuiStock/Mobile/commit/69a6c5a209b0534f711692f6a8ba3b0f24487ff4) | `69a6c5a209b0534f711692f6a8ba3b0f24487ff4` | Consumidor das APIs |

O checkout local está em `9bcb8679820f6c6032d9acf7a4f4a6be8d7fb0e0`. A comparação dos blobs rastreados com a árvore remota identificou diferença apenas em `clusters/us-east1/apps/api-auth/deployment.yaml`: a main remota já aponta Auth para `sha256:ba08e13890945e1236e125ab1375807c147de0ec58e1f4c973966f828a2e05a6`. Usar a main remota como base de implementação, para não reverter essa atualização.

O inventário da organização também inclui repositórios legados, landing page e dados. Nenhum novo serviço desses repositórios foi identificado nos manifests das quatro aplicações ou nos workflows de publicação examinados. `front-primeiro-landing` teve sua árvore consultada; não é o publicador da imagem do website. O escopo detalhado é o conjunto implantado acima, mais Mobile como consumidor.

Evidência é estática: código e configuração versionados. Não foram consultados valores no Bitwarden, estado do cluster, banco, pacotes GHCR ou execuções de produção. A main do código não prova qual commit gerou um digest já implantado. Não houve teste funcional ou deploy.

## Bloqueios antes de promover as novas imagens

| Prioridade | Problema comprovado | Atualização necessária | Arquivos / responsáveis |
|---|---|---|---|
| P0 | Nginx encaminha `/auth/login` como `/auth/login`; Auth atual atende `/login`, `/refresh`, `/logout` e `/csrf` na raiz | Remover `/auth` no proxy de todas as rotas Auth, preservando método, corpo e query. Manter os aliases de health/JWKS. Promover imagem e roteamento juntos | Infra: `clusters/us-east1/apps/website/nginx.conf`; testes Nginx |
| P0 | Website lê `AUTH_API_URL` e `CORE_API_URL`, com fallback para localhost; Dockerfile/workflow ainda fornecem apenas `VITE_API_URL=/api` | Adicionar ARG/ENV de build e build-args `AUTH_API_URL=/auth`, `CORE_API_URL=/api`; reconstruir website e promover o digest | quistock-dad: `Dockerfile`, `.github/workflows/publish-image.yaml`; Infra: deployment website |
| P0 | Core não recebe `AI_API_BASE_URL`; o código retorna `503 AI_NOT_CONFIGURED` com URL vazia | Definir `AI_API_BASE_URL=http://api-chatbot.api-chatbot.svc.cluster.local`, sem `/api/v1/conversations` | Infra: deployment api-core |
| P0 | Core encaminha o JWT validado de acesso para IA; Auth/Core usam RS256, IA aceita somente HS256 | Alinhar o contrato de autenticação antes de liberar chat. Preferência técnica: IA validar RS256 pelo JWKS da Auth, issuer, audience e expiração; alternativamente projetar token interno específico no Core. Requer código e testes entre serviços | AI_Multi-Agent e eventualmente DS_Backend; depois configurar as novas envs acordadas no Infra |
| P0 | `JWT_SECRET` do chatbot está mapeado para o mesmo ID Bitwarden da chave privada RSA da Auth | Remover esse compartilhamento na migração do contrato. Uma chave privada Base64 não converte token RS256 em HS256. Se token interno HMAC for escolhido, usar segredo aleatório próprio e restrito aos participantes | Infra: bitwarden-secret chatbot; provisionamento Bitwarden; código emissor/validador |
| P0 | Gateway aceita `x-csrf-token`, mas Core usa `X-XSRF-TOKEN`; Nginx apaga `Origin` e CORS permite qualquer origem HTTP(S) com cookies | Incluir ambos os headers CSRF; definir origens exatas autorizadas, preservar Origin e configurar `CORS_ALLOWED_ORIGINS` em Auth/Core. Validar o caminho completo com cookies | `terraform/eks/gateway.tf`, nginx.conf e deployments Auth/Core |

Fontes: [AuthController](https://github.com/QuiStock/DS_Auth/blob/8b9b52f2053a38f132caa415f7d48c1166ef6623/src/main/java/com/quistock/auth/controller/AuthController.java), [proxy Infra](https://github.com/QuiStock/QuiStock-Infra/blob/13832a08a9cff16cdd1b1835aff65475888cbecd/clusters/us-east1/apps/website/nginx.conf), [cliente Auth website](https://github.com/QuiStock/quistock-dad/blob/8d6a5f656f6d1085795626a9ccaceba2ce3fd3e7/src/services/api-auth.ts), [cliente Core website](https://github.com/QuiStock/quistock-dad/blob/8d6a5f656f6d1085795626a9ccaceba2ce3fd3e7/src/services/api-client.ts), [build website](https://github.com/QuiStock/quistock-dad/blob/8d6a5f656f6d1085795626a9ccaceba2ce3fd3e7/Dockerfile), [ChatController](https://github.com/QuiStock/DS_Backend/blob/edecdcfa40966326903c003ffdbc8de286aa2d4c/src/main/java/com/quistock/ds_backend/controller/ChatController.java), [ChatService](https://github.com/QuiStock/DS_Backend/blob/edecdcfa40966326903c003ffdbc8de286aa2d4c/src/main/java/com/quistock/ds_backend/service/ChatService.java), [validador JWT IA](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/src/auth/token.py).

Há contradições no README Auth sobre rotas antigas; o controller foi usado como evidência primária. Não basta confiar em health: as exceções atuais de health/JWKS no proxy podem passar enquanto login está quebrado. Env em um Pod Nginx não reconfigura um bundle Vite já compilado.

## Matriz de configuração

| Serviço | Configuração proposta / validação | Natureza |
|---|---|---|
| Core | `AI_API_BASE_URL=http://api-chatbot.api-chatbot.svc.cluster.local` | Nova configuração necessária para chat |
| Core | `AI_CONNECT_TIMEOUT_MS=5000`; definir `AI_READ_TIMEOUT_MS` abaixo do orçamento externo efetivo | Ajuste necessário: default de leitura é 60000 ms, gateway e Nginx são 30000 ms |
| Core/Auth | `CORS_ALLOWED_ORIGINS=<origens HTTPS exatas aprovadas>` | Configuração pública; coordenar com gateway e preservação de Origin |
| Core | `COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true`; `CSRF_COOKIE_SAME_SITE=Lax` para mesmo site, ou `None` quando houver acesso cross-site autorizado | Defaults seguros já existem; explicitar conforme topologia |
| Auth | `AUTH_COOKIE_SECURE=true`, `AUTH_COOKIE_PATH=/`; SameSite coerente com a topologia | Secure/Path já presentes. Path `/` é necessário para cookie de acesso alcançar Core |
| Auth | `AUTH_TRUSTED_PROXY_CIDRS=<redes reais dos proxies confiáveis>` | Opcional, mas necessário para rate limit por IP de cliente atrás do proxy; validar cadeia X-Forwarded-For antes |
| Auth | `AUTH_JWT_PREVIOUS_PUBLIC_KEYS` | Opcional para rotação de chave; verificar formato no serviço antes de mapear |
| Core/Auth | `DB_POOL_MAX_SIZE=3`, `DB_POOL_MIN_IDLE=0` | Nomes suportados atuais; overrides Spring já existentes continuam válidos, não são bloqueio |
| Core | `RUN_MIGRATIONS=true` por padrão | Tornar a estratégia explícita; desabilitar na aplicação somente após criar um executor separado |
| Core | `ERP_SYNC_ENABLED=false`, `HEALTH_ERP_REQUIRED=false` | Já configurados para ambiente sem ERP; manter enquanto essa premissa for válida |
| Core | Se habilitar ERP: `ERP_API_BASE_URL`, `ERP_API_PRODUCTS_PATH=/products`, `ERP_SYNC_FIXED_DELAY_MS=900000`, `ERP_SYNC_INITIAL_DELAY_MS=1000` e readiness correspondente | Condicional; URL vazia é incompatível com sync habilitado |
| IA API e worker | Manter `APP_ENVIRONMENT=production`, `AUTH_BYPASS_LOCAL_TESTS=false` | Já presentes, não são envs novas |
| IA API e worker | `OPENAI_MODEL`, `GEMINI_EMBEDDING_MODEL`, `GEMINI_EMBEDDING_TIER` | Fixar configuração operacional coerente com acesso e quota dos provedores. Defaults da main: `gpt-6-luna`, `gemini-embedding-2`, `free`; disponibilidade não foi testada |
| IA API e worker | `SUMMARY_QUEUE_STREAM=quistock:conversation-summary`, `SUMMARY_QUEUE_GROUP=summary-workers`, `SUMMARY_JOB_MAX_ATTEMPTS=5`, `SUMMARY_RECONCILIATION_INTERVAL_SECONDS=60` | Opcionais com defaults; explicitar em configuração compartilhada para evitar divergência |
| IA API e worker | `MEMORY_CONVERSATIONS_COLLECTION=conversations`, `MEMORY_SUMMARY_JOBS_COLLECTION=conversation_summary_jobs`, `MEMORY_SUMMARY_LOCKS_COLLECTION=conversation_summary_locks`, `MEMORY_SUMMARY_COLLECTION=conversation_summaries` | Opcionais; definir a mesma convenção em API, worker e provisionamento; não renomear coleções existentes sem migração |
| IA | `FAQ_VECTORSTORE_COLLECTION=faq_v2`, paths `FAQ_*`, parâmetros de recuperação e `HEALTH_PROBE_TIMEOUT_SECONDS` | Opcionais; só alterar com necessidade de ingestão/qualidade/timeout identificada |
| Website | `AUTH_API_URL=/auth`, `CORE_API_URL=/api` | Variáveis públicas de build; não são secrets nem runtime envs Kubernetes |

Fontes: [config Core](https://github.com/QuiStock/DS_Backend/blob/edecdcfa40966326903c003ffdbc8de286aa2d4c/src/main/resources/application.properties), [config Auth](https://github.com/QuiStock/DS_Auth/blob/8b9b52f2053a38f132caa415f7d48c1166ef6623/src/main/resources/application.properties), [Settings IA](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/src/config.py).

Os nomes opcionais acima não são novos secrets obrigatórios. Configuração não sensível pode ficar em ConfigMap/env. Os valores existentes no Bitwarden não foram lidos: a presença de um ID no YAML não comprova valor, conectividade, permissões ou modelo correto.

### Secrets e dependências

- IA ainda requer `OPENAI_API_KEY` e `GEMINI_API_KEY`: OpenAI executa chat/resumos/títulos, Gemini executa embeddings. `GROQ_API_KEY` e `HF_TOKEN` são aceitos apenas por compatibilidade e não usados em runtime; remover os mappings depois de promover as imagens que já dispensam esses provedores. Isso também evita o bootstrap exigir secrets obsoletos.
- Manter `POSTGRES_DSN` com credencial própria somente leitura para IA e `DB_USERNAME` de Auth com permissões mínimas de leitura. Core precisa das permissões de escrita e, se usar Flyway no startup, DDL compatível com as migrações.
- Validar `MONGODB_URI`/`MONGODB_DATABASE` de Auth em replica set com transações. IA usa outro nome de variável para banco: `MONGODB_DB`; preservar essa diferença.
- API/worker IA precisam do mesmo MongoDB, coleções, Qdrant e Redis. Conferir `REDIS_URL`: se o Redis temporário for mantido, o endereço interno é `redis://redis.api-chatbot.svc.cluster.local:6379/0`; não substituir um Redis externo sem verificar o destino atual.
- `OPENAI_MODEL` está hoje no Secret; pode migrar para configuração não sensível quando for oportuno. Não é necessário criar novos IDs Bitwarden para parâmetros públicos.

## Novos processos, imagens e dados

### Worker e pipeline de imagens — P1

A main publica duas imagens ARM64: `ghcr.io/quistock/ai-multi-agent` e `ghcr.io/quistock/ai-multi-agent-worker`. Infra ainda aponta o container `summary-worker` para o repositório da API. Atualizar o repositório da imagem do worker e seu digest real, obtido no workflow de publicação. Digests diferentes entre API/worker são esperados; o critério é terem sido construídos a partir da mesma revisão aprovada, cada um com seu Dockerfile. Não reutilizar o digest da API no repositório worker.

O command atual do worker continua válido (`python -m src.memory.worker.run_summary_worker`); pode usar o CMD da imagem específica. O worker atual já inclui consumidor Redis, relay da outbox MongoDB e reconciliação periódica em threads. Não criar CronJob duplicado para esses loops.

Manter os containers no mesmo Deployment é compatível com o publisher atual. Separar o worker em Deployment próprio é uma melhoria opcional para escala, rollout e observabilidade independentes; exige adaptar publisher, política de automerge e bootstrap. Monitorar progresso, falhas/retries e atraso de jobs: o worker não tem endpoint HTTP de saúde e a readiness da API não comprova consumo de fila.

A política `.github/scripts/image_update_automerge.py` rejeita mudança do nome do repositório da imagem. A primeira troca para `ai-multi-agent-worker` precisa de revisão/merge manual da PR concreta; atualizações posteriores apenas de digest continuam no fluxo vigente. Não enfraquecer a política para contornar a migração.

Fontes: [publisher IA](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/.github/workflows/publish-image.yaml), [worker](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/src/memory/worker/run_summary_worker.py), [deployment remoto](https://github.com/QuiStock/QuiStock-Infra/blob/13832a08a9cff16cdd1b1835aff65475888cbecd/clusters/us-east1/apps/api-chatbot/deployment.yaml).

### Memória, embeddings e Redis — P1

Adicionar procedimento de provisionamento versionado usando `python -m scripts.provision_memory_collections --check --vector-size <dimensão-validada>`, seguido de uma execução controlada de `--apply` para coleções novas/vazias. O script exige dimensão explícita, cria índices MongoDB, índices de payload Qdrant e índices de jobs; recusa apply em coleções com documentos/pontos. Não rodar um Job de apply indiscriminadamente em cada sync do Argo. Dados existentes exigem migração própria e backup.

Validar compatibilidade da dimensão/modelo dos vetores existentes antes de trocar o embedding Gemini e planejar reindexação do FAQ/memória quando necessário. A existência do endpoint Qdrant não comprova índices ou coleção compatíveis. API/worker executam sem root; qualquer processo de ingestão que grave em `FAQ_*` precisa de diretório gravável e política clara de persistência ou ingestão fora do runtime.

Redis temporário não tem PVC/AOF nem probes. Para ambiente que exija durabilidade, escolher Redis gerenciado ou StatefulSet com persistência, recuperação e monitoramento. MongoDB mantém jobs/outbox e há reconciliação, portanto perda do Redis não significa automaticamente perda definitiva dos resumos; validar replay/recuperação. Se permanecer temporário, documentar essa condição e testar restart durante processamento.

Fontes: [provisionamento](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/scripts/provision_memory_collections.py), [worker/reconciliação](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/src/memory/worker/run_summary_worker.py).

### Core, banco e ERP — P1

A main contém migrações Flyway V1–V7, com projeções ERP, gestão de usuários, roles canônicas e análise de vendas. Antes de promover a imagem, inspecionar `flyway_schema_history`, backup, permissões e compatibilidade dos dados. `baseline-on-migrate=true` com baseline 1 não prova que um schema preexistente corresponde ao V1. Preferir migração controlada antes do rollout; se ela continuar no startup, testar concorrência/tempo de startup e orçamento das probes.

Não adicionar processo ERP separado por suposição: a configuração atual controla o sincronizador do próprio Core. Se houver mais réplicas, verificar coordenação do scheduler e orçamento total de conexões antes de escalar. As novas capacidades não provam necessidade de aumentar nodes; medir recursos e reservar capacidade para surge dos rollouts (o Pod IA pede atualmente 1 GiB somando API e worker).

### Rede, cookies, timeout e documentação — P1

- Definir orçamento de latência do chat abaixo dos 30 segundos atuais do gateway: timeout de conexão, leitura, processamento e margem de resposta. Apenas aumentar Nginx para 60 segundos não resolve o limite externo. Se o produto exigir mais tempo, avaliar outra arquitetura de entrada ou processamento assíncrono.
- Preservar o JWKS interno já correto e issuer/audience iguais em Auth/Core. Não mudar issuer para o DNS Kubernetes durante a migração. Auth exige issuer HTTPS fora de loopback.
- Para frontend cross-site, alinhar também SameSite do CSRF Core; cookies Auth já usam `None`/Secure no Infra. Para mesmo site, escolher política coerente e testar os dois pares CSRF: Auth `AUTH-XSRF-TOKEN`/`X-CSRF-TOKEN`; Core `XSRF-TOKEN`/`X-XSRF-TOKEN`.
- Swagger/OpenAPI está na raiz de cada API. Mapear os prefixos públicos `/auth/...` e `/api/...` e alinhar forwarded prefix/contexto se a documentação for exposta. Testar assets, redirects e URLs geradas; não há env obrigatória nova para ligar Swagger.
- Readiness Auth `/health` depende de SQL e Mongo transacional; o timeout Kubernetes atual é implicitamente 1 segundo, inferior a `HEALTH_TIMEOUT_MS=4000`. Core também tem readiness com timeout implícito de 1 segundo. Ajustar após medir, com margem acima do orçamento interno. Preservar liveness independente de serviços externos.
- IA `/health` verifica PostgreSQL, MongoDB, Redis, Qdrant, Gemini e OpenAI, inclusive listagem de modelos. Revisar frequência, quotas, egress e timeout de readiness; manter TCP como liveness. Permitir rede interna Core→IA/Auth/Redis e saída aos serviços externos utilizados.

Fonte do health IA: [HealthService](https://github.com/QuiStock/AI_Multi-Agent/blob/7f33892e0eb8fe1abe21418ddfd1376ff546df13/src/api/services/health_service.py).

### Mobile — dependência de migração

O [config.xml](https://github.com/QuiStock/Mobile/blob/69a6c5a209b0534f711692f6a8ba3b0f24487ff4/app/src/main/res/values/config.xml) ainda aponta Auth/Core para Render. Migrar o cliente para os endereços públicos escolhidos com os prefixos corretos antes de retirar os serviços antigos. O [RetrofitModule](https://github.com/QuiStock/Mobile/blob/69a6c5a209b0534f711692f6a8ba3b0f24487ff4/app/src/main/java/com/quistock/quistock/app/di/RetrofitModule.kt) também mantém transporte legado do chatbot ligado à URL Auth: alinhar essa integração com o fluxo Core `/chat`, sem expor IA publicamente por conveniência. Conferir paths relativos/absolutos Retrofit antes de apenas acrescentar prefixos às URLs.

## Sequência de implementação e aceite

1. Partir da main remota de Infra; resolver contrato JWT Core→IA e corrigir build do website nos repositórios responsáveis.
2. Preparar backup/migrações SQL e coleções/índices Mongo/Qdrant; confirmar acesso, quotas, modelos e Redis. Executar check antes de qualquer apply de dados.
3. Preparar em uma mudança coordenada: rewrite Auth, URLs de build, env AI do Core, CORS/CSRF/cookies e timeout. Incluir configuração de rollback junto com as imagens anteriores.
4. Publicar API/worker ARM64 da revisão aprovada e website reconstruído. Verificar os pacotes GHCR públicos ou configurar imagePullSecrets; obter digests reais. Integrar a troca inicial do repositório worker por revisão explícita.
5. Atualizar documentação Infra: README do chatbot ainda fala em mesma imagem para dois containers; atualizar topologia, envs, ingestão, memória, recuperação e integração Core→IA.
6. Expandir os testes em `scripts/learner-lab/tests/nginx_integration.py`, `test_lab.py` e `terraform/eks/tests/gateway.tftest.hcl`. O smoke `verify_public` atual valida health/JWKS/SPA e preflight sem headers CSRF; não cobre os novos bloqueios.
7. Aceite de ambiente: login por `/auth/login`, refresh/logout com CSRF, leitura/escrita Core por cookie e Bearer, preflight com ambos os headers CSRF, origem não autorizada recusada, chat Core→IA com JWT real e política de timeout, fim da conversa gerando resumo/título, retomada/exclusão e recuperação após restart do worker/Redis. Verificar também os clientes Mobile e website compilado sem localhost.
8. Executar validação Terraform/manifests e integração Nginx; só então rollout coordenado e observação de readiness, erros, fila, recursos e migrações. Rollback de imagens/configuração não reverte automaticamente migrações de dados.

As verificações acima são critérios para a implementação futura; não foram executadas nesta investigação. O resultado entregue é o mapeamento fundamentado na main remota.
