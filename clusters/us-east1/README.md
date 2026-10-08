# QuiStock: quatro aplicações no EKS

Terraform mantém EKS, rede, add-ons, dois NLBs e API Gateway. O script instala
Argo CD e Bitwarden e configura o token inicial. Argo reconcilia Auth, Core,
chatbot e website; não provisiona recursos AWS.

```text
Browser/mobile → API Gateway HTTPS → VPC Link → NLB privado → website Nginx
                                                             /      → React
                                                             /api   → Core
                                                             /auth  → Auth
Core ↔ chatbot via Services internos (integração de aplicação pendente)
Browser → NLB público HTTPS → Argo CD (login obrigatório)
```

Website e APIs compartilham a URL automática `execute-api`. O Argo mantém a
URL `elb.amazonaws.com` com certificado autoassinado. Não há domínio próprio,
CloudFront, ACM, controlador de Ingress ou LoadBalancer criado pelo Kubernetes.

| Application Argo | Service | Secrets |
| --- | --- | --- |
| api-auth | ClusterIP, porta 80 → 8080 | auth-external |
| api-core | ClusterIP, porta 80 → 8080 | core-external |
| api-chatbot | ClusterIP, porta 80 → 8000 | chatbot-external |
| website | NodePort 30080 → 8080, somente NLB privado | nenhum |

As imagens de Auth/Core e seus paths de release permanecem. Website/chatbot
são estruturas com placeholders autorizados: preencha os digests ARM64 e IDs
Bitwarden antes de executar preflight/up/bootstrap/public. Veja os contratos
em [website](apps/website/README.md) e [chatbot](apps/api-chatbot/README.md).

Core recebe `/api/products` como `/products`; Auth recebe `/auth/login` como
`/auth/login`, conforme sua imagem atual. Core consulta JWKS por DNS interno.
CORS continua aberto para origens HTTP/HTTPS com cookies. Os novos Services
habilitam conectividade interna; as aplicações ainda precisam implementar a
integração Core/chatbot e compatibilizar sua autenticação.

Applications acompanham main, com selfHeal e sem prune automático. Bitwarden
atualiza Secrets sem reiniciar Pods: faça rollout após rotação. Não coloque
secrets no build React. O website serve arquivos React e faz o proxy no mesmo
container, substituindo o Deployment edge.

O [runbook](../../docs/learner-lab-feira.md) descreve reconstrução e migração.
Os endereços Terraform `edge` e a saúde `/edge-health` são mantidos para
reaproveitar o estado e o NLB existente, sem substituição de recursos AWS.
