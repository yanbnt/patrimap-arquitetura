"""Configurações de desenvolvimento (rede interna / máquina local)."""

from .base import *  # noqa: F401,F403

DEBUG = True

# Dev/teste na rede interna: aceita qualquer host (inclui o IP do PC acessado
# pelo celular). Em produção, prod.py usa ALLOWED_HOSTS restrito.
ALLOWED_HOSTS = ["*"]

# Acesso remoto via túnel (Cloudflare/ngrok): libera o CSRF para o domínio
# https do túnel — senão login e formulários falham (origem https externa).
CSRF_TRUSTED_ORIGINS = [
    "https://*.trycloudflare.com",
    "https://*.ngrok-free.app",
    "https://*.ngrok.io",
]

# Sem SMTP no .env (EMAIL_HOST vazio) → e-mails caem no console do servidor.
# Com EMAIL_HOST configurado, usa o SMTP de verdade (definido no base.py).
if not EMAIL_HOST:  # noqa: F405 (vem do base via *)
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
