# Cluster GKE do QuiStock

Este diretório cria **somente** o cluster GKE Autopilot de teste, uma VPC, uma sub-rede com faixas para Pods e Services e habilita as APIs Compute Engine e Kubernetes Engine. Região padrão: `us-east1`. O projeto é variável para permitir reconstrução em outra conta. Nenhum comando abaixo deve ser executado dentro do repositório sem conferir o projeto ativo.

Os manifests em `clusters/expotech` ainda são específicos do EKS (por exemplo, `karpenter.sh/nodepool: quistock-arm`). **Não aplique as Applications da AWS ao GKE**. A instalação do Argo CD, a adaptação dos Deployments, os Secrets e a entrada pública serão etapas posteriores, em PRs separadas.

## Antes de começar

- Faturamento ativo no projeto Google Cloud e permissões para habilitar APIs, criar VPC, bucket e cluster GKE.
- Google Cloud Shell com `gcloud` e Terraform. Confira `terraform version`.
- Escolha uma região que ofereça ARM64 no GKE Autopilot; `us-east1` é a região inicial do projeto. As imagens atuais do QuiStock são ARM64.
- Confirme que os intervalos `10.40.0.0/20`, `10.44.0.0/16` e `10.45.0.0/20` não conflitam com outras redes que serão conectadas à VPC.

## 1. Selecionar o projeto e criar o bucket do estado

O backend GCS guarda o estado do Terraform fora do Cloud Shell. O bucket deve existir **antes** de `terraform init`; ele permanece mesmo se o cluster for destruído. Não publique o estado, pois ele pode conter dados sensíveis. Rode no Cloud Shell:

```bash
export PROJECT_ID='project-74743ec7-e65e-4d5a-af5'
export TF_STATE_BUCKET="quistock-tfstate-${PROJECT_ID}"
gcloud config set project "$PROJECT_ID"
gcloud services enable storage.googleapis.com serviceusage.googleapis.com --project "$PROJECT_ID"
gcloud storage buckets create "gs://${TF_STATE_BUCKET}" \
  --project="$PROJECT_ID" \
  --location=us-east1 \
  --uniform-bucket-level-access \
  --public-access-prevention
gcloud storage buckets update "gs://${TF_STATE_BUCKET}" --versioning
```

Se o nome global do bucket já existir, escolha outro nome único e atualize `TF_STATE_BUCKET`. O bucket e suas versões de objeto têm custo de armazenamento. Restrinja o acesso ao bucket a quem administra a infraestrutura.

## 2. Examinar o plano antes de criar recursos

Faça checkout da branch aprovada do `QuiStock-Infra` no Cloud Shell e entre neste diretório. Configure o ID do projeto como variável de ambiente para que ele não precise ser gravado em `terraform.tfvars`:

```bash
cd terraform/gke
export TF_VAR_project_id="$PROJECT_ID"
terraform init \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="prefix=quistock/gke"
terraform fmt -check
terraform validate
terraform plan -out=cluster.tfplan
terraform show cluster.tfplan
```

O plano esperado cria duas habilitações de API, uma VPC, uma sub-rede e um cluster Autopilot. Confira **projeto, região, faixas IP e ações propostas**. `terraform plan` não cria o cluster. O arquivo `cluster.tfplan` pode conter dados sensíveis e é ignorado pelo Git.

## 3. Criar e conferir o cluster

Somente depois de aprovar o plano e os custos:

```bash
terraform apply cluster.tfplan
gcloud container clusters get-credentials quistock \
  --region us-east1 --project "$PROJECT_ID"
kubectl get nodes -L kubernetes.io/arch
```

O Autopilot cria capacidade de computação conforme os Pods exigem; um cluster recém-criado pode não apresentar nós até receber uma carga. Este Terraform não publica nenhuma API nem cria load balancer.

## 4. Destruir quando o ambiente não for mais necessário

Antes de destruir, retire as Applications do Argo CD e verifique recursos de nuvem criados por Services/Gateways e quaisquer dados persistentes. A proteção contra exclusão vem ativada por padrão. Para destruição planejada, primeiro grave `deletion_protection=false` no estado:

```bash
terraform apply -var='deletion_protection=false'
terraform destroy -var='deletion_protection=false'
```

Confirme o plano de cada comando. O bucket de estado não é gerenciado por este Terraform; mantenha-o para auditoria/reconstrução ou exclua-o separadamente depois de garantir que o estado não será mais necessário.

## Custos e próximos passos

O GKE cobra gerenciamento do cluster e computação; a franquia mensal da camada gratuita pode compensar a taxa de gerenciamento de um cluster Autopilot elegível, mas **não** cobre Pods, armazenamento ou load balancer. Consulte os [preços atuais do GKE](https://cloud.google.com/kubernetes-engine/pricing) e configure um alerta no Billing antes de `apply`.

Depois da criação, adaptaremos os manifests de Core e Auth para GKE/ARM64, instalaremos o Argo CD e testaremos Services internos. A entrada pública será criada só quando houver necessidade de acesso pelo navegador e aplicativo mobile.
