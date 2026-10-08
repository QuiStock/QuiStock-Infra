# Argo CD no EKS ARM64

Chart `argo/argo-cd` 10.9.6, instalado pelo script de bootstrap. Terraform cria
um NLB público separado com endereço HTTPS `elb.amazonaws.com`. TCP 443
encaminha ao HTTPS do Argo CD na NodePort 30081. O HTTP/NodePort 30082 não é
aberto publicamente. Não exige CloudFront, ACM, domínio ou controlador AWS.

Entrada pública IPv4 em 443 é aberta a qualquer origem. O login é obrigatório
(`users.anonymous.enabled=false`) e TLS permanece habilitado
(`server.insecure=false`). O certificado padrão é autoassinado; o navegador
mostra um aviso. O bootstrap configura `configs.cm.url` com o endereço real.
Selector global ARM64; Dex, ApplicationSet e notificações permanecem desativados.

Para operação local:

```bash
kubectl port-forward svc/argocd-server -n argocd 8443:443
```

Acesse `https://localhost:8443`. Para a CLI pública, use
`argocd login NOME.elb.amazonaws.com --insecure` para aceitar o certificado.
Recupere a senha somente em terminal privado e guarde-a no Bitwarden. Confira
KUBECONFIG/conta antes de operar. Teste login, sincronização e logs no navegador.

Veja o [runbook](../../../docs/learner-lab-feira.md) para atualização do cluster
existente com `update --migrate-argocd-public --apply`, recuperação e troca de
conta. Argo CD preserva os paths GitOps em `clusters/us-east1`.
