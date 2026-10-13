"""
Catálogo: entidades de referência que classificam e descrevem os ativos.

Fabricante → Modelo → (instância em inventory.Asset). Categoria define o TIPO
de ativo (equipamento de TI hoje; móveis/veículos no futuro) e é o que torna o
sistema extensível sem mexer no schema.
"""

from django.db import models


class Manufacturer(models.Model):
    """Fabricante do equipamento (Dell, HP, Lenovo, Apple...)."""

    name = models.CharField(
        "nome", max_length=120, unique=True,
        help_text="Nome do fabricante. Ex.: Dell, HP, Lenovo, Intelbras.",
    )
    support_url = models.URLField(
        "site de suporte", blank=True,
        help_text="Endereço do suporte do fabricante. Ex.: https://suporte.dell.com",
    )
    support_phone = models.CharField(
        "telefone de suporte", max_length=40, blank=True,
        help_text="Telefone do suporte técnico. Ex.: 0800 970 3355",
    )
    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre para anotações sobre o fabricante.",
    )

    class Meta:
        verbose_name = "fabricante"
        verbose_name_plural = "fabricantes"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    """
    Categoria do ativo. O `category_type` controla o comportamento e permite
    incorporar ativos gerais no futuro sem novas tabelas.
    """

    class Type(models.TextChoices):
        IT_EQUIPMENT = "it_equipment", "Equipamento de TI"
        PERIPHERAL = "peripheral", "Periférico"
        FURNITURE = "furniture", "Mobiliário"
        VEHICLE = "vehicle", "Veículo"
        TOOL = "tool", "Ferramenta"
        PPE = "ppe", "EPI"
        OTHER = "other", "Outro"

    name = models.CharField(
        "nome", max_length=120, unique=True,
        help_text="Nome da categoria. Ex.: Notebook, Monitor, Celular, Impressora.",
    )
    category_type = models.CharField(
        "tipo", max_length=20, choices=Type.choices, default=Type.IT_EQUIPMENT,
        help_text="Grupo geral do ativo. Define o comportamento; comece com "
                  "'Equipamento de TI'. (Móveis/veículos serão usados no futuro.)",
    )
    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre para anotações sobre a categoria.",
    )

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    """Fornecedor de compra ou de serviço (loja, distribuidor, assistência)."""

    name = models.CharField(
        "nome", max_length=160, unique=True,
        help_text="Razão social ou nome do fornecedor. Ex.: Kabum, Dell Brasil.",
    )
    contact_name = models.CharField(
        "contato", max_length=120, blank=True,
        help_text="Nome da pessoa de contato no fornecedor. Ex.: João (vendas).",
    )
    phone = models.CharField(
        "telefone", max_length=40, blank=True,
        help_text="Telefone do fornecedor. Ex.: (45) 3220-0000",
    )
    email = models.EmailField(
        "e-mail", blank=True,
        help_text="E-mail de contato. Ex.: vendas@fornecedor.com.br",
    )
    address = models.CharField(
        "endereço", max_length=255, blank=True,
        help_text="Endereço do fornecedor (rua, número, cidade).",
    )
    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre para anotações sobre o fornecedor.",
    )

    class Meta:
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AssetModel(models.Model):
    """
    Modelo de equipamento (ex.: "Latitude 5440"). Carrega specs e padrões
    herdados pelas instâncias: garantia padrão e vida útil (EOL).
    """

    name = models.CharField(
        "nome", max_length=160,
        help_text="Nome/linha do modelo. Ex.: Latitude 5440, EliteBook 840.",
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        verbose_name="fabricante",
        on_delete=models.PROTECT,
        related_name="models",
        help_text="Quem fabrica este modelo. Selecione um fabricante cadastrado.",
    )
    category = models.ForeignKey(
        Category,
        verbose_name="categoria",
        on_delete=models.PROTECT,
        related_name="models",
        help_text="A que categoria este modelo pertence. Ex.: Notebook.",
    )
    model_number = models.CharField(
        "código do modelo", max_length=120, blank=True,
        help_text="Código/SKU do fabricante. Ex.: P163G, 5440-i5.",
    )
    default_warranty_months = models.PositiveIntegerField(
        "garantia padrão (meses)", null=True, blank=True,
        help_text="Meses de garantia de fábrica. Ex.: 12, 36. "
                  "Os ativos deste modelo herdam este valor.",
    )
    eol_months = models.PositiveIntegerField(
        "vida útil / EOL (meses)", null=True, blank=True,
        help_text="Meses estimados de vida útil a partir da compra. Ex.: 60 (5 anos).",
    )
    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre (specs gerais, observações do modelo).",
    )

    class Meta:
        verbose_name = "modelo"
        verbose_name_plural = "modelos"
        ordering = ["manufacturer__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["manufacturer", "name"], name="unique_model_per_manufacturer"
            )
        ]

    def __str__(self):
        return f"{self.manufacturer} {self.name}"


class Status(models.Model):
    """
    Estado do ativo (ex.: "Em uso", "Em estoque", "Defeito", "Baixado").
    O `status_type` agrupa o comportamento independente do nome dado.
    """

    class Type(models.TextChoices):
        DEPLOYABLE = "deployable", "Disponível para uso"
        DEPLOYED = "deployed", "Em uso"
        PENDING = "pending", "Pendente / manutenção"
        BROKEN = "broken", "Defeito"
        LOST = "lost", "Perdido / roubado"
        ARCHIVED = "archived", "Baixado / descartado"

    name = models.CharField(
        "nome", max_length=80, unique=True,
        help_text="Nome exibido do status. Ex.: Em uso, Em estoque, Defeito.",
    )
    status_type = models.CharField(
        "tipo", max_length=20, choices=Type.choices, default=Type.DEPLOYABLE,
        help_text="Comportamento do status, independente do nome. "
                  "Ex.: 'Disponível para uso' libera o ativo para atribuição.",
    )
    color = models.CharField(
        "cor (hex)", max_length=7, blank=True,
        help_text="Cor em hexadecimal para etiquetas e dashboard. Ex.: #16a34a",
    )

    class Meta:
        verbose_name = "status"
        verbose_name_plural = "status"
        ordering = ["name"]

    def __str__(self):
        return self.name
