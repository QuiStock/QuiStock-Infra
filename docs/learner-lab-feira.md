# QuiStock no AWS Academy Learner Lab

O diretório GitOps continua `clusters/us-east1`; a região AWS é `us-east-1`.
As pipelines de digest não mudam. Esta infraestrutura é destinada à feira e
não oferece as garantias de disponibilidade de uma conta comercial permanente.
Nenhum recurso AWS é criado pela CI. O primeiro teste depende das permissões
efetivas do Learner Lab; não consideramos esse teste aprovado apenas com `validate`.

## Preparação única, reutilizável entre laboratórios

Todos os acessos têm permissões idênticas: valide um perfil de laboratório uma
vez e reutilize-o. IDs de conta, credenciais STS, IP administrativo, ARN do
certificado e destinos DNS precisam ser conferidos a cada troca.

1. Confira nas instruções do curso se EKS, Graviton, S3, ELB e ACM são permitidos,
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
   Use uma role administrativa diferente da role dos nós: o EKS cria uma
   Access Entry EC2_LINUX para a role dos nós e ela não pode ser STANDARD.
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
Não cria NAT, IAM roles, Karpenter, Auto Mode, autoscaler ou bancos.
Nós têm saída pública mas não têm regra de entrada aberta ao mundo; o endpoint
administrativo é restrito. O perfil depende de VPC CNI conseguir usar a role
existente do nó. Roles amplas do laboratório não equivalem a isolamento IAM
de produção. A opção STANDARD evita aceitar suporte estendido automaticamente.

O bootstrap instala Argo CD/Bitwarden, namespaces e solicita token Bitwarden
com prompt oculto. Cria `bw-auth-token` em ambos os namespaces por stdin,
aguarda as chaves de `auth-external` e `core-external`, aplica Auth, aguarda
Synced/Healthy e só então aplica Core. Não usa `prune` automático.
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

## Entrada pública opcional para a feira

Há um proxy Nginx compartilhado com dois hostnames e um Classic Load Balancer
HTTPS via controlador legado do EKS, sem criação de role/controller adicional.
Essa escolha reduz dependências IAM no laboratório; o controlador legado tem
manutenção limitada e não é a recomendação para uma conta comercial. Consulte
[balanceamento EKS](https://docs.aws.amazon.com/eks/latest/best-practices/load-balancing.html).
Se o laboratório não permitir ELB/ACM, esta publicação não funcionará e é um
bloqueio para o uso público; port-forward é apenas alternativa para teste local.

Pré-requisitos: dois nomes DNS estáveis, certificado ACM emitido na conta e
região atuais cobrindo ambos, controle do DNS fora da conta temporária e
permissão para o serviço EKS provisionar Classic LB e security groups.
O certificado não é criado pelo script: solicite/valide no ACM previamente,
ou importe certificado autorizado se o laboratório permitir. Sem acesso a
ACM, planeje um terminador HTTPS externo antes da feira.

```bash
python scripts/learner-lab/lab.py public --config .learner-lab/config.json --account ACCOUNT_ID --certificate-arn ARN_ACM --auth-host auth.example.com --core-host api.example.com
```

O comando instala dois proxies ARM e um Service HTTPS com TLS no ELB. Depois
aponte os dois CNAMEs para o hostname exibido. O template está em
`clusters/us-east1/edge/nginx.conf`; a publicação é gerenciada pelo script,
separadamente das Applications, porque certificado e DNS dependem da conta.
Não use hostnames AWS como issuer JWT. Confira SANs do certificado, CORS,
URLs do aplicativo, HTTPS, login e operação autenticada. O proxy preserva paths
e envia `X-Forwarded-Proto: https`; aplicações devem aceitar esse cabeçalho.
O endpoint `/edge-health` só testa o proxy; probes das APIs continuam necessários.
Esse perfil não inclui WAF, rate limit de borda ou uma política de disponibilidade
comercial. Fixe também digests dos componentes auxiliares após o ensaio.

## Recuperação e troca de conta

Renove credenciais expiradas pelo portal e repita `up --apply` na mesma conta:
o Terraform reaproveita o estado S3. Se a infraestrutura já estiver pronta,
use `bootstrap` para retomar apenas Kubernetes. Repetir bootstrap exige token
Bitwarden novamente. Atualizações de Secret não reiniciam APIs automaticamente;
após rotação use rollout restart e valide a aplicação.

Na próxima conta: inicie a sessão, configure novas credenciais, confirme o ID,
reutilize a configuração validada (atualize IP administrativo quando necessário),
execute preflight/up e prepare o certificado ACM. Não copie state ou kubeconfig
da conta anterior. Publique e teste o novo endpoint antes de trocar o DNS.
Reserve uma sobreposição curta; preserve a conta antiga para rollback até
expirar o TTL e validar clientes. Sessões/token/certificado permanecem específicos
de cada conta mesmo com permissões idênticas.

Não espere crédito zerar: reserve crédito para ensaio, recuperação e sobreposição.
O número de contas ainda é indefinido e cada uma tem orçamento independente.
EKS em suporte padrão custa US$0,10/h só pelo control plane; some EC2, EBS,
IPv4, ELB, S3 e tráfego ([preços](https://aws.amazon.com/eks/pricing/)).
US$50 não significam 500 horas de ambiente completo. Confira o saldo no portal
Learner Lab, pois APIs de Billing/Budgets podem estar restritas e os dados atrasados.
Registre custo/hora observado e duração das sessões após o primeiro ensaio.

## Desmontagem

```bash
python scripts/learner-lab/lab.py unpublish --config .learner-lab/config.json --account ACCOUNT_ID
# Confirme no AWS console que o ELB foi excluído.
python scripts/learner-lab/lab.py down --config .learner-lab/config.json --account ACCOUNT_ID --confirm-destroy ACCOUNT_ID
```

`down` recusa apagar infraestrutura enquanto houver Services LoadBalancer ou
Ingress. Retira Applications e destrói a infraestrutura daquela conta. A
confirmação com ID autoriza destruição sem prompt adicional. Se o cluster não
estiver acessível, recupere acesso primeiro ou faça recuperação manual com
plano Terraform revisado e conferência dos recursos de nuvem.
Confirme ELB, EC2, EBS, ENIs e outros recursos remanescentes no console.
O bucket e versões do estado ficam preservados e podem ser retirados separadamente
após backup seguro. O Terraform GKE e estado GCS permanecem separados: só
desative o ambiente antigo após o aceite da migração.
