from django.contrib import admin

from apps.admin_base import MakeModelAdmin as ModelAdmin

from .models import MaintenanceLog, Warranty


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(ModelAdmin):
    list_display = (
        "title",
        "asset",
        "maintenance_type",
        "started_on",
        "completed_on",
        "cost",
        "performed_by",
    )
    list_filter = ("maintenance_type", "warranty_affected", "started_on")
    search_fields = ("title", "description", "asset__asset_tag", "ticket_ref")
    autocomplete_fields = ("asset", "supplier")
    readonly_fields = ("created_at",)
    date_hierarchy = "started_on"
    list_select_related = ("asset", "performed_by")
    # Primeiro o QUE aconteceu, depois QUEM/QUANDO/QUANTO resolveu: é a ordem em
    # que o técnico preenche ao fechar a manutenção.
    fieldsets = (
        ("Identificação", {"fields": (("asset", "maintenance_type"),
                                      ("title", "ticket_ref"), "description")}),
        ("Execução", {"fields": (("started_on", "completed_on"),
                                 ("performed_by", "supplier"),
                                 ("cost", "warranty_affected"))}),
        ("Sistema", {"fields": ("created_at",)}),
    )

    def save_model(self, request, obj, form, change):
        if obj.performed_by_id is None:
            obj.performed_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Warranty)
class WarrantyAdmin(ModelAdmin):
    list_display = (
        "asset",
        "contract_type",
        "supplier",
        "contract_no",
        "start_date",
        "end_date",
        "cost",
    )
    list_filter = ("contract_type", "end_date")
    search_fields = ("asset__asset_tag", "contract_no", "supplier__name")
    autocomplete_fields = ("asset", "supplier")
    date_hierarchy = "end_date"
    list_select_related = ("asset", "supplier")
    fieldsets = (
        ("Identificação", {"fields": (("asset", "contract_type"),
                                      ("supplier", "contract_no"))}),
        ("Vigência e custo", {"fields": (("start_date", "end_date"), "cost")}),
        ("Observações", {"fields": ("notes",)}),
    )
