from django.contrib import admin

from apps.admin_base import MakeModelAdmin as ModelAdmin

from .models import Notificacao


@admin.register(Notificacao)
class NotificacaoAdmin(ModelAdmin):
    list_display = ("titulo", "destinatario", "nivel", "lida", "criada_em")
    list_filter = ("lida", "nivel", "criada_em")
    search_fields = ("titulo", "mensagem", "destinatario__username")
    list_select_related = ("destinatario",)
    readonly_fields = ("criada_em",)
    # O aviso primeiro, a situação depois; os links de ação e a chave de
    # desduplicação são coisa de máquina e ficam por último.
    fieldsets = (
        ("Aviso", {"fields": (("destinatario", "nivel"),
                              ("titulo", "icone"), "mensagem")}),
        ("Situação", {"fields": (("lida", "fixa"),)}),
        ("Links", {
            "description": "Para onde o clique leva e, em aviso de ação, "
                           "os endereços de aprovar e negar.",
            "fields": ("url", ("acao_ok_url", "acao_no_url")),
        }),
        ("Sistema", {"fields": (("chave", "criada_em"),)}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Cada usuário vê só as suas; superusuário vê todas.
        if request.user.is_superuser:
            return qs
        return qs.filter(destinatario=request.user)

    def has_add_permission(self, request):
        return False
