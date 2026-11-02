# Learner Lab com K3s descartável

Use `scripts/learner-lab/cluster.py` para configurar o backend, conferir a
conta, gerar variáveis e revisar/aplicar os planos. O [guia completo](../../docs/kubernetes-lab.md)
documenta criação, retomada, reconstrução, adoção e destruição.

O root gerencia toda a infraestrutura AWS. Uma criação nova não cria EKS ou
roles IAM. `legacy.tf` e seus `moved` blocks existem apenas para adotar o
state histórico sem trocar as URLs e retirar posteriormente o EKS inativo.
Não use `terraform/eks` sobre um state já adotado.

`compute_enabled=false` remove os nós/targets e preserva a rede. A destruição
completa remove os recursos deste state; não remove bancos externos, Bitwarden
ou o bucket que guarda o próprio state. `adopt_instances` e
`adopt_security_group` são preenchidos somente na primeira importação.
