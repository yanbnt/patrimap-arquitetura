"""
Desativa (corta o acesso de) usuários inativos há N dias (padrão 15).

Usa a última atividade registrada (AtividadeUsuario.visto_em); na ausência dela,
cai para o último login ou a data de cadastro. Superusuários nunca são afetados.
Desativa (is_active=False) em vez de excluir — reversível e auditável.

Pronto para ser agendado (ver "Manutenção Diária ITAM.bat").

Uso:  python manage.py desativar_inativos            # 15 dias
      python manage.py desativar_inativos --dias 30
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Desativa usuários sem atividade há N dias (padrão 15)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=15,
                            help="Dias de inatividade para desativar (padrão 15).")

    def handle(self, *args, **opts):
        dias = opts["dias"]
        limite = timezone.now() - timedelta(days=dias)
        desativados = []

        for u in User.objects.filter(is_active=True, is_superuser=False):
            ativ = getattr(u, "atividade", None)
            visto = ativ.visto_em if ativ else (u.last_login or u.date_joined)
            if visto and visto < limite:
                u.is_active = False
                u.save(update_fields=["is_active"])
                desativados.append(u.get_username())

        if desativados:
            self.stdout.write(self.style.SUCCESS(
                f"{len(desativados)} usuario(s) desativado(s) (inativos > {dias} dias): "
                + ", ".join(desativados)
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Nenhum usuario inativo ha mais de {dias} dias."
            ))
