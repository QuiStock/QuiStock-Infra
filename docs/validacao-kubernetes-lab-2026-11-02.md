# Validação do Kubernetes descartável — 02/11/2026

Conta `637423317921`, região `us-east-1`. Fluxo: `cluster.py` e
`terraform/lab`. As horas abaixo são UTC; as durações são amostras desta
execução, não um prazo garantido pela AWS ou pelo Learner Lab.

## Ensaios reais

| Cenário | Resultado | Duração observada |
|---|---|---|
| Adoção das EC2 e rede existentes | Mesmo state remoto, mesmos IDs e URLs; aplicações verificadas | Não cronometrada |
| Criação do zero em `quistock-rehearsal` | Rede, duas EC2, K3s, Argo, Bitwarden e cinco aplicações; verificação completa passou | 11min42s |
| Destruição completa do ensaio | 39 recursos removidos; state e serviços externos preservados | 1min53s |
| Retomada a partir das duas EC2 paradas | Nenhum recurso criado/destruído; mesmos IDs, registros Kubernetes e URLs; verificação passou | 10min28s na execução final |
| Retirada do EKS inativo | Sete recursos EKS removidos; nenhum recurso EKS restante no state | Não cronometrada |
| Reutilização de charts e Applications | Versões e revisão Git existentes reconhecidas sem baixar/reinstalar charts | Conferência adicional passou |

Criação isolada: início `21:55:36`, verificada às `22:07:18`, destruição
concluída às `22:09:11`. Revisão de aplicações:
`0caeccba0bc1fcf4ed2bc6eb1ca75b9ea0242594`.

A retomada final foi executada entre `22:19:04` e `22:29:32`. A medida inclui
ajuste do endpoint Kubernetes e reconciliação Helm. A otimização final de
reutilização dos charts foi conferida separadamente, sem nova medição de
stop/start. O primeiro ensaio detectou o comportamento do provider que trata
ausência de IP público numa EC2 parada como substituição; o plano foi
interrompido antes de destruir recursos e o lifecycle foi corrigido.

Nós principais preservados: servidor `i-0986adb2bed996199`, agente
`i-033d0616f8be929d4`. Seus IPs públicos mudaram após start, e os outputs e o
kubeconfig foram atualizados. Os registros dos nós no Kubernetes são anteriores
à parada, confirmando que o cluster foi retomado e não reconstruído.

## Verificações

- 64 testes Python passaram, incluindo conta/confirmação, proteção de rede,
  reparação do par após drift, proteção do state, ausência de token em modo
  não interativo e reutilização dos charts.
- Terraform: `fmt -check`, `validate` e dois testes com provider simulado passaram.
- As cinco Applications ficaram Synced/Healthy e os rollouts concluíram.
- Passaram saúde Auth/Core, JWKS, CSRF, login vazio rejeitado, rotas React,
  interface Observe e rejeição de acesso anônimo ao Observe e ao Argo.
- O security group implícito antigo do EKS não permaneceu após a retirada.

Nenhuma migração de banco, inicialização de memória ou indexação FAQ foi feita.
O token máquina do ensaio foi transmitido em memória; não foi gravado nos
arquivos de configuração, planos, relatório ou logs. Os arquivos locais de
acesso continuam ignorados pelo Git.

## Estado entregue e limites

O ambiente principal usa duas EC2 K3s, com 39 recursos AWS gerenciados por
Terraform, sem EKS. URLs preservadas:

- [Website](https://zqfcseddfb.execute-api.us-east-1.amazonaws.com)
- [Argo CD](https://tf-lb-20261102035749067700000008-6948d4daf635aa3d.elb.us-east-1.amazonaws.com)

O teste de retomada usou `StopInstances`/`StartInstances` com a sessão do Lab
ativa. Ainda falta ensaiar a expiração natural de quatro horas e End Lab/Start
Lab pelo portal. A perda individual de um nó e `down --keep-network` têm
cobertura de lógica/plano, mas não foram executados como ensaios reais nesta
rodada. Login autenticado, chat e demonstração no dispositivo também precisam
ser ensaiados antes da feira.

Reserve inicialmente pelo menos 30 minutos para iniciar e validar o ambiente,
ajustando a antecedência conforme novos ensaios. Permissões, saldo, timer,
conectividade e disponibilidade dos provedores externos permanecem pré-condições.
Operação e todos os comandos estão no [guia atual](kubernetes-lab.md).
