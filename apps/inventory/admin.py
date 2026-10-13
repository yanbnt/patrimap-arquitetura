from django.contrib import admin
from unfold.admin import TabularInline

from apps.admin_base import MakeModelAdmin as ModelAdmin
from apps.maintenance.models import MaintenanceLog, Warranty

from .models import Asset, Assignment


class AssignmentInline(TabularInline):
    """Histórico de check-in/out exibido na página do ativo (e criação rápida)."""

    model = Assignment
    extra = 0
    fields = ("action", "person", "at", "expected_return", "note", "by_user")
    readonly_fields = ("by_user",)
    autocomplete_fields = ("person",)
    ordering = ("-at",)


class MaintenanceInline(TabularInline):
    """Histórico de manutenções na página do ativo."""

    model = MaintenanceLog
    extra = 0
    fields = ("maintenance_type", "title", "started_on", "completed_on", "cost",
              "performed_by")
    readonly_fields = ("performed_by",)
    ordering = ("-started_on",)


class WarrantyInline(TabularInline):
    """Garantias estendidas / contratos na página do ativo."""

    model = Warranty
    extra = 0
    fields = ("contract_type", "supplier", "contract_no", "start_date", "end_date",
              "cost")
    autocomplete_fields = ("supplier",)
    ordering = ("end_date",)


@admin.register(Asset)
class AssetAdmin(ModelAdmin):
    list_display = (
        "asset_tag",
        "name",
        "model",
        "status",
        "assigned_to",
        "location",
        "warranty_expires",
    )
    list_filter = ("status", "model__category", "model__manufacturer", "location")
    search_fields = (
        "asset_tag",
        "serial",
        "name",
        "assigned_to__full_name",
        "model__name",
    )
    autocomplete_fields = ("model", "status", "location", "assigned_to", "supplier")
    readonly_fields = ("warranty_expires", "created_at", "updated_at")
    date_hierarchy = "purchase_date"
    list_select_related = ("model", "status", "assigned_to", "location")
    inlines = (AssignmentInline, MaintenanceInline, WarrantyInline)

    # Identificação → alocação → compra → specs → situação → observações, e o
    # que o sistema preenche no fim. `status` saiu da Identificação para a
    # Situação: é o que muda com o tempo, junto com a baixa (archived_at).
    fieldsets = (
        ("Identificação", {
            "fields": (("asset_tag", "serial"), ("name", "model")),
        }),
        ("Alocação", {
            "fields": (("assigned_to", "location"),),
        }),
        ("Compra e garantia", {
            "description": "O fim da garantia é calculado pela data de compra "
                           "mais os meses informados.",
            "fields": (("supplier", "order_number"),
                       ("purchase_date", "purchase_cost"),
                       ("warranty_months", "warranty_expires")),
        }),
        ("Especificações", {
            "description": "Campos livres em JSON, para o que a categoria do "
                           "ativo pede e o cadastro não tem.",
            "fields": ("custom",),
        }),
        ("Situação", {
            "fields": (("status", "archived_at"),),
        }),
        ("Observações", {
            "fields": ("notes",),
        }),
        ("Sistema", {
            "fields": (("created_at", "updated_at"),),
        }),
    )

    @admin.display(description="fim da garantia")
    def warranty_expires(self, obj):
        return obj.warranty_expires

    def save_formset(self, request, form, formset, change):
        """Preenche o usuário responsável nos eventos criados pelos inlines."""
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, Assignment) and obj.by_user_id is None:
                obj.by_user = request.user
            elif isinstance(obj, MaintenanceLog) and obj.performed_by_id is None:
                obj.performed_by = request.user
            obj.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()


@admin.register(Assignment)
class AssignmentAdmin(ModelAdmin):
    list_display = ("asset", "action", "person", "at", "expected_return", "by_user")
    list_filter = ("action", "at")
    search_fields = ("asset__asset_tag", "asset__name", "person__full_name")
    autocomplete_fields = ("asset", "person")
    readonly_fields = ("by_user", "created_at")
    date_hierarchy = "at"
    list_select_related = ("asset", "person", "by_user")
    fieldsets = (
        ("Movimentação", {
            "description": "Entrega (check-out) tira o ativo do estoque; "
                           "devolução (check-in) o devolve.",
            "fields": (("asset", "action"), ("person", "at"), "expected_return"),
        }),
        ("Observações", {"fields": ("note",)}),
        ("Sistema", {"fields": (("by_user", "created_at"),)}),
    )

    def save_model(self, request, obj, form, change):
        """Preenche 'registrado por' com o usuário atual."""
        if obj.by_user_id is None:
            obj.by_user = request.user
        super().save_model(request, obj, form, change)
