# EKS ARM64 no Learner Lab

Argo CD tem URL HTTPS CloudFront com certificado padrão e origem VPC no NLB
privado existente (listener 81, NodePort 30081), sem outro balanceador ou domínio.
Exige permissão CloudFront/VPC origins e a service-linked role correspondente.
Em us-east-1, `use1-az3` não é suportada; o plano rejeita essa zona.
Para clusters existentes use `lab.py update` e depois `update --apply`;
esse caminho preserva os tokens Bitwarden e recusa destruição/substituição.

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
