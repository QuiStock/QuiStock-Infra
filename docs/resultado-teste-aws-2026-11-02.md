# Resultado do teste AWS — 02/11/2026

Deploy executado a partir das branches dos PRs Draft, sem merge em main. O Terraform criou 43 recursos, sem alterações ou destruições no plano inicial. O PostgreSQL compartilhado já existia: nenhuma migração, DDL ou inicialização SQL foi executada. Jobs de memória e FAQ foram usados somente em modo check.

## Evidências funcionais

| Área | Evidência observada |
| --- | --- |
| EKS | Kubernetes 1.36; dois nós ARM64 Ready em duas zonas |
| GitOps | Auth, Core, IA, Observe e website sincronizados e saudáveis |
| Gateway | HTTPS, roteamento público, assets JS/CSS, SPA e respostas 404 conferidos |
| Segurança HTTP | Rejeição anônima, login inválido, origem não autorizada e atributos de cookies conferidos |
| API autenticada | 12 verificações aprovadas: login, perfil, lojas, saudação, FAQ, consulta comercial, histórico, encerramento, refresh, recuperação após reinício e logout |
| Persistência | Seis mensagens preservadas após reiniciar a IA; conversa encerrada; dois jobs de resumo concluídos; um ponto vetorial correspondente no Qdrant |
| Dependências IA | Health de PostgreSQL, MongoDB, Redis, Qdrant, Gemini, OpenAI e TypeSafe aprovado |
| JEV | Avaliação real aprovada com o alias disponível jev-latest |
| Observe | Login super_admin, traces correlacionados, spans, eventos, logs, citações, avaliação e uso de modelos visíveis |
| Website | Perfil e lojas carregaram no navegador autenticado após corrigir transporte de sessão |
| Android físico | APK Debug compilado com os endpoints AWS, instalado; usuário confirmou login e resposta do chat |

A bateria pública registrou 20 verificações aprovadas e a autenticada registrou 12, sem falhas. Os relatórios operacionais ficam em arquivos ignorados de `.learner-lab`, sem credenciais. O caso comercial retornou clarification_required, comportamento válido para a consulta ambígua; isso não comprova todas as consultas comerciais possíveis.

## Correções incorporadas aos Drafts

- Infra #40: alias TypeSafe disponível, digests das imagens corrigidas e executor de testes autenticados reproduzível.
- Website #25: no mesmo origin do Auth/Core, usa cookie HttpOnly sem enviar simultaneamente Authorization; em origins separados, usa Bearer sem cookies no Core. Mantém CSRF. Quatro testes de regressão e suíte de 109 testes aprovados; CI Linux aprovada. Perfil e lojas retestados na AWS.
- IA #44: contrato do Lab aceita agent_id e retorna a decisão de ferramenta do modelo usando apenas schemas dos cards, sem executar ferramentas. Cinco testes focados e CI Linux aprovados. Reteste autenticado do Lab ainda pendente de renovar a sessão do navegador.
- Mobile #68: build Debug real com /auth/ e /api/, login e resposta confirmados no aparelho. O build Demo offline não foi usado como evidência AWS.

## Limites e estado final

Este é um teste funcional de integração. Não valida carga, disponibilidade sob falha de zona, todos os perfis de autorização, integração ERP ou schedulers comerciais. Instrumentação Android e cobertura combinada não são declaradas aprovadas por este teste físico.

Os recursos AWS permanecem ativos. Destruição não foi executada. Nenhum PR foi marcado pronto ou mesclado. Para reproduzir, siga [o roteiro atômico](teste-aws-passo-a-passo.md).
