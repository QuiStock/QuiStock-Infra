# QuiStock no AWS Academy Learner Lab

O diretório GitOps continua `clusters/us-east1`; a região AWS é `us-east-1`.
As pipelines de digest não mudam. Esta infraestrutura atende desenvolvimento e feira e
não oferece as garantias de disponibilidade de uma conta comercial permanente.
Nenhum recurso AWS é criado pela CI. O primeiro teste depende das permissões
efetivas do Learner Lab; não consideramos esse teste aprovado apenas com `validate`.

## Preparação única, reutilizável entre laboratórios

Todos os acessos têm permissões idênticas: valide um perfil de laboratório uma
vez e reutilize-o. IDs de conta, credenciais STS, IP administrativo e URL do API Gateway precisam ser conferidos a cada troca.

1. Confira nas instruções do curso se EKS, Graviton, S3, ELBv2/NLB e API Gateway HTTP API/VPC Link são permitidos,
   quais tipos/tamanhos EC2 e zonas estão liberados, quotas e duração da sessão.
   Teste também o comportamento ao terminar e reiniciar a sessão; não suponha
   que encerrar a sessão encerre a cobrança ou preserve a disponibilidade.
2. Confira a `LabRole` (ou equivalente). Cluster precisa de trust em
   `eks.amazonaws.com`; nós, em `ec2.amazonaws.com`. As roles existentes precisam
   das permissões de cluster, EC2/ECR/VPC CNI e `iam:PassRole` pelo operador.
   A automação não cria nem altera IAM roles ou políticas. Service-linked roles
   precisam existir ou poder ser criadas pelo serviço. Consulte
   [cluster IAM](https://docs.aws.amazon.com/eks/latest/userguide/cluster-iam-role.html)
   e [node IAM](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html).
3. Identifique a role IAM do operador. Não use o ARN STS da sessão. O acesso
   administrativo será uma EKS Access Entry para essa role; se usar uma role
   diferente, configure o AWS CLI para assumir essa role antes do bootstrap.
   Uma role compartilhada concede acesso a todos os usuários que a assumem.
   O operador também precisa criar VPC Link, API/rotas/stage, security groups,
   NLB/listener/target group e anexar target groups ao Auto Scaling Group dos nós.
   Não é necessário criar uma role para um controlador Kubernetes de balanceadores.
   Use uma role administrativa diferente da role dos nós: o EKS cria uma
   Access Entry EC2_LINUX para a role dos nós e ela não pode ser STANDARD.
   O Learner Lab pode negar `iam:GetRole` para `voclabs`; o preflight não consulta
   os detalhes dessa role. `admin_role_name: voclabs` monta o ARN com a conta de
   destino e path IAM padrão. Se a role tiver outro path, informe
   `admin_role_arn` explicitamente com o ARN IAM completo, que tem prioridade.
   Isso não modifica IAM nem contorna o deny. A permissão de criar Access Entries
   e a existência do principal serão verificadas pelo EKS durante o apply.
4. Confirme uma versão Kubernetes em suporte padrão e as versões ARM64 dos
   add-ons. `aws eks describe-addon-versions --kubernetes-version VERSAO`
   lista compatibilidades. O exemplo exige preenchimento explícito dessas versões.
5. Valide os digests ARM64 de Auth/Core e as imagens dos charts fixados (Argo CD
   10.9.6, Bitwarden 2.0.3). GHCR público dispensa credenciais; repositório privado
   exige `imagePullSecret`. Argo CD também precisa de acesso de leitura ao Git
   se o repositório Infra deixar de ser público.
6. Mantenha PostgreSQL e MongoDB fora do ciclo de recriação. Confira allowlists,
   acesso TLS, MongoDB replica set e persistência. Nós públicos sem NAT têm IPs
   de saída variáveis: se o banco exigir origem fixa, este perfil precisa ser
   redesenhado antes da feira. Não liberar bancos indiscriminadamente.
7. O token Bitwarden deve ler todos os itens de Auth e Core, inclusive chaves
   JWT. Preserve issuer HTTPS, audience, chaves e dados ao trocar de conta.
8. Ensaie login, operação autenticada na Core, JWKS, release e troca de conta.
   Meça o tempo do processo completo. A criação EKS pode levar dezenas de minutos.

Se ARM64 ou as roles necessárias forem bloqueados, pare: o código não converte
automaticamente imagens para amd64 e não contorna restrições do laboratório.

## Ferramentas e credenciais

Use Python 3.10+, AWS CLI v2, Terraform 1.11.4+, kubectl compatível e Helm 3.
Execute da raiz de um clone atualizado. Pode ser terminal local ou ambiente
Linux disponível; CloudShell não é pressuposto obrigatório.
Obtenha credenciais temporárias pelo portal Learner Lab, incluindo
`AWS_SESSION_TOKEN`. Configure o AWS CLI fora do Git, sem colar credenciais
em chats/logs. Confirme `aws sts get-caller-identity`.

Copie `scripts/learner-lab/config.example.json` para
`.learner-lab/config.json` e preencha os placeholders. O arquivo contém apenas
parâmetros; nenhum token. Os defaults de capacidade são dois `t4g.medium`, mas
devem ser confirmados por teste de memória, pods/IPs, vCPU e rolling update.
As duas zonas devem pertencer à região configurada. O CIDR administrativo é
o IP público atual do operador com `/32`; nunca `0.0.0.0/0`.

## Primeira implantação de teste

Substitua `ACCOUNT_ID` pelo ID de 12 dígitos da conta:

```bash
python scripts/learner-lab/lab.py preflight --config .learner-lab/config.json --account ACCOUNT_ID
python scripts/learner-lab/lab.py up --config .learner-lab/config.json --account ACCOUNT_ID
# Examine o plano impresso antes de continuar.
python scripts/learner-lab/lab.py up --config .learner-lab/config.json --account ACCOUNT_ID --apply
```

`preflight` faz leituras, valida trust das roles, tipos ARM e compatibilidade
dos add-ons. Não prova PassRole, quotas, custo nem todas as permissões.
`up` cria/configura o bucket S3 mesmo sem `--apply`; o cluster só é aplicado
com essa flag. Bucket tem nome por conta/região, bloqueio público, SSE-S3,
versionamento e locking nativo. Ele permanece após `down`.
Não troque para um estado vazio para resolver erro de acesso ao bucket.

O Terraform cria VPC/sub-redes públicas em duas zonas, Internet Gateway,
EKS, Access Entry, add-ons e node group ARM On-Demand com capacidade fixa.
Também cria duas sub-redes privadas (sem NAT), um NLB interno, target group
anexado ao ASG do node group e API Gateway HTTP API com VPC Link. O ASG
registra automaticamente novos nós no target group, inclusive após substituição.
O NodePort 30080 aceita entrada somente do security group do NLB; o NLB
aceita porta 80 somente do VPC Link. Não abra o NodePort para clientes externos.
Não cria NAT, IAM roles, Karpenter, Auto Mode, autoscaler ou bancos.
Nós têm saída pública mas não têm regra de entrada aberta ao mundo; o endpoint
administrativo é restrito. O perfil depende de VPC CNI conseguir usar a role
existente do nó. Roles amplas do laboratório não equivalem a isolamento IAM
de produção. A opção STANDARD evita aceitar suporte estendido automaticamente.

O bootstrap instala Argo CD/Bitwarden, namespaces e solicita token Bitwarden
com prompt oculto. Cria `bw-auth-token` em ambos os namespaces por stdin,
aguarda as chaves de `auth-external` e `core-external`, aplica Auth, aguarda
Synced/Healthy e só então aplica Core e a Application `edge`. Não usa `prune`
automático. Kustomize gera a ConfigMap Nginx com hash, disparando um rollout
quando a configuração muda. O script aguarda targets NLB saudáveis e testa
preflight CORS, saúde das APIs e JWKS pela URL pública antes de reportar sucesso.
Não configure log de depuração ou shell tracing durante bootstrap.

Kubeconfig e dados Terraform ficam isolados em
`.learner-lab/ACCOUNT_ID/REGION/CLUSTER/`, ignorados pelo Git. Plans e state
podem conter informações sensíveis; proteja os arquivos e os backups.

```bash
python scripts/learner-lab/lab.py verify --config .learner-lab/config.json --account ACCOUNT_ID
# Aponte KUBECONFIG para o arquivo isolado, por exemplo em Bash:
export KUBECONFIG="$PWD/.learner-lab/ACCOUNT_ID/us-east-1/quistock/kubeconfig"
kubectl port-forward svc/argocd-server -n argocd 8443:443
```

Acesse `https://localhost:8443`. Recupere a senha inicial somente no terminal
privado, troque-a e guarde no Bitwarden. Não exponha a interface do Argo CD.
Para validar APIs sem publicação use port-forward dos Services de Auth e Core.
Os probes Core são `/health/readiness` e `/health/liveness`; Auth usa `/health`
para readiness e TCP para liveness. `verify` valida scheduling, chaves presentes,
rollout e Argo, mas não substitui os testes funcionais de login/bancos/JWKS.

## Entrada pública HTTPS para desenvolvimento e feira

A URL é nativa da AWS: `https://API_ID.execute-api.us-east-1.amazonaws.com`.
Não precisa de domínio próprio, DNS, certificado ACM ou computador com túnel.
API Gateway termina o HTTPS e encaminha HTTP dentro da VPC pelo VPC Link,
NLB interno e Service NodePort `edge`. Não há Classic LB nem controlador de
balanceadores no Kubernetes. O Terraform gerencia todo o caminho AWS; Argo CD
reconcilia o proxy em `clusters/us-east1/edge`.

Rotas públicas e paths recebidos pelos serviços:

| Público | Destino interno |
| --- | --- |
| `/api/products` | Core `/products` |
| `/api/chat` | Core `/chat` |
| `/auth/login`, `/auth/refresh`, `/auth/logout` | Auth, preservando `/auth/...` |
| `/auth/health` | Auth `/health` |
| `/auth/.well-known/jwks.json` | Auth `/.well-known/jwks.json` |

Core não tem prefixo `/api`; Auth já possui `/auth` no controller. O Nginx remove
apenas o prefixo da Core e mapeia explicitamente saúde/JWKS da Auth. Método,
corpo, query strings, Authorization, Cookie e múltiplos Set-Cookie são preservados.
A integração sobrescreve o path com `$request.path`, evitando prefixo de stage.
A raiz `/` não publica um website nesta PR. React futuramente terá sua própria
URL (S3/CloudFront) e usará a URL base do API Gateway na configuração.

`up --apply` já provisiona e publica as APIs. Para retomar só o proxy/verificação:

```bash
python scripts/learner-lab/lab.py public --config .learner-lab/config.json --account ACCOUNT_ID
```

O comando não solicita certificado/hostnames; reconcilia `edge`, aguarda targets
saudáveis e exibe as URLs base de Core/Auth. `verify` confere as APIs, Application
edge, preflight CORS e endpoints públicos. Teste também login real, refresh,
logout, autorização e operação autenticada na Core: saúde não substitui esses testes.

### CORS e clientes

CORS aceita qualquer origem HTTP/HTTPS, incluindo localhost, sem allowlist de IP.
Usamos `http://*` e `https://*` com credenciais permitidas, porque a Auth atual
emite cookies HttpOnly e o wildcard literal `*` é incompatível com cookies no
navegador. API Gateway responde a preflight e fornece os headers CORS; o proxy
remove Origin no encaminhamento para evitar uma segunda política no Spring.
Authorization e Content-Type estão explicitamente liberados. A autenticação
permanece nas aplicações; não há authorizer IAM/JWT adicional no API Gateway.

Para React com cookies, usar `credentials: 'include'` (fetch) ou
`withCredentials: true` (Axios). A Auth é configurada com cookies Secure,
SameSite=None e Path=/, sem domínio fixo. Navegadores que bloqueiam cookies de
terceiros ainda podem impedir login entre frontend/API de domínios distintos:
ensaiar no navegador alvo; CORS não elimina essa política do navegador.
CORS aberto também permite sites terceiros fazerem requisições com credenciais
quando o navegador as permite; autenticação não torna CORS uma barreira de segurança.
Clientes mobile nativos não dependem de CORS e devem administrar cookies/tokens
conforme o contrato de autenticação da API.

O endpoint administrativo EKS continua restrito por `admin_cidrs`: isso não
restringe os usuários das APIs. IPs de clientes mobile podem variar normalmente.
Mantenha um issuer JWT HTTPS idêntico em Auth/Core; o issuer é um identificador,
e não deve ser alterado automaticamente junto com a URL pública ao trocar de conta.
A Core continua consultando JWKS por DNS interno.

Há limites: HTTP API tem timeout de integração de 30s e limite de payload;
a configuração inicial aplica 50 requisições/s com burst 100. Ajustar e testar
para a carga real da feira, observando créditos e quotas. Não há garantia de
funcionamento além da duração/créditos/permissões do Learner Lab. VPC Link sem
tráfego por longo período pode ficar INACTIVE e precisar recriar ENIs ao receber
tráfego novamente; ensaiar e aquecer o ambiente antes da apresentação.
API Gateway e NLB têm custos além do EKS; uma URL AWS não significa hospedagem gratuita.
Consulte [integração privada](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-private.html)
e [CORS](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html).

## Recuperação e troca de conta

Renove credenciais expiradas pelo portal e repita `up --apply` na mesma conta:
o Terraform reaproveita o estado S3. Se a infraestrutura já estiver pronta,
use `bootstrap` para retomar apenas Kubernetes. Repetir bootstrap exige token
Bitwarden novamente. Atualizações de Secret não reiniciam APIs automaticamente;
após rotação use rollout restart e valide a aplicação.

Na próxima conta: inicie a sessão, configure novas credenciais, confirme o ID,
reutilize a configuração validada (atualize IP administrativo quando necessário),
execute preflight/up. Não copie state ou kubeconfig da conta anterior.
Teste o novo endpoint e atualize a URL base nos clientes mobile e no frontend.
Não há troca de DNS: a API nova terá outro ID/hostname. Reserve uma sobreposição
curta e preserve a conta antiga para rollback até validar os clientes.
Sessões, tokens e endpoints permanecem específicos de cada conta mesmo com
permissões idênticas. A expiração das credenciais do operador não deve ser
confundida com a duração da disponibilidade dos recursos: verificar o comportamento
do laboratório ao encerrar a sessão.

Não espere crédito zerar: reserve crédito para ensaio, recuperação e sobreposição.
O número de contas ainda é indefinido e cada uma tem orçamento independente.
EKS em suporte padrão custa US$0,10/h só pelo control plane; some EC2, EBS,
IPv4, NLB, API Gateway, S3 e tráfego ([preços](https://aws.amazon.com/eks/pricing/)).
US$50 não significam 500 horas de ambiente completo. Confira o saldo no portal
Learner Lab, pois APIs de Billing/Budgets podem estar restritas e os dados atrasados.
Registre custo/hora observado e duração das sessões após o primeiro ensaio.

## Desmontagem

```bash
python scripts/learner-lab/lab.py down --config .learner-lab/config.json --account ACCOUNT_ID --confirm-destroy ACCOUNT_ID
```

`down` recusa apagar infraestrutura enquanto houver Services LoadBalancer ou
Ingress externos ao perfil. Retira Applications edge/Core/Auth e destrói a
infraestrutura daquela conta, inclusive HTTP API, VPC Link, NLB e attachments
do ASG. Não há comando `unpublish` nem limpeza manual do NLB deste perfil. A
confirmação com ID autoriza destruição sem prompt adicional. Se o cluster não
estiver acessível, recupere acesso primeiro ou faça recuperação manual com
plano Terraform revisado e conferência dos recursos de nuvem.
Confirme ELB, EC2, EBS, ENIs e outros recursos remanescentes no console.
O bucket e versões do estado ficam preservados e podem ser retirados separadamente
após backup seguro. O Terraform GKE e estado GCS permanecem separados: só
desative o ambiente antigo após o aceite da migração.
