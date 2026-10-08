# API Auth e API Core no EKS

O estado desejado continua em `clusters/us-east1`, preservando os paths das pipelines de release. A região AWS do perfil inicial é `us-east-1`.

Consulte o [runbook Learner Lab](../../docs/learner-lab-feira.md) para provisionamento, bootstrap, Secrets, entrada HTTPS, recuperação e troca de conta. O script instala Bitwarden e Argo CD e aplica Auth antes de Core.

Ambas as APIs usam `kubernetes.io/arch: arm64`, Services ClusterIP e imagens GHCR por digest. Auth lê `auth-external`; Core lê `core-external`; os dois Secrets são sincronizados pelo operador Bitwarden e exigem `bw-auth-token` no respectivo namespace. Os UUIDs dos manifests não são valores secretos.

Preserve issuer HTTPS, audience, chaves JWT e bancos durante a troca de conta. Core obtém JWKS por `http://api-auth.api-auth.svc.cluster.local/.well-known/jwks.json`. Auth usa readiness `/health` e liveness TCP; Core usa `/health/readiness` e `/health/liveness`. Integração ERP permanece desligada no perfil atual.

Rolling updates usam `maxSurge: 1`, `maxUnavailable: 0`; reserve capacidade para os Pods extras. As Applications acompanham `main` com selfHeal e sem prune automático. Alteração de Secrets não reinicia Pods automaticamente.

A Application `edge` reconcilia o proxy Nginx e o Service NodePort interno. Terraform cria API Gateway HTTP API com HTTPS próprio, VPC Link e NLB privado. `/api/...` encaminha à Core removendo `/api`; `/auth/...` preserva o prefixo nativo da Auth. CORS aceita quaisquer origens HTTP/HTTPS com suporte a cookies. React futuramente terá uma URL separada; não são necessários domínio próprio ou ACM.
