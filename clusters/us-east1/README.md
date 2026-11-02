# QuiStock: cinco aplicações no EKS

Comece por [criar a infraestrutura do zero](../../docs/deploy-aws-do-zero.md).
Para senha do Argo CD, rotação de secrets e rollout, use
[comandos de operação](../../docs/comandos-operacao-aws.md).

Terraform mantém EKS, rede, add-ons, dois NLBs e API Gateway. O bootstrap instala
Argo CD e Bitwarden e configura o token inicial. Argo reconcilia Auth, Core,
IA com worker, Observe e website; não provisiona recursos AWS.

```text
Browser/mobile → API Gateway HTTPS → VPC Link → NLB privado → website Nginx
                                                             /           → React website
                                                             /api        → Core → IA interna
                                                             /auth       → Auth
                                                             /observe/   → frontend Observe
                                                             /api/v1/observability → API IA
Browser → NLB público HTTPS → Argo CD (login obrigatório)
```

Website, APIs e Observe compartilham a URL automática `execute-api`.
O proxy preserva `/api/v1/observability` para manter o cookie de sessão do Observe.
Argo usa a URL `elb.amazonaws.com` com certificado autoassinado. Não há domínio
próprio, CloudFront, ACM, controlador de Ingress ou LoadBalancer criado pelo Kubernetes.

| Application Argo | Service | Secrets consumidos |
| --- | --- | --- |
| api-auth | ClusterIP, porta 80 → 8080 | auth-external |
| api-core | ClusterIP, porta 80 → 8080 | core-external |
| api-chatbot | ClusterIP, porta 80 → 8000 | chatbot-external; API também usa chatbot-runtime-external |
| observe | ClusterIP, porta 80 → 8080 | nenhum no frontend |
| website | NodePort 30080 → 8080, somente NLB privado | nenhum |

As imagens estão fixadas por digest ARM64. A API e o summary-worker são dois
containers no mesmo pod: `2/2` indica ambos prontos. Os dois itens de runtime
TypeSafe/sessão Observe são mapeados pelos UUIDs da configuração local do bootstrap.
O worker não os recebe. Confira o [contrato da IA](apps/api-chatbot/README.md).

Core recebe `/api/products` como `/products`; Auth preserva `/auth/login`.
Core consulta JWKS e IA por DNS interno. O bootstrap gera `api-runtime` com a
origem HTTPS da conta. No website, Auth/Core no mesmo origin usam cookie sem
Authorization duplicado. O Observe usa sua própria sessão `super_admin`.

As Applications têm selfHeal e não fazem prune automático; o bootstrap define
`targetRevision` a partir de `infra_ref` (`codex/learner-lab-runtime-update` antes
do merge, ou `main` depois). Bitwarden atualiza Secrets sem reiniciar pods:
confirme sincronização e faça rollout dos consumidores. Não coloque secrets no React.

PostgreSQL compartilhado e demais dependências externas precisam estar preparados.
Auth/Core têm migrações e inicialização SQL desativadas. Os checks de memória/FAQ
não devem receber `--apply` no teste compartilhado.

Os endereços Terraform `edge` e o health `/edge-health` permanecem para
reaproveitar o estado e o NLB existente. Os documentos `learner-lab-feira.md`
e `learner-lab-atualizacao-runtime.md` registram migrações anteriores; para conta
vazia, use o guia atual acima e o [checklist funcional](../../docs/teste-aws-passo-a-passo.md).
