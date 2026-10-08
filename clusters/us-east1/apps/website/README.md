# Website React e entrada das APIs

Este Deployment substitui o proxy `edge`: um único container Nginx serve os
arquivos React e encaminha `/api` e `/auth`. Não há outro container/sidecar de proxy.

Preencha `REPLACE_WITH_WEBSITE_ARM64_IMAGE_DIGEST` em `deployment.yaml` com uma
imagem ARM64 por digest. A imagem deve conter Nginx, iniciar com
`nginx -g 'daemon off;'`, aceitar `/etc/nginx/nginx.conf` como configuração e
conter o build Vite em `/usr/share/nginx/html`. A configuração é fornecida por
ConfigMap com hash; alterações disparam rollout. O Nginx escuta em 8080.
O runtime sem privilégios da PR quistock-dad #14 é compatível: PID e diretórios
temporários são configurados em `/tmp`, sem exigir escrita em `/var/run`.

Compile o frontend com `VITE_API_URL=/api`; configure as chamadas de autenticação
com base `/auth`. Não coloque credenciais em variáveis Vite: são públicas no
bundle. Configure `credentials: 'include'` ou Axios `withCredentials: true`.
O frontend atual ainda precisa implementar suas chamadas de autenticação.

`/assets/*` retorna 404 quando o arquivo não existe. As demais rotas de frontend
fazem fallback para `index.html`, sem cache desse HTML. `/api` e `/auth` sempre
vão às APIs, inclusive quando elas retornam 404; não fazem fallback para React.

Por compatibilidade com a imagem Auth existente, `/auth/login` chega como
`/auth/login`. Para remover o prefixo, primeiro publique Auth com `/login`,
`/refresh` e `/logout` (incluindo suas regras de segurança), e depois altere
os dois blocos `/auth` no proxy. Saúde e JWKS já são mapeados para a raiz.

O Service NodePort 30080 recebe tráfego apenas do NLB privado gerenciado pelo
Terraform. A URL pública HTTPS é a do API Gateway, compartilhada com as APIs.
Não publique um LoadBalancer adicional para o website.
