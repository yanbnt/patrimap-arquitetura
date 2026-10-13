"""
Inventário: o ativo em si — o núcleo do sistema.

Cada Asset é uma instância física de um catalog.AssetModel. Campos estáveis e
consultados (patrimônio, série, compra, garantia, status) são colunas reais;
specs específicas por categoria ficam no JSON `custom` (validado na Fase 4).
"""

from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone


def _add_months(start: date, months: int) -> date:
    """Soma `months` meses a uma data, sem dependências externas."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    # Ajusta o dia para o último dia válido do mês destino.
    day = min(start.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


class Asset(models.Model):
    """Equipamento físico rastreável."""

    asset_tag = models.CharField(
        "patrimônio", max_length=60, unique=True,
        help_text="Código único de patrimônio/etiqueta. Ex.: MAKE-0001. "
                  "Não pode repetir.",
    )
    serial = models.CharField(
        "número de série", max_length=120, blank=True,
        help_text="Número de série do fabricante (serial/IMEI). Ex.: 5CG1234XYZ.",
    )
    name = models.CharField(
        "nome / apelido", max_length=160, blank=True,
        help_text="Opcional: nome de host ou apelido. Ex.: NB-MARIA, PC-RECEPCAO.",
    )

    model = models.ForeignKey(
        "catalog.AssetModel",
        verbose_name="modelo",
        on_delete=models.PROTECT,
        related_name="assets",
        help_text="Modelo do equipamento. Selecione um modelo cadastrado "
                  "(fabricante + categoria vêm dele).",
    )
    status = models.ForeignKey(
        "catalog.Status",
        verbose_name="status",
        on_delete=models.PROTECT,
        related_name="assets",
        help_text="Situação atual do ativo. Ex.: Em uso, Em estoque, Defeito.",
    )

    # --- Onde está e com quem (Fase 1: ponteiro denormalizado do detentor atual;
    #     o histórico de check-in/out chega na Fase 2) ---
    location = models.ForeignKey(
        "orgs.Location",
        verbose_name="local atual",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
        help_text="Onde o ativo está fisicamente agora. Ex.: Matriz › Sala da TI.",
    )
    assigned_to = models.ForeignKey(
        "orgs.Person",
        verbose_name="atribuído a",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
        help_text="Colaborador que está com o equipamento agora. "
                  "Vazio = em estoque / sem responsável.",
    )

    # --- Compra e garantia ---
    supplier = models.ForeignKey(
        "catalog.Supplier",
        verbose_name="fornecedor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
        help_text="De quem o ativo foi comprado. Selecione um fornecedor cadastrado.",
    )
    purchase_date = models.DateField(
        "data de compra", null=True, blank=True,
        help_text="Data da nota fiscal de compra. Ex.: 15/01/2025. "
                  "Usada para calcular o fim da garantia.",
    )
    purchase_cost = models.DecimalField(
        "valor de compra (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Valor pago no ativo, em reais. Ex.: 4500,00.",
    )
    order_number = models.CharField(
        "nº do pedido / NF", max_length=80, blank=True,
        help_text="Número do pedido de compra ou da nota fiscal. Ex.: NF 12345.",
    )
    warranty_months = models.PositiveIntegerField(
        "garantia (meses)", null=True, blank=True,
        help_text="Garantia deste ativo em meses. Ex.: 36. "
                  "Vazio = usa a garantia padrão do modelo.",
    )

    # --- Specs específicas por categoria (CPU/RAM, placa de veículo etc.) ---
    custom = models.JSONField(
        "campos customizados", default=dict, blank=True,
        help_text='Specs específicas em formato JSON. '
                  'Ex.: {"cpu": "i5", "ram": "16GB", "disco": "512GB SSD"}. '
                  "(Formulário dedicado por categoria virá na Fase 4.)",
    )

    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre para anotações sobre este ativo.",
    )

    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)
    archived_at = models.DateTimeField(
        "baixado em", null=True, blank=True,
        help_text="Data/hora em que o ativo foi baixado/descartado. "
                  "Preencha ao dar baixa definitiva.",
    )

    class Meta:
        verbose_name = "ativo"
        verbose_name_plural = "ativos"
        ordering = ["asset_tag"]

    def __str__(self):
        label = self.name or str(self.model)
        return f"{self.asset_tag} — {label}"

    @property
    def effective_warranty_months(self):
        """Garantia efetiva: a do ativo, ou a padrão do modelo."""
        if self.warranty_months:
            return self.warranty_months
        return self.model.default_warranty_months if self.model_id else None

    @property
    def warranty_expires(self):
        """Data de fim de garantia derivada da compra + meses de garantia."""
        months = self.effective_warranty_months
        if self.purchase_date and months:
            return _add_months(self.purchase_date, months)
        return None


class Assignment(models.Model):
    """
    Histórico de entrega (check-out) e devolução (check-in) de um ativo.

    Cada registro é um evento. Ao salvar, sincroniza o detentor atual do ativo
    (Asset.assigned_to) — ou seja, "quem está com o quê" sai sempre do último
    evento. Mantém a auditoria completa de quem ficou com cada equipamento.
    """

    class Action(models.TextChoices):
        CHECKOUT = "checkout", "Entrega (check-out)"
        CHECKIN = "checkin", "Devolução (check-in)"

    asset = models.ForeignKey(
        Asset,
        verbose_name="ativo",
        on_delete=models.CASCADE,
        related_name="assignments",
        help_text="Equipamento que está sendo entregue ou devolvido.",
    )
    action = models.CharField(
        "ação", max_length=10, choices=Action.choices, default=Action.CHECKOUT,
        help_text="Entrega = passa o ativo para um colaborador; "
                  "Devolução = colaborador devolve o ativo ao estoque.",
    )
    person = models.ForeignKey(
        "orgs.Person",
        verbose_name="colaborador",
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
        help_text="Quem recebe (na entrega) ou devolve (na devolução) o ativo.",
    )
    by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments_made",
        help_text="Usuário do sistema que registrou este evento (preenchido "
                  "automaticamente).",
    )
    at = models.DateTimeField(
        "data/hora", default=timezone.now,
        help_text="Quando o evento aconteceu. Ex.: 17/06/2026 14:30.",
    )
    expected_return = models.DateField(
        "devolução prevista", null=True, blank=True,
        help_text="Apenas para entrega: data prevista de devolução (se houver).",
    )
    note = models.TextField(
        "observação", blank=True,
        help_text="Texto livre. Ex.: 'Entregue com carregador e mochila'.",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "atribuição (check-in/out)"
        verbose_name_plural = "atribuições (check-in/out)"
        ordering = ["-at"]

    def __str__(self):
        return f"{self.get_action_display()} — {self.asset.asset_tag}"

    def save(self, *args, **kwargs):
        """Sincroniza o detentor atual do ativo conforme o evento."""
        super().save(*args, **kwargs)
        asset = self.asset
        if self.action == self.Action.CHECKOUT:
            asset.assigned_to = self.person
        else:  # CHECKIN
            asset.assigned_to = None
        asset.save(update_fields=["assigned_to", "updated_at"])
