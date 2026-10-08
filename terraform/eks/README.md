# EKS ARM64 no Learner Lab

Argo CD tem um NLB público separado em TCP 443 e HTTPS NodePort 30081,
com autenticação obrigatória e certificado autoassinado. Não exige CloudFront,
ACM ou domínio. IPv4 público em 443 é aberto a qualquer origem conforme
configuração autorizada. Veja o runbook para `update --migrate-argocd-public`
ao retomar o apply antigo; a exceção de destruição fica restrita à entrada do Argo.

Infraestrutura nova e estado S3 separado do GKE. NÃ£o cria roles IAM: recebe
ARNs de roles existentes com trust/permissÃµes compatÃ­veis com EKS e EC2.
Provider AWS 6.21.x; Terraform 1.11.4+. O cluster e os nodes sÃ£o provisionados
em sub-redes pÃºblicas com saÃ­da Internet Gateway, sem NAT, para reduzir custos.
Capacidade fixa; nÃ£o hÃ¡ autoscaler. Endpoint administrativo com CIDRs restritos.

Use o [runbook](../../docs/learner-lab-feira.md) e a configuraÃ§Ã£o em
`scripts/learner-lab/config.example.json`. As versÃµes Kubernetes/add-ons precisam
ser escolhidas e ensaiadas no laboratÃ³rio antes do primeiro apply.

ValidaÃ§Ã£o sem conta AWS:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test # plano com provider mock, sem acesso AWS
```

Os comandos de implantaÃ§Ã£o ficam no script para garantir conta de destino,
estado/kubeconfig isolados e ordem de bootstrap. A infraestrutura GKE continua
em `../gke` atÃ© sua retirada planejada. Nunca use o estado GCS do GKE neste root.
