"""
Painel de tarefas de saúde — automação.

Varre o parque e cria/atualiza/resolve `Tarefa` (sem telemetria, uptime alto,
score baixo) e notifica os responsáveis de cada loja + a gestão.

Idempotente (dedup por `Tarefa.chave` e por janela DEDUP_DIAS nas notificações).
Pronto para o agendador (junto do `notificar_preventivas`).

Uso:  python manage.py gerar_tarefas [--dry-run]
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notificacoes.models import Notificacao, notificar, usuarios_dos_grupos
from apps.parque.tarefas import (
    GESTAO, sincronizar_tarefas, tecnicos_da_unidade,
)

DEDUP_DIAS = 3  # não reenvia a mesma notificação dentro desse período
URL_PAINEL = "/parque/preventiva/?vista=tarefas"


class Command(BaseCommand):
    help = "Gera/atualiza tarefas de saúde do parque + notificações."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Apenas mostra o que faria, sem gravar/enviar.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        resumo = sincronizar_tarefas(dry_run=dry)
        por_unidade = resumo["por_unidade"]
        corte = timezone.now() - timedelta(days=DEDUP_DIAS)

        # 1) Notificações internas por loja (para os técnicos da unidade).
        notifs = 0
        for uid, dados in por_unidade.items():
            uni, qtd = dados["unidade"], dados["abertas"]
            titulo = f"Tarefas de manutenção — {uni.name}"
            msg = f"{qtd} tarefa(s) de saúde abertas na unidade {uni.name}."
            destin = [
                t for t in tecnicos_da_unidade(uid)
                if not Notificacao.objects.filter(
                    destinatario=t, titulo=titulo, criada_em__gte=corte).exists()
            ]
            if destin:
                if not dry:
                    notificar(destin, titulo, msg, url=URL_PAINEL,
                              icone="task_alt", nivel=Notificacao.Nivel.ALERTA)
                notifs += len(destin)

        # 2) Resumo para a gestão.
        total = sum(d["abertas"] for d in por_unidade.values())
        gestao = list(usuarios_dos_grupos(*GESTAO))
        if por_unidade and gestao:
            tg = "Tarefas de manutenção no parque"
            destin_g = [
                g for g in gestao
                if not Notificacao.objects.filter(
                    destinatario=g, titulo=tg, criada_em__gte=corte).exists()
            ]
            if destin_g:
                if not dry:
                    notificar(destin_g, tg,
                              f"{total} tarefa(s) de saúde abertas em "
                              f"{len(por_unidade)} unidade(s).",
                              url=URL_PAINEL, icone="task_alt",
                              nivel=Notificacao.Nivel.ALERTA)
                notifs += len(destin_g)

        prefixo = "[dry-run] " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefixo}{resumo['criadas']} criada(s) | "
            f"{resumo['reabertas']} reaberta(s) | "
            f"{resumo['resolvidas']} resolvida(s) auto | "
            f"{total} aberta(s) em {len(por_unidade)} unidade(s) | "
            f"{notifs} notificacao(oes)."
        ))
