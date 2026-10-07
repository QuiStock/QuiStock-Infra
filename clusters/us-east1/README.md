# API Auth e API Core no GKE

Esta pasta contém somente o estado desejado do **ambiente de teste** no GKE Autopilot. Auth é aplicada antes de Core: a Core só fica pronta quando o endpoint interno de chaves públicas da Auth responde. Ambos os Services são `ClusterIP`; nenhum endereço público é criado aqui.

## Pré-requisitos antes de aplicar cada Application

1. Crie os namespaces com os manifests em `clusters/us-east1/bootstrap`.
2. Instale o operador Bitwarden e forneça seu token de conta de máquina no namespace `api-auth`, conforme a seção abaixo. O manifesto `apps/api-auth/bitwarden-secret.yaml` sincroniza `auth-external` a partir do projeto de teste no Bitwarden Secrets Manager.
3. Até migrar a Core ao operador, recrie manualmente seus dois Secrets no cluster, sem adicionar valores ao Git:
   - `api-core/postgres-db`: `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`.
   - `api-core/api-core-config`: `AUTH_JWT_ISSUER`.
4. O `AUTH_JWT_ISSUER` deve ser **idêntico** nos dois Secrets e ser um identificador HTTPS estável. A Auth rejeita um issuer HTTP que não seja localhost. A Core acessa as chaves via DNS interno, independentemente do URL usado como issuer.
5. A Auth precisa de um usuário PostgreSQL somente leitura com acesso às tabelas `user_account` e `role`, e MongoDB de teste com replica set que suporte transações. Use um par RSA e uma chave HMAC próprios do teste; a chave HMAC exige pelo menos 32 bytes. `AUTH_JWT_PRIVATE_KEY_BASE64` e `AUTH_JWT_PUBLIC_KEY_BASE64` são os arquivos PEM codificados em base64, em uma linha.
6. Publique a primeira release de Auth. Aguarde a PR automática trocar `:bootstrap` pelo digest `sha256:...`, revise e faça merge. Confirme que a imagem GHCR está pública (ou configure `imagePullSecret`). Só então aplique a Application Auth. Repita para Core após Auth ficar pronta.

Para os Secrets da Core ainda não migrados, use `kubectl create secret generic NOME -n api-core --from-env-file=/caminho/privado/arquivo.env`. Crie o arquivo fora do Git, limite sua permissão a você e remova-o após o comando. `kubectl describe secret` mostra apenas nomes e tamanhos das chaves. **Não cole valores em issues, PRs ou chats.**

## Bitwarden Secrets Manager

A Auth usa o projeto de teste `quistock-gke-teste` da organização Bitwarden e a conta de máquina `gke-quistock-teste` com permissão **Can read**. Os UUIDs no manifesto não são valores secretos. Cada item do Secrets Manager corresponde a uma chave do Secret Kubernetes `api-auth/auth-external`. Mantenha o token da conta de máquina somente no Password Manager, nunca no Git.

Após criar o cluster e antes de aplicar a Application Auth, instale a versão fixada do operador:

```bash
helm repo add bitwarden https://charts.bitwarden.com/
helm repo update bitwarden
helm upgrade --install sm-operator bitwarden/sm-operator \
  --namespace sm-operator-system --create-namespace \
  --version 2.0.3 --wait --timeout 10m
kubectl get pods -n sm-operator-system
```

No Cloud Shell, crie o token de bootstrap sem incluí-lo no histórico do shell. O prompt oculta o token digitado ou colado. Se o token estiver vazio, nenhum Secret será criado:

```bash
read -r -s -p "Token Bitwarden: " BITWARDEN_OPERATOR_TOKEN
echo
if [ -z "$BITWARDEN_OPERATOR_TOKEN" ]; then
  echo "Token vazio; nenhum Secret foi criado."
else
  printf '%s' "$BITWARDEN_OPERATOR_TOKEN" |
    kubectl create secret generic bw-auth-token -n api-auth \
      --from-file=token=/dev/stdin
fi
unset BITWARDEN_OPERATOR_TOKEN
```

Em um cluster novo, repita somente a instalação do operador e o bootstrap do token; as chaves JWT e credenciais continuam no Bitwarden. Para girar o token, atualize `bw-auth-token` no cluster e confirme a reconciliação. Os valores sincronizados também existem no Secret Kubernetes, então limite RBAC e acesso ao cluster. Alterações em variáveis de ambiente de Secrets já montados não reiniciam Pods automaticamente; faça uma nova release ou reinicie o Deployment após rotação.

## Bootstrap

Na raiz do Infra, com `kubectl` apontando para o GKE:

```bash
kubectl apply -f clusters/us-east1/bootstrap/api-auth-namespace.yaml
kubectl apply -f clusters/us-east1/bootstrap/api-core-namespace.yaml
# Instale o operador e crie bw-auth-token conforme a seção anterior.
kubectl apply -f clusters/us-east1/apps/api-auth/bitwarden-secret.yaml
kubectl get bitwardensecret auth-external -n api-auth
kubectl describe secret auth-external -n api-auth
# Confirme que a imagem Auth já usa um digest sha256.
kubectl apply -f clusters/us-east1/bootstrap/api-auth-application.yaml
kubectl get application api-auth -n argocd
kubectl rollout status deployment/api-auth -n api-auth --timeout=10m
# Recrie os Secrets da Core e confirme que sua imagem usa um digest sha256.
kubectl apply -f clusters/us-east1/bootstrap/api-core-application.yaml
kubectl get application api-core -n argocd
kubectl rollout status deployment/api-core -n api-core --timeout=10m
```

A rota `/health` das duas APIs é uma checagem de dependências e serve para readiness. Os probes de startup e liveness usam apenas a porta TCP para não reiniciar o processo quando um serviço externo ficar indisponível. A Auth verifica PostgreSQL e MongoDB; a Core verifica PostgreSQL e JWKS da Auth. No teste, sincronização com ERP e checagem obrigatória do ERP ficam desligadas porque ainda não há um endpoint ERP configurado. Revise essas variáveis antes de produção.

## Rolling update

Uma release publica imagem ARM64 no GHCR e abre PR de digest no Infra. O Argo CD acompanha `main`; após o merge, o Deployment usa `maxSurge: 1` e `maxUnavailable: 0`. A nova versão só recebe tráfego do Service após passar na readiness. Compare o digest e os Pods antes e depois para confirmar o update.

O GKE 1.35.8 exige `kubernetes.io/arch: arm64` **e** `cloud.google.com/compute-class: autopilot-arm` para selecionar a plataforma ARM64 de uso geral. Os requests podem ser ajustados automaticamente pelo Autopilot; confira os valores efetivos e o custo após o primeiro deploy.
