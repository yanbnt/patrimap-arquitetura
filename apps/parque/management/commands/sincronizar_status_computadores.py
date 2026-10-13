"""
Reconcilia o status dos computadores com o vínculo real de baia.

O signal `sincronizar_status_computador` cuida do caminho normal (save de baia),
mas ele NÃO roda quando o vínculo muda por `queryset.update()` — que não dispara
signal. Este comando é a rede de segurança: passa o parque inteiro e corrige.

    python manage.py sincronizar_status_computadores            # aplica
    python manage.py sincronizar_status_computadores --dry-run  # só mostra

Rode depois de importação em massa, de correção manual no banco, ou como tarefa
agendada semanal.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.parque.models import Computador


class Command(BaseCommand):
    help = "Corrige o status dos computadores conforme o vínculo com baia."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Mostra o que seria corrigido, sem gravar.",
        )

    def handle(self, *args, **opts):
        seco = opts["dry_run"]

        # Em uso mas sem baia nenhuma → volta ao estoque.
        orfaos = Computador.objects.filter(
            status=Computador.Status.EM_USO, baia__isnull=True
        )
        # Numa baia mas com status de estoque → passa a "em uso".
        # Defeito/Desativado são status MANUAIS: não se mexe neles.
        esquecidos = Computador.objects.filter(
            baia__isnull=False, status=Computador.Status.EM_ESTOQUE
        )

        n_orfaos = orfaos.count()
        n_esquecidos = esquecidos.count()

        for c in orfaos[:20]:
            self.stdout.write(f"  em uso sem baia   → estoque: {c.patrimonio}")
        for c in esquecidos[:20]:
            self.stdout.write(f"  em baia com estoque → em uso: {c.patrimonio}")

        if seco:
            self.stdout.write(self.style.WARNING(
                f"[dry-run] {n_orfaos} para estoque, {n_esquecidos} para em uso."
            ))
            return

        with transaction.atomic():
            orfaos.update(status=Computador.Status.EM_ESTOQUE)
            esquecidos.update(status=Computador.Status.EM_USO)

        self.stdout.write(self.style.SUCCESS(
            f"Sincronizado: {n_orfaos} para estoque, {n_esquecidos} para em uso."
        ))
