# Teste em uma nova conta do Learner Lab

> Para o teste atual antes do merge, siga [o roteiro atômico](teste-aws-passo-a-passo.md). Este documento registra a preparação anterior.

Esta atualização coordena o [Infra #40](https://github.com/QuiStock/QuiStock-Infra/pull/40) com [AI_Multi-Agent #39](https://github.com/QuiStock/AI_Multi-Agent/pull/39), [quistock-dad #25](https://github.com/QuiStock/quistock-dad/pull/25) e os publishers manuais de [Auth #13](https://github.com/QuiStock/DS_Auth/pull/13)/[Core #41](https://github.com/QuiStock/DS_Backend/pull/41). Não exige recriar os bancos externos. Nenhum recurso AWS foi aplicado durante a implementação.

## Imagens e branch

As cinco referências de imagens (Auth, Core, website, API IA e worker) foram preenchidas com os digests publicados das revisões abaixo. `preflight` recusa placeholders para evitar provisionar um cluster com binários incompatíveis. API e worker vêm da mesma revisão, em repositórios GHCR diferentes. Não copiar o digest da API para o worker.

| Imagem | Revisão de origem | Publicação |
|---|---|---|
| Auth | `5874b506c70f52fb8e7e002ab661b1c0a7182db8` | [build](https://github.com/QuiStock/DS_Auth/actions/runs/41052761225) |
| Core | `ef0e5ebc4a6840c17fbed47b32f6431de69677ee` | [build](https://github.com/QuiStock/DS_Backend/actions/runs/41052767285) |
| Website | `686b6705b0f3f7dccb79ae5e811639fa17e21e92` | [build](https://github.com/QuiStock/quistock-dad/actions/runs/41052469568) |
| IA API/worker | `85f70bdba344e18beec6387696f0fe29f27cdd61` | [build](https://github.com/QuiStock/AI_Multi-Agent/actions/runs/41053800800) |

Os commits Auth/Core incluem apenas a alteração do publisher além da main analisada. Digests completos ficam nos manifests; arquitetura ARM64, revisão OCI e acesso anônimo GHCR foram conferidos.

Os workflows `publish-image.yaml` aceitam `infra_ref=codex/learner-lab-runtime-update`. A primeira troca para a imagem específica do worker precisa de revisão da PR de imagem: a política de automerge continua recusando mudanças no nome do repositório. Nenhuma PR desta atualização é mesclada automaticamente por esta tarefa.

Enquanto o Infra não estiver na main, use `"infra_ref": "codex/learner-lab-runtime-update"` no JSON local: o bootstrap aplica as Applications com essa revisão. Depois do merge, volte para `main` e execute `bootstrap`/`public` para reconciliar. Alterações locais não publicadas não são vistas pelo Argo CD.

## Configuração da conta nova

1. Inicie a sessão do novo Lab e configure suas credenciais temporárias pelo procedimento do laboratório, fora do Git. Use AWS CLI, Terraform 1.11.4+, kubectl e Helm no PATH.
2. Copie `scripts/learner-lab/config.example.json` para um arquivo em `.learner-lab/`. Informe versão Kubernetes/addons compatíveis e as roles disponíveis na nova conta. Não reutilize state nem kubeconfig da conta anterior.
3. Mantenha `cors_allowed_origins: []` se o website usar o próprio endereço do gateway. Se precisar de um website externo ou localhost, informe a origem exata, por exemplo `http://localhost:5173`, sem barra final. O bootstrap inclui automaticamente o endereço da nova API nos ConfigMaps `api-runtime` de Auth/Core.
4. Confira no Bitwarden: issuer HTTPS comum a Auth/Core/IA, credenciais PostgreSQL, MongoDB transacional da Auth, chaves OpenAI/Gemini, Qdrant e Redis. A IA não recebe mais a chave privada RSA da Auth. Os valores não são armazenados no Git ou no state Terraform.
5. Mantenha ERP desligado neste Lab enquanto não houver integração configurada. Migrações Flyway do Core continuam habilitadas no startup; confirme backup e compatibilidade do banco antes de promover a imagem do Core. Esse banco é externo e não é recriado com o cluster.

Com os valores reais no JSON e as imagens publicadas:

```powershell
python scripts/learner-lab/lab.py preflight --config .learner-lab/nova-conta.json --account ID_DA_NOVA_CONTA
python scripts/learner-lab/lab.py up --config .learner-lab/nova-conta.json --account ID_DA_NOVA_CONTA
# Revise o plano salvo antes de aplicar.
python scripts/learner-lab/lab.py up --config .learner-lab/nova-conta.json --account ID_DA_NOVA_CONTA --apply
python scripts/learner-lab/lab.py verify --config .learner-lab/nova-conta.json --account ID_DA_NOVA_CONTA
```

`up --apply` solicita o machine token Bitwarden de forma oculta e configura os três namespaces. O novo smoke verifica health/JWKS, CSRF Auth e validação de um login vazio (400), além da SPA. Não substitui um login real ou um teste do chat. Se uma etapa falhar, preserve o state e retome na mesma conta; não copie o state de outra conta.

## Memória e embeddings

API e worker compartilham `chatbot-config` e `chatbot-external`. Os parâmetros de fila, coleções, autenticação e embedding ficam explícitos no ConfigMap. `OPENAI_MODEL` e as credenciais existentes permanecem no Bitwarden; confira se o modelo e a quota são válidos. Não há necessidade de novos IDs para parâmetros públicos.

Descubra a dimensão efetiva do embedding e confirme os nomes das coleções. O comando abaixo cria um Job avulso com a imagem/configuração do worker implantado. Primeiro use somente check:

```powershell
python scripts/learner-lab/lab.py memory --config .learner-lab/nova-conta.json --account ID_DA_NOVA_CONTA --vector-size DIMENSAO_VALIDADA
# Apenas para coleções novas/vazias, depois de conferir o resultado:
python scripts/learner-lab/lab.py memory --config .learner-lab/nova-conta.json --account ID_DA_NOVA_CONTA --vector-size DIMENSAO_VALIDADA --apply
```

O Job tem retry zero e não é hook do Argo. O script recusa apply em coleções com dados: migrar dados existentes requer procedimento próprio. Alterar o modelo de embeddings pode exigir reindexação de FAQ/memória. Esse comando não ingere documentos FAQ.

O Redis temporário continua sem persistência e agora tem probes. O valor `REDIS_URL` existente foi preservado: se for usar o Redis interno, configure `redis://redis.api-chatbot.svc.cluster.local:6379/0` no Bitwarden. MongoDB mantém outbox/jobs; teste recuperação após restart do Redis/worker. Não crie CronJob para a reconciliação: ela já roda no processo do worker.

## Aceite funcional

- Website deve usar `/auth` e `/api`, sem localhost no bundle publicado.
- Login, refresh e logout devem funcionar por `/auth/...`, com cookies Secure e CSRF Auth.
- Core deve aceitar o cookie de acesso e o header CSRF `X-XSRF-TOKEN`; Auth usa outro par, `AUTH-XSRF-TOKEN`/`X-CSRF-TOKEN`.
- Chat por `/api/chat` deve autenticar a IA por RS256/JWKS e responder dentro do orçamento externo de 30 segundos. A Core usa conexão de 3 segundos e leitura de 24 segundos.
- Encerrar uma conversa deve produzir resumo/título pelo worker; verificar retomada, exclusão e recuperação após restart.
- Mobile ainda aponta para Render na main analisada. A migração de URLs/transporte do app é independente; o teste de subida do cluster não comprova o funcionamento do Mobile.

Auth/Core recebem a origem pública gerada pela nova conta. CORS externo é opcional e exige a mesma lista no JSON; não há wildcard com cookies. URLs públicas de build não contêm secrets. Portas, NodePorts, ARM64, state isolado por conta e proteções contra substituição destrutiva foram preservados.

Use também o runbook [learner-lab-feira.md](learner-lab-feira.md) para pré-requisitos, diagnóstico e desligamento.

## Verificações desta implementação

- Terraform 1.11.4: `validate` e quatro testes com provider AWS simulado passaram.
- Bootstrap: 43 testes passaram, incluindo isolamento da conta, configuração de origens, revisão Argo e provisionamento de memória em modo check.
- Nginx real em Docker: oito testes passaram, incluindo roteamento Auth/Core, prefixo encaminhado, cookies, CSRF, Origin e assets.
- IA: lint/formatação e mypy em 164 arquivos passaram; 313 testes unitários e 31 de integração passaram. Um teste real Gemini foi pulado por falta de chave local. Os testes locais não consultaram os bancos externos nem os provedores reais.
- Website: build com `/auth` e `/api`, 86 testes e publicação ARM64 passaram. O bundle compilado foi conferido sem os fallbacks localhost dos clientes.
- AWS: plano/apply, bootstrap real, credenciais externas e testes funcionais com usuário real ficam para a nova sessão do Learner Lab.
