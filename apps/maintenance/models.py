"""
Manutenção: histórico de reparos/intervenções da equipe de infra em cada ativo,
e garantias/contratos de serviço.

IMPORTANTE: NÃO é um helpdesk. O atendimento ao usuário final já existe em outro
sistema. Aqui registramos apenas o histórico interno da infra (o que foi feito,
por quem, quando, quanto custou) — opcionalmente referenciando o nº do chamado
do helpdesk existente.
"""

from django.conf import settings
from django.db import models


class MaintenanceLog(models.Model):
    """Uma intervenção de manutenção registrada para um ativo."""

    class Type(models.TextChoices):
        REPAIR = "repair", "Reparo"
        UPGRADE = "upgrade", "Upgrade / melhoria"
        PREVENTIVE = "preventive", "Manutenção preventiva"
        CALIBRATION = "calibration", "Calibração / ajuste"
        OTHER = "other", "Outro"

    asset = models.ForeignKey(
        "inventory.Asset",
        verbose_name="ativo",
        on_delete=models.CASCADE,
        related_name="maintenances",
        help_text="Equipamento que recebeu a manutenção.",
    )
    maintenance_type = models.CharField(
        "tipo", max_length=20, choices=Type.choices, default=Type.REPAIR,
        help_text="Natureza da intervenção. Ex.: Reparo, Upgrade, Preventiva.",
    )
    title = models.CharField(
        "título", max_length=160,
        help_text="Resumo curto. Ex.: 'Troca de SSD', 'Limpeza e troca de pasta'.",
    )
    description = models.TextField(
        "descrição", blank=True,
        help_text="Detalhe do que foi feito, peças trocadas, diagnóstico etc.",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="técnico responsável",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenances_done",
        help_text="Colaborador da infra que executou (preenchido automaticamente "
                  "se vazio).",
    )
    supplier = models.ForeignKey(
        "catalog.Supplier",
        verbose_name="fornecedor externo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenances",
        help_text="Assistência/fornecedor externo, se a manutenção foi terceirizada.",
    )
    started_on = models.DateField(
        "iniciada em", null=True, blank=True,
        help_text="Data de início. Ex.: 17/06/2026.",
    )
    completed_on = models.DateField(
        "concluída em", null=True, blank=True,
        help_text="Data de conclusão. Vazio = ainda em andamento.",
    )
    cost = models.DecimalField(
        "custo (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Custo da manutenção, em reais. Ex.: 250,00.",
    )
    warranty_affected = models.BooleanField(
        "afeta a garantia?", default=False,
        help_text="Marque se esta intervenção impacta/invalida a garantia.",
    )
    ticket_ref = models.CharField(
        "nº do chamado (helpdesk)", max_length=60, blank=True,
        help_text="Opcional: nº do chamado no helpdesk existente, para referência.",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "manutenção"
        verbose_name_plural = "manutenções"
        ordering = ["-started_on", "-created_at"]

    def __str__(self):
        return f"{self.get_maintenance_type_display()}: {self.title}"


class Warranty(models.Model):
    """Garantia estendida ou contrato de serviço vinculado a um ativo."""

    class Type(models.TextChoices):
        WARRANTY = "warranty", "Garantia estendida"
        SUPPORT = "support", "Contrato de suporte"
        SERVICE = "service", "Contrato de serviço"

    asset = models.ForeignKey(
        "inventory.Asset",
        verbose_name="ativo",
        on_delete=models.CASCADE,
        related_name="contracts",
        help_text="Equipamento coberto pelo contrato/garantia.",
    )
    contract_type = models.CharField(
        "tipo", max_length=20, choices=Type.choices, default=Type.WARRANTY,
        help_text="Tipo de cobertura. Ex.: Garantia estendida, Contrato de suporte.",
    )
    supplier = models.ForeignKey(
        "catalog.Supplier",
        verbose_name="fornecedor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        help_text="Fornecedor/prestador responsável pela cobertura.",
    )
    contract_no = models.CharField(
        "nº do contrato", max_length=80, blank=True,
        help_text="Número/identificação do contrato. Ex.: CT-2026-014.",
    )
    start_date = models.DateField(
        "início", null=True, blank=True,
        help_text="Data de início da cobertura.",
    )
    end_date = models.DateField(
        "vencimento", null=True, blank=True,
        help_text="Data de fim da cobertura. Usada para alertas de vencimento.",
    )
    cost = models.DecimalField(
        "custo (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Valor do contrato/garantia, em reais.",
    )
    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre sobre a cobertura.",
    )

    class Meta:
        verbose_name = "garantia / contrato"
        verbose_name_plural = "garantias / contratos"
        ordering = ["end_date"]

    def __str__(self):
        return f"{self.get_contract_type_display()} — {self.asset.asset_tag}"
