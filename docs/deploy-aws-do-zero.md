# Criar a infraestrutura AWS do zero

> Histórico do fluxo EKS. Para o ambiente K3s descartável da feira, use o
> [guia atual de Kubernetes no Lab](kubernetes-lab.md). Não aplique este root
> antigo sobre o state já adotado pelo novo fluxo.

Guia para **PowerShell 7.1+ no computador local**, na pasta `QuiStock-Infra`.
Não é necessário um cluster ou CloudShell para começar: o Terraform cria o
cluster, e o bootstrap instala os componentes Kubernetes depois.

Execute cada bloco separadamente. Confira a saída antes de continuar; se houver
erro, pare naquele passo. Os comandos abaixo são instruções de operação, não um
script único para colar de uma vez.

## O que deve existir antes

| Item | Preparação |
| --- | --- |
| Learner Lab | Sessão ativa, credenciais temporárias e região autorizada |
| IAM | Roles existentes para cluster EKS, nós EC2 e operador; o Terraform não cria roles |
| Bancos | PostgreSQL compartilhado, MongoDB, Redis e Qdrant acessíveis e já preparados |
| Provedores | OpenAI, Gemini e TypeSafe disponíveis, com credenciais no Bitwarden |
| Bitwarden Secrets Manager | Machine account com leitura dos itens mapeados e token de acesso válido |
| Imagens | API, worker, Observe, Auth, Core e website publicados em ARM64, por digest público |
| Contas de teste | Conta comercial ativa e conta `super_admin` do Observe |

**Não execute migrações, `memory --apply` ou `faq --apply` neste ambiente.**
Estrutura ausente ou incompatível exige interromper e registrar a pendência.

O teste de 02/11/2026 usou EKS 1.36, duas instâncias `t4g.medium` e Helm 3.
Versões e permissões devem ser conferidas a cada nova conta; não reutilize as
roles `c22...` de outra conta.

## 1. Preparar o checkout e as ferramentas

Se ainda não tiver o repositório:

```powershell
git clone https://github.com/QuiStock/QuiStock-Infra.git
Set-Location QuiStock-Infra
```

Antes do merge, use a branch testada. Se o checkout tiver alterações próprias,
resolva-as antes de trocar de branch.

```powershell
git status --short
git fetch origin
git switch codex/learner-lab-runtime-update
git pull --ff-only
```

Após o merge, use `main` tanto no checkout quanto em `infra_ref` no passo 6.
O bootstrap lê manifests locais e configura o Argo para a referência indicada;
os dois precisam representar a mesma revisão desejada.

Instale as ferramentas ausentes pelos distribuidores oficiais e reabra o terminal
para atualizar o PATH. Confira:

```powershell
$PSVersionTable.PSVersion
python --version
aws --version
terraform version
kubectl version --client
helm version
git --version
```

Requisitos do bootstrap: Python 3.10+, AWS CLI v2, Terraform 1.11.4+ e Helm 3;
kubectl deve ser compatível com o EKS escolhido. Downloads:
[Python](https://www.python.org/downloads/),
[AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
[Terraform](https://developer.hashicorp.com/terraform/install),
[kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-windows/),
[Helm](https://helm.sh/docs/intro/install/) e [Git](https://git-scm.com/downloads).

**Pode avançar quando:** todos os executáveis forem encontrados.

## 2. Configurar o acesso temporário AWS

Inicie o Learner Lab e obtenha os três campos: access key, secret key e session
token. Use um perfil próprio. Se ele já estiver válido, basta conferir a identidade;
não é necessário cadastrá-lo novamente.

```powershell
aws configure --profile quistock-lab
```

Informe access key, secret key, região `us-east-1` e saída `json` nos prompts.
O `aws configure` padrão não pede session token; caso ele ainda não esteja salvo,
adicione-o com entrada oculta no PowerShell 7.1+:

```powershell
$LabSessionToken = Read-Host "AWS session token" -MaskInput
aws configure set aws_session_token $LabSessionToken --profile quistock-lab
Remove-Variable LabSessionToken
```

Não publique o arquivo de credenciais nem cole seus valores no chat. O token AWS
é diferente do token de machine account do Bitwarden, solicitado mais adiante.

```powershell
$env:AWS_PROFILE = "quistock-lab"
$env:AWS_REGION = "us-east-1"
aws sts get-caller-identity
```

**Pode avançar quando:** `Account` corresponder à conta exibida pelo Learner Lab.
Se houver `ExpiredToken`, renove os três campos no mesmo perfil.

## 3. Definir os caminhos da sessão

Execute na raiz do repositório. Os caminhos absolutos evitam o erro em que o
PowerShell tenta salvar a configuração na pasta do usuário.

```powershell
if (-not (Test-Path .\scripts\learner-lab\lab.py)) { throw "Abra a raiz de QuiStock-Infra." }
$RepoRoot = (Resolve-Path .).Path
$Account = (aws sts get-caller-identity --query Account --output text).Trim()
if ($LASTEXITCODE -ne 0 -or $Account -notmatch '^\d{12}$') { throw "Identidade AWS inválida." }
$Region = $env:AWS_REGION
$Cluster = "quistock"
$Lab = Join-Path $RepoRoot "scripts\learner-lab\lab.py"
$LocalLab = Join-Path $RepoRoot ".learner-lab"
$Config = Join-Path $LocalLab "config-$Account.json"
$env:KUBECONFIG = Join-Path $LocalLab "$Account\$Region\$Cluster\kubeconfig"
New-Item -ItemType Directory -Force -Path $LocalLab | Out-Null
```

Guarde o ID da conta e esses caminhos. Em outro terminal, as variáveis precisam
ser definidas novamente; veja [abrir uma sessão de operação](comandos-operacao-aws.md#1-abrir-uma-sessão-de-operação).

## 4. Identificar as roles e a capacidade permitidas

```powershell
aws iam list-roles --query "Roles[].{Name:RoleName,Arn:Arn}" --output table
$ClusterRoleName = Read-Host "Nome da role do cluster EKS"
$NodeRoleName = Read-Host "Nome da role dos nós EC2"
aws iam get-role --role-name $ClusterRoleName --query Role.AssumeRolePolicyDocument
aws iam list-attached-role-policies --role-name $ClusterRoleName
aws iam get-role --role-name $NodeRoleName --query Role.AssumeRolePolicyDocument
aws iam list-attached-role-policies --role-name $NodeRoleName
```

Procure as roles `...LabEksClusterRole...` e `...LabEksNodeRole...` quando existirem.
A primeira deve confiar em `eks.amazonaws.com`; a segunda, em `ec2.amazonaws.com`.
Confira permissões de cluster EKS e, nos nós, Worker Node, CNI e leitura de ECR.
`LabRole` não foi suficiente na conta do teste; não presuma que será suficiente na nova.

O operador usado no teste era `voclabs`, distinto da role dos nós. Se o ARN retornado
por STS usar outra role, configure esse principal IAM em vez de copiar `voclabs`.
Não use o ARN STS `assumed-role/.../sessão` como role administrativa.

```powershell
aws ec2 describe-instance-type-offerings --region $Region --location-type availability-zone --filters Name=instance-type,Values=t4g.medium --query "InstanceTypeOfferings[].Location" --output table
```

Neste exemplo, as zonas serão `us-east-1a` e `us-east-1b`; confirme que ambas
aparecem e são permitidas pelo Lab. Se usar outra região, ajuste também as zonas.

**Pode avançar quando:** roles, região, duas zonas e instância ARM64 estiverem confirmadas.
O preflight verifica leituras e compatibilidade; permissões de `PassRole`, quotas
e restrições do Lab ainda podem impedir o apply.

## 5. Escolher Kubernetes e add-ons compatíveis

```powershell
aws eks describe-cluster-versions --region $Region --query "clusterVersions[].{Version:clusterVersion,Status:versionStatus}" --output table
$KubernetesVersion = Read-Host "Versão EKS em STANDARD_SUPPORT"
aws eks describe-addon-versions --region $Region --kubernetes-version $KubernetesVersion --addon-name vpc-cni --query "addons[].addonVersions[].{Version:addonVersion,Architectures:architecture}" --output json
$VpcCniVersion = Read-Host "Versão exata do vpc-cni compatível com ARM64"
aws eks describe-addon-versions --region $Region --kubernetes-version $KubernetesVersion --addon-name coredns --query "addons[].addonVersions[].{Version:addonVersion,Architectures:architecture}" --output json
$CoreDnsVersion = Read-Host "Versão exata do coredns compatível com ARM64"
aws eks describe-addon-versions --region $Region --kubernetes-version $KubernetesVersion --addon-name kube-proxy --query "addons[].addonVersions[].{Version:addonVersion,Architectures:architecture}" --output json
$KubeProxyVersion = Read-Host "Versão exata do kube-proxy compatível com ARM64"
```

Referência histórica aprovada em 02/11/2026, **não uma seleção automática**:
EKS `1.36`; CNI `v1.22.4-eksbuild.10`; CoreDNS `v1.14.7-eksbuild.22`;
kube-proxy `v1.36.0-eksbuild.58`.

Referência da consulta: [versões EKS disponíveis na AWS CLI](https://docs.aws.amazon.com/cli/latest/reference/eks/describe-cluster-versions.html).

## 6. Preparar Bitwarden e a configuração local

No **Secrets Manager**, confira os itens mapeados nos três manifests
`clusters/us-east1/apps/{api-auth,api-core,api-chatbot}/bitwarden-secret.yaml`.
A machine account deve poder ler todos eles. Prepare também:

- `TYPESAFE_API_KEY`: chave válida do provedor.
- `OBSERVABILITY_SESSION_SECRET`: segredo aleatório de pelo menos 32 caracteres.

Os campos abaixo recebem **UUIDs dos itens**, nunca seus valores.

```powershell
if (Test-Path $Config) { throw "Configuração já existe. Use a seção de retomada; não sobrescreva o estado da conta." }
Copy-Item (Join-Path $RepoRoot "scripts\learner-lab\config.example.json") $Config
$LabConfig = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$LabConfig.region = $Region
$LabConfig.cluster_name = $Cluster
$LabConfig.infra_ref = "codex/learner-lab-runtime-update"
$LabConfig.cluster_role_name = $ClusterRoleName
$LabConfig.node_role_name = $NodeRoleName
$LabConfig.admin_role_name = "voclabs"
$LabConfig.availability_zones = @("us-east-1a", "us-east-1b")
$LabConfig.kubernetes_version = $KubernetesVersion
$LabConfig.addon_versions.vpc_cni = $VpcCniVersion
$LabConfig.addon_versions.coredns = $CoreDnsVersion
$LabConfig.addon_versions.kube_proxy = $KubeProxyVersion
$LabAdminIp = (Invoke-RestMethod "https://checkip.amazonaws.com").Trim()
$LabConfig.admin_cidrs = @("$LabAdminIp/32")
$LabConfig.bitwarden_secret_ids.TYPESAFE_API_KEY = Read-Host "UUID do item TYPESAFE_API_KEY"
$LabConfig.bitwarden_secret_ids.OBSERVABILITY_SESSION_SECRET = Read-Host "UUID do item OBSERVABILITY_SESSION_SECRET"
[System.IO.File]::WriteAllText($Config, ($LabConfig | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
```

Se escolheu outras zonas, principal administrativo ou `main`, ajuste as atribuições
correspondentes **antes de gravar**. A configuração fica ignorada pelo Git e
contém IDs e parâmetros; os valores dos secrets permanecem no Bitwarden.
O IP administrativo deve ser o IPv4 público atual do computador, com `/32`,
em vez do `0.0.0.0/0` do exemplo original.

## 7. Validar e revisar o plano

```powershell
python $Lab preflight --account $Account --config $Config
```

**Esperado:** `Read checks passed`. Não continue se houver placeholder, role,
versão ou conta incorreta.

```powershell
python $Lab up --account $Account --config $Config
```

Essa etapa já cria/configura o bucket S3 de estado, mas **não aplica o cluster**.
Revise criações, duas máquinas ARM64 e ausência de destruições inesperadas.
O primeiro teste registrou `43 to add`; esse número é evidência histórica,
não um requisito para revisões futuras.

## 8. Criar o cluster e instalar as aplicações

```powershell
python $Lab up --account $Account --config $Config --apply
```

O comando recalcula o plano, aplica Terraform, espera os nós e executa o bootstrap.
Quando aparecer `Bitwarden machine token (hidden):`, cole o **access token da
machine account do Secrets Manager** no terminal. Não é a senha do cofre,
não é um UUID de item e não é o session token AWS. A entrada fica oculta.

Espere a conclusão. A criação de `application.argoproj.io/...` não significa que
seus pods já estão prontos. Para acompanhar, abra outro terminal, configure o
mesmo perfil/kubeconfig conforme o documento de operação e execute:

```powershell
kubectl get nodes -o wide
kubectl get applications -n argocd
kubectl get pods -n api-chatbot -o wide
kubectl rollout status deployment/api-chatbot -n api-chatbot --timeout=5m
```

No chatbot, `2/2` significa API e worker prontos no mesmo pod.
Se ficar em `1/2`, use [diagnóstico](comandos-operacao-aws.md#5-diagnóstico-sem-expor-secrets);
não apague o estado nem reinicie o provisionamento do zero.

## 9. Confirmar o deploy e abrir as interfaces

```powershell
python $Lab verify --account $Account --config $Config
python $Lab public --account $Account --config $Config
```

**Esperado:** cinco aplicações Synced/Healthy, pods prontos e URLs impressas.

| URL emitida | Uso |
| --- | --- |
| Website/API HTTPS | Website em `/`, Core em `/api`, Auth em `/auth` |
| Observe HTTPS | `/observe/`; login próprio `super_admin` |
| Argo CD HTTPS | NLB público próprio; usuário inicial `admin` |

Para descobrir a senha do Argo, siga [o comando PowerShell](comandos-operacao-aws.md#2-descobrir-a-senha-inicial-do-argo-cd).
Seu certificado padrão é autoassinado, diferente do HTTPS público do API Gateway.
Os endereços mudam quando a infraestrutura é recriada; não copie URLs antigas.

## 10. Executar o teste funcional

Primeiro, somente os checks dos dados já preparados:

```powershell
python $Lab memory --account $Account --config $Config --vector-size 768
python $Lab faq --account $Account --config $Config
```

Cada comando informa o nome do Job e como ler seus logs. Não acrescente `--apply`.
Confira a dimensão 768 usada pelas imagens atuais e as coleções existentes.

Em seguida, execute os [passos funcionais 51–71](teste-aws-passo-a-passo.md#dados-e-caminhos-funcionais):
website, Android real, chat, FAQ, consulta comercial, worker, histórico, Observe
e recuperação. A bateria autenticada pede credenciais apenas no terminal:

```powershell
$BaseUrl = Read-Host "Origem HTTPS emitida pelo deploy, sem barra final"
python .\scripts\learner-lab\tests\live_authenticated.py --base-url $BaseUrl --restart-kubeconfig $env:KUBECONFIG --account $Account
```

Esse teste cria uma conversa sintética e reinicia a IA para conferir persistência.
Não executa migrações; não substitui o teste do APK no aparelho. A avaliação JEV
do chat e o preview do Lab são verificações distintas.

## 11. Retomar sem recriar a infraestrutura

Se só as credenciais AWS expiraram, renove-as e confira STS. Preserve a mesma
configuração, diretório `.learner-lab/<conta>/<região>/<cluster>` e bucket S3.
Refaça as variáveis do terminal pelo [guia de operação](comandos-operacao-aws.md#1-abrir-uma-sessão-de-operação).

Se Terraform terminou e o bootstrap foi interrompido:

```powershell
python $Lab bootstrap --account $Account --config $Config
python $Lab verify --account $Account --config $Config
```

O bootstrap pode pedir novamente o token Bitwarden. Não execute `up` com uma
configuração/estado vazio para tentar resolver erro de permissão ou timeout.

## 12. Encerrar quando não precisar mais dos recursos

Somente após decidir encerrar o teste e guardar as evidências:

```powershell
python $Lab down --account $Account --config $Config --confirm-destroy $Account
```

Isso destrói os recursos Terraform dessa conta. Bancos externos e bucket de
estado são preservados. Confira EKS, EC2, NLB, API Gateway e VPC no console;
recursos ativos continuam consumindo o orçamento do Lab. Não apague o estado
antes de confirmar a remoção dos recursos.
