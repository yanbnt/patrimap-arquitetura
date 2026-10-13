"""
Orçamentos — pedidos de compra/serviço que passam por aprovação.

A fonte dos dados será o **Bitrix24** (futuramente): cada tarefa do Bitrix que
contém as informações de um orçamento vira um registro aqui, sincronizado por um
job. Por enquanto o modelo já existe para uso manual e para receber o sync.

Estados de interesse (pedido do usuário): **Pendente de aprovação** e **Aprovado**.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Orcamento(models.Model):
    """Um orçamento (vindo de uma tarefa do Bitrix) sujeito a aprovação."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente de aprovação"
        APROVADO = "aprovado", "Aprovado"
        NEGADO = "negado", "Negado"

    # --- Origem no Bitrix (preenchido pelo sync futuro) ---
    bitrix_task_id = models.CharField(
        "ID da tarefa (Bitrix)", max_length=40, blank=True, db_index=True,
        help_text="Identificador da tarefa no Bitrix24 que originou o orçamento. "
                  "Preenchido automaticamente pela sincronização.",
    )
    link_bitrix = models.URLField(
        "link da tarefa (Bitrix)", blank=True,
        help_text="URL direta da tarefa no Bitrix24.",
    )

    # --- Conteúdo do orçamento ---
    titulo = models.CharField(
        "título", max_length=200,
        help_text="Resumo do orçamento. Ex.: 'Compra de 5 monitores', "
                  "'Troca de servidor da loja Centro'.",
    )
    descricao = models.TextField(
        "descrição", blank=True,
        help_text="Detalhes do orçamento: itens, justificativa, condições.",
    )
    valor = models.DecimalField(
        "valor (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Valor total do orçamento, em reais. Ex.: 4500,00.",
    )
    fornecedor = models.CharField(
        "fornecedor", max_length=160, blank=True,
        help_text="Fornecedor/loja do orçamento. Ex.: Kabum, Dell.",
    )
    solicitante = models.CharField(
        "solicitante", max_length=160, blank=True,
        help_text="Quem pediu o orçamento (vem da tarefa do Bitrix).",
    )

    # --- Aprovação ---
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
        help_text="Pendente de aprovação, Aprovado ou Negado.",
    )
    motivo = models.CharField(
        "motivo (negação)", max_length=200, blank=True,
        help_text="Motivo informado ao negar o orçamento.",
    )
    data_solicitacao = models.DateField(
        "data da solicitação", null=True, blank=True,
        help_text="Quando o orçamento foi solicitado/criado.",
    )
    data_aprovacao = models.DateField(
        "data da aprovação", null=True, blank=True,
        help_text="Preenchida quando o orçamento é aprovado.",
    )
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="aprovado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orcamentos_aprovados",
        help_text="Usuário que aprovou (preenchido automaticamente na aprovação).",
    )

    # --- Carga bruta do Bitrix (para depuração/auditoria do sync) ---
    dados_bitrix = models.JSONField(
        "dados do Bitrix (bruto)", default=dict, blank=True,
        help_text="Payload original da tarefa do Bitrix, para referência.",
    )

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        ordering = ["status", "-data_solicitacao", "-criado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["bitrix_task_id"],
                condition=models.Q(bitrix_task_id__gt=""),
                name="unique_bitrix_task_id_quando_preenchido",
            )
        ]

    def __str__(self):
        return self.titulo

    @property
    def aprovado(self):
        return self.status == self.Status.APROVADO

    def aprovar(self, user):
        self.status = self.Status.APROVADO
        self.data_aprovacao = timezone.localdate()
        self.aprovado_por = user
        self.save()

    def negar(self, user, motivo=""):
        self.status = self.Status.NEGADO
        self.data_aprovacao = timezone.localdate()
        self.aprovado_por = user
        self.motivo = (motivo or "")[:200]
        self.save()
