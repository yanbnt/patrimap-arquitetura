"""
SERVIDOR DA EMPRESA — máquina Windows dedicada, exposta por IP público + porta.

Diferente dos outros três módulos, e por quê:

  · `local_server.py` é para LAN confiável: fixa `ALLOWED_HOSTS = ["*"]` de
    propósito, porque o IP interno pode mudar por DHCP. Numa máquina alcançável
    pela internet isso é aceitar qualquer cabeçalho Host — é o que permite
    envenenar link de recuperação de senha.
  · `prod.py` é para VPS com HTTPS: força `SECURE_SSL_REDIRECT` e cookie
    "secure". Ligado sem certificado, o login TRAVA (redireciona para um https
    que não existe e o cookie de sessão não viaja em http).
  · `tunnel.py` é para o túnel do Cloudflare, que já entrega HTTPS por fora.

Aqui é o meio que faltava: DEBUG desligado, hosts declarados de verdade,
estáticos pelo WhiteNoise, cabeçalhos de segurança ligados — e o HTTPS
CONTROLADO POR UMA LINHA do `.env`, para o mesmo arquivo servir antes e depois
de existir certificado.

Rodar (é o que o serviço do Windows faz):
    set DJANGO_SETTINGS_MODULE=config.settings.servidor
    waitress-serve --host=0.0.0.0 --port=%ITAM_PORTA% config.wsgi:application

AVISO QUE NÃO DÁ PARA MAQUIAR
-----------------------------
Sem HTTPS, quem entrar de fora manda login e senha em texto aberto pela
internet — qualquer ponto do caminho (Wi-Fi, provedor, rede da loja) lê. Isto
não é opinião de estilo: é a senha do sistema circulando legível. As duas
saídas práticas estão em `deploy/INSTALAR-NO-SERVIDOR.md`; enquanto não
houver uma delas, mantenha o acesso de fora restrito a quem precisa e trate
toda senha daqui como conhecida.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# --- QUEM PODE CHAMAR ESTE SERVIDOR ---------------------------------------
# Obrigatório no .env. Sem isto o Django recusa toda requisição — e é o que
# queremos: melhor um erro na instalação do que um servidor aberto na internet
# aceitando qualquer Host.
#
#   ITAM_HOSTS=10.0.0.10,itam.exemplo.com.br,SRVITAM
ALLOWED_HOSTS = env.list("ITAM_HOSTS", default=[])  # noqa: F405

# --- HTTPS: uma linha liga tudo -------------------------------------------
# Ligue `ITAM_HTTPS=True` SÓ quando existir certificado de verdade na frente
# (proxy reverso, Cloudflare ou IIS). Ligar sem isso derruba o login.
HTTPS_ATIVO = env.bool("ITAM_HTTPS", default=False)  # noqa: F405

# Porta usada nas origens de CSRF (o navegador manda host:porta).
_PORTA = env("ITAM_PORTA", default="8000")  # noqa: F405
_ESQUEMA = "https" if HTTPS_ATIVO else "http"
_SUFIXO = "" if (HTTPS_ATIVO and _PORTA == "443") or _PORTA == "80" else f":{_PORTA}"

CSRF_TRUSTED_ORIGINS = env.list(  # noqa: F405
    "ITAM_ORIGENS",
    default=[f"{_ESQUEMA}://{h}{_SUFIXO}" for h in ALLOWED_HOSTS if h and h != "*"],
)

if HTTPS_ATIVO:
    # Atrás de proxy/Cloudflare: é o cabeçalho que diz se a ponta era https.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS começa curto (1 dia) de propósito: se algo der errado no
    # certificado, o navegador esquece rápido. Suba depois de uma semana boa.
    SECURE_HSTS_SECONDS = 86400
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
else:
    # Em HTTP o cookie "secure" simplesmente não é enviado — login travaria.
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# --- Cabeçalhos que valem em qualquer caso --------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True

# Sessão expira em 12 horas e é renovada a cada acesso: máquina de loja fica
# ligada o dia inteiro, e sessão eterna num servidor público é chave na porta.
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True

# --- Estáticos ------------------------------------------------------------
# O waitress não serve arquivo estático e aqui não existe o `--insecure` do
# runserver: quem serve é o WhiteNoise, logo depois do SecurityMiddleware.
MIDDLEWARE = [
    MIDDLEWARE[0],  # noqa: F405  SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Comprimido, sem manifest hasheado: um estático faltando não derruba a
    # página inteira — em servidor sem ninguém de plantão isso importa.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- IP real de quem acessa ------------------------------------------------
# Só confie no cabeçalho do proxy se existir proxy. Direto na internet, o
# REMOTE_ADDR já é o IP verdadeiro, e confiar no cabeçalho deixaria qualquer um
# falsificar o IP no log de acesso e escapar do bloqueio por tentativas.
SENHA_TEMP_CONFIA_NO_PROXY = env.bool("ITAM_ATRAS_DE_PROXY", default=False)  # noqa: F405
AXES_IPWARE_PROXY_COUNT = 1 if SENHA_TEMP_CONFIA_NO_PROXY else None

# --- E-mail ---------------------------------------------------------------
# Sem SMTP no .env, mensagem vai para o log em vez de estourar erro na tela de
# recuperação de senha.
if not EMAIL_HOST:  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
