# Argo CD no GKE Autopilot

Esta pasta substitui **apenas a configuração Helm do Argo CD** usada no EKS. O chart é `argo/argo-cd` versão **10.9.6** (Argo CD v3.5.3). Os manifests em `clusters/expotech` continuam específicos da AWS e não devem ser aplicados ao GKE.

O Service da interface permanece `ClusterIP`. Não é criado IP público nem load balancer. Dex, notificações e ApplicationSet ficam sem Pods porque ainda não são necessários. Os componentes ativos têm requests explícitos; no Autopilot a cobrança depende dos requests efetivos dos Pods e o GKE pode ajustá-los aos mínimos permitidos. Confirme os requests reais após a instalação.

## Instalar após criar o cluster com Terraform

No Cloud Shell, com `kubectl` apontando para o cluster GKE `quistock`, entre na raiz de um clone atualizado do `QuiStock-Infra`:

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
helm template argocd argo/argo-cd \
  --namespace argocd \
  --version 10.9.6 \
  --values clusters/us-east1/argocd/values.yaml >/tmp/quistock-argocd-rendered.yaml
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --version 10.9.6 \
  --values clusters/us-east1/argocd/values.yaml \
  --wait --timeout 20m
```

O `helm template` confere a renderização local, mas não instala nada. Revise erros antes do `upgrade --install`. O Helm gerencia a instalação inicial do Argo CD; depois, as Applications do Argo CD acompanharão o repo Infra.

## Conferir

```bash
helm list -n argocd
kubectl get pods,svc -n argocd
kubectl get svc argocd-server -n argocd
```

O `argocd-server` deve permanecer `ClusterIP`. Para abrir a interface a partir de um computador com `kubectl` configurado para este GKE, use `kubectl port-forward -n argocd svc/argocd-server 8080:443` e acesse `https://localhost:8080`. A senha inicial do usuário `admin` está no Secret `argocd-initial-admin-secret`; troque-a após o primeiro acesso e guarde-a no Bitwarden. Não cole a senha em logs, chats ou no Git.

Acompanhe os requests efetivos com `kubectl get pods -n argocd -o yaml` ou `kubectl describe pod`; ajuste os valores se houver OOM ou mudanças automáticas do Autopilot. Isso ainda não instala Core ou Auth.
