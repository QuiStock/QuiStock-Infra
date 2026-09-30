# Runbook: EKS Auto Mode, Argo CD e releases

Este documento registra o ambiente `expotech` e a ordem para reconstruí-lo. Comandos de cluster usam AWS CloudShell em `us-east-1`; os nomes e ARNs de IAM mudam quando o Learner Lab é recriado. Nunca copie credenciais de banco, LLM, tokens ou o Secret de Argo CD para este repositório.

## 1. Criar o cluster

O cluster atual `quistock` foi criado pelo console EKS com Kubernetes 1.36 e EKS Auto Mode. O Auto Mode está habilitado para computação e load balancing, com NodePools internos `system` e `general-purpose`. Ele usa roles de cluster e de nó fornecidas pelo Learner Lab. O endpoint público da API Kubernetes está habilitado. Esses IDs da conta atual são transitórios.

Para repetir pelo console: inicie o Learner Lab, escolha `us-east-1`, abra **EKS → Create cluster → Quick configuration**, selecione as roles de cluster e nó do laboratório e subnets da VPC, habilite EKS Auto Mode e aguarde o status **Active**. O [guia oficial do console](https://docs.aws.amazon.com/eks/latest/userguide/automode-get-started-console.html) descreve cada tela.

Para automatizar quando as permissões da nova conta permitirem, use [`scripts/create-auto-cluster.sh`](../scripts/create-auto-cluster.sh). Ele **cria** um cluster novo e exige as roles e subnets da nova conta:

```bash
export AWS_REGION=us-east-1
export CLUSTER_NAME=quistock
export K8S_VERSION=1.36
export CLUSTER_ROLE_ARN='<ARN da role EKS do novo lab>'
export NODE_ROLE_ARN='<ARN da role de nós do novo lab>'
export SUBNET_IDS_JSON='["subnet-...","subnet-..."]'
./scripts/create-auto-cluster.sh
```

A execução requer `eks:CreateCluster`, acesso às roles (`iam:PassRole`) e a rede/subnets preparadas. O Learner Lab pode negar ações IAM; nesse caso, use as roles existentes e a opção do console. A [AWS documenta o mesmo modelo de criação via CLI](https://docs.aws.amazon.com/eks/latest/userguide/automode-get-started-cli.html). Não reutilize ARNs ou subnet IDs de uma conta antiga.

Conecte `kubectl` e confirme:

```bash
aws eks update-kubeconfig --region us-east-1 --name quistock
kubectl config current-context
kubectl get nodepools
```

Antes dos comandos com caminhos locais, obtenha a branch principal do repositório:

```bash
git clone https://github.com/QuiStock/QuiStock-Infra.git
cd QuiStock-Infra
```

## 2. Criar o NodePool ARM64

O serviço usa `m6g.large` ARM64 na NodePool `quistock-arm`. A instalação do Argo CD usa esse NodePool, portanto crie-o **antes** do Helm:

```bash
kubectl apply -f clusters/expotech/nodepools/quistock-arm.yaml
kubectl get nodepool quistock-arm
```

O manifest usa o `NodeClass default` do EKS Auto Mode. Ao agendar os primeiros Pods, confirme que surgiram nós Ready com `kubectl get nodes -L kubernetes.io/arch,karpenter.sh/nodepool`.

## 3. Instalar Argo CD

O chart Helm do Argo CD usa [`clusters/expotech/argocd/values.yaml`](../clusters/expotech/argocd/values.yaml), que agenda os componentes no NodePool ARM64. O cluster atual usa o chart Helm `argo-cd-10.9.2` (confirmado pelo label do Deployment `argocd-server`). O CloudShell atual não tem `helm` instalado; [instale Helm 3 pelo procedimento oficial](https://docs.helm.sh/docs/v3/intro/install/) e confira `helm version`. Fixe a versão do chart:

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --values clusters/expotech/argocd/values.yaml \
  --version 10.9.2
kubectl rollout status deployment/argocd-server -n argocd --timeout=5m
```

No cluster atual, o Service `argocd-server` é `ClusterIP`. Para acesso local, use `kubectl port-forward -n argocd svc/argocd-server 8080:443` em um terminal **no computador** e abra `https://localhost:8080`. O usuário inicial é `admin`; obtenha a senha no cluster com `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`. Troque a senha inicial e remova esse Secret depois da troca, conforme o [guia do Argo CD](https://argo-cd.readthedocs.io/en/stable/getting_started/). Guarde a senha nova no Bitwarden.

## 4. Bootstrap do estado GitOps

Aplique as Applications uma vez para que o Argo CD passe a acompanhar a branch protegida `main` do Infra:

```bash
kubectl apply -f clusters/expotech/bootstrap/nodepool-application.yaml
kubectl apply -f clusters/expotech/bootstrap/api-core-namespace.yaml
kubectl apply -f clusters/expotech/bootstrap/api-chatbot-namespace.yaml
kubectl apply -f clusters/expotech/bootstrap/web-frontend-namespace.yaml
```

Antes de aplicar cada Application de serviço, complete o Secret e confirme que a imagem referida no Deployment existe e pode ser baixada. Então:

```bash
kubectl apply -f clusters/expotech/bootstrap/api-core-application.yaml
kubectl apply -f clusters/expotech/bootstrap/api-chatbot-application.yaml
kubectl apply -f clusters/expotech/bootstrap/web-frontend-application.yaml
kubectl get applications -n argocd
```

Não aplique as Applications do chatbot ou frontend enquanto o digest no manifest ainda for `:bootstrap`. Esse marcador é substituído pela PR da primeira release de cada repositório.

## 5. Secrets fora do Git

Mantenha os valores no Bitwarden. No cluster novo, recrie Secrets no namespace certo; nunca publique a saída de `kubectl get secret -o yaml`.

- `api-core/postgres-db`: `DB_URL` (JDBC PostgreSQL com TLS), `DB_USERNAME`, `DB_PASSWORD`. O cluster atual usa o banco de **teste** do Aiven.
- `api-chatbot/chatbot-external`: `GEMINI_API_KEY`, `GROQ_API_KEY`, `MONGODB_URI`, `MONGODB_DB`, `QDRANT_URL`, `QDRANT_API_KEY`, `REDIS_URL`.

Crie os Secrets com os valores copiados do cofre em um terminal privado. Uma opção é montar arquivos locais temporários `.env` fora do repositório, com exatamente as chaves listadas, e executar:

```bash
kubectl create secret generic postgres-db \
  --namespace api-core \
  --from-env-file=/caminho/privado/api-core.env
kubectl create secret generic chatbot-external \
  --namespace api-chatbot \
  --from-env-file=/caminho/privado/chatbot.env
kubectl describe secret postgres-db -n api-core
kubectl describe secret chatbot-external -n api-chatbot
```

`describe` confirma nomes e tamanhos das chaves, sem revelar valores. Remova o arquivo temporário após a criação. Para trocar credenciais, atualize o Secret e reinicie os Deployments conforme necessário. Para o cluster temporário, o time escolheu **instâncias de teste** de Gemini/Groq, MongoDB, Qdrant e Redis. As credenciais serão fornecidas pelo responsável pelo chatbot. Não use valores produtivos nesse Secret.

## 6. Publicar serviços por release

O `DS_Backend` já segue este fluxo. A API Chatbot passa a segui-lo depois do merge das PRs de contêiner e Infra:

1. CI valida o build `linux/arm64`.
2. Crie uma release estável no repositório do serviço.
3. GitHub Actions publica a imagem no GHCR e abre uma PR no `QuiStock-Infra` alterando o digest da imagem. A branch `main` do Infra requer PR.
4. Revise e faça merge da PR de Infra. O Argo CD sincroniza `main` automaticamente.
5. O Deployment usa `RollingUpdate` com `maxSurge: 1` e `maxUnavailable: 0`. Valide nova imagem, Pod Ready e Service HTTP.

Cada repositório produtor precisa de `INFRA_REPO_TOKEN` como GitHub Actions secret, com permissões **Contents: read/write** e **Pull requests: read/write** somente no repositório Infra. A imagem GHCR deve ser pública ou o namespace precisa de um `imagePullSecret`. Não coloque o token em workflows ou manifests.

Validação exemplo:

```bash
kubectl get application api-core -n argocd
kubectl rollout status deployment/api-core -n api-core --timeout=5m
kubectl get pods -n api-core -o wide
kubectl get deployment api-core -n api-core -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

Para testar o Service localmente, `kubectl port-forward -n api-core svc/api-core 18080:80` e, em outro terminal, `curl -i http://127.0.0.1:18080/api/flows`. O `HTTP 200` e `[]` foram observados no cluster atual. Os logs também mostraram conexão PostgreSQL aberta pelo Hikari.

## 7. Comunicação e acesso público

A Core acessará o chatbot internamente pelo DNS `http://api-chatbot.api-chatbot.svc.cluster.local`. O Service `ClusterIP` do chatbot não é público. Site React e aplicativo mobile precisam de endpoints HTTPS públicos para Core e Auth; o Argo CD pode permanecer privado. EKS Auto Mode pode criar um ALB por `IngressClass`/`Ingress`; domínio, certificado ACM e regras serão adicionados quando os serviços e contratos de API estiverem prontos. [Referência AWS](https://docs.aws.amazon.com/eks/latest/userguide/auto-configure-alb.html).

## 8. Estado pendente

- **API Chatbot:** publicar primeira imagem, configurar o token de Infra, obter credenciais das instâncias de teste com o responsável, criar Secret e aplicar a Application; validar `/health` e uma requisição real com serviços externos.
- **API Auth:** repositório ainda não existe. Repetir o padrão de Dockerfile ARM64, workflow de release, namespace, Secret, Deployment, Service e Application quando existir.
- **Frontend React:** o repositório `QuiStock/quistock-dad` tem PRs para imagem ARM64 e Application. Após merge, configurar o token de Infra, publicar primeira release, aprovar PR de digest, aplicar Application e testar o Service. O login atual em `src/partials/BoxLogin/index.tsx` apenas verifica se os campos foram preenchidos; ainda não autentica. Alinhar `VITE_API_URL` e rotas `/stores`/`/managers` com APIs reais antes de expor o site como funcional.
- **Mobile:** não roda no EKS. Configurar a URL pública de Auth/Core no app e distribuir por sua própria esteira.
- **Reconstrução integral:** registrar a versão Helm atual e os IDs de rede/roles da nova conta. As permissões do Learner Lab podem impedir a criação automatizada dessas roles.
