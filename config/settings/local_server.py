"""
Servidor LOCAL na rede interna (LAN) — HTTP, DEBUG desligado, servido pelo waitress.

Por que um settings próprio (e não o prod.py):
  • prod.py é pra VPS com HTTPS: força SSL redirect, HSTS e cookies "secure" — isso
    QUEBRARIA um servidor de rede local em HTTP (redirecionaria pra https inexistente
    e o cookie de sessão não iria por http → login travado).
  • Aqui é rede interna confiável, sem HTTPS. Segurança de host header via ALLOWED_HOSTS.

O que este módulo faz:
  • DEBUG=False (não vaza traceback).
  • Estáticos servidos pelo WhiteNoise (waitress não serve estáticos sozinho; e aqui
    não existe o `--insecure` do runserver de desenvolvimento).
  • Banco SQLite (do base). Mídia via .env (fora do OneDrive) — servida pela view
    `media_protegida` (login exigido), que já funciona com DEBUG=False.

Rodar (use o iniciar-servidor.bat):
    set DJANGO_SETTINGS_MODULE=config.settings.local_server
    waitress-serve --host=0.0.0.0 --port=8000 config.wsgi:application
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# Rede interna: aceita qualquer host. Seguro aqui porque é LAN confiável e DEBUG=False
# (o check de Host header protege sobretudo sites na internet). Fixamos "*" de propósito
# — o IP do servidor pode mudar por DHCP e não queremos travar o acesso.
# RECOMENDAÇÃO: reserve um IP fixo pra esta máquina no roteador (DHCP reservation).
ALLOWED_HOSTS = ["*"]

# CSRF: confia nas origens HTTP da rede local (host:porta) p/ login e formulários.
CSRF_TRUSTED_ORIGINS = env.list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://servidor.local:8000", "http://LAB12:8000",
    ],
)

# WhiteNoise serve os estáticos coletados (STATIC_ROOT) — logo após o SecurityMiddleware.
MIDDLEWARE = [
    MIDDLEWARE[0],  # noqa: F405  django.middleware.security.SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Comprime (gzip) sem manifest hasheado — mais robusto num 1º deploy (não quebra
    # se algum template referenciar um estático inexistente).
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Sem SMTP configurado no .env → e-mails vão pro log do servidor (não dá erro de envio).
if not EMAIL_HOST:  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
