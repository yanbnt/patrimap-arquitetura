"""
Verificação de localização por IP público (telemetria).

Recalcula, a partir das coletas do agente, qual unidade é "dona" de cada IP
público (por maioria) e detecta máquinas cuja localização cadastrada diverge da
detectada. Para cada divergência, gera uma NOTIFICAÇÃO interna avisando os
responsáveis da loja (ambas: a cadastrada e a detectada) e a gestão, dizendo que
a localização está errada e oferecendo a correção.

Idempotente: dedup por `chave='geoloc:<serial>'` dentro de DEDUP_DIAS.
Pronto para o agendador (ver "Manutenção Diária ITAM.bat").

Uso:  python manage.py verificar_localizacao [--dry-run]
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notificacoes.models import Notificacao, notificar, usuarios_dos_grupos
from apps.parque import geoloc

GESTAO = ["Gerente", "Supervisor"]
RESPONSAVEIS = ["Técnico de Pós Venda", "Estagiário"]
DEDUP_DIAS = 3
URL_PAINEL = "/parque/agente/#divergencias"


def responsaveis_das_unidades(*unidade_ids):
    ids = [u for u in unidade_ids if u]
    if not ids:
        return []
    return list(
        User.objects.filter(
            is_active=True, groups__name__in=RESPONSAVEIS,
            colaborador__location_id__in=ids,
        ).distinct()
    )


class Command(BaseCommand):
    help = "Detecta e notifica divergências de localização (IP público × cadastro)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Apenas mostra o que faria, sem notificar.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        corte = timezone.now() - timedelta(days=DEDUP_DIAS)

        divergencias = geoloc.recalcular()

        gestao = list(usuarios_dos_grupos(*GESTAO))
        notifs = 0
        for t in divergencias:
            cad = t.unidade_cadastrada
            det = t.unidade_detectada
            patr = t.alvo
            chave = f"geoloc:{t.serial}"
            titulo = f"Localização divergente — {patr}"
            msg = (f"Cadastrado em {cad.name if cad else '—'}, mas reportando de "
                   f"{det.name if det else '—'}. Confira e corrija.")

            destin = responsaveis_das_unidades(
                cad.id if cad else None, det.id if det else None) + gestao
            # dedup por destinatário + chave dentro da janela
            destin = [
                u for u in {d.pk: d for d in destin}.values()
                if not Notificacao.objects.filter(
                    destinatario=u, chave=chave, criada_em__gte=corte).exists()
            ]
            if destin:
                if not dry:
                    notificar(destin, titulo, msg, url=URL_PAINEL,
                              icone="wrong_location", nivel=Notificacao.Nivel.ALERTA,
                              chave=chave)
                notifs += len(destin)

        prefixo = "[dry-run] " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefixo}{len(divergencias)} divergência(s) de localização | "
            f"{notifs} notificação(oes)."
        ))
