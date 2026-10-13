"""
Pré-voo do servidor: confere se a máquina está pronta para hospedar o ITAM.

    python manage.py checar_producao --settings=config.settings.local_server

Não altera nada — só olha e diz o que está OK, o que é aviso e o que impede
subir. Use ANTES de colocar no ar e depois de toda atualização.
"""

import os
import socket
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Confere se o ambiente está pronto para hospedar o sistema."

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.erros = 0
        self.avisos = 0

    # -------------------------------------------------------------- saídas
    def ok(self, msg):
        self.stdout.write(self.style.SUCCESS("  [ok]    ") + msg)

    def aviso(self, msg):
        self.avisos += 1
        self.stdout.write(self.style.WARNING("  [aviso] ") + msg)

    def erro(self, msg):
        self.erros += 1
        self.stdout.write(self.style.ERROR("  [ERRO]  ") + msg)

    def secao(self, titulo):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(titulo))

    # --------------------------------------------------------------- rotina
    def handle(self, *args, **opts):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Pré-voo do ITAM Make — settings: %s" % os.environ.get(
                "DJANGO_SETTINGS_MODULE", "?")))

        self._segredos()
        self._banco()
        self._estaticos_e_midia()
        self._email()
        self._logs()
        self._rede()

        self.stdout.write("")
        if self.erros:
            self.stdout.write(self.style.ERROR(
                f"{self.erros} problema(s) impedem subir · {self.avisos} aviso(s)."))
        elif self.avisos:
            self.stdout.write(self.style.WARNING(
                f"Pronto para subir, com {self.avisos} aviso(s) para revisar."))
        else:
            self.stdout.write(self.style.SUCCESS("Tudo certo. Pode subir."))
        self.stdout.write("")

    # ------------------------------------------------------------- seções
    def _segredos(self):
        self.secao("1. Segredos e chaves")

        if settings.DEBUG:
            self.erro("DEBUG está LIGADO. Em servidor, use "
                      "--settings=config.settings.local_server (ou prod).")
        else:
            self.ok("DEBUG desligado.")

        chave = getattr(settings, "SECRET_KEY", "")
        if not chave or "change-me" in chave or len(chave) < 40:
            self.erro("SECRET_KEY fraca ou padrão. Gere uma no .env.")
        else:
            self.ok("SECRET_KEY definida.")

        cripto = (getattr(settings, "CAMPO_CRIPTO_KEY", "") or "").strip()
        if cripto:
            self.ok("CAMPO_CRIPTO_KEY definida (senhas de máquina cifradas com "
                    "chave própria).")
        else:
            self.aviso("CAMPO_CRIPTO_KEY vazia: as senhas de máquina são cifradas "
                       "com chave derivada do SECRET_KEY. Funciona, mas trocar o "
                       "SECRET_KEY torna as senhas ilegíveis. "
                       "Gere uma: manage.py gerar_chave_campos")

        if not (getattr(settings, "TELEMETRIA_TOKEN", "") or "").strip():
            self.aviso("TELEMETRIA_TOKEN vazio: o endpoint do agente responde 503 "
                       "(telemetria desligada).")
        else:
            self.ok("TELEMETRIA_TOKEN definido.")

    def _banco(self):
        self.secao("2. Banco de dados")
        cfg = settings.DATABASES["default"]
        engine = cfg["ENGINE"].rsplit(".", 1)[-1]
        nome = str(cfg.get("NAME", ""))
        self.ok(f"Engine: {engine} · {nome}")

        if engine.startswith("sqlite"):
            caminho = Path(nome)
            # Compara PARTE do caminho, não o texto inteiro: uma pasta chamada
            # "projeto-onedrive" não é o OneDrive.
            partes = {p.lower() for p in caminho.parts}
            if partes & {"onedrive", "dropbox", "google drive", "googledrive", "icloudrive"}:
                self.erro("O banco está numa pasta SINCRONIZADA na nuvem. Com WAL "
                          "ligado isso CORROMPE o banco. Mova para uma pasta local "
                          "(ex.: C:/dados) e ajuste DATABASE_URL.")
            else:
                self.ok("Banco fora de pasta sincronizada (OneDrive/Dropbox).")

            if caminho.exists():
                mb = caminho.stat().st_size / (1024 * 1024)
                self.ok(f"Arquivo existe ({mb:.1f} MB).")
            else:
                self.aviso("Arquivo do banco ainda não existe — rode `migrate`.")

            try:
                with connection.cursor() as cur:
                    cur.execute("PRAGMA journal_mode;")
                    modo = (cur.fetchone() or [""])[0]
                    cur.execute("PRAGMA foreign_keys;")
                    fk = (cur.fetchone() or [0])[0]
                if str(modo).lower() == "wal":
                    self.ok("journal_mode = WAL (leitura e escrita simultâneas).")
                else:
                    self.aviso(f"journal_mode = {modo} (esperado WAL).")
                self.ok("foreign_keys ligado." if fk else "foreign_keys DESLIGADO.")
            except Exception as e:  # noqa: BLE001
                self.aviso(f"Não consegui ler os PRAGMA do SQLite: {e}")

        # Migrações pendentes
        try:
            from django.db.migrations.executor import MigrationExecutor

            executor = MigrationExecutor(connection)
            plano = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plano:
                self.erro(f"{len(plano)} migração(ões) pendente(s). Rode: manage.py migrate")
            else:
                self.ok("Nenhuma migração pendente.")
        except Exception as e:  # noqa: BLE001
            self.aviso(f"Não consegui checar migrações: {e}")

    def _estaticos_e_midia(self):
        self.secao("3. Estáticos e mídia")
        raiz = Path(getattr(settings, "STATIC_ROOT", "") or "")
        if not raiz:
            self.erro("STATIC_ROOT não definido.")
        elif not raiz.exists():
            self.erro(f"{raiz} não existe. Rode: manage.py collectstatic --noinput")
        else:
            # Os arquivos do redesign precisam estar coletados.
            faltando = [
                nome for nome in (
                    "css/make-admin.css", "css/make-pro.css", "css/make-ui.css",
                    "css/make-auth.css", "css/make-assistente.css",
                    "js/make-admin.js", "js/make-assistente.js",
                )
                if not (raiz / nome).exists()
            ]
            if faltando:
                self.erro("Estáticos NÃO coletados: " + ", ".join(faltando) +
                          ". Rode: manage.py collectstatic --noinput")
            else:
                self.ok("Estáticos do sistema coletados (inclui o redesign e o assistente).")

        midia = Path(getattr(settings, "MEDIA_ROOT", "") or "")
        if not midia:
            self.aviso("MEDIA_ROOT não definido: uploads vão para a pasta do projeto.")
        elif not midia.exists():
            self.aviso(f"MEDIA_ROOT {midia} não existe — será criado no 1º upload.")
        else:
            if {p.lower() for p in midia.parts} & {"onedrive", "dropbox"}:
                self.aviso("MEDIA_ROOT está no OneDrive: anexos podem sumir/duplicar.")
            else:
                self.ok(f"MEDIA_ROOT em {midia}")

    def _email(self):
        self.secao("4. E-mail (recuperação de senha)")
        host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "console" in backend or not host:
            self.aviso("Sem SMTP: a senha temporária vai para o LOG, não para o "
                       "e-mail do usuário. Configure EMAIL_HOST/USER/PASSWORD no .env.")
            return
        self.ok(f"SMTP: {host}:{getattr(settings, 'EMAIL_PORT', '?')}")
        try:
            socket.getaddrinfo(host, getattr(settings, "EMAIL_PORT", 587))
            self.ok("DNS do servidor de e-mail resolve.")
        except OSError as e:
            self.erro(f"Não resolvi o DNS de {host}: {e}")

    def _logs(self):
        self.secao("5. Log")
        cfg = getattr(settings, "LOGGING", None)
        if not cfg:
            self.erro("LOGGING não configurado: falha em produção fica invisível.")
            return
        self.ok("LOGGING configurado.")
        for h in (cfg.get("handlers") or {}).values():
            arquivo = h.get("filename")
            if not arquivo:
                continue
            pasta = Path(arquivo).parent
            if pasta.exists() and os.access(pasta, os.W_OK):
                self.ok(f"Pasta de log gravável: {pasta}")
            else:
                self.erro(f"Sem permissão de escrita em {pasta}")

    def _rede(self):
        self.secao("6. Rede")
        hosts = getattr(settings, "ALLOWED_HOSTS", [])
        if not hosts:
            self.erro("ALLOWED_HOSTS vazio: o Django recusa todas as requisições.")
        elif hosts == ["*"]:
            self.aviso("ALLOWED_HOSTS = ['*'] — aceitável em LAN confiável; "
                       "restrinja se o servidor for exposto à internet.")
        else:
            self.ok(f"ALLOWED_HOSTS: {', '.join(hosts)}")

        try:
            ip = socket.gethostbyname(socket.gethostname())
            self.ok(f"Este servidor responde em http://{ip}:8000 (nome: "
                    f"{socket.gethostname()})")
            self.aviso("Reserve um IP fixo para esta máquina no roteador — se o "
                       "DHCP trocar o IP, os atalhos dos usuários quebram.")
        except OSError:
            self.aviso("Não consegui descobrir o IP local.")
