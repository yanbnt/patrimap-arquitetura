"""
Manutenção preventiva — automação (ciclo de 60 dias).

Para cada máquina com preventiva PENDENTE ou VENCIDA:
  1) cria uma TAREFA (Reparo tipo 'preventiva', não concluída) atribuída ao
     técnico/estagiário da loja, se ainda não houver uma tarefa aberta;
  2) gera NOTIFICAÇÃO interna (sino) para os responsáveis da loja e um resumo
     para a gestão;
  3) envia um e-mail-resumo para a gestão (Gerente/Supervisor).

Idempotente: não duplica tarefa (pula se já há preventiva aberta) nem notificação
(janela de DEDUP_DIAS). Pronto para ser agendado (ver "Manutenção Diária ITAM.bat").

Uso:  python manage.py notificar_preventivas
"""

from datetime import timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notificacoes.models import Notificacao, notificar, usuarios_dos_grupos
from apps.parque.models import Baia, Reparo
from apps.parque.tarefas import GESTAO, tecnicos_da_unidade

DEDUP_DIAS = 3  # não reenvia a mesma notificação dentro desse período


class Command(BaseCommand):
    help = "Gera tarefas + notificações + e-mail de manutenção preventiva pendente."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Apenas mostra o que faria, sem criar/enviar nada.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        hoje = timezone.localdate()
        corte = timezone.now() - timedelta(days=DEDUP_DIAS)

        baias = (
            Baia.objects.select_related("setor__unidade", "computador")
            .prefetch_related("reparos")
        )

        por_unidade = {}   # unidade_id -> {"unidade": Location, "baias": [...]}
        tarefas = 0
        for b in baias:
            if b.preventiva_status not in ("pendente", "vencida"):
                continue
            uni = b.setor.unidade
            dados = por_unidade.setdefault(uni.id, {"unidade": uni, "baias": []})
            dados["baias"].append(b)

            # 1) Tarefa automática (só se não houver preventiva aberta).
            if not b.tem_tarefa_preventiva_aberta:
                if not dry:
                    tecs = tecnicos_da_unidade(uni.id)
                    Reparo.objects.create(
                        baia=b, tipo=Reparo.Tipo.PREVENTIVA,
                        titulo="Manutenção preventiva (gerada automaticamente)",
                        descricao=(f"Preventiva pendente há {b.dias_sem_preventiva} dia(s). "
                                   "Realize e marque 'concluído em' para reiniciar o ciclo de 60 dias."),
                        data=hoje, tecnico=(tecs[0] if tecs else None),
                        afeta_desempenho=False,
                    )
                tarefas += 1

        # 2) Notificações internas (responsáveis por loja) + resumo p/ gestão.
        notifs = 0
        for uid, dados in por_unidade.items():
            uni, qtd = dados["unidade"], len(dados["baias"])
            titulo = f"Preventiva pendente — {uni.name}"
            msg = f"{qtd} máquina(s) na unidade {uni.name} precisam de manutenção preventiva."
            destin = [
                t for t in tecnicos_da_unidade(uid)
                if not Notificacao.objects.filter(
                    destinatario=t, titulo=titulo, criada_em__gte=corte).exists()
            ]
            if destin:
                if not dry:
                    notificar(destin, titulo, msg, url="/parque/mapa-preventiva/",
                              icone="build", nivel=Notificacao.Nivel.ALERTA)
                notifs += len(destin)

        gestao = list(usuarios_dos_grupos(*GESTAO))
        total = sum(len(d["baias"]) for d in por_unidade.values())
        if por_unidade and gestao:
            tg = "Preventivas pendentes no parque"
            destin_g = [
                g for g in gestao
                if not Notificacao.objects.filter(
                    destinatario=g, titulo=tg, criada_em__gte=corte).exists()
            ]
            if destin_g:
                if not dry:
                    notificar(destin_g, tg,
                              f"{total} máquina(s) com preventiva pendente/vencida em "
                              f"{len(por_unidade)} unidade(s).",
                              url="/parque/mapa-preventiva/", icone="build",
                              nivel=Notificacao.Nivel.ALERTA)
                notifs += len(destin_g)

        # 3) E-mail-resumo para a gestão.
        enviados = 0
        emails = [g.email for g in gestao if g.email]
        if por_unidade and emails and not dry:
            linhas = [f"- {d['unidade'].name}: {len(d['baias'])} máquina(s)"
                      for d in por_unidade.values()]
            corpo = ("Resumo de manutenção preventiva (ciclo de 60 dias)\n\n"
                     f"Total: {total} máquina(s) com preventiva pendente/vencida.\n\n"
                     + "\n".join(linhas)
                     + "\n\nAbra o sistema em Início → 'Preventivas pendentes'.\n— ITAM Make Distribuidora")
            try:
                send_mail("Patrimap — Manutenção preventiva pendente", corpo, None,
                          emails, fail_silently=False)
                enviados = len(emails)
            except Exception as e:  # SMTP fora do ar não derruba o restante
                self.stdout.write(self.style.WARNING(f"E-mail não enviado: {e}"))

        prefixo = "[dry-run] " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefixo}{total} pendente(s) em {len(por_unidade)} unidade(s) | "
            f"{tarefas} tarefa(s){' a criar' if dry else ' criada(s)'} | "
            f"{notifs} notificacao(oes) | {enviados} e-mail(s)."
        ))
