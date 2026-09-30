# QuiStock Infra

Estado desejado do ambiente EKS Auto Mode do QuiStock. O Argo CD acompanha as pastas em `clusters/expotech`; a branch `main` é protegida e uma mudança de imagem entra por pull request.

- [Runbook: do zero ao deploy](docs/eks-auto-mode-runbook.md)
- [Modelo para adicionar Auth ou outro serviço](docs/new-service-checklist.md)
- [NodePool ARM64](clusters/expotech/nodepools/quistock-arm.yaml)
- [API Core](clusters/expotech/apps/api-core/)
- API Chatbot e worker: manifests em revisão na [PR #4](https://github.com/QuiStock/QuiStock-Infra/pull/4).

## Estado verificado

A API Core foi publicada no GHCR, sincronizada pelo Argo CD, respondeu HTTP 200 em `/api/flows` pelo Service e abriu conexão com o PostgreSQL de teste. A release v1.0.3 gerou uma PR de digest no Infra e o usuário observou o rolling update no Argo CD.

A API Chatbot está em preparação. Seus manifests não devem ser aplicados como Application antes de existir uma imagem publicada e o Secret `chatbot-external` no namespace `api-chatbot`. A API Auth ainda não tem repositório. O frontend React está no repositório `QuiStock/quistock-dad` e ainda precisa de deploy e de alinhamento dos endpoints públicos.
