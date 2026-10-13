"""
Acesso remoto SEGURO pelo túnel (Cloudflare/ngrok).

Herda as facilidades do dev (hosts liberados, CSRF do túnel, e-mail no console),
mas com **DEBUG DESLIGADO** — assim um erro não vaza traceback/segredos para quem
acessa pela internet. Use isto (não o dev) ao expor o sistema pelo túnel.

Rodar:
    python manage.py runserver 0.0.0.0:8001 --noreload --insecure \
        --settings=config.settings.tunnel

(`--insecure` faz o runserver servir os estáticos mesmo com DEBUG=False.)
"""

from .dev import *  # noqa: F401,F403

DEBUG = False

# Túnel: força o navegador a sempre revalidar (fim do "mudei mas não aparece" por cache).
MIDDLEWARE = ["config.middleware.NoCacheMiddleware", *MIDDLEWARE]  # noqa: F405

# Aqui o REMOTE_ADDR é sempre o loopback do cloudflared: o IP real do usuário
# vem no cabeçalho do proxy. Usado só para registrar o acesso no log.
SENHA_TEMP_CONFIA_NO_PROXY = True
