# QuiStock no AWS Academy Learner Lab

## Desenho mínimo

Quatro Deployments de aplicação: Auth, Core, chatbot e website. O container
Nginx do website serve o build React e roteia `/api` e `/auth`. API Gateway
fornece HTTPS confiável com URL automática, conectado pelo VPC Link ao NLB
privado e à NodePort 30080. Argo CD conserva um NLB público próprio em 443,
com login obrigatório e certificado autoassinado. Não há domínio, ACM,
CloudFront, Ingress controller, autoscaler ou bancos dentro do cluster.

Terraform gerencia os recursos AWS; o script cuida do bootstrap de Argo,
Bitwarden e Applications. Argo gerencia os manifests das aplicações no Git.
O perfil atende desenvolvimento/feira; depende das permissões e da duração do
Learner Lab. Não execute apply AWS na CI.

## Preparação

Ferramentas: Python 3.10+, AWS CLI v2, Terraform 1.11.4+, kubectl e Helm 3.
Obtenha credenciais temporárias incluindo AWS_SESSION_TOKEN fora do Git.
Confirme `aws sts get-caller-identity`. Copie
`scripts/learner-lab/config.example.json` para `.learner-lab/config.json` e
preencha versões Kubernetes/add-ons, roles e capacidade.

O cluster usa duas zonas, sub-redes públicas para nós ARM64 com Internet
Gateway e capacidade fixa; não usa NAT. As duas sub-redes adicionais são para
o NLB privado/VPC Link. Os security groups limitam NodePort 30080 ao NLB
privado e 30081 ao NLB do Argo. O endpoint EKS usa admin_cidrs com autenticação
IAM; o exemplo permite qualquer IPv4. Não abra os NodePorts ao mundo.

Use roles existentes com trust `eks.amazonaws.com` e `ec2.amazonaws.com`,
respectivamente. A role do operador deve ser diferente da role dos nós.
`admin_role_name: voclabs` evita consultar GetRole, que pode ser negado;
`admin_role_arn` aceita um path IAM explícito. O script não cria roles nem
contorna restrições. Confirme PassRole, service-linked roles, EKS Access
Entries, tipos Graviton, quotas, API Gateway/VPC Link e NLBs no laboratório.
O preflight valida leituras/compatibilidade; não prova todas as permissões.

Antes de provisionar:

1. Preencha a imagem ARM64 por digest do website e do chatbot nos manifests.
   Os contratos estão em `clusters/us-east1/apps/{website,api-chatbot}/README.md`.
2. Preencha os IDs Bitwarden do chatbot; preserve os de Auth/Core. O token
   máquina precisa ler os itens mapeados dos três serviços.
3. Mantenha PostgreSQL, MongoDB, Redis e Qdrant externos à recriação. Confirme
   TLS/allowlists e o contrato de dados. Nós públicos possuem saída com IPs
   variáveis; uma exigência de saída fixa requer outro desenho.
4. Implemente Core/chatbot nas aplicações: a Core atual ainda não chama IA,
   e JWT HMAC do chatbot não é compatível com RSA/JWKS de Auth/Core.
5. Compile o React com `VITE_API_URL=/api`, Auth em `/auth` e uso de cookies.
   Não coloque credenciais no bundle. Imagens privadas exigem imagePullSecrets;
   a estrutura pressupõe imagens públicas como as APIs atuais.
6. Confirme memória, IPs de Pods e folga para rolling updates. Dois t4g.medium
   são um ponto inicial de teste, sem garantia de capacidade para a carga real.

O script recusa placeholders antes de provisionar. Secrets ficam fora do Git
e do Terraform. O token Bitwarden inicial é solicitado por prompt oculto e
criado em cada namespace por stdin. Não use shell tracing/log de depuração.

### Publicar website e chatbot antes de aplicar o Infra

As PRs [AI_Multi-Agent #26](https://github.com/QuiStock/AI_Multi-Agent/pull/26)
e [quistock-dad #14](https://github.com/QuiStock/quistock-dad/pull/14) publicam
imagens ARM64 em releases estáveis ou pelo workflow manual de publicação.
Integre essas PRs nos respectivos serviços. Para preparar o Infra ainda em PR,
execute a publicação com `infra_ref=codex/simplify-four-apps`; após o merge
do Infra, use `main`.

Com `INFRA_REPO_TOKEN` configurado no serviço, a publicação abre uma PR de
digest para a branch indicada. Sem esse token, copie do resumo da execução
as referências `ghcr.io/quistock/web-frontend@sha256:...` e
`ghcr.io/quistock/ai-multi-agent@sha256:...` para os manifests. Confira que os
pacotes GHCR estão públicos, ou configure imagePullSecrets. Complete os IDs
Bitwarden, integre os digests na PR de Infra e mescle em main antes do bootstrap.
Esses workflows não executam Terraform nem modificam Secrets.

## Recriação do zero

```bash
python scripts/learner-lab/lab.py preflight --config .learner-lab/config.json --account ACCOUNT_ID
python scripts/learner-lab/lab.py up --config .learner-lab/config.json --account ACCOUNT_ID
# Revise o plano; depois aplique o mesmo alvo.
python scripts/learner-lab/lab.py up --config .learner-lab/config.json --account ACCOUNT_ID --apply
```

`up` configura o bucket de estado mesmo sem --apply; aplica o cluster somente
com essa flag. O bucket S3 é isolado por conta/região, com bloqueio público,
criptografia, versionamento e locking. State, plans e kubeconfig local ficam
em `.learner-lab/ACCOUNT_ID/REGION/CLUSTER/`, ignorado pelo Git.
Nunca troque para um estado vazio para resolver erro de acesso.

O bootstrap instala Argo/Bitwarden com charts fixados, cria namespaces e o
token, aguarda Secrets e sincroniza Auth, Core e chatbot; depois publica o
website. Espera targets NLB saudáveis, valida CORS, saúde/JWKS, HTML/fallback
React e acesso público do Argo com rejeição de usuário anônimo. Não altera
senhas, issuer ou bancos. Não há prune automático.

```bash
python scripts/learner-lab/lab.py verify --config .learner-lab/config.json --account ACCOUNT_ID
```

A URL do website é a mesma base HTTPS das APIs, impressa ao concluir. Argo
usa `https://NOME.elb.amazonaws.com`; aceite o certificado autoassinado no
navegador. Para CLI: `argocd login NOME.elb.amazonaws.com --insecure`.
Recupere a senha inicial apenas em terminal privado, troque-a e guarde-a no
Bitwarden. A verificação automatizada confia no certificado público obtido
via Kubernetes, sem ler senha/chave privada nem desligar TLS das APIs.

## Migração do proxy edge para website

### Recuperar nós que falham com a LabRole

Se o console EC2 mostrar `nodeadm` falhando em `ec2:DescribeInstances` por
negação explícita de uma SCP, repetir Helm ou recriar o cluster não resolve.
Use a role de nós fornecida pelo laboratório (`...LabEksNodeRole...`), a mesma
selecionada na interface EKS, em `node_role_name` da configuração local. Mantenha
`cluster_role_name`, `admin_role_name`, versão, subnets, quantidade e tipos de
instância. O nome da role não prova que a SCP permita a chamada: confirme o
bootstrap das novas instâncias. O script não altera IAM, SCPs ou Access Entries
dos nós; o EKS gerencia a entrada `EC2_LINUX` da nova role.

A troca de role exige substituir o nodegroup, não o cluster. Pare outros
processos de Terraform/Helm e revise o plano:

```bash
python scripts/learner-lab/lab.py update --config .learner-lab/config.json --account ACCOUNT_ID --migrate-node-role
python scripts/learner-lab/lab.py update --config .learner-lab/config.json --account ACCOUNT_ID --migrate-node-role --apply
```

A flag só permite substituir `aws_eks_node_group.arm` quando a única causa de
substituição é `node_role_arn`, mantendo capacidade ARM64 e rede. Permite também
recriar os dois anexos ASG aos target groups existentes dos NLBs. Cluster, NLBs,
target groups, API Gateway, Secrets e role administrativa são preservados.
Há indisponibilidade durante a troca; não execute `down`, `state rm` ou crie um
nodegroup paralelo pela interface. Se o apply for interrompido, repita o mesmo
comando/configuração/estado; a flag aceita reconectar os anexos quando o plano
retoma a criação do nodegroup.

Antes de instalar/atualizar Argo CD, o script espera até 15 minutos pela
quantidade configurada de nós ARM64 Ready e sem cordon, mostrando progresso a
cada minuto. Se não registrarem, examine os novos logs EC2: não tente superar
uma SCP com permissões IAM adicionais. Uma nova negação exige reavaliar a
configuração suportada do laboratório.

Se houver uma revisão Helm `pending-*` de uma execução anterior, o script
interrompe antes de outro upgrade (a migração AWS já foi aplicada). Depois de
os nós ficarem Ready e de confirmar que nenhum Helm está ativo, consulte
`helm history argocd -n argocd` e recupere a última revisão bem-sucedida:

```bash
helm rollback argocd REVISAO_BEM_SUCEDIDA -n argocd --wait --timeout 10m
python scripts/learner-lab/lab.py update --config .learner-lab/config.json --account ACCOUNT_ID --apply
```

Não apague Secrets de release do Helm. O segundo update reaplica os valores
atuais do Argo CD após o rollback. Só prossiga ao bootstrap das aplicações
depois de recuperar nós e Argo CD.

### Trocar o proxy público

Só execute após publicar imagens, preencher IDs e mesclar os manifests em
main: as Applications acompanham main, não a branch local. Primeiro revise
as alterações Terraform (adicionam a rota $default e website_url; preservam
cluster, NLBs, target groups, NodePort e /edge-health):

```bash
python scripts/learner-lab/lab.py update --config .learner-lab/config.json --account ACCOUNT_ID
python scripts/learner-lab/lab.py update --config .learner-lab/config.json --account ACCOUNT_ID --apply
python scripts/learner-lab/lab.py bootstrap --config .learner-lab/config.json --account ACCOUNT_ID --migrate-website
```

Bootstrap pede o token novamente para adicionar o namespace chatbot. A flag
`--migrate-website` autoriza uma breve indisponibilidade pública: retira a
Application edge sem cascata Argo, remove seu Service e Deployment e entrega
NodePort 30080 ao website. Não remove namespace edge, ConfigMaps antigos,
Secrets ou recursos AWS. Sem a flag, a presença do edge interrompe a troca.
Retomar o mesmo comando é seguro: verifica se a entrada antiga ainda existe.

Se Auth/Core/chatbot já estiverem prontos, retome apenas publicação com
`lab.py public --config ... --account ... --migrate-website`. Esse comando não
instala os serviços internos nem atualiza Terraform. Se a Application antiga
não puder ser removida, corrija o erro antes de continuar; nunca abra outro LB.

O GKE e o mecanismo anterior `update --migrate-argocd-public` permanecem para
recuperação de estados existentes. A flag de migração Argo permite somente
remoções/substituições do listener, duas regras de acesso aos nós, regra antiga
CloudFront, origem VPC e distribuição CloudFront; não permite destruir cluster,
API Gateway, NLB privado ou target groups. Remova esse legado em mudança
separada depois de conferir os estados reais. Não use down/state rm na migração.

## Rotas e cookies

| Público | Serviço/caminho interno |
| --- | --- |
| `/`, rotas React | website, fallback index.html |
| `/assets/*` | arquivo estático; ausente retorna 404 |
| `/api/products` | Core `/products` |
| `/auth/login`, `/auth/refresh`, `/auth/logout` | Auth, preservando `/auth` |
| `/auth/health` | Auth `/health` |
| `/auth/.well-known/jwks.json` | Auth `/.well-known/jwks.json` |

Preservar /auth é necessário para a imagem atual. Remover o prefixo exige
publicar novas rotas e regras de segurança na Auth antes de modificar o proxy.
Método, corpo, query, Authorization, Cookie e múltiplos Set-Cookie são
preservados. Não há rota pública para chatbot; Core e chatbot podem usar DNS
interno, sem passar pelo gateway. ClusterIP não implementa isolamento entre Pods.

CORS aceita origens http://* e https://* com credenciais, inclusive localhost;
não use Access-Control-Allow-Origin literal * com cookies. O gateway responde
a preflight; Nginx remove Origin antes de chamar Spring para evitar duas
políticas. Essa abertura autoriza origens de terceiros no navegador: a
aplicação precisa proteger operações autenticadas contra CSRF.

React usa credentials: include / withCredentials: true. Mobile nativo mantém
um cookie jar, envia Cookie e processa todos os Set-Cookie, sem depender de
CORS. Auth mantém Secure, HttpOnly, SameSite=None, Path=/ e sem domínio fixo.
Website e APIs na mesma origem evitam dependência de cookies de terceiros no
website publicado; localhost continua exigindo teste no navegador alvo.
Preserve issuer/audience/chaves ao recriar ou trocar de conta.

HTTP API mantém timeout de integração de 30s, limites de payload e throttling
50 req/s com burst 100: teste chamadas de chat e tamanho dos bundles. Este
perfil não é uma CDN. VPC Link pode esfriar após longa inatividade; ensaie
antes da apresentação. Saúde não substitui login/refresh/logout, autorização,
chat real, dados e testes do app mobile.

## Recuperação, custos e desmontagem

Renove credenciais e repita o comando na mesma conta/estado. Para outra conta,
confirme identidade, reutilize configuração e execute preflight/up. Não copie
state/kubeconfig entre contas. URLs automáticas mudam: atualize mobile e
clientes externos; o React com caminhos relativos acompanha a nova origem.
Secrets rotacionados não reiniciam Pods; faça rollout restart e valide.

EKS, EC2/EBS, IPv4, NLBs, API Gateway, S3 e tráfego consomem créditos. Confira
saldo e comportamento ao encerrar a sessão no portal; não suponha que encerrar
a sessão interrompa cobrança ou preserve disponibilidade. Reserve crédito
para ensaio e rollback. A criação EKS pode levar dezenas de minutos.

```bash
python scripts/learner-lab/lab.py down --config .learner-lab/config.json --account ACCOUNT_ID --confirm-destroy ACCOUNT_ID
```

Down exige a conta como confirmação, recusa Services LoadBalancer/Ingress
externos ao perfil, retira as Applications e destrói somente o estado AWS
selecionado. Preserva bucket de estado e bancos externos. Confira recursos
remanescentes no console. O estado GKE é separado e nunca usado pelo root EKS.
