"""Garante que todo colaborador ATIVO com loja tenha uma baia no mapa.

Visão unificada (pedido do gerente): cada pessoa de uma loja aparece nos mapas
(computadores e notebooks) mesmo sem dispositivo. Este comando cria a baia vazia
que faltar, no setor do departamento do colaborador (ou "A alocar").

Uso:
    python manage.py garantir_baias_colaboradores [--dry-run]
"""
from django.core.management.base import BaseCommand

from apps.orgs.models import Person
from apps.parque.signals import garantir_baia_do_colaborador


class Command(BaseCommand):
    help = "Cria a baia que falta para cada colaborador ativo com loja definida."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Só mostra quantas baias seriam criadas, sem gravar.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        pessoas = (
            Person.objects.filter(active=True, location__isnull=False)
            .select_related("location", "department")
        )
        criadas, ja_tinham, sem_loja = 0, 0, 0
        from apps.parque.models import Baia
        for p in pessoas:
            if Baia.objects.filter(colaborador=p).exists():
                ja_tinham += 1
                continue
            if dry:
                setor = (p.department.name if p.department_id else "") or "A alocar"
                self.stdout.write(f"  criaria baia p/ {p.full_name} em {p.location.name} > {setor}")
                criadas += 1
                continue
            if garantir_baia_do_colaborador(p) is not None:
                criadas += 1
        total_sem_loja = Person.objects.filter(active=True, location__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"{'[dry-run] ' if dry else ''}baias criadas: {criadas} | ja tinham: {ja_tinham} | "
            f"colaboradores ativos SEM loja (nao entram): {total_sem_loja}"
        ))
