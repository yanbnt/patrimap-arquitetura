from django.contrib import admin

from apps.admin_base import MakeModelAdmin as ModelAdmin

from .models import AssetModel, Category, Manufacturer, Status, Supplier

# Todo cadastro do catálogo usa os MESMOS grupos, na ordem em que a pessoa
# preenche (Identificação → Endereço → Contato → Observações), com os campos
# curtos em par na mesma linha. É o formato aprovado em orgs/LocationAdmin.


@admin.register(Manufacturer)
class ManufacturerAdmin(ModelAdmin):
    list_display = ("name", "support_phone", "support_url")
    search_fields = ("name",)
    fieldsets = (
        ("Identificação", {"fields": ("name",)}),
        ("Contato do suporte", {"fields": (("support_phone", "support_url"),)}),
        ("Observações", {"fields": ("notes",)}),
    )


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("name", "category_type")
    list_filter = ("category_type",)
    search_fields = ("name",)
    fieldsets = (
        ("Identificação", {"fields": (("name", "category_type"),)}),
        ("Observações", {"fields": ("notes",)}),
    )


@admin.register(Supplier)
class SupplierAdmin(ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email")
    search_fields = ("name", "contact_name", "email")
    fieldsets = (
        ("Identificação", {"fields": (("name", "contact_name"),)}),
        ("Endereço", {"fields": ("address",)}),
        ("Contato", {"fields": (("phone", "email"),)}),
        ("Observações", {"fields": ("notes",)}),
    )


@admin.register(AssetModel)
class AssetModelAdmin(ModelAdmin):
    list_display = (
        "name",
        "manufacturer",
        "category",
        "model_number",
        "default_warranty_months",
        "eol_months",
    )
    list_filter = ("category", "manufacturer")
    search_fields = ("name", "model_number", "manufacturer__name")
    autocomplete_fields = ("manufacturer", "category")
    # Garantia e vida útil ficam em grupo próprio porque são HERDADAS por cada
    # ativo deste modelo — não descrevem o modelo, definem o padrão dos ativos.
    fieldsets = (
        ("Identificação", {"fields": (("name", "model_number"),
                                      ("manufacturer", "category"))}),
        ("Padrões herdados pelos ativos", {
            "fields": (("default_warranty_months", "eol_months"),),
        }),
        ("Observações", {"fields": ("notes",)}),
    )


@admin.register(Status)
class StatusAdmin(ModelAdmin):
    list_display = ("name", "status_type", "color")
    list_filter = ("status_type",)
    search_fields = ("name",)
    fieldsets = (
        ("Identificação", {"fields": (("name", "status_type"), "color")}),
    )
