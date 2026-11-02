# QuiStock Infra

Infraestrutura AWS com Terraform, Kubernetes K3s ARM64, Argo CD e Bitwarden Secrets Manager.

- **Guia atual:** [arquitetura, criação, retomada, reconstrução, acesso ao Argo, verificação e destruição](docs/kubernetes-lab.md).
- **Configuração:** [exemplo do cluster descartável](scripts/learner-lab/cluster.example.json).
- **Histórico EKS:** [deploy anterior](docs/deploy-aws-do-zero.md) e [operação anterior](docs/comandos-operacao-aws.md).
- **Histórico da recuperação:** [transição emergencial para K3s](docs/recuperacao-k3s-lab.md).
- **Teste funcional:** [roteiro atômico de validação](docs/teste-aws-passo-a-passo.md).
- **Validação atual:** [criação do zero, destruição e retomada K3s em 02/11/2026](docs/validacao-kubernetes-lab-2026-11-02.md).
- **Evidências EKS históricas:** [resultado do teste anterior](docs/resultado-teste-aws-2026-11-02.md).
- **Arquitetura:** [aplicações e caminhos no cluster](clusters/us-east1/README.md).

O deploy usa bancos e provedores externos já preparados. Não execute migrações,
inicialização de memória ou indexação FAQ no banco de teste compartilhado.
