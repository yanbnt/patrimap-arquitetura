from django.contrib import admin
from django.utils import timezone
from unfold.decorators import display

from apps.admin_base import MakeModelAdmin as ModelAdmin

from .models import Orcamento


@admin.register(Orcamento)
class OrcamentoAdmin(ModelAdmin):
    list_display = (
        "titulo",
        "status_badge",
        "valor",
        "fornecedor",
        "solicitante",
        "data_solicitacao",
        "data_aprovacao",
    )
    list_filter = ("status", "data_solicitacao", "data_aprovacao")
    search_fields = ("titulo", "descricao", "fornecedor", "solicitante", "bitrix_task_id")
    date_hierarchy = "data_solicitacao"
    list_select_related = ("aprovado_por",)
    actions = ("aprovar_orcamentos",)
    readonly_fields = ("bitrix_task_id", "dados_bitrix", "criado_em", "atualizado_em")

    # O que se pede primeiro, quem decide depois. O que vem do Bitrix é
    # preenchido pela integração e fica no fim, sempre visível (o dono não
    # quer caixa dentro de caixa).
    fieldsets = (
        ("Orçamento", {
            "fields": (("titulo", "valor"), ("fornecedor", "solicitante"),
                       "descricao"),
        }),
        ("Aprovação", {
            "fields": (("status", "aprovado_por"),
                       ("data_solicitacao", "data_aprovacao")),
        }),
        ("Sistema", {
            "description": "Vem da integração com o Bitrix24.",
            "fields": (("bitrix_task_id", "link_bitrix"),
                       ("criado_em", "atualizado_em"), "dados_bitrix"),
        }),
    )

    @display(
        description="situação",
        label={
            "Pendente de aprovação": "warning",
            "Aprovado": "success",
            "Negado": "danger",
        },
    )
    def status_badge(self, obj):
        return obj.get_status_display()

    @admin.action(description="Aprovar orçamento(s) selecionado(s)")
    def aprovar_orcamentos(self, request, queryset):
        atualizados = 0
        for orc in queryset.exclude(status=Orcamento.Status.APROVADO):
            orc.status = Orcamento.Status.APROVADO
            if not orc.data_aprovacao:
                orc.data_aprovacao = timezone.localdate()
            if orc.aprovado_por_id is None:
                orc.aprovado_por = request.user
            orc.save()
            atualizados += 1
        self.message_user(request, f"{atualizados} orçamento(s) aprovado(s).")

    def save_model(self, request, obj, form, change):
        """Ao marcar como Aprovado, preenche quem aprovou e a data, se vazios."""
        if obj.status == Orcamento.Status.APROVADO:
            if not obj.data_aprovacao:
                obj.data_aprovacao = timezone.localdate()
            if obj.aprovado_por_id is None:
                obj.aprovado_por = request.user
        super().save_model(request, obj, form, change)
