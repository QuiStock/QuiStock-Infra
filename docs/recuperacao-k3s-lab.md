# Recuperação com Kubernetes autogerenciado no Learner Lab

> Registro da recuperação emergencial. O ciclo de vida independente do EKS
> passa a ser operado por `cluster.py`, conforme o [guia atual](kubernetes-lab.md).

Use quando as EC2 do EKS são criadas, mas o bootstrap dos nós falha e não há
uma configuração EKS suportada disponível no laboratório. O diagnóstico desta
conta foi uma negação explícita de SCP para `ec2:DescribeInstances` no nodeadm.
Recriar o mesmo EKS não corrige essa negação. Este caminho usa K3s em EC2 com
operações autorizadas pelo laboratório; não altera IAM ou SCP.

## Arquitetura e limites

Dois nós Ubuntu 24.04 ARM64 `t4g.large`, um servidor K3s e um agente. São
Kubernetes e Argo CD reais, mas não EKS. O servidor único não oferece alta
disponibilidade. O estado Kubernetes fica no EBS do servidor: não termine essa
instância sem backup. Uma nova destruição das EC2 pelo laboratório exige
recuperação a partir de backup ou outro bootstrap; esta mudança não garante
persistência imposta pelo Lab.

Reaproveita VPC, subnets, security group dos nós, NLBs, target groups e API
Gateway existentes. Mantém URLs e bancos externos. Os novos nós não recebem
perfil IAM: K3s não precisa de credenciais AWS para esta configuração.
O security group adicional permite SSH e API Kubernetes somente para os
`admin_cidrs` /32 existentes; portas entre nós são restritas ao próprio grupo.
Traefik e ServiceLB ficam desabilitados; os manifests usam os NodePorts atuais.

O EKS original e seu Terraform state são preservados. Os novos recursos são
gerenciados pelo script e registrados em `k3s-recovery/recovery.json`, e ainda
não pertencem ao Terraform. Não use `lab.py update/up/down` para administrar
esse novo cluster. Após publicação, os anexos ASG aos target groups ficam
diferentes do Terraform original; um apply pode restaurar o roteamento antigo.
`lab.py verify` também continua apontando para o EKS: use `recover_k3s.py verify`
para verificar o novo cluster, conforme os comandos abaixo.
O EKS e os nós originais continuam consumindo créditos enquanto existirem.

## Recuperação executada em 02/11/2026

Na conta `637423317921`, os novos nós `i-0986adb2bed996199` (servidor) e
`i-033d0616f8be929d4` (agente) ficaram Ready com `v1.37.1+k3s1`.
As cinco Applications ficaram Synced/Healthy e seus rollouts concluíram.
Os dois novos targets ficaram saudáveis em ambos os NLBs; o ASG antigo foi
desanexado, e os targets antigos concluíram a drenagem.

O `verify` completo terminou com exit code 0. Passaram saúde pública de Auth
e Core, JWKS, CSRF, rejeição de login vazio, rotas React, interface Observe,
rejeição de acesso anônimo ao Observe e ao Argo CD. Isso não substitui os
testes funcionais autenticados de login, chat e operações comerciais.
A senha administrativa, chave de sessão e certificado do Argo foram
comparados em memória e preservados. Os 51 testes unitários passaram.

URLs preservadas:

- Website: <https://zqfcseddfb.execute-api.us-east-1.amazonaws.com>
- Argo CD: <https://tf-lb-20261102035749067700000008-6948d4daf635aa3d.elb.us-east-1.amazonaws.com>

Após a verificação, a redução do nodegroup EKS antigo concluiu com status
Successful e `minSize=0,maxSize=2,desiredSize=0`, evitando manter as duas EC2 defeituosas.
Essa capacidade também difere do Terraform original. O control plane EKS
continua existindo e consumindo créditos; preserva os Secrets originais.
Não execute o `down` antigo: ele também removeria a rede e as URLs em uso.

## Execução e retomada

Requer AWS CLI, Python, kubectl, Terraform, Helm e OpenSSH. Ferramentas em
`.learner-lab/tools` também são reconhecidas. A API EKS antiga precisa estar
acessível para copiar os Secrets. Eles passam diretamente entre APIs em
memória, sem imprimir ou gravar seus valores. As chaves SSH e o kubeconfig
ficam no diretório local ignorado pelo Git: proteja-o como credencial.

```powershell
$env:AWS_PROFILE = "quistock-lab"
$Account = "637423317921"
$Config = ".learner-lab/config-$Account.json"
$Recovery = "scripts/learner-lab/recover_k3s.py"

python $Recovery prepare --config $Config --account $Account
python $Recovery provision --config $Config --account $Account
python $Recovery install --config $Config --account $Account
python $Recovery migrate --config $Config --account $Account
# Publica somente após rollouts e Applications Synced/Healthy.
python $Recovery publish --config $Config --account $Account
python $Recovery verify --config $Config --account $Account

$env:KUBECONFIG = Join-Path $PWD ".learner-lab/$Account/us-east-1/quistock/k3s-recovery/kubeconfig"
kubectl get nodes -o wide
kubectl get pods -A
```

`prepare` fixa a release estável publicada no GitHub no inventário local.
`provision` reutiliza os IDs registrados e tokens de idempotência EC2.
`install` pode ser repetido para atualizar o kubeconfig após uma mudança de IP
público. `migrate` preserva os Secrets das aplicações e do Argo CD, inclusive a
senha e o certificado, e reinstala charts e Applications. Não copia tokens
de ServiceAccount nem histórico de releases Helm.

`publish` registra primeiro ambos os novos nós nos dois target groups e espera
que fiquem saudáveis. Só então desanexa os target groups do ASG antigo, salvando
antes a lista dos targets anteriores. A verificação pública pode aguardar o
período de drenagem dos antigos targets. Em falhas, consulte o inventário e
retome a mesma fase; não apague o diretório para gerar outro estado.

Para rollback do roteamento, reconecte os dois target groups ao ASG registrado
em `old_asg` e remova os dois novos targets, somente após confirmar que os nós
EKS voltaram a atender as aplicações. O script não destrói nenhum cluster.

## Documentação do K3s

- [Requisitos ARM64 e rede](https://docs.k3s.io/installation/requirements)
- [Configuração de instalação](https://docs.k3s.io/installation/configuration)
- [Serviços de rede](https://docs.k3s.io/networking/networking-services)
