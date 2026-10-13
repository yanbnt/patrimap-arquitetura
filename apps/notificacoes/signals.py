"""Eventos que geram notificações.

- Novo Reparo/chamado → avisa Gerentes, Supervisores e o técnico responsável.
- Atribuição/devolução (Assignment) → avisa Gerentes e Supervisores.

Garantia vencendo é gerada pelo comando `notificar_garantias` (agendável na
Fase 6), não por signal.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from apps.inventory.models import Assignment
from apps.orcamentos.models import Orcamento
from apps.parque.models import AdiamentoPreventiva, Reparo, Transferencia

from .models import Notificacao, notificar, usuarios_dos_grupos

GESTAO = ["Gerente", "Supervisor"]
# Quem pode decidir uma transferência (mesmos grupos do "pode_mover_baia").
APROVADORES = ["Gerente", "Supervisor", "Técnico de Pós Venda"]


@receiver(post_save, sender=Reparo)
def _notificar_reparo(sender, instance, created, **kwargs):
    if not created:
        return
    baia = instance.baia
    url = reverse("admin:parque_reparo_change", args=[instance.pk])
    titulo = f"{instance.get_tipo_display()}: {baia}"
    msg = (instance.titulo or "").strip()

    # Gestão é avisada de todo chamado novo.
    notificar(
        usuarios_dos_grupos(*GESTAO), titulo, msg, url=url,
        icone="construction", nivel=Notificacao.Nivel.ALERTA,
    )
    # O técnico designado também (sem duplicar se ele for da gestão).
    if instance.tecnico_id and not instance.tecnico.groups.filter(name__in=GESTAO).exists():
        notificar(
            instance.tecnico, f"Você foi designado: {titulo}", msg, url=url,
            icone="engineering", nivel=Notificacao.Nivel.ALERTA,
        )


@receiver(post_save, sender=Assignment)
def _notificar_assignment(sender, instance, created, **kwargs):
    if not created:
        return
    url = reverse("admin:inventory_assignment_change", args=[instance.pk])
    acao = instance.get_action_display()
    pessoa = instance.person or "—"
    titulo = f"{acao}: {instance.asset.asset_tag}"
    msg = f"{pessoa}"
    notificar(
        usuarios_dos_grupos(*GESTAO), titulo, msg, url=url,
        icone="swap_horiz", nivel=Notificacao.Nivel.INFO,
        excluir=instance.by_user,
    )


@receiver(post_save, sender=Transferencia)
def _notificar_transferencia_pendente(sender, instance, **kwargs):
    """Transferência pendente → notificação FIXA de aprovar/negar para os aprovadores.
    Quando é decidida (autorizada/negada), a notificação some sozinha."""
    chave = f"transf:{instance.pk}"
    existentes = Notificacao.objects.filter(chave=chave)
    if instance.status == Transferencia.Status.PENDENTE:
        if existentes.exists():
            return  # já notificado (evita duplicar a cada save)
        origem = instance.baia_origem or "?"
        destino = instance.baia_destino or "?"
        msg = (f"Solicitada por {instance.registrado_por}"
               if instance.registrado_por_id else "")
        notificar(
            usuarios_dos_grupos(*APROVADORES),
            titulo=f"Aprovar transferência: {origem} → {destino}",
            mensagem=msg, icone="swap_horiz", nivel=Notificacao.Nivel.ALERTA,
            excluir=instance.registrado_por,
            fixa=True, chave=chave,
            acao_ok_url=reverse("parque_decidir_transferencia", args=[instance.pk, "autorizar"]),
            acao_no_url=reverse("parque_decidir_transferencia", args=[instance.pk, "negar"]),
        )
    else:
        existentes.delete()  # decidida → resolve a notificação fixa


@receiver(post_save, sender=AdiamentoPreventiva)
def _notificar_adiamento_pendente(sender, instance, **kwargs):
    """Pedido de adiamento pendente → notificação FIXA de aprovar/negar para a
    gestão (Supervisor/Gerente). Ao decidir, some sozinha."""
    chave = f"adiar:{instance.pk}"
    existentes = Notificacao.objects.filter(chave=chave)
    if instance.status == AdiamentoPreventiva.Status.PENDENTE:
        if existentes.exists():
            return
        quem = f"Solicitado por {instance.solicitante}" if instance.solicitante_id else ""
        msg = (f"{quem} · nova data {instance.nova_data:%d/%m/%Y} · "
               f"{instance.justificativa[:120]}")
        notificar(
            usuarios_dos_grupos(*GESTAO),
            titulo=f"Aprovar adiamento: {instance.patrimonio or instance.local}",
            mensagem=msg, icone="event_busy", nivel=Notificacao.Nivel.ALERTA,
            excluir=instance.solicitante,
            fixa=True, chave=chave,
            acao_ok_url=reverse("parque_decidir_adiamento", args=[instance.pk, "aprovar"]),
            acao_no_url=reverse("parque_decidir_adiamento", args=[instance.pk, "negar"]),
        )
    else:
        existentes.delete()  # decidido → resolve a notificação fixa


@receiver(post_save, sender=Orcamento)
def _notificar_orcamento_pendente(sender, instance, **kwargs):
    """Orçamento pendente → notificação FIXA de aprovar/negar para a gestão."""
    chave = f"orc:{instance.pk}"
    existentes = Notificacao.objects.filter(chave=chave)
    if instance.status == Orcamento.Status.PENDENTE:
        if existentes.exists():
            return
        val = f" · R$ {instance.valor}" if instance.valor is not None else ""
        notificar(
            usuarios_dos_grupos(*GESTAO),
            titulo=f"Aprovar orçamento: {instance.titulo}",
            mensagem=f"{instance.solicitante or ''}{val}".strip(" ·"),
            icone="request_quote", nivel=Notificacao.Nivel.ALERTA,
            fixa=True, chave=chave,
            acao_ok_url=reverse("orcamentos_decidir", args=[instance.pk, "aprovar"]),
            acao_no_url=reverse("orcamentos_decidir", args=[instance.pk, "negar"]),
        )
    else:
        existentes.delete()  # decidido → resolve a notificação fixa
