# API Auth e API Core no GKE

Esta pasta contém somente o estado desejado do **ambiente de teste** no GKE Autopilot. Auth é aplicada antes de Core: a Core só fica pronta quando o endpoint interno de chaves públicas da Auth responde. Ambos os Services são `ClusterIP`; nenhum endereço público é criado aqui.

## Pré-requisitos antes de aplicar cada Application

1. Faça merge desta PR e das PRs dos workflows de release de `DS_Auth` e `DS_Backend`, que devem atualizar `clusters/us-east1/apps/...` no Infra.
2. Crie os namespaces com os manifests em `clusters/us-east1/bootstrap`.
3. No Bitwarden, guarde separadamente as credenciais **de teste** de cada API. Recrie os Secrets no cluster sem adicionar valores ao Git:
   - `api-auth/auth-external`: `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `MONGODB_URI`, `MONGODB_DATABASE`, `AUTH_JWT_ISSUER`, `AUTH_JWT_PRIVATE_KEY_BASE64`, `AUTH_JWT_PUBLIC_KEY_BASE64`, `AUTH_JWT_KEY_ID`, `AUTH_RATE_LIMIT_HMAC_KEY`.
   - `api-core/postgres-db`: `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`.
   - `api-core/api-core-config`: `AUTH_JWT_ISSUER`.
4. O `AUTH_JWT_ISSUER` deve ser **idêntico** nos dois Secrets e ser um identificador HTTPS estável. A Auth rejeita um issuer HTTP que não seja localhost. A Core acessa as chaves via DNS interno, independentemente do URL usado como issuer.
5. A Auth precisa de um usuário PostgreSQL somente leitura com acesso às tabelas `user_account` e `role`, e MongoDB de teste com replica set que suporte transações. Use um par RSA e uma chave HMAC próprios do teste; a chave HMAC exige pelo menos 32 bytes. `AUTH_JWT_PRIVATE_KEY_BASE64` e `AUTH_JWT_PUBLIC_KEY_BASE64` são os arquivos PEM codificados em base64, em uma linha.
6. Publique a primeira release de Auth. Aguarde a PR automática trocar `:bootstrap` pelo digest `sha256:...`, revise e faça merge. Confirme que a imagem GHCR está pública (ou configure `imagePullSecret`). Só então aplique a Application Auth. Repita para Core após Auth ficar pronta.

Os Secrets podem ser criados com `kubectl create secret generic NOME -n NAMESPACE --from-env-file=/caminho/privado/arquivo.env`. Crie o arquivo fora do Git, limite sua permissão a você e remova-o após o comando. `kubectl describe secret` mostra apenas nomes e tamanhos das chaves. **Não cole valores em issues, PRs ou chats.**

## Bootstrap

Na raiz do Infra, com `kubectl` apontando para o GKE:

```bash
kubectl apply -f clusters/us-east1/bootstrap/api-auth-namespace.yaml
kubectl apply -f clusters/us-east1/bootstrap/api-core-namespace.yaml
# Recrie os Secrets antes das Applications.
# Confirme que os dois digests substituíram :bootstrap.
kubectl apply -f clusters/us-east1/bootstrap/api-auth-application.yaml
kubectl get application api-auth -n argocd
kubectl rollout status deployment/api-auth -n api-auth --timeout=10m
kubectl apply -f clusters/us-east1/bootstrap/api-core-application.yaml
kubectl get application api-core -n argocd
kubectl rollout status deployment/api-core -n api-core --timeout=10m
```

A rota `/health` das duas APIs é uma checagem de dependências e serve para readiness. Os probes de startup e liveness usam apenas a porta TCP para não reiniciar o processo quando um serviço externo ficar indisponível. A Auth verifica PostgreSQL e MongoDB; a Core verifica PostgreSQL e JWKS da Auth. No teste, sincronização com ERP e checagem obrigatória do ERP ficam desligadas porque ainda não há um endpoint ERP configurado. Revise essas variáveis antes de produção.

## Rolling update

Uma release publica imagem ARM64 no GHCR e abre PR de digest no Infra. O Argo CD acompanha `main`; após o merge, o Deployment usa `maxSurge: 1` e `maxUnavailable: 0`. A nova versão só recebe tráfego do Service após passar na readiness. Compare o digest e os Pods antes e depois para confirmar o update.

O GKE 1.35.8 exige `kubernetes.io/arch: arm64` **e** `cloud.google.com/compute-class: autopilot-arm` para selecionar a plataforma ARM64 de uso geral. Os requests podem ser ajustados automaticamente pelo Autopilot; confira os valores efetivos e o custo após o primeiro deploy.
