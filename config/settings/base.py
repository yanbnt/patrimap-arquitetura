"""
Configurações base do Patrimap — o sistema de gestão de ativos de TI da Make Distribuidora.

Compartilhadas por todos os ambientes. Sobrescritas em dev.py / prod.py.
Lê variáveis de ambiente de um arquivo .env via django-environ.
"""

import mimetypes
import os
from pathlib import Path

import environ

# Garante o tipo correto do .webp (logo) ao ser servido como estático.
mimetypes.add_type("image/webp", ".webp", True)
from django.templatetags.static import static
from django.utils.translation import gettext_lazy as _

# itam/  (dois níveis acima de config/settings/base.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
# Lê .env na raiz do projeto, se existir.
environ.Env.read_env(BASE_DIR / ".env")

# SECURITY ----------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")

# Chave dos campos cifrados (senha de notebook e AnyDesk).
#
# O `apps/parque/campos.py` sempre documentou ler `settings.CAMPO_CRIPTO_KEY`,
# mas a variável NUNCA foi ligada aqui: o `getattr` caía no vazio e a chave
# saía derivada do SECRET_KEY. Consequência silenciosa: trocar o SECRET_KEY
# (rotação de segredo, novo deploy) tornaria as senhas já cifradas ilegíveis.
#
# Ligada agora, antes da migração 0061 rodar em produção. Sem valor no .env o
# comportamento é o mesmo de hoje (deriva do SECRET_KEY), então isto não muda
# nada para quem já rodou — mas permite fixar a chave com
# `python manage.py gerar_chave_campos` e guardá-la fora do banco.
CAMPO_CRIPTO_KEY = env("CAMPO_CRIPTO_KEY", default="")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Token do endpoint de TELEMETRIA (agente de coleta de desempenho nas máquinas).
# Vazio = endpoint desligado (responde 503). Definir no .env (NÃO versionado).
TELEMETRIA_TOKEN = env("TELEMETRIA_TOKEN", default="")
# Chave PRIVADA (RSA, PEM em base64) para decifrar a telemetria E2EE. Quando
# definida, o endpoint EXIGE payload cifrado com a chave pública (RSA+AES). A
# pública é derivada dela e embutida no agente. Gerar: manage.py telemetria_gerar_chave.
TELEMETRIA_PRIV_KEY = env("TELEMETRIA_PRIV_KEY", default="")

# APLICAÇÕES --------------------------------------------------------------
# unfold (tema do admin) DEVE vir antes de django.contrib.admin.
UNFOLD_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
]

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "axes",  # proteção anti-brute-force no login (bloqueio por tentativas)
    # Adicionados conforme as fases avançam:
    # "rest_framework", "django_filters", "import_export", "django_q", ...
]

LOCAL_APPS = [
    "apps.catalog",
    "apps.orgs",
    "apps.inventory",
    "apps.maintenance",
    "apps.parque",
    "apps.orcamentos",
    "apps.notificacoes",
]

INSTALLED_APPS = UNFOLD_APPS + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Presença: registra a última atividade (painel "Usuários online").
    "apps.orgs.middleware.AtividadeUsuarioMiddleware",
    # Obriga a trocar a senha quando o acesso foi feito com senha temporária.
    "apps.orgs.middleware.TrocaSenhaObrigatoriaMiddleware",
    # AxesMiddleware DEVE ser o ÚLTIMO: intercepta o login p/ aplicar o bloqueio.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notificacoes.context_processors.notificacoes",
                "apps.parque.context_processors.navegacao",
                # As lojas no pé da gaveta (menu de 5 destinos).
                "apps.parque.context_processors.unidades_menu",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# BANCO DE DADOS ----------------------------------------------------------
# DATABASE_URL controla o banco. Dev usa SQLite (sem instalar nada, é o default).
# Produção = app na AWS + banco no SUPABASE (PostgreSQL). Para apontar, defina no
# .env (sem tocar em código):
#   DATABASE_URL=postgres://postgres.<ref>:<senha>@<host-session-pooler>:5432/postgres
#   DB_SSL_REQUIRE=True                 # Supabase exige TLS
#   DB_CONN_MAX_AGE=60                  # conexões persistentes (AWS↔Supabase é cross-network)
#   # Se usar o TRANSACTION pooler (PgBouncer, porta 6543) em vez do session pooler:
#   #   DB_CONN_MAX_AGE=0  +  DB_DISABLE_SERVER_SIDE_CURSORS=True
# Preferir o SESSION pooler (5432, tem IPv4; a conexão direta do Supabase é IPv6-only).
# Defaults abaixo preservam 100% o comportamento atual do SQLite (sem SSL, sem pool).
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
# Ajustes por env (aplicados sobre o dict; defaults preservam o SQLite do dev).
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)
if env.bool("DB_SSL_REQUIRE", default=False):
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "require"
# Necessário só no transaction pooler (PgBouncer, 6543) do Supabase; default não afeta.
if env.bool("DB_DISABLE_SERVER_SIDE_CURSORS", default=False):
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

# SQLite: WAL + espera maior no lock. Sem isso, leitura e escrita simultâneas
# (servidor 24/7 + agentes de telemetria enviando dados) davam
# "database is locked" com os 5 s de timeout padrão.
# ATENÇÃO: WAL exige que o arquivo do banco NÃO esteja em pasta sincronizada
# (OneDrive/Dropbox) — a sincronização do -wal/-shm corrompe o banco. O .env
# do servidor já aponta para fora do OneDrive (C:/dados).
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {}).update({
        "timeout": env.int("DB_TIMEOUT", default=20),
        "init_command": (
            "PRAGMA journal_mode=WAL;"
            "PRAGMA synchronous=NORMAL;"
            "PRAGMA foreign_keys=ON;"
        ),
    })

# CACHE -------------------------------------------------------------------
# Auditoria 2.4: não havia `CACHES` nenhum, então o Django caía no LocMemCache
# anônimo — um cache por PROCESSO, silenciosamente errado para as duas coisas
# que já dependem dele:
#   • o rate limit da recuperação de senha (`apps/orgs/views.py:100-110`): com
#     mais de um worker do waitress, cada processo tem o seu contador e o
#     limite de 3 pedidos vira, na prática, 3 × nº de processos;
#   • o cache do dashboard (Onda 2, item 2.4): cada processo reaquece o seu.
# Seguimos em LocMemCache (nenhuma dependência nova), mas agora NOMEADO — a
# `LOCATION` fixa garante que todo `caches["default"]` do processo é o MESMO
# dicionário — e com TIMEOUT/MAX_ENTRIES por env.
# Para o cache valer ENTRE processos/máquinas, use Redis: instale o pacote
# `redis`, defina REDIS_URL no .env e descomente o bloco abaixo (o backend já
# vem no Django 4+, não precisa de django-redis).
CACHE_TIMEOUT = env.int("CACHE_TIMEOUT", default=300)           # 5 min (default do Django)
CACHE_MAX_ENTRIES = env.int("CACHE_MAX_ENTRIES", default=5000)  # antes de podar o cache
REDIS_URL = env("REDIS_URL", default="")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "itam-default",
        "TIMEOUT": CACHE_TIMEOUT,
        "OPTIONS": {"MAX_ENTRIES": CACHE_MAX_ENTRIES},
    }
}

# --- Redis (cache compartilhado entre processos) — trocar por env, sem código:
# if REDIS_URL:
#     CACHES["default"] = {
#         "BACKEND": "django.core.cache.backends.redis.RedisCache",
#         "LOCATION": REDIS_URL,          # ex.: redis://127.0.0.1:6379/1
#         "TIMEOUT": CACHE_TIMEOUT,
#         "KEY_PREFIX": "itam",
#     }

# LIMITES DE UPLOAD / CORPO DA REQUISIÇÃO ---------------------------------
# Auditoria 4.5: nada era declarado aqui, então valiam os defaults implícitos
# do Django (2,5 MB de corpo, 1.000 campos) — sem ninguém saber e sem poder
# ajustar no servidor. Os valores abaixo são MAIS FOLGADOS que esse default
# (planilha de import e anexos de manutenção continuam passando), mas agora o
# teto é explícito e regulável por env, em vez de acidental.
# ATENÇÃO: `DATA_UPLOAD_MAX_MEMORY_SIZE` NÃO conta o tamanho dos ARQUIVOS
# enviados — limitar o tamanho de um arquivo continua sendo trabalho da
# validação do formulário (item 4.8: hoje só a extensão é checada).
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024      # 10 MB de POST (fora arquivos)
)
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "FILE_UPLOAD_MAX_MEMORY_SIZE", default=5 * 1024 * 1024       # acima disso vai p/ arquivo temporário
)
# Teto de campos por POST (anti-DoS por colisão de hash). Telas que editam
# muitas linhas de uma vez (mapa, transferências em lote) pedem folga sobre 1.000.
DATA_UPLOAD_MAX_NUMBER_FIELDS = env.int("DATA_UPLOAD_MAX_NUMBER_FIELDS", default=2000)

# VALIDAÇÃO DE SENHA ------------------------------------------------------
# Sem regras de complexidade de senha (a equipe define a senha livremente).
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# RECUPERAÇÃO DE SENHA -----------------------------------------------------
# Validade (horas) da senha temporária enviada por e-mail; depois disso ela
# para de funcionar e o usuário precisa pedir uma nova.
SENHA_TEMP_VALIDADE_HORAS = env.int("SENHA_TEMP_VALIDADE_HORAS", default=24)
# Limite de pedidos de recuperação por USUÁRIO/E-MAIL dentro da janela
# (anti-spam/DoS). A chave é o identificador digitado, não o IP: atrás do túnel
# o IP vem de cabeçalho e trocá-lo zerava o contador.
SENHA_TEMP_MAX_PEDIDOS = env.int("SENHA_TEMP_MAX_PEDIDOS", default=3)
SENHA_TEMP_JANELA_MINUTOS = env.int("SENHA_TEMP_JANELA_MINUTOS", default=15)
# Só ligue onde o Django REALMENTE está atrás de um proxy confiável (túnel
# Cloudflare/ngrok, feito em tunnel.py). Serve apenas para registrar o IP real
# no log de acesso — não entra em nenhuma decisão de segurança.
SENHA_TEMP_CONFIA_NO_PROXY = env.bool("SENHA_TEMP_CONFIA_NO_PROXY", default=False)

# AUTENTICAÇÃO ------------------------------------------------------------
# Permite login por usuário OU e-mail (case-insensitive) na tela de login.
AUTHENTICATION_BACKENDS = [
    # AxesStandaloneBackend PRIMEIRO: bloqueia o login após muitas tentativas
    # falhas (não autentica; só barra/deixa passar para o próximo backend).
    "axes.backends.AxesStandaloneBackend",
    # Subclasse de ModelBackend: trata login por usuário OU e-mail, herda as
    # permissões e ainda barra senha temporária expirada. (Não somar o
    # ModelBackend padrão aqui, senão ele autenticaria ignorando a expiração.)
    "apps.orgs.backends.EmailOuUsernameBackend",
]

# Pós-login sem ?next= vai pro sistema (admin), não pro /accounts/profile/ (404).
LOGIN_URL = "admin:login"
# O login cai em /inicio/, que manda para o Mural quem o abre e para o
# painel quem nao o abre — sem jogar 8 dos 13 num "acesso negado".
LOGIN_REDIRECT_URL = "/inicio/"
LOGOUT_REDIRECT_URL = "admin:login"

# SEGURANÇA (todos os ambientes) ------------------------------------------
# Anti-brute-force no login (django-axes): trava após várias tentativas falhas.
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)   # tentativas até bloquear
AXES_COOLOFF_TIME = env.int("AXES_COOLOFF_TIME", default=1)     # horas de bloqueio
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]         # bloqueia o par usuário+IP
AXES_RESET_ON_SUCCESS = True                                   # zera o contador ao acertar
AXES_ENABLE_ACCESS_FAILURE_LOG = True

# Cabeçalhos de proteção do navegador.
SECURE_CONTENT_TYPE_NOSNIFF = True          # impede MIME-sniffing
SECURE_REFERRER_POLICY = "same-origin"      # não vaza a URL interna para fora
X_FRAME_OPTIONS = "DENY"                     # anti-clickjacking (não embutir em iframe)
SESSION_COOKIE_HTTPONLY = True               # cookie de sessão fora do alcance do JS
SESSION_COOKIE_SAMESITE = "Lax"

# Sessão expira em 12h; janela deslizante (usuário ativo não é deslogado).
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = True

# INTERNACIONALIZAÇÃO -----------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
# Traduções do projeto (pt-BR) — cobrem as strings do django-unfold, que não
# vem com tradução. Têm prioridade sobre as traduções dos apps.
LOCALE_PATHS = [BASE_DIR / "locale"]

# ARQUIVOS ESTÁTICOS ------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Arquivos de mídia (uploads, anexos de manutenção etc.)
# MEDIA_ROOT vem do .env — NÃO deixe dentro do OneDrive (ele "some" com os arquivos:
# deixa só na nuvem / não sincroniza), gerando 404 nos anexos. Default = BASE_DIR/media.
MEDIA_URL = "media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# TEMA DO ADMIN (django-unfold) -------------------------------------------
# Visual clean + Material com a identidade da Make Distribuidora.
# Estrutura em verde médio (#32673A); verde lima (#CBF542) só como destaque
# (via static/css/make-admin.css). Tema claro/escuro alternável pelo usuário.
MAKE_LOGO_URL = (
    "https://exemplo.com.br/arquivos/empresa/"
    "LOGOe0e4e12c3f410d633905c499ad7e6818.webp"
)
def _asset_versionado(rel_path):
    """
    URL do estático com ?v=<mtime> para o navegador sempre pegar a versão nova
    ao editarmos o CSS/JS (evita ficar com arquivo antigo em cache).

    O mtime é lido do arquivo QUE VAI SER SERVIDO. Em produção o WhiteNoise
    serve o STATIC_ROOT (`staticfiles/`), não a pasta de origem — e ler o mtime
    da origem criava o pior dos mundos: a URL anunciava versão nova enquanto o
    servidor entregava o arquivo antigo (por falta de `collectstatic`), e o
    navegador então guardava o conteúdo VELHO sob a URL NOVA, em cache, sem jeito
    de sair dali sem limpar à mão. Foi assim que o botão de menu ficou morto na
    máquina do dono: HTML novo pedindo um JS que não conhecia o botão.

    Lendo do destino, a versão só muda quando o arquivo servido muda de fato.
    """
    url = static(rel_path)
    candidatos = []
    if STATIC_ROOT:
        candidatos.append(Path(STATIC_ROOT) / rel_path)
    candidatos.append(BASE_DIR / "static" / rel_path)
    for caminho in candidatos:
        try:
            return f"{url}?v={int(os.path.getmtime(caminho))}"
        except OSError:
            continue
    return url


# ---------------------------------------------------------------------------
# QUEM VÊ CADA ITEM DO MENU
#
# A condição não é mais escrita aqui: ela vem do registro único de telas
# (apps/orgs/acessos.py), que a tela /parque/acessos/ edita. Antes, cada item
# tinha a lista de grupos digitada à mão nesta linha E a view tinha a sua —
# duas listas para a mesma pergunta, que divergiram na prática.
#
# O import acontece DENTRO da função de propósito: settings é carregado antes
# do registro de apps, e importar modelo aqui estoura AppRegistryNotReady.
# ---------------------------------------------------------------------------
def _porta(tela):
    def condicao(request):
        from apps.orgs.acessos import pode_ver_tela
        return pode_ver_tela(request.user, tela, request=request)
    return condicao


UNFOLD = {
    "SITE_TITLE": "Patrimap",
    "SITE_HEADER": "Patrimap · Make Distribuidora",
    "SITE_SUBHEADER": "Gestão de Ativos de TI",
    "SITE_SYMBOL": "inventory_2",  # ícone Material Symbols (fallback)
    # Logo local da Make (mesma da tela de login).
    "SITE_LOGO": {
        "light": lambda request: static("img/make-logo.webp"),
        "dark": lambda request: static("img/make-logo.webp"),
    },
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "apps.dashboard.dashboard_callback",
    # Sem "THEME" fixo => o usuário alterna entre claro e escuro no header.
    "BORDER_RADIUS": "10px",
    "STYLES": [
        lambda request: _asset_versionado("css/make-admin.css"),
        # Acabamento profissional (tokens + componentes padrão). Carrega DEPOIS
        # do make-admin para poder corrigir. Contrato: DESIGN-PRO.md.
        lambda request: _asset_versionado("css/make-pro.css"),
        # Sistema de interface: MATERIAL DESIGN 3 (Material You) com a paleta
        # tonal derivada do verde da Make. Carrega por ÚLTIMO — é ele que define
        # superfície, forma, tipografia e componentes. Contrato: DESIGN-SYSTEM.md.
        lambda request: _asset_versionado("css/make-m3.css"),
        # Assistente de ajuda (widget flutuante em todas as telas).
        lambda request: _asset_versionado("css/make-assistente.css"),
        # O chat do time: widget em toda tela, como o assistente. Ele se
        # esconde sozinho para quem nao abre o Mural (o servidor responde
        # `pode: false` e a bolha nem e' criada).
        lambda request: _asset_versionado("css/make-chat.css"),
    ],
    "SCRIPTS": [
        lambda request: _asset_versionado("js/make-admin.js"),
        # Movimento do M3: ripple no toque e top app bar reagindo à rolagem.
        lambda request: _asset_versionado("js/make-m3.js"),
        lambda request: _asset_versionado("js/make-assistente.js"),
        lambda request: _asset_versionado("js/make-chat.js"),
    ],
    # Paleta primária = verde vivo (linha Intelbras), estilo Material.
    "COLORS": {
        "primary": {
            "50": "232 250 239",
            "100": "198 244 217",
            "200": "140 232 180",
            "300": "76 214 138",
            "400": "30 192 105",
            "500": "0 166 81",    # #00A651 — verde Intelbras
            "600": "0 145 63",    # #00913F
            "700": "0 120 53",
            "800": "6 95 44",
            "900": "8 71 36",
            "950": "3 40 20",
        },
        # Cinza NEUTRO (sem o azul do slate padrão) — tema escuro puxado p/ preto.
        "base": {
            "50": "250 250 250",
            "100": "244 244 244",
            "200": "228 228 228",
            "300": "212 212 212",
            "400": "161 161 161",
            "500": "112 112 112",
            "600": "82 82 82",
            "700": "55 55 55",
            "800": "33 33 33",
            "900": "20 20 20",
            "950": "10 10 10",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        # ARQUITETURA DO MENU (redesign 09/2026) — organizado pelo que a pessoa
        # FAZ, não pelo nome do modelo no banco. Sete telas reais não tinham
        # entrada nenhuma (o MAPA — a tela mais usada do sistema —, Aprovações,
        # Orçamentos, Peças, Etiquetas, Fora de uso, Montar caixa): chegava-se
        # nelas por dentro de outra tela ou pelo sino. Agora:
        #   topo      = o que se abre todo dia
        #   Manutenção = o ciclo do chamado, do abrir ao aprovar o custo
        #   Patrimônio = a coisa física: onde está, para onde vai, o que saiu
        #   Cadastros  = o que muda de vez em quando
        #   Administração = restrita, como já era
        # "Ajuda" saiu: virou o assistente (botão flutuante e "?" da barra).
        # ARQUITETURA DO MENU — organizado pelo que a pessoa FAZ.
        #
        # NOTA DE RECONSTRUÇÃO (04/09/2026): este bloco foi substituído por um
        # menu de 5 itens e depois RESTAURADO, a pedido do dono. Eu não havia
        # guardado cópia do original antes de trocar — erro meu. Estrutura,
        # rótulos, links, badges e permissões foram reconstruídos a partir do
        # que estava documentado nesta sessão; alguns ÍCONES podem não ser
        # idênticos aos de antes. Se quiser o original exato, o arquivo está no
        # OneDrive: clique com o direito em base.py > Histórico de versões.
        "navigation": [
            {
                "items": [
                    # "Inicio" e' a tela inicial de verdade: leva ao Mural
                    # para quem o abre, e ao painel para quem nao o abre.
                    {"title": _("Início"), "icon": "home", "link": "/inicio/",
                     "permission": _porta("inicio")},
                    {"title": _("Mapa do parque"), "icon": "map",
                     "link": "/parque/mapa-completo/", "permission": _porta("mapa")},
                    # AS TRÊS TELAS DE GERIR, UMA EMBAIXO DA OUTRA (09/2026).
                    #
                    # O Dashboard ANTIGO (apps/dashboard) saiu do menu; quem
                    # ficou com o nome é esta tela — a que conclui, para
                    # diretoria e RH. Junto dela, Arquivo (o que provar),
                    # Preventiva (o que fazer) e Registros (o que foi feito):
                    # o caminho de quem gerencia, numa coluna só, em vez de
                    # espalhado por três grupos de menu.
                    #
                    # Cada view repete a checagem de acesso; esconder do menu
                    # não é controle de acesso.
                    # "Dashboard" e' o nome que a casa usa. O nome interno do
                    # modulo e da URL segue leitura-executiva — renomear isso
                    # nao muda nada para quem usa e quebra link guardado.
                    {"title": _("Dashboard"), "icon": "insights",
                     "link": "/parque/leitura-executiva/",
                     "permission": _porta("dashboard")},
                    # A condicao aqui e' a MESMA de arquivo.py:pode_ler. Menu mais
                    # restrito que a view esconde tela que a pessoa pode abrir;
                    # menu mais frouxo entrega 403. Os dois sao defeito.
                    {"title": _("Arquivo"), "icon": "topic", "link": "/parque/arquivo/",
                     "permission": _porta("arquivo")},
                    {"title": _("Preventiva"), "icon": "event_repeat",
                     "link": "/parque/preventiva/", "permission": _porta("preventiva")},
                    # MURAL: era "Registros" (calendario de seis semanas com
                    # tres fontes). Virou feed com as dez fontes, comentario,
                    # foto do servico e quem assumiu a demanda — e comeu os
                    # itens "Usuarios online" e "Logs", que saem daqui.
                    #
                    # O ITEM "Mural" SAIU DO MENU EM 18/09/2026, a pedido do
                    # Jonas: o Mural passou a ser a tela inicial, e ter "Inicio"
                    # e "Mural" lado a lado levando ao mesmo lugar e' dizer duas
                    # vezes a mesma coisa.
                    #
                    # Ninguem perde acesso: "Inicio" (/inicio/) e' aberta a
                    # todos e manda para o Mural EXATAMENTE quem tem a tela
                    # "registros" — os demais seguem para o painel de sempre
                    # (ver apps/parque/mural.py:inicio). A porta continua sendo
                    # "registros" na tela de Usuarios e acessos, e a URL
                    # /parque/mural/ continua valendo para link guardado.
                ],
            },
            {
                "title": _("Manutenção"),
                "separator": True,
                "items": [
                    {"title": _("Chamados"), "icon": "handyman",
                     "link": "/parque/reparos/", "permission": _porta("chamados")},
                    # Preventiva subiu para o topo com Registros: uma diz o que
                    # fazer, a outra o que foi feito — e as duas juntas sao
                    # metade do trabalho de quem gerencia. Ficar aqui deixava o
                    # par separado por dois grupos de menu.
                    # Registros subiu para o topo, junto de Dashboard e
                    # Arquivo: o calendário de conferência do RH é uma das três
                    # telas de gerir, não um passo do ciclo do chamado.
                    {"title": _("Assistência externa"), "icon": "home_repair_service",
                     "link": "/parque/autorizadas/", "permission": _porta("autorizadas")},
                    {"title": _("Orçamentos"), "icon": "request_quote",
                     "link": "/orcamentos/", "permission": _porta("orcamentos")},
                    # Aprovações: a view exige GRUPOS_MOVIMENTACAO — mostrar para
                    # quem não pode decidir só entregaria um 403.
                    {"title": _("Aprovações"), "icon": "how_to_reg",
                     "link": "/parque/aprovacoes/",
                     "badge": "apps.parque.badges.aprovacoes_pendentes",
                     "permission": _porta("aprovacoes")},
                ],
            },
            {
                "title": _("Patrimônio"),
                "separator": True,
                "items": [
                    # DOIS itens, não cinco.
                    #
                    # A tela de Estoque já é o hub do patrimônio: ela tem bloco
                    # para Computadores, Notebooks, Peças e periféricos e a
                    # faixa de "Fora de uso" com a contagem. Ter os mesmos
                    # destinos também no menu era dois caminhos para a mesma
                    # tela — o dono apontou ("menu cheio de item sendo que tem
                    # tudo na tela Estoque").
                    #
                    # Saíram do menu e continuam alcançáveis:
                    #   · Peças e periféricos → bloco "Periféricos" do Estoque
                    #   · Fora de uso         → faixa "Requer atenção" do Estoque
                    #   · Etiquetas           → "Imprimir etiqueta" no popup da máquina
                    # As URLs seguem existindo; nada de link morto.
                    {"title": _("Estoque"), "icon": "inventory_2",
                     "link": "/parque/estoque/", "permission": _porta("estoque")},
                    {"title": _("Transferências"), "icon": "swap_horiz",
                     "link": "/parque/transferencias/", "permission": _porta("transferencias")},
                ],
            },
            {
                "title": _("Cadastros"),
                "separator": True,
                "items": [
                    # UMA PORTA para os cadastros do parque.
                    #
                    # Eram cinco itens (Colaboradores, Setores, Lojas,
                    # Computadores, Notebooks) levando a cinco listas do
                    # admin. O dono pediu duas vezes para unificar: agora a
                    # tela /cadastros/ tem as cinco em abas, com busca e a
                    # ficha do registro ao lado. As telas antigas do admin
                    # continuam existindo por URL (e o "Editar dados" da
                    # ficha leva a elas) — sairam apenas do menu.
                    {"title": _("Cadastros"), "icon": "folder_managed",
                     "link": "/cadastros/", "permission": _porta("cadastros")},
                    {"title": _("Agente e telemetria"), "icon": "sensors",
                     "link": "/parque/agente/", "permission": _porta("agente")},
                    # UM item no lugar de dois. A tela de acessos tem a lista de
                    # pessoas, a de grupos e o que cada grupo destrava — as duas
                    # telas do admin viraram uma. /admin/auth/user/ e
                    # /admin/auth/group/ continuam existindo por URL.
                    {"title": _("Usuários e acessos"), "icon": "manage_accounts",
                     "link": "/parque/acessos/", "permission": _porta("acessos")},
                ],
            },
            # A seção "Administração" tinha só dois itens e os dois moram no
            # Mural agora: "Usuários online" é a faixa de rostos no alto (com
            # a aba "Quem entrou no sistema" para a lista inteira) e "Logs" é
            # a aba "Acessos e ações". As telas /admin/orgs/usuarioonline/ e
            # /logs/ seguem de pé por URL, com as MESMAS permissões — o Mural
            # lê as telas "online" e "logs" do registro para decidir quem vê
            # cada faixa, então ninguém passou a ver o que não via.
            {
                # ÚLTIMA OPÇÃO DO MENU — Central de Ajuda.
                #
                # O "?" da barra de cima saiu porque o assistente flutuante
                # cobre a dúvida rápida. Mas o assistente ABRE esta tela ("ver
                # no manual"), e uma tela que existe precisa de porta própria:
                # sem o item, chegar ao manual completo dependia de acertar a
                # pergunta no chat. Fica no fim, separada, visível para todos —
                # é leitura, não tem o que restringir.
                "separator": True,
                "items": [
                    # A Central de Ajuda MORREU (09/2026). Era a unica tela aberta a
                    # visitante — 139 KB de guia com nome de colaborador e
                    # patrimonio de verdade, publicos na internet — e era
                    # redundante: o assistente flutuante responde o mesmo, em
                    # toda tela, sem pagina para manter. O "?" da barra e o
                    # Alt+H abrem o assistente.
                ],
            },
        ],
    },
}

# --- E-mail (recuperação de senha, alertas) ---
# Para envio REAL, configure no .env: EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER,
# EMAIL_HOST_PASSWORD (SMTP do provedor corporativo). Sem isso, o dev usa console.
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Patrimap · Make Distribuidora <pessoa@exemplo.com.br>",
)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# LOGGING -----------------------------------------------------------------
# Auditoria 1.9: o projeto não tinha NENHUM logging configurado (`grep -rn
# "import logging" apps/ config/` → zero) nem bloco `LOGGING`. Combinado com os
# `except Exception: pass` do item 2.4, TODA falha em produção era invisível:
# o badge sumia, o sino ficava vazio, o e-mail não saía — e não havia onde olhar.
#
# Agora: console (sempre, é o que o waitress/runserver captura) + arquivo
# rotativo (o histórico que sobrevive ao reinício do serviço).
#   LOG_DIR      pasta dos arquivos            (default: <projeto>/logs)
#   LOG_LEVEL    nível dos NOSSOS apps         (default: INFO; use DEBUG p/ investigar)
#   LOG_TO_FILE  False = só console            (útil em teste/CI, que não deve sujar disco)
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()
LOG_TO_FILE = env.bool("LOG_TO_FILE", default=True)
LOG_MAX_BYTES = env.int("LOG_MAX_BYTES", default=5 * 1024 * 1024)  # 5 MB por arquivo
LOG_BACKUP_COUNT = env.int("LOG_BACKUP_COUNT", default=5)          # + 5 backups = 30 MB no máximo

# O RotatingFileHandler NÃO cria a pasta: sem este makedirs o Django morre no
# boot com FileNotFoundError ao instanciar o handler (não é erro de request,
# é o processo não subir). Só criamos quando o handler de arquivo vai existir.
if LOG_TO_FILE:
    os.makedirs(LOG_DIR, exist_ok=True)

_LOG_HANDLERS = ["console"] + (["arquivo"] if LOG_TO_FILE else [])

LOGGING = {
    "version": 1,
    # False: não desliga os loggers que o Django/bibliotecas já criaram ao
    # importar — desligá-los é a forma clássica de "meu log não aparece".
    "disable_existing_loggers": False,
    "formatters": {
        # A stack de exceção entra sozinha no fim da linha sempre que o log é
        # feito com `logger.exception(...)` (ou `exc_info=True`) — que é como
        # os `except` do item 2.4 passaram a registrar. Por isso o ERROR sai
        # com traceback sem precisar de formatter separado.
        "verboso": {
            # Separador ASCII de propósito: o console do Windows é cp1252 e
            # transformaria um travessão em "?" em toda linha.
            "format": "[{levelname}] {asctime} {name}:{lineno} | {message}",
            "datefmt": "%d/%m/%Y %H:%M:%S",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verboso",
        },
    },
    # Rede de segurança: o que não cair em nenhum logger abaixo (django-axes,
    # openpyxl, environ...) ainda aparece a partir de WARNING. Sem isto, um
    # bloqueio de brute-force do axes não iria a lugar nenhum.
    "root": {"handlers": _LOG_HANDLERS, "level": "WARNING"},
    "loggers": {
        # Framework: INFO já mostra as migrações, autoreload e afins.
        "django": {"handlers": _LOG_HANDLERS, "level": "INFO", "propagate": False},
        # Uma linha por requisição do runserver. Vai SÓ para o console: no
        # arquivo ela enche os 5 MB em pouco tempo e faz o rodízio apagar
        # justamente os tracebacks que queremos guardar. (O waitress do
        # local_server.py nem usa este logger.)
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Erro 500 com traceback. propagate=False para não sair duplicado pelo
        # logger pai ("django"), que também tem handlers.
        "django.request": {"handlers": _LOG_HANDLERS, "level": "ERROR", "propagate": False},
        # Host header suspeito, CSRF rejeitado, tentativa de path traversal...
        # Mesmo motivo do propagate=False acima.
        "django.security": {"handlers": _LOG_HANDLERS, "level": "WARNING", "propagate": False},
        # NOSSO código: cobre apps.parque, apps.notificacoes, apps.orgs, ...
        # (o logger de cada módulo é `logging.getLogger(__name__)`, que começa
        # com "apps." e portanto herda daqui).
        "apps": {"handlers": _LOG_HANDLERS, "level": LOG_LEVEL, "propagate": False},
    },
}

if LOG_TO_FILE:
    LOGGING["handlers"]["arquivo"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(LOG_DIR / "itam.log"),
        "maxBytes": LOG_MAX_BYTES,
        "backupCount": LOG_BACKUP_COUNT,
        "formatter": "verboso",
        "encoding": "utf-8",  # sem isto, acento em mensagem quebra no Windows (cp1252)
    }
