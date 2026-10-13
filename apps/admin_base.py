"""Base compartilhada dos admins do ITAM.

`MakeModelAdmin` estende o ModelAdmin do unfold e:
- injeta o `help_text` de cada campo como atributo `title` no widget (dica no
  hover, além do texto visível padrão do unfold);
- adiciona a ação em lote "Alterar selecionado" no dropdown de ações (o Django
  já traz "Excluir/Remover selecionados"). Ambas respeitam a permissão do papel.
"""

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from unfold.admin import ModelAdmin


class HelpTooltipMixin:
    """Copia o help_text do campo para o atributo title (dica no hover)."""

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for field in form.base_fields.values():
            if field.help_text:
                field.widget.attrs.setdefault("title", str(field.help_text))
        return form


class SemExcluirRelacionadoMixin:
    """Tira a ação EXCLUIR do botão ao lado de um campo de seleção.

    O Django embrulha todo ForeignKey do formulário num `RelatedFieldWidgetWrapper`
    com três atalhos: adicionar, alterar e EXCLUIR o registro apontado. O ícone de
    excluir não desvincula — ele APAGA o registro do sistema.

    Isso já custou caro: alguém abriu um notebook e usou o atalho ao lado de
    "Colaborador" achando que estava tirando a pessoa DAQUELE notebook. O cadastro
    da pessoa sumiu do sistema. Só voltou porque o sinal
    `garantir_colaborador_do_usuario` recria o Person quando o usuário loga — para
    quem NÃO tem conta de acesso, teria sumido de vez e em silêncio.

    Na baia o estrago seria maior: `computador` e `notebook` têm o mesmo atalho, e
    ali ele apagaria a máquina inteira, com histórico de reparos e transferências.

    Desvincular continua possível — é limpar a seleção e salvar. O que sai é só o
    atalho que destrói.

    Excluir de verdade continua existindo onde faz sentido: na tela do próprio
    registro, que tem confirmação e mostra o que será levado junto.
    """

    # Tem de ser `formfield_for_dbfield`, NÃO `formfield_for_foreignkey`.
    #
    # O Django monta o `RelatedFieldWidgetWrapper` em `formfield_for_dbfield`,
    # DEPOIS que `formfield_for_foreignkey` devolve o campo. Mexer lá atinge o
    # widget de dentro, que nem tem `can_delete_related` — o `hasattr` dá falso
    # e a proteção não acontece, sem erro nenhum para denunciar.
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        campo = super().formfield_for_dbfield(db_field, request, **kwargs)
        widget = getattr(campo, "widget", None)
        if widget is not None and hasattr(widget, "can_delete_related"):
            widget.can_delete_related = False
        return campo


class MakeModelAdmin(HelpTooltipMixin, SemExcluirRelacionadoMixin, ModelAdmin):
    """ModelAdmin padrão do projeto: visual unfold + dicas + ações em lote."""

    # Formulário SEM o modo comprimido do unfold.
    #
    # Com `compressed_fields = True` (o default dele), a tag
    # `fieldset_line_classes` acrescenta `border-b border-base-200
    # border-dashed min-h-[59px]` em cada linha e trava o rótulo numa coluna
    # fixa de 224px. Era daí que vinham os "separadores pontilhados estranhos"
    # e o espaço morto que o dono apontou na tela de adicionar loja/setor —
    # desligar aqui resolve nos 20+ admins de uma vez, em vez de caçar o
    # pontilhado com CSS.
    compressed_fields = False

    actions = ["alterar_selecionado"]

    def get_actions(self, request):
        """Adiciona ícone/rótulo à ação de exclusão padrão do Django."""
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            func, name, _desc = actions["delete_selected"]
            actions["delete_selected"] = (func, name, "Excluir selecionados")
        return actions

    @admin.action(description="Alterar selecionado", permissions=["change"])
    def alterar_selecionado(self, request, queryset):
        """Abre a tela de edição do item selecionado (selecione exatamente 1)."""
        if queryset.count() != 1:
            self.message_user(
                request,
                "Para alterar, selecione exatamente 1 registro.",
                level=messages.WARNING,
            )
            return None
        obj = queryset.first()
        info = (self.model._meta.app_label, self.model._meta.model_name)
        return HttpResponseRedirect(
            reverse("admin:%s_%s_change" % info, args=[obj.pk])
        )
