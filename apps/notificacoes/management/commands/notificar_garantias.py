"""
Notifica a gestão sobre garantias/contratos vencendo nos próximos N dias.

Pronto para ser agendado (Fase 6 — Django-Q2). Não duplica: pula um contrato
se já houver notificação recente com o mesmo link para o usuário.

Uso:
    python manage.py notificar_garantias            # janela padrão (30 dias)
    python manage.py notificar_garantias --dias 15
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from apps.maintenance.models import Warranty
from apps.notificacoes.models import Notificacao, notificar, usuarios_dos_grupos

GESTAO = ["Gerente", "Supervisor"]
# Não reenvia a mesma notificação por este período (evita spam diário).
DEDUP_DIAS = 25


class Command(BaseCommand):
    help = "Cria notificações para garantias/contratos vencendo em breve."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=30,
                            help="Janela em dias para considerar 'vencendo' (padrão 30).")

    def handle(self, *args, **options):
        dias = options["dias"]
        hoje = timezone.localdate()
        limite = hoje + timedelta(days=dias)

        vencendo = (
            Warranty.objects
            .filter(end_date__isnull=False, end_date__gte=hoje, end_date__lte=limite)
            .select_related("asset")
        )

        gestao = list(usuarios_dos_grupos(*GESTAO))
        corte = timezone.now() - timedelta(days=DEDUP_DIAS)
        criadas = 0

        for w in vencendo:
            url = reverse("admin:maintenance_warranty_change", args=[w.pk])
            restam = (w.end_date - hoje).days
            titulo = f"Garantia vencendo: {w.asset.asset_tag}"
            msg = f"{w.get_contract_type_display()} vence em {w.end_date:%d/%m/%Y} ({restam} dia(s))"

            destinatarios = [
                u for u in gestao
                if not Notificacao.objects.filter(
                    destinatario=u, url=url, criada_em__gte=corte,
                ).exists()
            ]
            if destinatarios:
                notificar(
                    destinatarios, titulo, msg, url=url,
                    icone="verified", nivel=Notificacao.Nivel.ALERTA,
                )
                criadas += len(destinatarios)

        self.stdout.write(self.style.SUCCESS(
            f"{vencendo.count()} contrato(s) vencendo; {criadas} notificacao(oes) criada(s)."
        ))
