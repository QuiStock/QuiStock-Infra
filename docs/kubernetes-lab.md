# Kubernetes descartável no Learner Lab

Este é o fluxo de operação do QuiStock para a feira. O ponto de entrada é
`scripts/learner-lab/cluster.py`; `lab.py` e `recover_k3s.py` ficam como histórico
do EKS e da recuperação emergencial. Não misture os comandos antigos com o
novo root Terraform.

Na conta do exemplo, a adoção e a retirada do EKS já foram concluídas. Use os
comandos normais de `up`, `verify`, `access` e `down`; não é necessário repetir
as flags de migração. Os [resultados dos ensaios](validacao-kubernetes-lab-2026-11-02.md)
registram o que foi efetivamente testado e os cenários ainda pendentes.

## Arquitetura

```text
Navegador / aplicativo
    -> API Gateway HTTPS -> VPC Link -> NLB privado -> NodePort 30080
                                                      -> website / APIs / Observe
Operador -> NLB público TCP 443 -> NodePort 30081 -> Argo CD HTTPS autenticado

Kubernetes K3s: servidor + agente, duas EC2 Ubuntu ARM64 t4g.large
Git -> Argo CD -> cinco Applications
Bitwarden -> operador Secrets Manager -> Secrets Kubernetes
Aplicações -> bancos e provedores externos
```

O servidor também executa aplicações. Não há alta disponibilidade do control
plane. Não há backup/restauração de SQLite, volumes permanentes de aplicação
ou nova plataforma de observabilidade. O Redis temporário pode ser perdido,
conforme o contrato desta demonstração. As chaves JWT e demais configurações
duráveis vêm do Bitwarden. Sessões e senha inicial do Argo podem mudar numa
reconstrução completa; isso não muda as chaves JWT das aplicações.

Terraform gerencia VPC, quatro subnets, Internet Gateway, rotas, security
groups, API Gateway, VPC Link, NLBs, target groups, duas EC2 e seus registros
nos target groups. O script instala K3s, charts e Applications. Os nós não
recebem credenciais AWS nem roles IAM. Não há NAT, autoscaler ou EKS em uma
criação nova. Os discos raiz são criptografados e apagados com as EC2.

Apenas o state Terraform precisa persistir para gerenciar os recursos AWS.
O bucket S3 privado, criptografado e versionado é separado por conta/região,
com locking. A chave histórica `<cluster>/eks.tfstate` é mantida inclusive no
fluxo K3s para permitir adotar a rede existente sem um segundo state concorrente.
O kubeconfig, a chave SSH e o inventário ficam ignorados em `.learner-lab`.
O inventário é cache: os IDs e URLs correntes vêm do Terraform. Se perder a
chave SSH, `up --apply` reconstrói o par para instalar uma chave nova.

## Preparação de um terminal PowerShell

Instale Python 3.10+, AWS CLI v2, Terraform 1.11.4+, kubectl compatível com a
versão Kubernetes fixada, Helm 3.17.3+ e OpenSSH (`ssh` e `ssh-keygen`). Ferramentas
locais em `.learner-lab/tools` e `.learner-lab/tools/windows-amd64` também são
usadas pelo script. Não execute apply AWS pela CI.

Inicie o Lab no portal e renove as credenciais temporárias do perfil, incluindo
`AWS_SESSION_TOKEN`, pelos meios habituais. Não grave credenciais em arquivos
versionados ou no JSON de configuração.

```powershell
$env:AWS_PROFILE = "quistock-lab"
$Account = "637423317921"
$Region = "us-east-1"
$Cluster = "quistock"
$Config = ".learner-lab/cluster-$Account.json"
$Lab = "scripts/learner-lab/cluster.py"
$Runtime = Join-Path $PWD ".learner-lab/$Account/$Region/$Cluster"
$env:KUBECONFIG = Join-Path $Runtime "k3s-recovery/kubeconfig"
aws sts get-caller-identity
```

Para uma configuração nova, copie `scripts/learner-lab/cluster.example.json`
para `$Config`. Preencha o IP público do operador como `/32`, os dois IDs
Bitwarden de runtime e uma revisão Git publicada e validada em `infra_ref`.
Os mapeamentos Bitwarden de Auth, Core e chatbot estão nos manifests existentes.
Não é preciso fornecer nomes de roles EKS, versões de add-ons ou tokens AWS no JSON.

`ami_id` deve ser uma AMI Ubuntu ARM64 oficial, disponível na conta/região;
a do exemplo foi validada em us-east-1 e não é portátil entre regiões.
`k3s_version` é uma versão explícita, sem consulta a `latest`. Os charts estão
fixados no código. As imagens das aplicações são as da revisão Git escolhida.
As contas de bancos e provedores externos devem continuar disponíveis e aceitar
a saída das novas EC2. Mudar de conta/região não copia dados dos bancos.

## Criar do zero

```powershell
python $Lab up --config $Config --account $Account
# Revise o plano exibido; depois:
python $Lab up --config $Config --account $Account --apply
```

Sem `--apply`, o script prepara/inicializa o bucket de state e gera o plano,
mas não cria ou inicia EC2. Com `--apply`, aplica o plano, inicia instâncias
paradas, instala K3s, instala Argo/Bitwarden, sincroniza os Secrets, aplica as
Applications, espera os rollouts e executa a verificação pública.

Um cluster novo precisa de um **Bitwarden machine token**, com leitura dos
itens mapeados. O script pede por prompt oculto antes de aplicar um plano que
cria um servidor. O token passa em memória e por stdin ao Kubernetes, sem
entrar em Terraform, planos, argumentos de processo ou logs. Para execução
não interativa, `BWS_ACCESS_TOKEN` pode ser fornecido por um gerenciador de
Secrets ao processo; não coloque o valor literalmente na linha de comando.
Use também `--non-interactive` para falhar claramente, sem aguardar um prompt,
caso o token necessário esteja ausente.
Um cluster existente reutiliza os `bw-auth-token` já presentes.

Ao finalizar, as URLs e o caminho do kubeconfig são exibidos. Em conta vazia,
as URLs automáticas serão novas. Clientes com endpoint fixo devem recebê-las;
o website usa os caminhos relativos existentes.

## Retomar após fim da sessão de quatro horas

1. Inicie novamente o Lab e aguarde o portal indicar que está pronto.
2. Renove as credenciais AWS e confira a conta com STS.
3. Atualize `admin_cidrs` se o IP do operador mudou, inclusive na rede da feira.
4. Execute o mesmo `up --apply`.

```powershell
python $Lab up --config $Config --account $Account --apply
```

Se ambas as EC2 sobreviveram, instâncias paradas são iniciadas. O script
atualiza o kubeconfig e conserva uma instalação K3s já pronta. Se o novo IP
público exigir ajustar o certificado do servidor, reinstala a configuração
da versão fixada. Há possibilidade de breve indisponibilidade nessa etapa.
O Terraform ignora a ausência temporária da associação de IP público enquanto
a EC2 está parada; esse atributo não pode disparar uma substituição dos nós.
Depois do start, um refresh atualiza os IPs nos outputs do state.
Charts já implantados nas versões fixadas e Applications na revisão escolhida
são reutilizados; a retomada não precisa baixar novamente os charts nesses casos.

Se um nó foi destruído, o refresh Terraform detecta a perda e o script gera
novo plano para substituir o par descartável. O servidor e o agente são
recriados juntos, evitando associar credenciais antigas a um servidor novo.
O bootstrap recupera os Secrets do Bitwarden. Não consulta o EKS antigo.
Rede e URLs permanecem se esses recursos sobreviveram.

Não use `Reset` do portal para retomar uma sessão: ele pode apagar a conta.
O comportamento real de End Lab/expiração deve ser ensaiado neste laboratório;
o script não pode impedir desligamentos ou mudanças de política impostos pelo Lab.

## Forçar reconstrução do Kubernetes

Use quando as instâncias existem, mas o estado Kubernetes ficou inutilizável:

```powershell
python $Lab up --config $Config --account $Account --rebuild
python $Lab up --config $Config --account $Account --rebuild --apply
```

Isso destrói e recria os dois nós e o estado Kubernetes, com indisponibilidade.
Os bancos externos e o Bitwarden ficam intactos. O token máquina será
necessário para o novo bootstrap. O plano bloqueia destruição/substituição
de rede, URLs e EKS legado durante `up`. Se ele recusar uma mudança protegida,
investigue a diferença de configuração; não apague o state para contornar.

## Adotar o ambiente recuperado anteriormente

Essa etapa é uma única transição. Usa o mesmo bucket/chave Terraform anterior,
importa as EC2 e o security group do inventário emergencial e registra os
targets no Terraform. Os `moved` blocks ajustam os endereços do EKS legado;
nenhum state é copiado ou removido manualmente.

```powershell
python $Lab up --config $Config --account $Account --adopt-legacy
python $Lab up --config $Config --account $Account --adopt-legacy --apply
```

A adoção mantém os endereços públicos e o EKS antigo com zero nós. O control
plane legado ainda cobra; ele só existe no fluxo adotado e está incluído na
destruição completa. Não é usado para instalar ou recuperar aplicações.
Uma criação em conta vazia não cria esse legado. O par atual precisa do
inventário `k3s-recovery/recovery.json` e da chave emergencial para a primeira
importação. Depois da adoção, os recursos são encontrados pelo state.

Depois de validar a adoção e o bootstrap independente, retire somente o EKS
inativo para encerrar sua cobrança, preservando K3s e URLs:

```powershell
python $Lab up --config $Config --account $Account --retire-legacy
python $Lab up --config $Config --account $Account --retire-legacy --apply
```

É uma etapa separada e explícita. O plano permite remover apenas os recursos
EKS legados conhecidos; não autoriza trocar NLBs, API Gateway ou a VPC.

## Acesso ao Kubernetes, Argo CD e logs

```powershell
# Regenera o kubeconfig sem alterar a infraestrutura:
python $Lab access --config $Config --account $Account
$env:KUBECONFIG = Join-Path $Runtime "k3s-recovery/kubeconfig"
kubectl get nodes -o wide
kubectl get applications -n argocd
kubectl get pods -A

# Alternativa de acesso ao Argo, sem depender do NLB:
kubectl port-forward -n argocd svc/argocd-server 8443:443
# Abra https://localhost:8443; Ctrl+C encerra o encaminhamento.
```

O Argo usa certificado autoassinado. No endereço público, abra a URL impressa
por `access` e autentique-se. Em cluster novo, obtenha a senha inicial apenas
num terminal privado:

```powershell
$Encoded = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}'
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Encoded))
Remove-Variable Encoded
# Usuário: admin. Não cole a senha em chats, tickets ou logs.
```

Se a senha já foi trocada, use a senha atual; o Secret inicial pode estar
ausente ou conter a senha antiga. Em reconstrução, haverá um Argo novo.
Com a CLI opcional: `argocd login HOST_DO_NLB --insecure` (prompt de senha).
O `--insecure` é específico do certificado autoassinado do Argo.

```powershell
kubectl logs -n api-auth deployment/api-auth --tail=100
kubectl logs -n api-core deployment/api-core --tail=100
kubectl logs -n api-chatbot deployment/api-chatbot -c api-chatbot --tail=100
kubectl logs -n api-chatbot deployment/api-chatbot -c summary-worker --tail=100
kubectl get events -A --sort-by=.lastTimestamp
kubectl describe pod -n NAMESPACE NOME_DO_POD
```

Após alterar um Secret no Bitwarden, aguarde a sincronização do operador e
reinicie os consumidores que recebem valores por variáveis de ambiente:

```powershell
kubectl rollout restart deployment/api-auth -n api-auth
kubectl rollout restart deployment/api-core -n api-core
kubectl rollout restart deployment/api-chatbot -n api-chatbot
python $Lab verify --config $Config --account $Account
```

Mudanças em `api-runtime` também exigem reiniciar os consumidores para renovar
variáveis de ambiente. Não reinicie antes de o novo Secret/ConfigMap estar disponível.

Logs de aplicações podem conter informações sensíveis; revise antes de compartilhar.
Para inspecionar EC2 e acessar por SSH:

```powershell
$env:TF_DATA_DIR = Join-Path $Runtime "lab-terraform-data"
$Outputs = terraform -chdir=terraform/lab output -json | ConvertFrom-Json
$ServerIP = $Outputs.nodes.value.server.public_ip
$Key = Join-Path $Runtime "k3s-recovery/id_ed25519"
ssh -i $Key "ubuntu@$ServerIP"
# No servidor: sudo systemctl status k3s
# No agente:   sudo systemctl status k3s-agent
```

## Verificação e ensaio da feira

```powershell
python $Lab verify --config $Config --account $Account
```

Verifica nós ARM64 Ready, chaves dos Secrets sem exibir valores, Applications
Synced/Healthy, rollouts, saúde pública de Auth/Core, JWKS, CSRF, rejeição de
login vazio, rotas React, interface Observe e rejeição de acesso anônimo ao
Observe e ao Argo. Não faz migrações de banco, indexação FAQ ou inicialização
de memória. Não substitui login real, refresh/logout, chat e demonstração mobile.

Antes da feira, execute e cronometre os ensaios: End Lab/Start Lab real,
expiração natural da sessão, `--rebuild`, criação do zero em um alvo isolado e
`down --keep-network` seguido de `up`. Registre resultado e duração; esses
cenários não são declarados testados só porque os testes unitários passaram.
Inicie o Lab com folga baseada no pior tempo medido e faça o teste funcional
pela rede e pelos dispositivos da feira. Verifique saldo, prazo do curso e timer.

## Destruir

Somente as EC2 e seus registros nos targets, preservando rede e URLs:

```powershell
python $Lab down --config $Config --account $Account --keep-network --confirm-destroy $Account
python $Lab down --config $Config --account $Account --keep-network --confirm-destroy $Account --apply
```

Isso não é uma pausa: o próximo `up` fará bootstrap de um cluster novo e
pedirá token Bitwarden. NLBs, API Gateway, volumes eventualmente retidos pelo
legado e EKS legado continuam cobrando enquanto existirem.

Destruição completa de tudo que está no state, incluindo o EKS legado adotado:

```powershell
python $Lab down --config $Config --account $Account --confirm-destroy $Account
python $Lab down --config $Config --account $Account --confirm-destroy $Account --apply
```

O bucket de state e seu histórico, os bancos externos, Bitwarden e arquivos
locais de acesso são preservados. A próxima criação terá URLs novas. Revise
o plano para conferir o alvo e recursos remanescentes. Não rode o `down` antigo.
Não apague manualmente state, planos ou bucket para resolver erro de acesso.

## Diagnóstico rápido

| Sintoma | Ação |
|---|---|
| ExpiredToken / conta incorreta | Start Lab, renove o perfil e confira STS |
| Timeout SSH ou API Kubernetes | Confira IP `/32`, Lab ativo e estado EC2; execute `up` |
| Certificado após troca de IP | Execute `up --apply` para reconciliar o acesso |
| Nó perdido | Execute `up --apply`; o par será reconstruído |
| K3s corrompido | Revise e execute `up --rebuild --apply` |
| Secret não sincroniza | Confira token máquina, permissões e mapeamentos Bitwarden |
| Argo pending-* | Confirme que não há outro Helm ativo; consulte `helm history argocd -n argocd` antes de recuperar a revisão |
| Plano quer substituir rede/URLs | Preserve state e corrija configuração; `up` bloqueia essa mudança |
| Erro após apply | Corrija a causa e repita `up --apply` na mesma conta/state |
| Falha de provider no sandbox local | Execute validações em terminal com permissão para comunicação local do provider |

Não é necessário conceder novas permissões IAM para os nós. Uma operação AWS
negada deve ser tratada conforme as permissões do laboratório, sem tentar
contornar SCPs. O ambiente não promete disponibilidade fora de uma sessão ativa.
