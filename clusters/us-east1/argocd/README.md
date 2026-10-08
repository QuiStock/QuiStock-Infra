# Argo CD no EKS ARM64

Chart `argo/argo-cd` 10.9.6, instalado pelo script de bootstrap. Terraform publica uma URL HTTPS `cloudfront.net` com certificado da AWS e origem VPC no NLB privado existente. O Service NodePort HTTP 30081 aceita tráfego somente do NLB. O selector global preserva ARM64. Dex, ApplicationSet e notificações permanecem desativados.

Para operação:

```bash
kubectl port-forward svc/argocd-server -n argocd 8080:80
```

Acesse `http://localhost:8080` para operação local. A URL pública HTTPS é impressa pelo script; o bootstrap configura `configs.cm.url` com esse endereço. TLS termina no CloudFront; `server.insecure` habilita HTTP somente no caminho privado até o servidor. Cache fica desabilitado e cookies/Authorization/query strings são encaminhados. Login continua obrigatório; CORS aberto das APIs não se aplica ao Argo CD.

Recupere a senha inicial somente em terminal privado, troque-a após o primeiro acesso e guarde no Bitwarden. O operador deve conferir KUBECONFIG e conta antes de qualquer comando. Para CLI remota use `argocd login DOMINIO.cloudfront.net --grpc-web`; gRPC nativo não é suportado pela origem VPC. Teste login, acompanhamento de sincronização e logs na conta real.

Veja o [runbook](../../../docs/learner-lab-feira.md) para instalação, versões, acesso e recuperação. Argo CD acompanha os mesmos paths GitOps anteriores; nenhuma pipeline de release precisa mudar de diretório.
