"""Gera o par de chaves RSA da telemetria E2EE e grava a PRIVADA (base64) no .env.

A chave pública é derivada dela automaticamente e embutida no agente no download.
Uso:
    python manage.py telemetria_gerar_chave [--forcar]
"""
import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gera o par de chaves da telemetria E2EE e grava a privada no .env."

    def add_arguments(self, parser):
        parser.add_argument("--forcar", action="store_true",
                            help="Sobrescreve a chave existente (invalida os agentes atuais).")

    def handle(self, *args, **opts):
        env_path = Path(settings.BASE_DIR) / ".env"
        conteudo = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        ja_tem = any(l.startswith("TELEMETRIA_PRIV_KEY=") for l in conteudo.splitlines())
        if ja_tem and not opts["forcar"]:
            self.stdout.write(self.style.WARNING(
                "Ja existe TELEMETRIA_PRIV_KEY no .env. Use --forcar para regenerar "
                "(vai exigir rebaixar o agente em todas as maquinas)."))
            return

        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = priv.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        b64 = base64.b64encode(pem).decode()

        linhas = [l for l in conteudo.splitlines() if not l.startswith("TELEMETRIA_PRIV_KEY=")]
        linhas.append(f"TELEMETRIA_PRIV_KEY={b64}")
        env_path.write_text("\n".join(linhas).strip() + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            "Chave RSA-2048 gerada e gravada no .env (TELEMETRIA_PRIV_KEY). "
            "Reinicie o servidor e gere um novo pacote do agente (a publica muda)."))
