# Teste completo na AWS antes do merge

Estado: preparação de código; nenhuma etapa AWS deste roteiro foi executada. Primeiro passo pendente: criação de `OBSERVABILITY_SESSION_SECRET`.
Execute uma linha por vez, confirme a evidência e só então avance. No chat, o acompanhamento começa no passo 1.
O Learner Lab começa sem recursos AWS. PostgreSQL, MongoDB, Redis, Qdrant, Gemini e TypeSafe são dependências externas e precisam estar disponíveis; este Terraform não as cria.

## Preparação sem consumir a sessão do Lab

1. No **Bitwarden Secrets Manager**, crie `OBSERVABILITY_SESSION_SECRET` com valor aleatório de pelo menos 32 caracteres, gerado localmente. Evidência: item salvo; anote somente seu UUID. Não envie o valor no chat.
2. Crie `TYPESAFE_API_KEY` no mesmo projeto, com uma chave válida do TypeSafe. Evidência: UUID anotado, sem expor a chave.
3. Conceda à machine account usada pelo operador Bitwarden acesso aos dois itens. Evidência: permissão de leitura no projeto.
4. Confira os itens já mapeados nos três arquivos `clusters/us-east1/apps/*/bitwarden-secret.yaml`. Evidência: todos existem e a mesma machine account consegue lê-los; não copie valores para Git.
5. Confira no provedor PostgreSQL se o banco de teste está isolado ou possui backup aprovado. Evidência: identificação do banco e backup, sem connection string no chat. O Core executa Flyway ao iniciar.
6. Confira a existência de `public.super_admin` e de uma conta exclusiva de teste com senha BCrypt. Evidência: tabela e conta presentes, usuário SQL da IA com SELECT. As migrações do Core não criam essa tabela; se faltar, pare e solicite o provisionamento ao responsável pelo banco.
7. Confira uma conta comercial ativa `MANAGER` ou `EMPLOYEE`, vinculada a exatamente uma loja ativa. Evidência: login e vínculo conferidos localmente, sem dados pessoais no chat.
8. Confira que o usuário PostgreSQL da IA tem os SELECTs necessários às tabelas comerciais. Evidência: grants confirmados pelo administrador do banco.
9. Confira que os nomes das três coleções de memória são distintos e não coincidem com outras coleções. Evidência: nomes validados; não reutilize coleções de produção para inicialização.
10. Execute `python --version`. Evidência: Python 3.10 ou superior.
11. Execute `aws --version`. Evidência: AWS CLI instalada.
12. Execute `terraform version`. Evidência: Terraform 1.11.4 ou superior.
13. Execute `kubectl version --client`. Evidência: cliente instalado.
14. Execute `helm version`. Evidência: Helm instalado.
15. Execute `git --version`. Evidência: Git instalado.
16. Atualize a branch de Infra `codex/learner-lab-runtime-update`. Evidência: checkout sem alterações locais inesperadas, Draft PR atualizado.
17. Confira que as imagens dos cinco Deployments e do worker estão fixadas por digest ARM64 público e que não há `REPLACE_WITH_` nos manifests. Evidência: CI de Infra aprovada e pulls anônimos possíveis.

## Nova sessão AWS

18. Inicie a sessão no Learner Lab. Evidência: sessão ativa e orçamento disponível.
19. Configure as três credenciais temporárias AWS somente no terminal/perfil local, incluindo o session token. Evidência: nenhum segredo salvo em arquivos versionados.
20. Execute `aws sts get-caller-identity`. Evidência: Account corresponde à nova conta do Lab. Compartilhe apenas o ID da conta, nunca as credenciais.
21. Confirme a região permitida no Lab e a disponibilidade de `t4g.medium`. Evidência: região e instância suportadas.
22. Consulte `LabRole` e a role de nós permitida; confira políticas EKS Worker, CNI e ECR na role de nós. Evidência: nomes/ARNs existentes e adequados; não presuma que a role de cluster serve para os nós.
23. Consulte versões EKS em suporte padrão disponíveis na região. Evidência: versão escolhida e compatível com kubectl.
24. Consulte versões de `vpc-cni` compatíveis com a versão escolhida. Evidência: versão exata anotada.
25. Consulte versões de `coredns` compatíveis. Evidência: versão exata anotada.
26. Consulte versões de `kube-proxy` compatíveis. Evidência: versão exata anotada.
27. Copie `scripts/learner-lab/config.example.json` para `.learner-lab/config-<ACCOUNT>.json`. Evidência: arquivo local ignorado pelo Git.
28. Preencha a região da configuração. Evidência: região permitida no Lab.
29. Preencha as roles de cluster, nós e administrador. Evidência: nomes/ARNs conferidos nos passos de IAM.
30. Preencha a versão EKS. Evidência: suporte padrão confirmado.
31. Preencha as três versões dos addons. Evidência: compatibilidade conferida.
32. Preencha `admin_cidrs` com seu IP público atual `/32`. Evidência: acesso administrativo limitado a esse IP.
33. Preencha os dois UUIDs em `bitwarden_secret_ids`. Evidência: IDs distintos; os valores permanecem no Bitwarden.
34. Defina `infra_ref` como `codex/learner-lab-runtime-update`. Evidência: o teste usará a branch do Draft PR, antes do merge.
35. No PowerShell, defina `$Account = "<ACCOUNT>"`. Evidência: ID da nova conta.
36. Defina `$Config = ".learner-lab/config-$Account.json"`. Evidência: arquivo da nova conta.
37. Defina `$Lab = "scripts/learner-lab/lab.py"`. Evidência: script presente no checkout.
38. Execute `python $Lab preflight --account $Account --config $Config`. Evidência: conta, versões, permissões e manifests validados. Erro interrompe o teste; não force a próxima etapa.
39. Execute `python $Lab up --account $Account --config $Config`. Evidência: plano de criação revisável. Esta etapa cria o bucket de estado, mas não aplica o plano de infraestrutura.
40. Revise o plano: somente recursos da nova conta, duas máquinas ARM64, nenhum destroy inesperado. Evidência: endereços e estimativa de custo aceitos antes de aplicar.
41. Execute `python $Lab up --account $Account --config $Config --apply`. Evidência: Terraform conclui, dois nós Ready ARM64 e bootstrap iniciado. Preserve `.learner-lab/<ACCOUNT>` e o bucket de estado para retomada.
42. Quando solicitado no bootstrap, forneça o token da machine account Bitwarden no prompt oculto. Evidência: Secrets sincronizados, sem valores impressos. Se a sessão cair, renove credenciais e retome com `bootstrap`, sem apagar o estado.
43. Execute `python $Lab verify --account $Account --config $Config`. Evidência: cinco aplicações Synced/Healthy, API e worker Ready, segredos com todas as chaves.
44. Execute `python $Lab public --account $Account --config $Config`. Evidência: NLB saudável; website, Auth, Core e Observe acessíveis por HTTPS; Observe sem cookie retorna 401.
45. Abra o URL do Argo CD informado pelo script. Evidência: certificado HTTPS validado e aplicações saudáveis na branch de teste.

## Dados e caminhos funcionais

46. Execute `python $Lab memory --account $Account --config $Config --vector-size 768`. Evidência: Job check concluído; veja os logs usando o comando informado. 768 é a dimensão configurada pelo embedding da revisão atual.
47. Revise contagens e dimensão. Evidência: se houver dados, não execute inicialização; valide a coleção existente separadamente. Se houver incompatibilidade, pare para planejar migração, sem apagar coleções.
48. Somente para coleções novas e vazias, execute `python $Lab memory --account $Account --config $Config --vector-size 768 --apply`. Evidência: índices criados, coleção vetorial com dimensão correta; nenhum dado apagado.
49. Execute `python $Lab faq --account $Account --config $Config`. Evidência: documentos empacotados encontrados, dimensão compatível e contagem visível nos logs; nenhum embedding chamado em check.
50. Para FAQ nova ou com manifesto Mongo compatível, execute `python $Lab faq --account $Account --config $Config --apply`. Evidência: `failed=0`. Coleção populada sem manifesto exige migração separada, não force reinicialização. Esta etapa usa Gemini e pode consumir créditos.
51. Abra o website no URL HTTPS emitido. Evidência: SPA e assets carregam sem erros de MIME ou 404.
52. Faça login comercial no website com a conta de teste. Evidência: fluxo normal de sessão, consultas Core autenticadas, sem CORS indevido.
53. Confira uma tela de dados da loja de teste. Evidência: dados correspondem à loja autorizada e uma rota protegida sem sessão é negada.
54. Compile o Mobile na branch `codex/aws-test-endpoints` com `-Pquistock.authBaseUrl=<URL>/auth/ -Pquistock.coreBaseUrl=<URL>/api/`. Evidência: recursos gerados apontam à AWS; mantenha arquivos Firebase e senhas somente no ambiente local/CI autorizado.
55. Instale o APK em dispositivo/emulador. Evidência: app inicia sem falhas; este passo é distinto dos testes unitários e da cobertura combinada da CI.
56. Faça login comercial no app. Evidência: `/auth/login` chega ao Auth, perfil e loja carregam pelo Core.
57. Renove a sessão pelo fluxo normal do app. Evidência: CSRF e refresh usam `/auth/`, sem loop de login ou vazamento de cookies para outros caminhos.
58. Envie uma mensagem de saudação no chat. Evidência: resposta, conversation ID e mensagem no histórico; nenhum segredo nos logs.
59. Envie uma pergunta baseada em um documento FAQ conhecido. Evidência: resposta fundamentada e citações do documento correto.
60. Envie uma consulta comercial permitida para a conta/loja. Evidência: resposta somente com dados autorizados e sem operações comerciais de escrita pela IA.
61. Encerre a conversa pelo app. Evidência: worker consome o job e persiste o resumo sem erro recorrente em Redis/Mongo/Qdrant.
62. Consulte o histórico e retome a conversa. Evidência: isolamento por usuário e persistência após reinício do app.

## Observe e recuperação

63. Abra `/observe/` em janela privada. Evidência: frontend carrega, dados protegidos não aparecem antes do login.
64. Tente senha inválida na conta de observabilidade. Evidência: login negado, nenhuma sessão emitida.
65. Faça login com a conta de `super_admin`. Evidência: cookie HttpOnly/Secure com Path `/api/v1/observability`, sem valor copiado no chat.
66. Abra os traces da conversa usada nos passos anteriores. Evidência: correlação da requisição, etapas, métricas e custos, sem conteúdo sensível indevido.
67. Execute uma única avaliação de laboratório com entrada sintética. Evidência: resposta do JEV/TypeSafe e resultado visível no Observe. Confirme consumo no provedor antes de repetir.
68. Faça logout do Observe. Evidência: sessão removida e endpoint protegido volta a negar acesso.
69. Reinicie controladamente o Deployment da IA em `api-chatbot`. Evidência: API e worker voltam Ready e dados históricos permanecem disponíveis.
70. Repita uma consulta de histórico. Evidência: conversa/resumo preservados após reinício.
71. Registre resultados por passo, SHA das imagens e falhas remanescentes. Evidência: nenhum teste pendente apresentado como aprovado. Os schedulers ERP e análise comercial permanecem desligados; sua ativação exige cenário de dados e validação próprios.

## Encerramento

72. Confirme que não haverá mais teste nesta sessão e que os resultados estão salvos. Evidência: decisão explícita de encerrar os recursos de teste.
73. Execute `python $Lab down --account $Account --config $Config --confirm-destroy $Account`. Evidência: Terraform remove recursos da conta correta; bancos externos e bucket de estado são preservados.
74. Confira no console AWS EKS, EC2, NLB, API Gateway, VPC e CloudFront. Evidência: nenhum recurso faturável residual do teste; mantenha bucket/estado para auditoria até decisão posterior.
75. Após todos os critérios aprovados, revise os Draft PRs e decida a ordem de merge. Evidência: validação prática registrada antes de promover PRs para review.
