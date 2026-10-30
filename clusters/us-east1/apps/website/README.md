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

Compile o frontend com `AUTH_API_URL=/auth` e `CORE_API_URL=/api`.
Não coloque credenciais em variáveis Vite: são públicas no
bundle. Configure `credentials: 'include'` ou Axios `withCredentials: true`.
Os clientes enviam cookies e usam os pares CSRF distintos de Auth e Core.

`/assets/*` retorna 404 quando o arquivo não existe. As demais rotas de frontend
fazem fallback para `index.html`, sem cache desse HTML. `/api` e `/auth` sempre
vão às APIs, inclusive quando elas retornam 404; não fazem fallback para React.

O proxy remove os prefixos públicos: `/auth/login` chega como `/login` e
`/api/chat` chega como `/chat`. Origin, cookies, Authorization e os headers
CSRF são preservados. X-Forwarded-Prefix permite gerar URLs da documentação
com o prefixo público; Auth/Core processam forwarded headers.

O Service NodePort 30080 recebe tráfego apenas do NLB privado gerenciado pelo
Terraform. A URL pública HTTPS é a do API Gateway, compartilhada com as APIs.
Não publique um LoadBalancer adicional para o website.
