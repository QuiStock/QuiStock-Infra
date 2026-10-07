# Argo CD no EKS ARM64

Chart `argo/argo-cd` 10.9.6, instalado pelo script de bootstrap. O Service usa ClusterIP e não cria balanceador público. O selector global preserva ARM64. Dex, ApplicationSet e notificações permanecem desativados.

Para operação:

```bash
kubectl port-forward svc/argocd-server -n argocd 8443:443
```

Acesse `https://localhost:8443`. O certificado padrão pode gerar aviso local. Recupere a senha inicial somente em terminal privado, troque-a após o primeiro acesso e guarde no Bitwarden. O operador deve conferir KUBECONFIG e conta antes de qualquer comando.

Veja o [runbook](../../../docs/learner-lab-feira.md) para instalação, versões, acesso e recuperação. Argo CD acompanha os mesmos paths GitOps anteriores; nenhuma pipeline de release precisa mudar de diretório.
