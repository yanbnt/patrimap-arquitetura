"""
Gera uma chave para cifrar campos sensíveis (senha de máquina / AnyDesk).

    python manage.py gerar_chave_campos

Copie a saída para o `.env`:

    CAMPO_CRIPTO_KEY=<a chave impressa>

IMPORTANTE
----------
• Guarde a chave FORA do backup do banco. Com o banco e a chave juntos, cifrar
  não protege de nada.
• Trocar a chave torna as senhas já gravadas ilegíveis. Para trocar de verdade:
  decifre com a chave antiga (`migrate parque 0060`), troque a chave, e cifre de
  novo (`migrate parque`).
• Sem `CAMPO_CRIPTO_KEY` no .env, a chave é derivada do `SECRET_KEY` — funciona,
  mas aí trocar o SECRET_KEY também torna as senhas ilegíveis.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gera uma CAMPO_CRIPTO_KEY nova para o .env."

    def handle(self, *args, **opts):
        from cryptography.fernet import Fernet

        chave = Fernet.generate_key().decode()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("CAMPO_CRIPTO_KEY=" + chave))
        self.stdout.write("")
        self.stdout.write(
            "Cole a linha acima no .env. Guarde uma cópia em local seguro,\n"
            "SEPARADA do backup do banco — perder a chave é perder as senhas."
        )
