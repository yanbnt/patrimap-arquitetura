"""
Relatório de colaboradores das baias.

Desde que o campo `Baia.colaborador` virou uma seleção (ForeignKey para
orgs.Person), as Pessoas são criadas automaticamente durante o import
(`import_planilha`). Este comando apenas reporta a situação atual.

Uso:
    python manage.py sincronizar_colaboradores
"""

from django.core.management.base import BaseCommand

from apps.orgs.models import Person
from apps.parque.models import Baia


class Command(BaseCommand):
    help = "Reporta colaboradores (Pessoas) e baias com/sem colaborador."

    def handle(self, *args, **opts):
        total_pessoas = Person.objects.count()
        com = Baia.objects.filter(colaborador__isnull=False).count()
        sem = Baia.objects.filter(colaborador__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"Pessoas cadastradas: {total_pessoas} | "
            f"baias com colaborador: {com} | sem colaborador: {sem}"
        ))
