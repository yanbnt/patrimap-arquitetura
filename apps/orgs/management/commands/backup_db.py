"""
Backup do banco de dados.

- SQLite (dev): usa a API de backup do próprio sqlite3 (consistente mesmo com o
  servidor rodando) e salva uma cópia .sqlite3 datada.
- PostgreSQL (prod): chama `pg_dump` e salva um .sql datado.

Mantém apenas os N backups mais recentes (--manter, padrão 30). Os arquivos vão
para a pasta `backups/` na raiz do projeto (ou --destino).

Uso:
    python manage.py backup_db
    python manage.py backup_db --destino "D:/Backups/ITAM" --manter 60
"""

import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Gera um backup datado do banco de dados e limpa os antigos."

    def add_arguments(self, parser):
        parser.add_argument("--destino", default=None, help="Pasta de destino dos backups.")
        parser.add_argument("--manter", type=int, default=30, help="Quantos backups manter.")

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")
        destino = Path(opts["destino"]) if opts["destino"] else Path(settings.BASE_DIR) / "backups"
        destino.mkdir(parents=True, exist_ok=True)
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")

        if "sqlite" in engine:
            origem = Path(db["NAME"])
            if not origem.exists():
                raise CommandError(f"Banco SQLite não encontrado: {origem}")
            alvo = destino / f"itam-{carimbo}.sqlite3"
            # Backup online consistente via API do sqlite3.
            with sqlite3.connect(str(origem)) as src, sqlite3.connect(str(alvo)) as dst:
                src.backup(dst)
            self._fim(alvo, destino, "*.sqlite3", opts["manter"])

        elif "postgresql" in engine:
            alvo = destino / f"itam-{carimbo}.sql"
            env = os.environ.copy()
            if db.get("PASSWORD"):
                env["PGPASSWORD"] = db["PASSWORD"]
            cmd = ["pg_dump", "-h", db.get("HOST") or "localhost",
                   "-p", str(db.get("PORT") or 5432),
                   "-U", db.get("USER") or "postgres", "-d", db["NAME"]]
            try:
                with open(alvo, "wb") as fh:
                    subprocess.run(cmd, check=True, stdout=fh, env=env)
            except FileNotFoundError:
                raise CommandError("pg_dump não encontrado no PATH.")
            except subprocess.CalledProcessError as e:
                raise CommandError(f"pg_dump falhou (código {e.returncode}).")
            self._fim(alvo, destino, "*.sql", opts["manter"])
        else:
            raise CommandError(f"Engine de banco não suportado para backup: {engine}")

    def _fim(self, alvo, destino, padrao, manter):
        tamanho = alvo.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f"Backup criado: {alvo} ({tamanho:.0f} KB)"))
        antigos = sorted(destino.glob(padrao), key=lambda p: p.stat().st_mtime, reverse=True)
        for velho in antigos[manter:]:
            velho.unlink()
            self.stdout.write(f"Removido backup antigo: {velho.name}")
