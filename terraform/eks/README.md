# EKS ARM64 no Learner Lab

Infraestrutura nova e estado S3 separado do GKE. Não cria roles IAM: recebe
ARNs de roles existentes com trust/permissões compatíveis com EKS e EC2.
Provider AWS 6.21.x; Terraform 1.11.4+. O cluster e os nodes são provisionados
em sub-redes públicas com saída Internet Gateway, sem NAT, para reduzir custos.
Capacidade fixa; não há autoscaler. Endpoint administrativo com CIDRs restritos.

Use o [runbook](../../docs/learner-lab-feira.md) e a configuração em
`scripts/learner-lab/config.example.json`. As versões Kubernetes/add-ons precisam
ser escolhidas e ensaiadas no laboratório antes do primeiro apply.

Validação sem conta AWS:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
```

Os comandos de implantação ficam no script para garantir conta de destino,
estado/kubeconfig isolados e ordem de bootstrap. A infraestrutura GKE continua
em `../gke` até sua retirada planejada. Nunca use o estado GCS do GKE neste root.
