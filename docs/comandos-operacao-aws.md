# Comandos de operação AWS

> Estes comandos apontam para o EKS anterior. Criação, recuperação, acesso ao
> Argo, verificação e destruição do K3s estão no [guia atual](kubernetes-lab.md).

Exemplos para PowerShell 7.1+, executados na raiz de `QuiStock-Infra`.
Para criar tudo pela primeira vez, siga [deploy do zero](deploy-aws-do-zero.md).
Esta página não exige executar Terraform para consultar o cluster ou reiniciar pods.

## 1. Abrir uma sessão de operação

Em cada novo terminal, selecione a conta esperada e a configuração local existente:

```powershell
$RepoRoot = (Resolve-Path .).Path
$env:AWS_PROFILE = "quistock-lab"
$Account = Read-Host "ID da conta AWS esperada (12 dígitos)"
if ($Account -notmatch '^\d{12}$') { throw "Conta inválida." }
$Config = Join-Path $RepoRoot ".learner-lab\config-$Account.json"
$Lab = Join-Path $RepoRoot "scripts\learner-lab\lab.py"
$LabConfig = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$Region = $LabConfig.region
$Cluster = $LabConfig.cluster_name
$env:AWS_REGION = $Region
$ActualAccount = (aws sts get-caller-identity --query Account --output text).Trim()
if ($LASTEXITCODE -ne 0 -or $ActualAccount -ne $Account) { throw "Perfil AWS não corresponde à conta esperada." }
$env:KUBECONFIG = Join-Path $RepoRoot ".learner-lab\$Account\$Region\$Cluster\kubeconfig"
aws eks update-kubeconfig --name $Cluster --region $Region --kubeconfig $env:KUBECONFIG
kubectl config current-context
kubectl get nodes
```

**Esperado:** contexto `arn:aws:eks:<região>:<conta>:cluster/<cluster>` e nós Ready.
`ExpiredToken` exige renovar as credenciais AWS, não recriar o cluster.
O `lab.py` define KUBECONFIG apenas no processo filho: exportá-lo neste terminal
é necessário para que seus comandos `kubectl` usem o mesmo arquivo.

## 2. Descobrir a senha inicial do Argo CD

O usuário inicial é **`admin`**. Execute em terminal privado: o último comando
abaixo mostra a senha, portanto não o use em terminal gravado ou compartilhado.

```powershell
$ArgoPasswordBase64 = kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}'
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ArgoPasswordBase64)) { throw "Secret inicial indisponível; não tente decodificar argocd-secret." }
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ArgoPasswordBase64))
Remove-Variable ArgoPasswordBase64
```

Se a CLI `argocd` estiver instalada, a alternativa é:

```powershell
argocd admin initial-password -n argocd
```

Essa é a **senha inicial**, não uma recuperação de senha alterada. Se ela já foi
trocada ou o Secret inicial removido, use a senha guardada pelo administrador.
`argocd-secret` armazena hash, que não pode ser decodificado para recuperar a senha.
Este roteiro não redefine senhas nem remove Secrets.

A URL pública aparece na saída de `lab.py public`. O Argo deste projeto usa
certificado autoassinado no NLB próprio. Como alternativa de acesso local:

```powershell
kubectl port-forward svc/argocd-server -n argocd 8443:443
```

Mantenha esse terminal aberto e acesse `https://localhost:8443`.
O port-forward não torna o certificado confiável; segue sendo o certificado do Argo.
O website e o Observe usam o HTTPS separado do API Gateway.

Referência: [acesso e senha inicial do Argo CD](https://argo-cd.readthedocs.io/en/stable/getting_started/#4-login-using-the-cli).

## 3. Aplicar alterações de secrets do Bitwarden aos pods

A sequência é **salvar no Bitwarden → confirmar sincronização do Secret Kubernetes
→ reiniciar o Deployment consumidor → conferir rollout e saúde**. Argo Refresh
sozinho não atualiza variáveis de ambiente de um container já iniciado.
Essa necessidade de reinício é descrita na [documentação Kubernetes de Secrets](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/#define-container-environment-variables-using-secret-data).

### Escolher o consumidor

| Namespace | BitwardenSecret / Secret Kubernetes | Deployment a reiniciar |
| --- | --- | --- |
| `api-auth` | `auth-external` | `api-auth` |
| `api-core` | `core-external` | `api-core` |
| `api-chatbot` | `chatbot-external` | `api-chatbot` — reinicia API e worker |
| `api-chatbot` | `chatbot-runtime-external` | `api-chatbot` — os dois secrets de runtime são consumidos somente pela API |

`chatbot-runtime-external` contém `TYPESAFE_API_KEY` e
`OBSERVABILITY_SESSION_SECRET`, com UUIDs vindos da configuração local.
Website e Observe são frontends; não recebem esses secrets no build ou no pod.
Não é necessário reiniciá-los por rotação de chave dos provedores da IA.
Trocar o segredo de sessão do Observe exige novo login no Observe.

Se um mesmo item Bitwarden alimenta mais de um serviço, confira a sincronização
e reinicie cada consumidor afetado, um por vez.

### Confirmar a sincronização

Exemplo para uma chave de IA, como `OPENAI_API_KEY`. Ajuste as três variáveis
conforme a tabela antes de executar.

```powershell
$Namespace = "api-chatbot"
$SecretName = "chatbot-external"
$Deployment = "api-chatbot"
kubectl get secret $SecretName -n $Namespace -o 'custom-columns=NAME:.metadata.name,VERSION:.metadata.resourceVersion'
```

Anote a versão **antes de editar o item**. Agora salve o novo valor no Bitwarden
Secrets Manager, mantendo o mesmo UUID. Aguarde a sincronização periódica do
operador; o intervalo depende da configuração instalada. Acompanhe somente metadados:

```powershell
kubectl get secret $SecretName -n $Namespace -o 'custom-columns=NAME:.metadata.name,VERSION:.metadata.resourceVersion' --watch
```

Use `Ctrl+C` após observar atualização. Confira também o resultado da reconciliação:

```powershell
kubectl get bitwardensecret $SecretName -n $Namespace -o jsonpath='{.status}'
```

Uma nova `resourceVersion` indica atualização do objeto, não prova isoladamente
qual valor foi recebido. Confirme sincronização bem-sucedida após a edição no
status/logs do operador e depois valide a aplicação. Se já editou o Bitwarden
antes de anotar a versão, use o status de sincronização, em vez de esperar uma
segunda mudança desnecessária. Não imprima `.data`, `env` ou o YAML completo de Secrets.

Se a sincronização falhar:

```powershell
kubectl get pods -n sm-operator-system
kubectl logs -n sm-operator-system deployment/sm-operator-controller-manager --all-containers=true --tail=80
```

Confira token da machine account, acesso aos itens e seus UUIDs. Não avance para
o restart esperando que ele sincronize o Bitwarden. Reiniciar pods consumidores
antes da sincronização apenas os inicia com os valores antigos. Não é necessário
reiniciar o operador na rotação normal. Consulte o [operador oficial Bitwarden](https://bitwarden.com/help/secrets-manager-kubernetes-operator/).

### Forçar os pods a receber os valores sincronizados

Depois de confirmar a sincronização:

```powershell
kubectl rollout restart "deployment/$Deployment" -n $Namespace
kubectl rollout status "deployment/$Deployment" -n $Namespace --timeout=5m
kubectl get pods -n $Namespace -o wide
```

**Atalhos**, para usar somente nos serviços afetados, após sincronizar seus Secrets:

```powershell
kubectl rollout restart deployment/api-auth -n api-auth
kubectl rollout status deployment/api-auth -n api-auth --timeout=5m

kubectl rollout restart deployment/api-core -n api-core
kubectl rollout status deployment/api-core -n api-core --timeout=5m

kubectl rollout restart deployment/api-chatbot -n api-chatbot
kubectl rollout status deployment/api-chatbot -n api-chatbot --timeout=5m
```

O último reinicia API e `summary-worker`, que compartilham o pod.
Espere a conclusão de cada rollout antes de iniciar o próximo; há capacidade
limitada no Lab. Confira login, fluxo afetado e health. Se falhar, use a seção 5.
`rollout undo` não restaura o valor antigo do Secret; uma reversão de credencial
exige corrigir o item no Bitwarden, sincronizar e realizar novo rollout.

### UUID novo ou token da machine account substituído

Trocar o **valor do mesmo item** segue a sequência acima. Trocar seu **UUID**
exige atualizar o mapeamento correspondente: os três manifests para itens usuais,
ou `bitwarden_secret_ids` da configuração local para os dois itens de runtime.
A mudança de mapeamento deve ser revisada pelo fluxo do projeto antes de aplicá-la.

Para renovar o token da machine account, o bootstrap existente solicita a nova
credencial por prompt oculto e atualiza `bw-auth-token` nos três namespaces:

```powershell
python $Lab bootstrap --account $Account --config $Config
```

Esse comando reexecuta o bootstrap completo; não é apenas um restart. Depois,
confira a sincronização e reinicie os consumidores se seus valores mudaram.

## 4. Solicitar atualização do Git no Argo CD

Para reler os manifests da branch configurada, após um commit já estar remoto:

```powershell
kubectl annotate application -n argocd api-auth api-core api-chatbot observe website argocd.argoproj.io/refresh=hard --overwrite
kubectl get applications -n argocd -o 'custom-columns=NAME:.metadata.name,REVISION:.spec.source.targetRevision,SYNC:.status.sync.status,HEALTH:.status.health.status'
```

Com a sincronização automática configurada no projeto, o Argo reconcilia os
manifests. O comando não faz build/publicação de imagem, não muda a branch,
não sincroniza valores do Bitwarden e não garante restart se o template do pod
não mudou. Para secrets, use a seção 3. Para nova imagem, confirme primeiro o
digest desejado no Deployment antes de interpretar `rollout status` como sucesso
da revisão nova.

## 5. Diagnóstico sem expor secrets

```powershell
kubectl get nodes -o wide
kubectl get applications -n argocd
kubectl get pods -A
kubectl get events -n api-chatbot --sort-by=.metadata.creationTimestamp
kubectl describe pods -n api-chatbot -l app=api-chatbot
kubectl logs deployment/api-chatbot -n api-chatbot -c api-chatbot --tail=100
kubectl logs deployment/api-chatbot -n api-chatbot -c summary-worker --tail=100
```

Para o container anterior após um crash, identifique o pod atual e use
`kubectl logs <POD> -n api-chatbot -c api-chatbot --previous --tail=100`.
Logs podem conter dados da aplicação; revise-os antes de compartilhá-los.

| Sintoma | Próximo passo |
| --- | --- |
| IA `1/2 Running` | Veja API e worker separadamente; health depende dos provedores e bancos |
| `Pending` | Veja Events, memória/IPs disponíveis nos nós e capacidade para o rollout |
| `ImagePullBackOff` | Confira digest, publicação pública e arquitetura ARM64 |
| Secret ausente | Veja status do BitwardenSecret e logs do operador; não substitua por valor no manifest |
| `Forbidden` / timeout de kubectl | Confira STS, perfil, kubeconfig, role administrativa e IP `/32` |
| Modelo TypeSafe indisponível | Confira catálogo do provedor e `TYPESAFE_JEV_MODEL`; o teste usou `jev-latest` |
| Observe sem dados | Confira logs/métricas da IA; não presuma senha inválida se login respondeu 200 |

Verificação completa da infraestrutura já criada:

```powershell
python $Lab verify --account $Account --config $Config
```

Para reler URLs e verificar os caminhos públicos pelo fluxo do bootstrap:

```powershell
python $Lab public --account $Account --config $Config
```

Não use `down`, exclusão de pods em massa, migrações ou reinicialização dos
bancos como tentativa de diagnóstico.
