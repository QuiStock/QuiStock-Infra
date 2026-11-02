# QuiStock Infra

Infraestrutura AWS com Terraform, EKS ARM64, Argo CD e Bitwarden Secrets Manager.

- **Primeiro deploy:** [criar a infraestrutura do zero no PowerShell](docs/deploy-aws-do-zero.md).
- **Operação:** [senha do Argo CD, rotação de secrets, rollout e diagnóstico](docs/comandos-operacao-aws.md).
- **Teste funcional:** [roteiro atômico de validação](docs/teste-aws-passo-a-passo.md).
- **Evidências:** [resultado do teste AWS de 02/11/2026](docs/resultado-teste-aws-2026-11-02.md).
- **Arquitetura:** [aplicações e caminhos no cluster](clusters/us-east1/README.md).

O deploy usa bancos e provedores externos já preparados. Não execute migrações,
inicialização de memória ou indexação FAQ no banco de teste compartilhado.
