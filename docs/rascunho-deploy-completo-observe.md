# Rascunho do teste completo na AWS, com QuiStock Observe

> Para o teste atual antes do merge, siga [o roteiro atômico](teste-aws-passo-a-passo.md). Este documento registra a preparação anterior.

Estado revisado em 01/11/2026 pelo plugin GitHub. Este documento é um plano de preparação e aceite: não executa deploy, migrações ou acesso aos bancos externos. A execução dos comandos AWS abaixo depende de concluir a preparação descrita aqui.

## Revisões que fundamentam o plano

| Projeto | Main examinada |
|---|---|
| AI_Multi-Agent | `31af7716c92eeb33e55ef04d24693e497f1af08d` |
| DS_Auth | `966451d746964d9e0b589935989044c5f6057869` |
| DS_Backend | `98b7be8470354ec44677ddf340fee6c731954151` |
| quistock-dad | `493e78bdfbaec574bf3935e724120db9213260d4` |
| Mobile | `47de98976946176bc62e3477f90596bb3b19c5b4` |
| QuiStock-Infra | `13832a08a9cff16cdd1b1835aff65475888cbecd` |

A [PR Infra #40](https://github.com/QuiStock/QuiStock-Infra/pull/40) continua aberta, com head `9bee274d4e2733001b7c961c98e913828c25842f`. Seus digests e bootstrap representam a entrega anterior e precisam ser atualizados. Os checks disponíveis nas revisões examinadas de AI, Auth, Core e website estão concluídos com sucesso; isso não comprova as seis imagens atuais nem funcionamento com os serviços externos.

## Correções confirmadas no Observe

- Backend implementa login/logout, sessão HS256 própria com validade de uma hora e cookie HttpOnly/Secure em produção. Conversas de negócio continuam usando RS256/JWKS; os dois segredos são independentes.
- Todas as rotas operacionais de observabilidade, inclusive laboratório, exigem a sessão própria. Login consulta `public.super_admin`, valida hash BCrypt e trata falhas sem devolver detalhes do banco.
- Frontend envia `credentials: include`; aceita configuração de API no build. CORS permite uma origem configurada e rejeita escritas com Origin diferente.
- TypeSafe passou a integrar `/health`, por consulta de modelos, além de OpenAI, Gemini, PostgreSQL, MongoDB, Redis e Qdrant.
- Mobile passou a usar a Core autenticada para chat, histórico e encerramento. As URLs de configuração ainda apontam para Render.

Fontes: [sessão](https://github.com/QuiStock/AI_Multi-Agent/blob/31af7716c92eeb33e55ef04d24693e497f1af08d/src/auth/observability_session.py), [rotas](https://github.com/QuiStock/AI_Multi-Agent/blob/31af7716c92eeb33e55ef04d24693e497f1af08d/src/api/routes/observability.py), [CORS](https://github.com/QuiStock/AI_Multi-Agent/blob/31af7716c92eeb33e55ef04d24693e497f1af08d/src/api/observability_cors.py), [frontend](https://github.com/QuiStock/AI_Multi-Agent/blob/31af7716c92eeb33e55ef04d24693e497f1af08d/src/observability/front-observer/src/main.js).

## Preparação necessária antes de gastar recursos AWS

### 1. Imagens e publicação

Atualizar as branches de revisão sobre as mains fixadas, preservando o build do website com `AUTH_API_URL=/auth` e `CORE_API_URL=/api`. A main do website ainda não incorporou essa correção.

Criar a imagem estática ARM64 do Observe, usando o projeto Vite existente. Restaurar a publicação coordenada de API/worker IA e adicionar o frontend: o publisher atual da AI só publica a imagem da API. Validar arquitetura, imports/startup, revisão OCI e acesso ao GHCR para cada digest. Publicar seis imagens de aplicação: Auth, Core, website, IA API, worker e Observe. Atualizar os manifests na branch de teste, sem merge em main.

A API IA mudou o padrão de porta para 10000. Para preservar o contrato Kubernetes atual, definir explicitamente `PORT=8000` no container da API e testar startup/readiness/Service com essa porta. O worker mantém seu comando Python e não precisa de porta HTTP.

Fontes: [Dockerfile API](https://github.com/QuiStock/AI_Multi-Agent/blob/31af7716c92eeb33e55ef04d24693e497f1af08d/Dockerfile.api), [publisher](https://github.com/QuiStock/AI_Multi-Agent/blob/31af7716c92eeb33e55ef04d24693e497f1af08d/.github/workflows/publish-image.yaml).

### 2. Topologia e contrato de cookies

Reaproveitar API Gateway, VPC Link, NLB e Nginx existentes. Acrescentar Deployment/Service ClusterIP/Application Argo do Observe; o frontend não recebe secrets. O worker continua junto da API IA no Deployment atual.

| Caminho público proposto | Encaminhamento |
|---|---|
| `/` | Website |
| `/auth/...` | Auth, removendo `/auth` |
| `/api/...` | Core, removendo `/api` |
| `/observe/` | Interface Observe e assets compilados com base `/observe/` |
| `/api/v1/observability/...` | IA, preservando o path completo; regra anterior à regra genérica `/api/` |

O cookie atual tem Path fixo `/api/v1/observability`. Manter a API pública nesse caminho evita perda do cookie no browser. A proposta anterior `/observe/api/v1/observability` exigiria reescrita/configuração do Path do cookie e não será adotada neste teste. A configuração do frontend será `VITE_API_BASE_URL=/api/v1`.

Configurar `OBSERVABILITY_FRONTEND_ORIGIN` com a origem HTTPS real gerada para a nova conta. O bootstrap deverá gerar essa configuração para a API IA, além dos ConfigMaps Auth/Core. Mesmo usando a mesma origem, o valor precisa estar correto: o middleware recusa POST com Origin diferente.

Preservar Cookie, Set-Cookie, Origin e Content-Type no proxy, sem cache nas respostas de sessão/dados. Confirmar que `/api/v1/conversations/...` não passou a ser publicado diretamente por engano.

### 3. Secrets e preparação de dados externos

| Item | Ação |
|---|---|
| `OBSERVABILITY_SESSION_SECRET` | Criar segredo aleatório próprio, no mínimo 32 caracteres, entregue à API IA; não reutilizar a chave RSA ou segredo de conversa |
| `OBSERVABILITY_FRONTEND_ORIGIN` | Gerar a partir do endpoint HTTPS da nova conta, sem path |
| `TYPESAFE_API_KEY` | Mapear no Bitwarden e verificar acesso ao modelo configurado |
| `TYPESAFE_API_BASE_URL`, `TYPESAFE_JEV_MODEL`, `TYPESAFE_JEV_TIMEOUT_SECONDS` | Tornar explícitos na configuração operacional |
| PostgreSQL IA | Confirmar SELECT nas tabelas consultadas pelo domínio e em `public.super_admin`; manter credencial somente leitura |
| Conta Observe | Confirmar uma conta operacional em `public.super_admin`, email sem duplicidade normalizada e senha em BCrypt |
| Contas de negócio | Confirmar roles e vínculos de loja compatíveis com a autenticação atual da IA |
| MongoDB/Qdrant/Redis | Conferir conectividade, índices, coleções, dimensão dos vetores e recuperação de jobs |

Nenhuma das migrações Core V1–V7 examinadas cria `super_admin`. Sua existência e provisionamento precisam ser verificados no banco externo antes do teste; não serão presumidos nem feitos automaticamente pelo login. Não consultar ou imprimir hashes/senhas em logs de diagnóstico.

A AWS será criada do zero; PostgreSQL, MongoDB, Qdrant e Bitwarden permanecem externos, conforme a arquitetura atual. Preparar dados isolados/backup antes de permitir as migrações Flyway no startup da nova Core.

### 4. Memória, scheduler e bootstrap

- Substituir o comando `scripts.provision_memory_collections` do bootstrap: o módulo foi removido da AI. Há também entrypoints antigos de ingestão/reconciliação apontando para scripts removidos. Restaurar uma CLI operacional mantida e incluída na imagem, com modo check separado de apply e ingestão de FAQ verificável.
- Definir `ANALYSIS_SCHEDULE_ENABLED=false` inicialmente, junto de ERP desligado, enquanto o Lab não tiver snapshot comercial preparado. O scheduler diário já existe na Core às 08:00 America/Sao_Paulo; seu teste será separado, sem criar CronJob duplicado.
- Acrescentar Observe a bootstrap, espera de Applications/rollout, verificação pública e desligamento. Manter state/kubeconfig isolados por conta e suporte a `infra_ref` da branch de revisão.
- Revisar orçamento de probes com os novos timeouts e a sétima dependência TypeSafe. Readiness depende de serviços externos; liveness deve continuar independente deles.
- Manter uma réplica/processo da API IA no primeiro teste. O feed ao vivo é local ao processo; traces definitivos ficam no MongoDB. Medir capacidade e surge antes de aumentar réplicas ou nodes.

## Roteiro de execução depois da preparação

1. Iniciar Learner Lab, configurar credenciais temporárias e confirmar conta/roles. Preencher Kubernetes/addons compatíveis e `infra_ref=codex/learner-lab-runtime-update` no JSON local.
2. Executar gates locais/CI: Terraform validate/test, manifests/Kustomize, seis builds ARM64, teste real do proxy e testes de cookies/autenticação do Observe pelo caminho público proposto. Confirmar ausência de URLs Render/localhost nos bundles destinados à AWS.
3. Executar preflight e plano. O `up` sem `--apply` já cria/configura o bucket de state; a criação do restante exige `--apply`.
4. Aplicar e deixar bootstrap aguardar nodes, Argo, Bitwarden, secrets, aplicações e targets saudáveis. Registrar URLs e revisões implantadas.
5. Conferir/preparar índices e coleções com a CLI de memória corrigida. Reindexar FAQ quando necessário, sem aplicar indiscriminadamente sobre dados existentes.
6. Executar a matriz de aceite abaixo, guardando request/conversation/trace IDs, horários e resultados, sem credenciais ou conteúdo sensível.
7. Executar desligamento após o teste e conferir recursos residuais; preservar state e bancos externos.

Comandos previstos, executáveis somente depois das correções de Infra/publicação:

```powershell
$labAccount = "ID_DA_CONTA_NOVA"
python scripts/learner-lab/lab.py preflight --config .learner-lab/nova-conta.json --account $labAccount
python scripts/learner-lab/lab.py up --config .learner-lab/nova-conta.json --account $labAccount
# Revisar o plano antes da aplicação.
python scripts/learner-lab/lab.py up --config .learner-lab/nova-conta.json --account $labAccount --apply
python scripts/learner-lab/lab.py verify --config .learner-lab/nova-conta.json --account $labAccount
# Ao terminar, este comando remove os recursos gerenciados da conta alvo:
python scripts/learner-lab/lab.py down --config .learner-lab/nova-conta.json --account $labAccount --confirm-destroy $labAccount
```

## Matriz de aceite

| Área | Resultado esperado |
|---|---|
| Infra vazia | State isolado; nodes ARM64 Ready; Argo e cinco Applications saudáveis; seis imagens de aplicação nas revisões fixadas |
| Roteamento | SPA/Observe/assets carregam; Auth/Core/Observe API chegam aos serviços corretos, sem fallback HTML indevido |
| Login de negócio | Login e refresh retornam token e cookies; leitura/escrita autorizadas funcionam; logout limpa sessão |
| Chat web/API | Core encaminha JWT RS256, retorna resposta, permite histórico/encerramento; usuário sem escopo é recusado |
| Mobile | Build de teste aponta para Auth/Core AWS; chat, histórico, encerramento e recuperação de sessão funcionam |
| Observe anônimo | Dados e laboratório retornam 401 com configuração válida; credenciais erradas são recusadas |
| Observe autorizado | Login super_admin emite cookie no Path público correto; métricas/traces/conversas/laboratório funcionam; expiração e logout limpam acesso no browser |
| CORS | Origem configurada funciona; POST de origem diferente é recusado; as duas sessões de negócio/Observe permanecem independentes |
| Correlação | Um chat real aparece no feed e no trace persistido; métricas/tokens/JEV correspondem às chamadas realizadas, com incompletude sinalizada quando faltar uso |
| Worker/memória | Encerramento gera resumo/título; restart de worker/Redis recupera jobs conforme o contrato; histórico durável permanece acessível |
| Scheduler | Após preparar ERP/dados, habilitar e validar execução diária/coordenação separadamente; teste inicial permanece desligado |
| Encerramento | Recursos AWS gerenciados removidos; bucket de state preservado; bancos externos intactos |

Nesta revisão não houve testes de execução novos, login real, consulta aos bancos, publicação de imagens ou comandos AWS. As evidências novas são leitura de código remoto e status dos checks de CI.
