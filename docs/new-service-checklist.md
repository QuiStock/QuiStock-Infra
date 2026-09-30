# Adicionar um serviço ao GitOps (modelo para API Auth)

A API Auth ainda não possui repositório nem imagem. Este procedimento deve ser executado quando o responsável entregar o código e o contrato HTTP. Não use um Deployment vazio para aparentar que Auth está funcional.

## Contrato de execução

Antes de criar manifests, confirme com o responsável:

- porta HTTP e rota de saúde que retorna sucesso somente quando o processo pode atender tráfego;
- variáveis de ambiente, banco externo e Secret necessários, sem copiar valores para Git;
- arquitetura `linux/arm64`;
- endpoint de login, formato do token, expiração, renovação e como Core valida o token;
- se o serviço deve ser público para navegador e mobile;
- versão inicial para a primeira release.

## Repositório do serviço

1. Crie um Dockerfile de produção ARM64 e um `.dockerignore` que exclua arquivos locais, credenciais e artefatos de teste da imagem final.
2. Crie um check em pull requests que execute o build `linux/arm64` sem publicar a imagem.
3. Crie workflow em `release: published` para releases estáveis. Publique `ghcr.io/quistock/<pacote>:<tag>` e use o digest `sha256:...` emitido por `docker/build-push-action`.
4. Configure `INFRA_REPO_TOKEN` em **Settings → Secrets and variables → Actions** do repositório. O token deve ser limitado ao `QuiStock-Infra`, com **Contents: read/write** e **Pull requests: read/write**. Guarde o token no Bitwarden.
5. O workflow deve fazer checkout do Infra, substituir somente a referência de imagem do serviço e abrir PR para `main`. Não atualize `main` diretamente.
6. Proteja a branch `main` do serviço e revise o check ARM64 antes do merge. Crie a primeira release a partir de um commit de `main`.

Use os workflows de `DS_Backend` e `AI_Multi-Agent` como exemplos, adaptando nomes e caminhos sem alterar o fluxo de aprovação.

## Repositório Infra

1. Adicione `clusters/expotech/bootstrap/<servico>-namespace.yaml`.
2. Adicione `clusters/expotech/apps/<servico>/deployment.yaml` com `nodeSelector` ARM64/`quistock-arm`, requests/limits medidos, `RollingUpdate` com `maxSurge: 1` e `maxUnavailable: 0`, e probes HTTP adequados à aplicação.
3. Adicione `service.yaml` do tipo `ClusterIP`.
4. Adicione `clusters/expotech/bootstrap/<servico>-application.yaml` apontando para essa pasta em `main`, com sync automatizado. Revise e faça merge via PR.
5. Crie o namespace e o Secret no cluster. O Git contém só referências às chaves do Secret. Verifique os nomes com `kubectl describe secret`, sem exibir valores.
6. Publique a primeira release do serviço. Aguarde a PR automática trocar `:bootstrap` pelo digest real, revise e faça merge. Só então aplique a Application do Argo CD.

## Validação

```bash
kubectl get application <servico> -n argocd
kubectl rollout status deployment/<servico> -n <namespace> --timeout=5m
kubectl get pods -n <namespace> -o wide
kubectl get svc -n <namespace>
```

Faça uma requisição HTTP à rota de saúde através de `kubectl port-forward`. Depois faça uma chamada representativa que use a dependência externa; uma rota de saúde simples não prova que o banco ou provedor de identidade funciona. Em uma segunda release, compare o digest e o nome do Pod antes e depois do merge da PR Infra para comprovar o rolling update.

## Acesso público

Mantenha o Service interno até definir domínio, certificado ACM e política de autenticação. No EKS Auto Mode, um `IngressClass` com controlador `eks.amazonaws.com/alb` e um `Ingress` podem criar ALB para tráfego HTTPS; veja a [documentação AWS](https://docs.aws.amazon.com/eks/latest/userguide/auto-configure-alb.html). O navegador e o mobile precisam de URL HTTPS pública para Auth e Core. A Core chama o chatbot pelo DNS interno, não por um endereço público.
