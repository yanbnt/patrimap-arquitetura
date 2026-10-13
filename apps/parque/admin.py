from django.contrib import admin, messages
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import TabularInline
from unfold.decorators import action, display

from apps.admin_base import MakeModelAdmin as ModelAdmin

from .forms import BaiaForm, ComputadorForm, ReparoForm
from .models import (
    AdiamentoPreventiva, Autorizada, Baia, ComentarioEvento, Computador,
    DocumentoEquipamento, EnvioAutorizada,
    GrupoManutencao, MarcaEvento, MovimentacaoBaia,
    MovimentacaoPeca, Notebook, Peca, RegistroEnvioAutorizada, Remessa, Reparo, Setor,
    Tarefa, TelemetriaMaquina, TermoResponsabilidade, Transferencia, TransferenciaNotebook,
    pode_mover_baia, proximo_patrimonio,
)

_CORES_DESEMPENHO = {
    "Crítico": "#e0533f", "Baixo": "#ef8f3c", "Bom": "#8fb82e", "Ótimo": "#00a651",
}

# Grupos cujos usuários podem ser "Técnico responsável" por um reparo.
GRUPOS_TECNICOS = ["Estagiário", "Técnico de Pós Venda"]


def _redirect_etiquetas(ids):
    """Redireciona para a página de etiquetas com os ids informados."""
    ids = [str(i) for i in ids if i]
    url = reverse("parque_etiquetas")
    return redirect(f"{url}?ids={','.join(ids)}") if ids else None


def tecnicos_queryset():
    """Usuários ativos dos grupos Estagiário / Técnico de Pós Venda."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return (
        User.objects.filter(groups__name__in=GRUPOS_TECNICOS, is_active=True)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )


class NavUnidadeSetorMixin:
    """
    Barra de navegação Unidade › Setor no topo da lista (mesma de Baias).
    Cada admin define os parâmetros de filtro que ligam o modelo à unidade e ao
    setor (parque.Setor). Se `nav_setor_param` for None, mostra só as unidades.
    """

    list_before_template = "parque/setor_buttons.html"
    nav_unidade_param = None
    nav_setor_param = None

    def changelist_view(self, request, extra_context=None):
        from apps.orgs.models import Location

        extra_context = extra_context or {}
        sel_setor = request.GET.get(self.nav_setor_param) if self.nav_setor_param else None
        sel_unidade = request.GET.get(self.nav_unidade_param)

        active_uni = None
        if sel_setor:
            s = Setor.objects.filter(pk=sel_setor).first()
            active_uni = s.unidade_id if s else None
        elif sel_unidade and sel_unidade.isdigit():
            active_uni = int(sel_unidade)

        def make_url(params):
            q = request.GET.copy()
            for k in (self.nav_unidade_param, self.nav_setor_param, "p"):
                if k:
                    q.pop(k, None)
            for k, v in params.items():
                q[k] = v
            enc = q.urlencode()
            return f"?{enc}" if enc else "?"

        unidades = (
            Location.objects.filter(setores__isnull=False).distinct().order_by("name")
        )
        unidade_botoes = [
            {"nome": "Todas", "url": make_url({}), "ativo": active_uni is None}
        ]
        for u in unidades:
            unidade_botoes.append({
                "nome": u.name,
                "url": make_url({self.nav_unidade_param: u.id}),
                "ativo": active_uni == u.id,
            })

        setor_botoes = []
        if active_uni is not None and self.nav_setor_param:
            setor_botoes.append({
                "nome": "Todos os setores",
                "url": make_url({self.nav_unidade_param: active_uni}),
                "ativo": not sel_setor,
            })
            for s in Setor.objects.filter(unidade_id=active_uni).order_by("nome"):
                setor_botoes.append({
                    "nome": s.nome,
                    "url": make_url({self.nav_setor_param: s.id}),
                    "ativo": sel_setor == str(s.id),
                })

        extra_context["unidade_botoes"] = unidade_botoes
        extra_context["setor_botoes"] = setor_botoes
        return super().changelist_view(request, extra_context)


@admin.register(Setor)
class SetorAdmin(NavUnidadeSetorMixin, ModelAdmin):
    list_display = ("nome", "unidade", "qtd_baias")
    list_filter = ("unidade",)
    search_fields = ("nome", "unidade__name")
    autocomplete_fields = ("unidade",)
    fieldsets = (
        ("Identificação", {"fields": (("unidade", "nome"),)}),
    )
    # Navegação: só botões de Unidade (a lista já é de setores).
    nav_unidade_param = "unidade__id__exact"

    @admin.display(description="baias")
    def qtd_baias(self, obj):
        return obj.baias.count()


class _DocumentoInline(TabularInline):
    """Anexos do equipamento (PDF/PNG/JPEG/DOCX) — 1+ por máquina."""
    model = DocumentoEquipamento
    extra = 1
    # `tipo` vem primeiro de propósito: é ele que faz o documento contar no
    # dossiê do arquivo (/parque/arquivo/). Anexo sem tipo entra como "Outro" e
    # não fecha pendência nenhuma.
    fields = ("tipo", "arquivo", "descricao", "enviado_em", "validado_em")
    readonly_fields = ("enviado_em", "validado_em")


class DocumentoComputadorInline(_DocumentoInline):
    fk_name = "computador"


class DocumentoNotebookInline(_DocumentoInline):
    fk_name = "notebook"


@admin.register(Computador)
class ComputadorAdmin(NavUnidadeSetorMixin, ModelAdmin):
    form = ComputadorForm
    # Barra de botões Unidade › Setor no topo (pelo caminho baia→setor→unidade),
    # para o estagiário de cada unidade filtrar rápido e gerar as etiquetas.
    nav_unidade_param = "baia__setor__unidade__id__exact"
    nav_setor_param = "baia__setor__id__exact"
    list_display = ("patrimonio", "quem_usa", "unidade_col", "baia_col", "resumo_specs",
                    "qtd_reparos", "status_badge")
    list_filter = ("status", "baia__setor__unidade", "baia__setor", "marca", "data_compra")
    date_hierarchy = "data_compra"
    search_fields = ("patrimonio", "serial", "marca", "processador", "armazenamento",
                     "ultima_unidade", "ultima_baia", "colaborador__full_name")
    list_select_related = ("baia", "baia__setor", "baia__setor__unidade", "colaborador")
    # `colaborador` é SÓ LEITURA de propósito: quem o define é o colaborador da
    # baia (signal `sincronizar_usuario_do_pc`). Editável aqui, o valor digitado
    # some no próximo save da mesa — campo que desfaz sozinho o que a pessoa
    # escreveu é pior do que campo que não existe.
    readonly_fields = ("patrimonio", "etiqueta_link", "qtd_reparos", "colaborador",
                       "ultima_unidade", "ultima_baia", "criado_em", "atualizado_em")
    actions = ("gerar_etiquetas",)

    @admin.action(description="Gerar etiqueta(s) de patrimônio")
    def gerar_etiquetas(self, request, queryset):
        return _redirect_etiquetas(queryset.values_list("pk", flat=True))

    @admin.display(description="Etiqueta de patrimônio")
    def etiqueta_link(self, obj):
        if not obj or not obj.pk:
            return "Salve o computador para gerar a etiqueta."
        url = f"{reverse('parque_etiquetas')}?ids={obj.pk}"
        return format_html(
            '<a href="{}" target="_blank" style="display:inline-flex;gap:6px;'
            'align-items:center;background:#00a651;color:#fff;font-weight:700;'
            'padding:8px 16px;border-radius:9999px;text-decoration:none">'
            "Gerar / imprimir etiqueta</a>",
            url,
        )
    inlines = (DocumentoComputadorInline,)
    # Identificação → Configuração → Compra → o que o sistema apurou →
    # Observações → Sistema. O bloco de Configuração é o MESMO em Computador,
    # Notebook e nas specs manuais da Baia: sistema operacional na linha inteira
    # (o valor é longo) e as peças em par.
    fieldsets = (
        ("Identificação", {
            "fields": (("patrimonio", "serial"), ("marca", "status"),
                       "etiqueta_link"),
        }),
        ("Configuração", {
            "fields": ("sistema_operacional", ("processador", "memoria_ram"),
                       ("placa_mae", "armazenamento")),
        }),
        ("Compra", {
            "description": "O código Sankhya liga este equipamento ao ERP.",
            "fields": (("data_compra", "valor_compra"), "sankhya_id"),
        }),
        # A descrição diz o que vale para o BLOCO (nada aqui se digita); cada
        # campo explica a si mesmo no próprio texto de ajuda. Já estiveram as
        # duas coisas aqui em cima, e na tela a regra da baia saía escrita duas
        # vezes seguidas, uma logo abaixo da outra.
        ("Quem usa e onde está", {
            "description": "Preenchido pelo sistema.",
            "fields": ("colaborador", ("ultima_unidade", "ultima_baia"), "qtd_reparos"),
        }),
        ("Observações", {"fields": ("notes",)}),
        ("Sistema", {"fields": (("criado_em", "atualizado_em"),)}),
    )
    # No CADASTRO, mostra o campo "loja" (gera o patrimônio); patrimônio não é digitável.
    add_fieldsets = (
        ("Identificação", {
            "description": "O patrimônio é gerado automaticamente pela loja escolhida.",
            "fields": (("loja", "serial"), ("marca", "status")),
        }),
        ("Configuração", {
            "fields": ("sistema_operacional", ("processador", "memoria_ram"),
                       ("placa_mae", "armazenamento")),
        }),
        ("Compra", {
            "description": "O código Sankhya liga este equipamento ao ERP.",
            "fields": (("data_compra", "valor_compra"), "sankhya_id"),
        }),
        ("Observações", {"fields": ("notes",)}),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def save_model(self, request, obj, form, change):
        # Ao cadastrar sem patrimônio, gera pela loja escolhida e guarda a unidade.
        if not change and not (obj.patrimonio or "").strip():
            loja = form.cleaned_data.get("loja")
            if loja:
                obj.patrimonio = proximo_patrimonio(loja.name)
                if not obj.ultima_unidade:
                    obj.ultima_unidade = loja.name
        super().save_model(request, obj, form, change)

    @display(
        description="situação",
        label={
            "Em estoque": "info",
            "Em uso": "success",
            "Com defeito": "danger",
            "Desativado": "warning",
        },
    )
    def status_badge(self, obj):
        return obj.get_status_display()

    @admin.display(description="quem usa", ordering="colaborador__full_name")
    def quem_usa(self, obj):
        # Travessão quando não há ninguém: máquina em estoque ou numa mesa vazia
        # não tem dono, e essa é a resposta certa — não um vazio ambíguo.
        return obj.colaborador.full_name if obj.colaborador_id else "—"

    @admin.display(description="unidade")
    def unidade_col(self, obj):
        b = getattr(obj, "baia", None)
        if b:
            return b.setor.unidade.name
        return obj.ultima_unidade or "—"

    @admin.display(description="baia / posição")
    def baia_col(self, obj):
        b = getattr(obj, "baia", None)
        if b:
            return f"{b.setor.nome} › {b.nome}"
        # desativado/estoque: mostra a última posição conhecida (se houver)
        if obj.ultima_baia:
            return format_html('{} <span style="color:#9ca3af">(última)</span>', obj.ultima_baia)
        return "—"


class TransferenciaSaidaInline(TabularInline):
    """Movimentações em que esta baia foi a ORIGEM."""

    model = Transferencia
    fk_name = "baia_origem"
    verbose_name_plural = "Saídas (PC que saiu desta baia)"
    extra = 0
    fields = ("data_saida", "baia_destino", "colaborador_saida", "so_antigo")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class TransferenciaEntradaInline(TabularInline):
    """Movimentações em que esta baia foi o DESTINO."""

    model = Transferencia
    fk_name = "baia_destino"
    verbose_name_plural = "Entradas (PC que chegou nesta baia)"
    extra = 0
    fields = ("data_entrada", "baia_origem", "colaborador_destino", "so_novo")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class ReparoInline(TabularInline):
    """Reparos / manutenções desta baia (histórico da infra)."""

    model = Reparo
    fk_name = "baia"  # Reparo tem 2 FKs p/ Baia (baia + baia_realocacao); este inline usa a 'baia'.
    extra = 0
    fields = ("data", "previsao_conclusao", "tipo", "titulo", "peca",
              "realizar_cotacao", "custo", "afeta_desempenho", "tecnico")
    ordering = ("-data",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tecnico":
            kwargs["queryset"] = tecnicos_queryset()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class DispositivoFilter(admin.SimpleListFilter):
    """Filtra baias pelo dispositivo alocado (deriva do vínculo, não do antigo pc_status)."""
    title = "dispositivo"
    parameter_name = "dispositivo"

    def lookups(self, request, model_admin):
        return [
            ("pc", "Com PC"),
            ("notebook", "Notebook"),
            ("vazia", "Sem dispositivo"),
            ("defeito", "Com defeito"),
        ]

    def queryset(self, request, qs):
        v = self.value()
        if v == "pc":
            return qs.filter(computador__isnull=False)
        if v == "notebook":
            return qs.filter(notebook__isnull=False)
        if v == "vazia":
            return qs.filter(computador__isnull=True, notebook__isnull=True)
        if v == "defeito":
            return qs.filter(computador__status=Computador.Status.DEFEITO)
        return qs


@admin.register(Baia)


class BaiaAdmin(NavUnidadeSetorMixin, ModelAdmin):
    form = BaiaForm
    actions_list = ["ver_no_mapa"]
    nav_unidade_param = "setor__unidade__id__exact"
    nav_setor_param = "setor__id__exact"

    @action(description="Ver no mapa")
    def ver_no_mapa(self, request):
        return redirect("/parque/mapa-completo/")
    list_display = (
        "nome",
        "setor",
        "colaborador",
        "pc_badge",
        "desempenho_badge",
        "resumo_pc",
    )
    list_filter = ("setor__unidade", "setor", DispositivoFilter)
    search_fields = (
        "nome",
        "colaborador__full_name",
        "processador",
        "sistema_operacional",
        "setor__nome",
        "setor__unidade__name",
    )
    # Sem edição inline na lista (renderizar 113 selects travava a página).
    # No FORMULÁRIO os FKs são caixas de seleção com busca (autocomplete/select2) —
    # dropdown estilizado e pesquisável (Computador/Notebook têm search_fields).
    autocomplete_fields = ("setor", "colaborador", "computador", "notebook")
    list_select_related = ("setor", "setor__unidade")
    inlines = (ReparoInline, TransferenciaEntradaInline, TransferenciaSaidaInline)

    def get_queryset(self, request):
        # prefetch dos reparos para o índice de desempenho não gerar N+1.
        return super().get_queryset(request).prefetch_related("reparos")

    @admin.display(description="desempenho")
    def desempenho_badge(self, obj):
        n = obj.indice_desempenho
        if n is None:
            return "—"
        classe = obj.classe_desempenho
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:9999px;font-weight:700;font-size:12px;white-space:nowrap">'
            "{} · {}</span>",
            _CORES_DESEMPENHO.get(classe, "#64748b"), n, classe,
        )

    def save_formset(self, request, form, formset, change):
        """Abre a cotação dos reparos criados pelo inline (técnico é escolhido)."""
        instances = formset.save(commit=False)
        for obj in instances:
            obj.save()
            if isinstance(obj, Reparo):
                obj.garantir_orcamento(request.user)
                obj.aplicar_desativacao()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()

    @display(
        description="situação",
        label={
            "Com PC": "success",
            "Notebook": "info",
            "Com defeito": "danger",
            "Sem PC": "warning",
        },
    )
    def pc_badge(self, obj):
        return obj.situacao_label

    def _dispositivo(self, obj):
        """O equipamento vinculado a esta mesa (computador OU notebook), ou None."""
        if obj.computador_id:
            return obj.computador
        if obj.notebook_id:
            return obj.notebook
        return None

    @admin.display(description="ID Sankhya")
    def equip_sankhya(self, obj):
        d = self._dispositivo(obj)
        if not d:
            return "—"
        return d.sankhya_id or "(vazio)"

    @admin.display(description="Valor de compra")
    def equip_valor(self, obj):
        d = self._dispositivo(obj)
        if not d or d.valor_compra is None:
            return "—"
        return f"R$ {d.valor_compra:.2f}".replace(".", ",")

    @admin.display(description="Documentos")
    def equip_documentos(self, obj):
        d = self._dispositivo(obj)
        if not d:
            return "—"
        docs = list(d.documentos.all())
        if not docs:
            return "Nenhum documento anexado."
        return format_html_join(
            mark_safe("<br>"),
            '<a href="{}" target="_blank">{}</a>',
            ((doc.arquivo.url, str(doc)) for doc in docs if doc.arquivo),
        )

    @admin.display(description="Editar dados do equipamento")
    def equip_editar_link(self, obj):
        d = self._dispositivo(obj)
        if not d:
            return "Vincule um computador ou notebook para registrar ID Sankhya, valor e documentos."
        if obj.computador_id:
            url = reverse("admin:parque_computador_change", args=[obj.computador_id])
            rotulo = "Editar cadastro do computador"
        else:
            url = reverse("admin:parque_notebook_change", args=[obj.notebook_id])
            rotulo = "Editar cadastro do notebook"
        return format_html(
            '<a href="{}" style="display:inline-flex;gap:6px;align-items:center;'
            'background:#00a651;color:#fff;font-weight:700;padding:8px 16px;'
            'border-radius:8px;text-decoration:none">{}</a>', url, rotulo,
        )

    # Onde a mesa fica → o que está nela → os periféricos. As specs manuais
    # caíram para o fim (são legado, só valem sem dispositivo vinculado) e
    # perderam o "collapse": caixa dentro de caixa foi reprovada pelo dono.
    fieldsets = (
        ("Localização", {
            "fields": (("setor", "nome"), "colaborador"),
        }),
        ("Dispositivo", {
            "description": "Aloque UM dispositivo à mesa: um computador OU um notebook "
                           "do estoque. Deixe ambos vazios para uma mesa sem equipamento.",
            "fields": (("computador", "notebook"),),
        }),
        ("Equipamento — ID Sankhya, valor e documentos", {
            "description": "Dados do equipamento que está nesta mesa. São editados no "
                           "cadastro do próprio computador/notebook (botão abaixo) — a "
                           "informação é a mesma em todo o sistema.",
            "fields": (("equip_sankhya", "equip_valor"), "equip_documentos",
                       "equip_editar_link"),
        }),
        ("Periféricos", {
            "fields": (("mouse", "teclado"), ("webcam", "headset"),
                       ("monitor", "leitor_cod_barras")),
        }),
        ("Specs manuais (legado)", {
            "description": "Usadas só quando a mesa NÃO tem dispositivo vinculado. "
                           "Prefira alocar um computador/notebook do estoque.",
            "fields": ("sistema_operacional", ("processador", "memoria_ram"),
                       ("placa_mae", "armazenamento")),
        }),
        ("Observações", {
            "fields": ("notes",),
        }),
        ("Sistema", {
            "fields": ("atualizado_em",),
        }),
    )
    readonly_fields = ("atualizado_em", "equip_sankhya", "equip_valor",
                       "equip_documentos", "equip_editar_link")

    # As specs da BAIA só valem para mesa VAZIA. Havendo computador ou notebook
    # vinculado, o mapa lê as specs DELE (`Baia.eff_cpu` → `computador
    # .cpu_efetivo`) e o que está aqui é ignorado — mas os campos continuavam
    # editáveis do mesmo jeito. A pessoa digitava, salvava com sucesso, o parque
    # não mudava, e nada na tela explicava por quê.
    #
    # Pior: o botão "Editar cadastro" do painel do mapa aponta para ESTA tela
    # (`templates/parque/_baia.html`, `data-edit`), então este era o caminho
    # natural de quem queria corrigir a máquina. Era o defeito relatado pelo
    # Jonas em 21/09/2026 ("atualizo o cadastro e no parque não sobe").
    #
    # Com dispositivo vinculado os campos ficam só leitura e o texto do grupo
    # diz onde editar de verdade. Mesa vazia segue editável, que é o caso de uso
    # legítimo destes campos.
    _SPECS_DA_BAIA = ("sistema_operacional", "processador", "memoria_ram",
                      "placa_mae", "armazenamento")

    def _tem_dispositivo(self, obj):
        return bool(obj and (obj.computador_id or obj.notebook_id))

    def get_readonly_fields(self, request, obj=None):
        ro = tuple(super().get_readonly_fields(request, obj))
        if self._tem_dispositivo(obj):
            ro += tuple(c for c in self._SPECS_DA_BAIA if c not in ro)
        return ro

    def get_fieldsets(self, request, obj=None):
        fs = super().get_fieldsets(request, obj)
        if not self._tem_dispositivo(obj):
            return fs
        dev = obj.computador or obj.notebook
        qual = "computador" if obj.computador_id else "notebook"
        saida = []
        for titulo, opcoes in fs:
            if titulo == "Specs manuais (legado)":
                opcoes = dict(opcoes)
                opcoes["description"] = (
                    f"Esta mesa tem {qual} vinculado ({dev}), então o parque mostra "
                    f"as specs DELE e estes campos ficam sem efeito — por isso estão "
                    f"bloqueados aqui. Para corrigir processador, memória, disco ou "
                    f"sistema, edite o cadastro do próprio {qual}. Estes campos voltam "
                    f"a valer se a mesa ficar sem dispositivo."
                )
            saida.append((titulo, opcoes))
        return saida


@admin.register(Transferencia)
class TransferenciaAdmin(NavUnidadeSetorMixin, ModelAdmin):
    # Navegação por unidade/setor do DESTINO (para onde o PC foi).
    nav_unidade_param = "baia_destino__setor__unidade__id__exact"
    nav_setor_param = "baia_destino__setor__id__exact"
    list_display = (
        "data_entrada",
        "baia_origem",
        "baia_destino",
        "colaborador_saida",
        "colaborador_destino",
        "status_badge",
        "registrado_por",
        "acoes",
    )
    list_filter = (
        "status",
        "data_entrada",
        "baia_destino__setor__unidade",
        "baia_destino__setor",
    )
    search_fields = (
        "baia_origem__nome",
        "baia_destino__nome",
        "colaborador_saida",
        "colaborador_destino",
    )
    autocomplete_fields = ("baia_origem", "baia_destino")
    readonly_fields = ("registrado_por", "created_at", "status", "decidido_por",
                       "decidido_em", "motivo", "entre_lojas", "setor_destino",
                       "nome_baia_destino", "computador", "bitrix_task_id")
    date_hierarchy = "data_entrada"
    list_select_related = ("baia_origem", "baia_destino", "registrado_por")

    # Origem e destino têm o MESMO desenho (mesa+data em par, colaborador na
    # linha inteira, specs em par) para a pessoa comparar as duas colunas de
    # olho. A decisão saiu do "Registro" para um grupo Situação próprio.
    fieldsets = (
        ("Origem (de onde o PC saiu)", {
            "fields": (
                ("baia_origem", "data_saida"), "colaborador_saida",
                ("so_antigo", "processador_antigo"),
                ("placa_mae_antigo", "ram_antigo", "armazenamento_antigo"),
            ),
        }),
        ("Destino (para onde o PC foi)", {
            "fields": (
                ("baia_destino", "data_entrada"), "colaborador_destino",
                ("so_novo", "processador_novo"),
                ("placa_mae_novo", "ram_novo", "armazenamento_novo"),
            ),
        }),
        ("Transferência entre lojas", {
            "description": "Preenchido pelo fluxo do caminhão (Transferência entre lojas).",
            "fields": (("entre_lojas", "computador"),
                       ("setor_destino", "nome_baia_destino")),
        }),
        ("Situação", {
            "fields": (("status", "motivo"), ("decidido_por", "decidido_em")),
        }),
        ("Observações", {
            "fields": ("observacao",),
        }),
        ("Sistema", {
            "fields": (("registrado_por", "created_at"), "bitrix_task_id"),
        }),
    )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["transfer_lojas_url"] = reverse("parque_transferencia_lojas")
        extra_context["todas_transferencias_url"] = reverse("parque_transferencias")
        # Visualizou as transferências → zera o badge de "novas" no menu.
        from django.utils import timezone
        request.session["transferencias_visto_em"] = timezone.now().isoformat()
        return super().changelist_view(request, extra_context)

    def get_queryset(self, request):
        self._request = request
        return super().get_queryset(request)

    @admin.display(description="situação")
    def status_badge(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:9999px;'
            'font-weight:700;font-size:12px;white-space:nowrap">{}</span>',
            _CORES_MOV.get(obj.status, "#64748b"), obj.get_status_display(),
        )

    @admin.display(description="ações")
    def acoes(self, obj):
        partes = []
        # Protocolo: transferências entre lojas já autorizadas.
        if obj.entre_lojas and obj.status == Transferencia.Status.AUTORIZADA:
            url_prot = reverse("parque_protocolo_transferencia", args=[obj.pk])
            partes.append(format_html(
                '<a href="{}" target="_blank" style="background:#0c7a3e;color:#fff;'
                'padding:4px 12px;border-radius:9999px;text-decoration:none;font-weight:700;'
                'font-size:12px">Protocolo</a>', url_prot,
            ))
        # Autorizar / negar: pendentes (para quem pode decidir).
        if obj.status == Transferencia.Status.PENDENTE:
            req = getattr(self, "_request", None)
            if req and pode_mover_baia(req.user):
                url_aut = reverse("parque_decidir_transferencia", args=[obj.pk, "autorizar"])
                url_neg = reverse("parque_decidir_transferencia", args=[obj.pk, "negar"])
                partes.append(format_html(
                    '<a href="{}" style="background:#00a651;color:#fff;padding:4px 12px;'
                    'border-radius:9999px;text-decoration:none;font-weight:700;font-size:12px">Autorizar</a> '
                    '<a href="{}" onclick="return confirm(\'Negar esta transferência?\')" '
                    'style="background:#e0533f;color:#fff;padding:4px 12px;border-radius:9999px;'
                    'text-decoration:none;font-weight:700;font-size:12px">Negar</a>',
                    url_aut, url_neg,
                ))
            else:
                partes.append("aguardando autorização")
        if not partes:
            return "—"
        return mark_safe(" ".join(partes))

    def save_model(self, request, obj, form, change):
        """Preenche quem registrou. Autorizados aplicam direto; os demais geram
        uma transferência PENDENTE (só tem efeito após aprovação)."""
        if obj.registrado_por_id is None:
            obj.registrado_por = request.user
        autorizado = pode_mover_baia(request.user)
        if not change:
            obj.status = (
                Transferencia.Status.AUTORIZADA if autorizado
                else Transferencia.Status.PENDENTE
            )
        super().save_model(request, obj, form, change)
        if obj.status == Transferencia.Status.AUTORIZADA:
            obj.aplicar_no_destino()
        else:
            messages.warning(
                request,
                "Transferência registrada e enviada para autorização — só terá "
                "efeito depois que um responsável aprovar.",
            )


@admin.register(Reparo)
class ReparoAdmin(ModelAdmin):
    form = ReparoForm
    list_display = ("data", "baia", "tipo", "titulo", "status_manutencao", "peca",
                    "realizar_cotacao", "custo", "tecnico", "acoes_reparo")

    @admin.display(description="manutenção")
    def status_manutencao(self, obj):
        if obj.concluido_em:
            cor, txt = "#00a651", f"Finalizado · {obj.concluido_em:%d/%m}"
        elif obj.previsao_conclusao:
            cor, txt = "#ef8f3c", "Em manutenção"
        else:
            return "—"
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:9999px;'
            'font-weight:700;font-size:12px;white-space:nowrap">{}</span>', cor, txt,
        )

    @admin.display(description="ações")
    def acoes_reparo(self, obj):
        if obj.previsao_conclusao and not obj.concluido_em:
            url = reverse("parque_finalizar_reparo_admin", args=[obj.pk])
            return format_html(
                '<a href="{}" onclick="return confirm(\'Finalizar este reparo? '
                'A tarefa do Bitrix será fechada.\')" style="background:#00a651;color:#fff;'
                'padding:4px 12px;border-radius:9999px;text-decoration:none;font-weight:700;'
                'font-size:12px">Finalizar</a>', url,
            )
        return ""
    list_filter = ("tipo", "peca", "realizar_cotacao", "afeta_desempenho", "data",
                   "baia__setor__unidade")
    search_fields = ("titulo", "descricao", "baia__nome",
                     "baia__colaborador__full_name", "bitrix_task_id")
    autocomplete_fields = ("baia",)
    readonly_fields = ("orcamento", "created_at")
    date_hierarchy = "data"
    list_select_related = ("baia", "tecnico", "orcamento")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tecnico":
            kwargs["queryset"] = tecnicos_queryset()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Trava a máquina: ao abrir o chamado a partir de uma baia (?baia=) ou ao
        # editar um reparo existente, NÃO se pode trocar a baia. `disabled` mantém o
        # valor inicial e bloqueia a edição.
        if (request.GET.get("baia") or obj is not None) and "baia" in form.base_fields:
            form.base_fields["baia"].disabled = True
        return form

    def add_view(self, request, form_url="", extra_context=None):
        # "Abrir chamado" (com ?baia=) usa a TELA CUSTOM estilo tarefa, não o admin
        # cru. Sem baia (ex.: + Adicionar pelo menu), segue o formulário do admin.
        baia = request.GET.get("baia")
        if baia and str(baia).isdigit():
            params = request.GET.copy()
            params.pop("baia", None)
            url = reverse("parque_abrir_chamado", args=[baia])
            qs = params.urlencode()
            return redirect(f"{url}?{qs}" if qs else url)
        return super().add_view(request, form_url, extra_context)

    # Abrir o chamado → dizer que peça troca → registrar a execução. O número
    # da tarefa no Bitrix e o orçamento gerado saíram para o grupo Sistema:
    # quem abre o chamado não preenche nenhum dos dois.
    fieldsets = (
        ("Chamado", {
            "fields": (("baia", "tipo"), "titulo",
                       ("data", "previsao_conclusao"), "descricao"),
        }),
        ("Peça a trocar / cotação", {
            "fields": (("peca", "peca_outro"),
                       ("nova_especificacao", "realizar_cotacao")),
        }),
        ("Execução", {
            "fields": (("tecnico", "custo"), "afeta_desempenho"),
        }),
        ("Sistema", {
            "fields": (("bitrix_task_id", "orcamento"), "created_at"),
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.garantir_orcamento(request.user)
        obj.aplicar_desativacao()


_CORES_MOV = {"pendente": "#ef8f3c", "autorizada": "#00a651", "negada": "#e0533f"}


@admin.register(MovimentacaoBaia)
class MovimentacaoBaiaAdmin(ModelAdmin):
    list_display = ("criado_em", "tipo_badge", "baia", "rota", "status_badge", "info_pc",
                    "solicitante", "decidido_por", "acoes")
    list_filter = ("status", "tipo", "baia__setor__unidade")
    search_fields = ("baia__nome", "baia_parceira__nome", "info_pc", "colaborador_nome",
                     "patrimonio", "solicitante__username")
    date_hierarchy = "criado_em"
    list_select_related = ("baia", "baia_parceira", "setor_origem", "setor_destino",
                           "solicitante", "decidido_por")
    readonly_fields = ("tipo", "baia", "baia_parceira", "setor_origem", "setor_destino",
                       "info_pc", "colaborador_nome", "patrimonio", "info_pc_parceira",
                       "colaborador_parceira", "patrimonio_parceira", "status",
                       "solicitante", "decidido_por", "motivo", "criado_em", "decidido_em")
    # Quase tudo aqui é retrato do momento do arrasto no mapa. Os grupos
    # separam a rota, a máquina movida e a máquina parceira (que só existe na
    # troca) — antes eram 18 campos empilhados sem nenhum título.
    fieldsets = (
        ("Movimentação", {
            "fields": (("tipo", "baia"), ("setor_origem", "setor_destino"),
                       "baia_parceira"),
        }),
        ("Máquina movida", {
            "fields": (("patrimonio", "colaborador_nome"), "info_pc"),
        }),
        ("Máquina parceira", {
            "description": "Só preenchida quando o tipo é troca de computadores.",
            "fields": (("patrimonio_parceira", "colaborador_parceira"),
                       "info_pc_parceira"),
        }),
        ("Decisão", {
            "fields": (("status", "motivo"), ("solicitante", "decidido_por"),
                       "decidido_em"),
        }),
        ("Observações", {"fields": ("observacao",)}),
        ("Sistema", {"fields": ("criado_em",)}),
    )

    def has_add_permission(self, request):
        # Movimentações nascem do arrastar no mapa, não do "Adicionar".
        return False

    def get_queryset(self, request):
        self._request = request
        return super().get_queryset(request)

    @admin.display(description="tipo")
    def tipo_badge(self, obj):
        cor = "#067a38" if obj.tipo == MovimentacaoBaia.Tipo.TROCAR else "#7c3aed"
        rotulo = "Troca de PC" if obj.tipo == MovimentacaoBaia.Tipo.TROCAR else "Mover baia"
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:9999px;'
            'font-weight:700;font-size:11px;white-space:nowrap">{}</span>', cor, rotulo,
        )

    @admin.display(description="movimentação")
    def rota(self, obj):
        if obj.tipo == MovimentacaoBaia.Tipo.TROCAR:
            return format_html("{} ↔ <b>{}</b>", obj.baia or "?", obj.baia_parceira or "?")
        return format_html("{} → <b>{}</b>", obj.setor_origem or "?", obj.setor_destino or "?")

    @admin.display(description="situação")
    def status_badge(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:9999px;'
            'font-weight:700;font-size:12px;white-space:nowrap">{}</span>',
            _CORES_MOV.get(obj.status, "#64748b"), obj.get_status_display(),
        )

    @admin.display(description="ações")
    def acoes(self, obj):
        if obj.status != MovimentacaoBaia.Status.PENDENTE:
            return "—"
        req = getattr(self, "_request", None)
        if not (req and pode_mover_baia(req.user)):
            return "aguardando autorização"
        url_aut = reverse("parque_decidir_solicitacao", args=[obj.pk, "autorizar"])
        url_neg = reverse("parque_decidir_solicitacao", args=[obj.pk, "negar"])
        return format_html(
            '<a href="{}" style="background:#00a651;color:#fff;padding:4px 12px;'
            'border-radius:9999px;text-decoration:none;font-weight:700;font-size:12px">Autorizar</a> '
            '<a href="{}" onclick="return confirm(\'Negar esta solicitação?\')" '
            'style="background:#e0533f;color:#fff;padding:4px 12px;border-radius:9999px;'
            'text-decoration:none;font-weight:700;font-size:12px">Negar</a>',
            url_aut, url_neg,
        )


@admin.register(Notebook)
class NotebookAdmin(ModelAdmin):
    actions_list = ["ver_no_mapa"]
    list_display = ("marca", "modelo", "colaborador_col", "unidade_setor", "serial",
                    "resumo_specs", "status_badge")

    @action(description="Ver no mapa")
    def ver_no_mapa(self, request):
        return redirect("/parque/mapa-notebooks/")
    list_filter = ("status", "marca", "colaborador", "unidade_setor", "data_compra")
    date_hierarchy = "data_compra"
    search_fields = ("marca", "modelo", "colaborador__full_name", "usuario",
                     "unidade_setor", "serial", "processador", "conta", "anydesk",
                     "observacoes", "bitrix_task_id", "titulo")
    list_select_related = ("colaborador",)
    list_per_page = 50
    readonly_fields = ("patrimonio", "etiqueta_link", "titulo", "bitrix_task_id",
                       "criada_em_origem", "atualizada_em_origem", "criado_em", "atualizado_em")
    inlines = (DocumentoNotebookInline,)
    actions = ("gerar_etiquetas",)

    # Campos de senha só para superusuário. Cifrar protege o BACKUP; esconder da
    # tela protege de quem tem acesso ao admin mas não precisa da credencial.
    CAMPOS_SIGILOSOS = ("senha", "anydesk_senha")

    def _sem_sigilosos(self, fields):
        """Tira os campos de senha, inclusive de dentro de uma linha pareada.

        Sem entrar na tupla da linha, o `not in` compararia a LINHA com a lista
        de sigilosos, daria "não está" e a senha vazaria para quem não é
        superusuário — o pareamento de campos criaria um furo de segurança.
        """
        limpo = []
        for item in fields:
            if isinstance(item, (tuple, list)):
                linha = tuple(f for f in item if f not in self.CAMPOS_SIGILOSOS)
                if len(linha) == 1:
                    limpo.append(linha[0])
                elif linha:
                    limpo.append(linha)
            elif item not in self.CAMPOS_SIGILOSOS:
                limpo.append(item)
        return tuple(limpo)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets
        podados = []
        for titulo, opcoes in fieldsets:
            opcoes = dict(opcoes)
            opcoes["fields"] = self._sem_sigilosos(opcoes.get("fields", ()))
            if opcoes["fields"]:
                podados.append((titulo, opcoes))
        return tuple(podados)

    @admin.display(description="Etiqueta de patrimônio")
    def etiqueta_link(self, obj):
        if not obj or not obj.pk or not obj.patrimonio:
            return "Salve o notebook para gerar a etiqueta."
        url = f"{reverse('parque_etiquetas')}?nb_ids={obj.pk}"
        return format_html(
            '<a href="{}" target="_blank" style="display:inline-flex;gap:6px;'
            'align-items:center;background:#00a651;color:#fff;font-weight:700;'
            'padding:8px 16px;border-radius:9999px;text-decoration:none">'
            "Gerar / imprimir etiqueta</a>", url,
        )

    @admin.action(description="Gerar etiqueta(s) de patrimônio")
    def gerar_etiquetas(self, request, queryset):
        ids = [str(pk) for pk in queryset.values_list("pk", flat=True)]
        if not ids:
            return None
        return redirect(f"{reverse('parque_etiquetas')}?nb_ids={','.join(ids)}")

    # Mesma sequência do Computador (Identificação → Configuração → Compra),
    # com Uso e Acesso pelo meio porque notebook anda com uma pessoa. Cada par
    # de credencial fica na mesma linha (usuário ao lado da senha).
    fieldsets = (
        ("Identificação", {
            "fields": (("patrimonio", "serial"), ("marca", "modelo"),
                       ("status", "etiqueta_link")),
        }),
        ("Uso", {
            "description": "O colaborador é escolhido na lista de pessoas cadastradas.",
            "fields": (("colaborador", "unidade_setor"),),
        }),
        ("Acesso", {
            "description": "Credenciais do equipamento (Conta, Senha, AnyDesk). "
                           "As senhas ficam cifradas no banco; só superusuário as vê.",
            "fields": (("conta", "senha"), ("anydesk", "anydesk_senha")),
        }),
        ("Configuração", {
            "fields": ("sistema_operacional", ("processador", "memoria_ram"),
                       ("placa_mae", "armazenamento")),
        }),
        ("Compra", {
            "description": "O código Sankhya liga este equipamento ao ERP.",
            "fields": (("data_compra", "valor_compra"), "sankhya_id"),
        }),
        ("Observações", {
            "fields": ("observacoes",),
        }),
        ("Sistema", {
            "description": "Vem da importação do Bitrix24 e do próprio sistema.",
            "fields": (("bitrix_task_id", "titulo"),
                       ("criada_em_origem", "atualizada_em_origem"),
                       ("criado_em", "atualizado_em")),
        }),
    )

    @admin.display(description="colaborador", ordering="colaborador__full_name")
    def colaborador_col(self, obj):
        if obj.colaborador_id:
            return obj.colaborador.full_name
        # Registros antigos só têm o nome em texto (vindo da planilha).
        if obj.usuario:
            return format_html('{} <span style="color:#9ca3af">(texto)</span>', obj.usuario)
        return "—"

    def save_model(self, request, obj, form, change):
        # Mantém o texto `usuario` em sincronia com o colaborador escolhido,
        # para o mapa e demais telas que ainda leem o campo de texto.
        if obj.colaborador_id:
            obj.usuario = obj.colaborador.full_name
        super().save_model(request, obj, form, change)

    @display(
        description="situação",
        label={"Ativo": "success", "Com defeito": "danger", "Obsoleto / sem uso": "warning"},
    )
    def status_badge(self, obj):
        return obj.get_status_display()


@admin.register(TransferenciaNotebook)
class TransferenciaNotebookAdmin(ModelAdmin):
    list_display = ("data", "equipamento", "unidade_origem", "unidade_destino",
                    "usuario", "status_badge", "acoes")
    list_filter = ("status", "unidade_destino", "data")
    search_fields = ("marca", "modelo", "serial", "usuario", "unidade_origem",
                     "usuario_destino", "bitrix_task_id")
    date_hierarchy = "data"
    list_select_related = ("unidade_destino", "notebook")
    autocomplete_fields = ("notebook", "unidade_destino")
    readonly_fields = ("registrado_por", "decidido_por", "decidido_em",
                       "bitrix_task_id", "created_at")
    actions = ("autorizar_transferencias", "negar_transferencias")
    # Origem e destino em grupos separados, como na transferência de PC: é
    # de onde saiu / para onde vai, e a pessoa lê um de cada vez.
    fieldsets = (
        ("Equipamento", {
            "description": "Escolhido o notebook, marca, modelo, série e "
                           "configuração ficam como registro do que saiu.",
            "fields": ("notebook", ("marca", "modelo"), ("serial", "specs")),
        }),
        ("Origem (de onde o notebook saiu)", {
            "fields": (("unidade_origem", "usuario"),),
        }),
        ("Destino (para onde o notebook vai)", {
            "fields": (("unidade_destino", "usuario_destino"), "data"),
        }),
        ("Situação", {
            "fields": (("status", "motivo"), ("decidido_por", "decidido_em")),
        }),
        ("Observações", {"fields": ("observacao",)}),
        ("Sistema", {"fields": (("registrado_por", "created_at"), "bitrix_task_id")}),
    )

    _CORES_STATUS = {
        "pendente": "#ef8f3c", "autorizada": "#00a651", "negada": "#9ca3af",
    }

    @admin.display(description="equipamento")
    def equipamento(self, obj):
        nome = " ".join(p for p in [obj.marca, obj.modelo] if p) or "Notebook"
        return f"{nome}{f' · {obj.serial}' if obj.serial else ''}"

    @admin.display(description="situação")
    def status_badge(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;border-radius:9999px;'
            'font-weight:700;font-size:12px;white-space:nowrap">{}</span>',
            self._CORES_STATUS.get(obj.status, "#64748b"), obj.get_status_display(),
        )

    @admin.display(description="ações")
    def acoes(self, obj):
        if obj.status == TransferenciaNotebook.Status.AUTORIZADA:
            url_prot = reverse("parque_protocolo_notebook", args=[obj.pk])
            return format_html(
                '<a href="{}" target="_blank" style="background:#0c7a3e;color:#fff;'
                'padding:4px 12px;border-radius:9999px;text-decoration:none;font-weight:700;'
                'font-size:12px">Protocolo</a>', url_prot,
            )
        if obj.status == TransferenciaNotebook.Status.PENDENTE:
            return format_html('<span style="color:#ef8f3c;font-weight:700">Aguardando autorização</span>')
        return "—"

    @admin.action(description="Autorizar transferências selecionadas")
    def autorizar_transferencias(self, request, queryset):
        if not pode_mover_baia(request.user):
            self.message_user(request, "Você não tem permissão para autorizar transferências.", messages.ERROR)
            return
        n = 0
        for t in queryset.filter(status=TransferenciaNotebook.Status.PENDENTE):
            t.autorizar(request.user)
            n += 1
        self.message_user(request, f"{n} transferência(s) autorizada(s) e aplicada(s).", messages.SUCCESS)

    @admin.action(description="Negar transferências selecionadas")
    def negar_transferencias(self, request, queryset):
        if not pode_mover_baia(request.user):
            self.message_user(request, "Você não tem permissão para decidir transferências.", messages.ERROR)
            return
        n = 0
        for t in queryset.filter(status=TransferenciaNotebook.Status.PENDENTE):
            t.negar(request.user)
            n += 1
        self.message_user(request, f"{n} transferência(s) negada(s).", messages.SUCCESS)


@admin.register(Peca)
class PecaAdmin(NavUnidadeSetorMixin, ModelAdmin):
    nav_unidade_param = "unidade__id__exact"
    list_display = ("tipo_col", "descricao", "unidade", "quantidade", "estoque_badge")
    list_filter = ("tipo", "unidade")
    search_fields = ("descricao", "notes")
    autocomplete_fields = ("unidade",)
    list_select_related = ("unidade",)
    fieldsets = (
        ("Identificação", {"fields": ("tipo", "descricao")}),
        ("Estoque", {"fields": (("unidade", "quantidade"),)}),
        ("Observações", {"fields": ("notes",)}),
    )
    actions = ["transferir_selecionada", "montar_caixa_selecionadas", "alterar_selecionado"]

    @admin.action(description="Transferir", permissions=["change"])
    def transferir_selecionada(self, request, queryset):
        """Transfere UMA peça (selecione exatamente 1)."""
        if queryset.count() != 1:
            self.message_user(request, "Para transferir, selecione exatamente 1 peça.",
                              level=messages.WARNING)
            return None
        return redirect(reverse("parque_transferir_peca", args=[queryset.first().pk]))

    @admin.action(description="Montar caixa de envio", permissions=["change"])
    def montar_caixa_selecionadas(self, request, queryset):
        """Abre a tela de montar caixa já com os itens selecionados (2 ou mais)."""
        if queryset.count() < 2:
            self.message_user(request, "Selecione 2 ou mais itens para montar uma caixa "
                              "(para 1 item, use Transferir).", level=messages.WARNING)
            return None
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return redirect(reverse("parque_montar_caixa") + f"?ids={ids}")

    @admin.display(description="tipo")
    def tipo_col(self, obj):
        return obj.get_tipo_display()

    @display(description="estoque", label={"Em falta": "danger", "OK": "success"})
    def estoque_badge(self, obj):
        return "Em falta" if obj.em_falta else "OK"

    @admin.display(description="ações")
    def acoes_peca(self, obj):
        if obj.quantidade <= 0:
            return "—"
        url = reverse("parque_transferir_peca", args=[obj.pk])
        return format_html(
            '<a href="{}" style="background:#067a38;color:#fff;padding:4px 12px;'
            'border-radius:9999px;text-decoration:none;font-weight:700;font-size:12px">'
            "Transferir</a>", url,
        )


@admin.register(MovimentacaoPeca)
class MovimentacaoPecaAdmin(ModelAdmin):
    list_display = ("em", "tipo_col", "descricao", "quantidade", "unidade_origem",
                    "unidade_destino", "por_usuario", "protocolo")
    list_filter = ("tipo", "unidade_origem", "unidade_destino")
    search_fields = ("descricao",)
    date_hierarchy = "em"
    list_select_related = ("unidade_origem", "unidade_destino", "por_usuario")
    readonly_fields = ("tipo", "descricao", "quantidade", "unidade_origem",
                       "unidade_destino", "por_usuario", "em")
    fieldsets = (
        ("Item", {"fields": (("tipo", "quantidade"), "descricao")}),
        ("Rota", {"fields": (("unidade_origem", "unidade_destino"),
                             ("colaborador_destino", "data_chegada"))}),
        ("Sistema", {"fields": (("por_usuario", "em"),
                                ("remessa", "bitrix_task_id"))}),
    )

    def has_add_permission(self, request):
        return False  # nasce da tela de transferência, não do "Adicionar".

    @admin.display(description="tipo")
    def tipo_col(self, obj):
        return obj.get_tipo_display()

    @admin.display(description="comprovante")
    def protocolo(self, obj):
        # Item solto: protocolo individual. Item de uma caixa: protocolo da caixa.
        if obj.remessa_id:
            url = reverse("parque_protocolo_remessa", args=[obj.remessa_id])
            rotulo = "Protocolo (caixa)"
        else:
            url = reverse("parque_protocolo_peca", args=[obj.pk])
            rotulo = "Protocolo"
        return format_html(
            '<a href="{}" target="_blank" style="background:#0c7a3e;color:#fff;'
            'padding:4px 12px;border-radius:9999px;text-decoration:none;font-weight:700;'
            'font-size:12px">{}</a>', url, rotulo,
        )


class _ItemRemessaInline(TabularInline):
    model = MovimentacaoPeca
    extra = 0
    can_delete = False
    fields = ("tipo", "descricao", "quantidade")
    readonly_fields = ("tipo", "descricao", "quantidade")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Remessa)
class RemessaAdmin(ModelAdmin):
    list_display = ("em", "unidade_origem", "unidade_destino", "qtd_itens",
                    "colaborador_destino", "data_chegada", "protocolo")
    list_filter = ("unidade_origem", "unidade_destino", "em")
    date_hierarchy = "em"
    list_select_related = ("unidade_origem", "unidade_destino", "colaborador_destino", "por_usuario")
    readonly_fields = ("unidade_origem", "unidade_destino", "colaborador_destino",
                       "data_chegada", "por_usuario", "em")
    inlines = (_ItemRemessaInline,)
    fieldsets = (
        ("Rota", {"fields": (("unidade_origem", "unidade_destino"),)}),
        ("Recebimento", {"fields": (("colaborador_destino", "data_chegada"),)}),
        ("Sistema", {"fields": (("por_usuario", "em"),)}),
    )

    def has_add_permission(self, request):
        return False  # caixas nascem da tela "Montar caixa".

    @admin.display(description="itens")
    def qtd_itens(self, obj):
        return obj.itens.count()

    @admin.display(description="comprovante")
    def protocolo(self, obj):
        url = reverse("parque_protocolo_remessa", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" style="background:#0c7a3e;color:#fff;'
            'padding:4px 12px;border-radius:9999px;text-decoration:none;font-weight:700;'
            'font-size:12px">Protocolo</a>', url,
        )


@admin.register(TermoResponsabilidade)
class TermoResponsabilidadeAdmin(ModelAdmin):
    """Termos de responsabilidade de notebooks — gerados na tela de notebooks.

    O RH acompanha aqui o que está pendente/assinado e sobe o documento assinado
    (subir o arquivo marca o termo como assinado automaticamente).
    """

    list_display = ("colaborador_nome", "tipo", "equipamento_desc", "status_badge",
                    "criado_em", "assinado_em", "imprimir")
    # Entrega e devolução são o mesmo documento em sentidos opostos, e a
    # pergunta do RH é sempre sobre um dos dois — por isso filtro, não coluna
    # solta.
    list_filter = ("tipo", "status")
    search_fields = ("colaborador_nome", "equipamento_desc")
    date_hierarchy = "criado_em"
    # O que o RH faz aqui é subir o arquivo assinado: o grupo Assinatura é o
    # único editável e vem depois dos dados do termo, que já vêm prontos.
    fieldsets = (
        ("Termo", {"fields": (("colaborador_nome", "equipamento_desc"),
                              ("notebook", "colaborador"))}),
        ("Assinatura", {
            "description": "Subir o arquivo assinado marca o termo como assinado.",
            "fields": (("status", "assinado_em"), "arquivo_assinado"),
        }),
        ("Sistema", {"fields": (("criado_por", "criado_em"),)}),
    )
    readonly_fields = ("colaborador_nome", "equipamento_desc", "notebook", "colaborador",
                       "criado_por", "criado_em", "assinado_em")
    actions = ("marcar_assinado",)

    def has_add_permission(self, request):
        return False  # termos nascem da tela de notebooks (botão "Gerar termo").

    @admin.display(description="situação")
    def status_badge(self, obj):
        cor = "#00a651" if obj.status == TermoResponsabilidade.Status.ASSINADO else "#ef8f3c"
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;border-radius:9999px;'
            'font-weight:700;font-size:12px">{}</span>', cor, obj.get_status_display(),
        )

    @admin.display(description="documento")
    def imprimir(self, obj):
        url = reverse("parque_termo_imprimir", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" style="background:#0c7a3e;color:#fff;'
            'padding:4px 12px;border-radius:9999px;text-decoration:none;font-weight:700;'
            'font-size:12px">Termo</a>', url,
        )

    def save_model(self, request, obj, form, change):
        # RH sobe o arquivo assinado → marca como assinado automaticamente.
        if obj.arquivo_assinado and obj.status != TermoResponsabilidade.Status.ASSINADO:
            obj.status = TermoResponsabilidade.Status.ASSINADO
            if not obj.assinado_em:
                obj.assinado_em = timezone.now()
        super().save_model(request, obj, form, change)

    @action(description="Marcar como assinado")
    def marcar_assinado(self, request, queryset):
        n = 0
        for termo in queryset:
            if termo.status != TermoResponsabilidade.Status.ASSINADO:
                termo.marcar_assinado()
                n += 1
        self.message_user(
            request, f"{n} termo(s) marcado(s) como assinado(s).", messages.SUCCESS
        )


@admin.register(Autorizada)
class AutorizadaAdmin(ModelAdmin):
    """Cadastro das autorizadas / assistências técnicas externas.

    Mesmos grupos da loja e do colaborador (Identificação → Documentos →
    Endereço → Contato → Observações): cadastro do sistema tem UM formato.
    """
    list_display = ("nome", "cidade", "uf", "telefone", "email", "ativo")
    list_filter = ("ativo", "uf")
    search_fields = ("nome", "cnpj", "contato", "cidade", "email")
    ordering = ("nome",)
    # Grupo com UM campo dentro vira cartão vazio: o dono viu o resultado
    # ("ridículo e mal feito") — três cartões grandes, um campo em cada. Campo
    # curto anda em par na mesma linha, e só sobra grupo próprio quando o
    # assunto realmente muda.
    fieldsets = (
        ("Identificação", {"fields": (("nome", "cnpj"), ("contato", "ativo"))}),
        ("Endereço", {"fields": ("endereco", ("cidade", "uf"))}),
        ("Contato", {"fields": (("telefone", "email"),)}),
        ("Observações", {"fields": ("observacoes",)}),
    )


class _RegistroEnvioInline(TabularInline):
    model = RegistroEnvioAutorizada
    extra = 0
    fields = ("texto", "autor", "criado_em")
    readonly_fields = ("autor", "criado_em")


@admin.register(EnvioAutorizada)
class EnvioAutorizadaAdmin(ModelAdmin):
    """Consulta/edição de envios (o fluxo do dia a dia é pelo quadro Kanban)."""
    list_display = ("equipamento_display", "autorizada", "status", "sem_conserto", "criado_em")
    list_filter = ("status", "sem_conserto", "autorizada")
    search_fields = ("equipamento_desc", "patrimonio", "serial", "bitrix_task_id")
    autocomplete_fields = ("autorizada",)
    readonly_fields = ("criado_em", "atualizado_em", "data_finalizado")
    inlines = [_RegistroEnvioInline]
    # Percurso do envio: para quem vai → o que vai → como voltou → os papéis.
    # Os seis anexos ficam juntos, dois por linha, em vez de virarem uma coluna
    # de 24 campos empilhados (era este formulário que o dono chamou de
    # "ridículo e mal feito").
    fieldsets = (
        ("Envio", {
            "description": "O equipamento pode ser um computador OU um notebook "
                           "do parque; para item avulso, deixe os dois vazios e "
                           "descreva abaixo.",
            "fields": (("autorizada", "quantidade"), ("computador", "notebook")),
        }),
        ("Equipamento", {
            "fields": (("equipamento_desc", "patrimonio"), "serial", "problema"),
        }),
        ("Situação", {
            "fields": (("status", "devolutiva"), ("sem_conserto", "valor_reparo")),
        }),
        ("Documentos", {
            "fields": (("os_make", "os_arquivo"),
                       ("orcamento_arquivo", "comprovante_pagamento"),
                       ("autorizacao_arquivo", "foto_recebido"),
                       "autorizacao_texto"),
        }),
        ("Sistema", {
            "fields": (("registrado_por", "bitrix_task_id"),
                       ("criado_em", "atualizado_em"), "data_finalizado"),
        }),
    )

    @display(description="Equipamento")
    def equipamento_display(self, obj):
        return obj.equipamento_display


class _TelemetriaPendenteFilter(admin.SimpleListFilter):
    title = "vínculo"
    parameter_name = "vinculo"

    def lookups(self, request, model_admin):
        return [("pendente", "Pendentes (sem máquina)"), ("ok", "Vinculadas")]

    def queryset(self, request, qs):
        if self.value() == "pendente":
            return qs.filter(computador__isnull=True, notebook__isnull=True)
        if self.value() == "ok":
            return qs.filter(Q(computador__isnull=False) | Q(notebook__isnull=False))
        return qs


@admin.register(TelemetriaMaquina)
class TelemetriaMaquinaAdmin(ModelAdmin):
    """Coletas do agente (score real). Só-leitura, exceto o vínculo com a máquina:
    ao escolher o Computador/Notebook, o SERIAL é atrelado ao patrimônio (a próxima
    coleta casa sozinha)."""
    list_display = ("serial", "hostname", "alvo_col", "local_col", "cpu_modelo", "ram_gb",
                    "ram_tipo", "disco_tipo", "disco_total_gb", "particao", "gpu_col",
                    "uptime_col", "geo_col", "vinculo_col", "visto_em")
    list_filter = (_TelemetriaPendenteFilter, "local_ignorado", "ram_tipo", "disco_tipo",
                   "particao", "gpu_tipo", "geo_pais")
    search_fields = ("serial", "hostname", "cpu_modelo", "so", "gpu", "geo_cidade")
    autocomplete_fields = ("computador", "notebook")
    ordering = ("-visto_em",)
    readonly_fields = ("serial", "mac", "hostname", "so", "cpu_modelo", "cpu_nucleos", "cpu_ghz",
                       "ram_gb", "ram_tipo", "disco_tipo", "disco_total_gb", "disco_livre_gb",
                       "particao", "gpu", "gpu_tipo", "uptime_col", "ip_publico",
                       "geo_col", "geo_lat", "geo_lon", "unidade_detectada",
                       "visto_em", "criado_em", "raw")
    # A única coisa que se FAZ nesta tela é vincular a coleta a um patrimônio —
    # por isso esse grupo é o primeiro. A coleta em si foi partida em "Máquina"
    # (quem é) e "Hardware" (o que tem dentro): eram 18 campos numa coluna só.
    fieldsets = (
        ("Vincular ao patrimônio", {
            "fields": (("computador", "notebook"),),
            "description": "Escolha a máquina correspondente a este nº de série. "
                           "O serial será gravado no cadastro dela para casar automaticamente.",
        }),
        ("Máquina", {"fields": (("serial", "hostname"), ("mac", "so"))}),
        ("Hardware", {"fields": (("cpu_modelo", "cpu_nucleos"),
                                 ("cpu_ghz", "ram_gb"),
                                 ("ram_tipo", "disco_tipo"),
                                 ("disco_total_gb", "disco_livre_gb"),
                                 ("particao", "gpu"),
                                 ("gpu_tipo", "uptime_col"))}),
        ("Localização", {
            "description": "Deduzida pelo IP público. Marque 'ignorar' quando a "
                           "unidade detectada estiver errada de propósito (home office).",
            "fields": (("ip_publico", "geo_col"), ("geo_lat", "geo_lon"),
                       ("unidade_detectada", "local_ignorado")),
        }),
        ("Sistema", {"fields": (("visto_em", "criado_em"), "raw")}),
    )

    def has_add_permission(self, request):
        return False

    @display(description="Máquina")
    def alvo_col(self, obj):
        return obj.alvo

    @display(description="Situação")
    def vinculo_col(self, obj):
        return "⏳ Pendente" if obj.pendente else "Vinculada"

    @display(description="Vídeo")
    def gpu_col(self, obj):
        if not obj.gpu:
            return "—"
        etq = "Dedicada" if obj.gpu_tipo == "dedicada" else "Integrada"
        return f"{etq} · {obj.gpu}"

    @display(description="Tempo ligada")
    def uptime_col(self, obj):
        return obj.uptime_humano or "—"

    @display(description="Localização")
    def geo_col(self, obj):
        return obj.geo_label or "—"

    @display(description="Local")
    def local_col(self, obj):
        if obj.local_divergente:
            cad = obj.unidade_cadastrada
            det = obj.unidade_detectada
            return f"{cad.name if cad else '—'} → {det.name if det else '—'}"
        if obj.local_ignorado:
            return "ignorado"
        return "ok" if obj.unidade_detectada_id else "—"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Atrela o serial ao patrimônio escolhido (próxima coleta casa sozinha).
        serial = (obj.serial or "").strip()
        if obj.computador and (obj.computador.serial or "").lower() != serial.lower():
            obj.computador.serial = serial
            obj.computador.save(update_fields=["serial"])
        if obj.notebook and (obj.notebook.serial or "").lower() != serial.lower():
            obj.notebook.serial = serial
            obj.notebook.save(update_fields=["serial"])
        # Espelha a coleta nos campos tel_* da máquina AGORA (sem esperar a próxima
        # coleta): assim o status de telemetria e o score refletem o vínculo na hora.
        obj.aplicar_na_maquina()


@admin.register(GrupoManutencao)
class GrupoManutencaoAdmin(ModelAdmin):
    list_display = ("nome", "unidade", "total_membros", "criado_por", "criada_em")
    list_filter = ("unidade",)
    search_fields = ("nome",)
    filter_horizontal = ("baias", "notebooks")
    readonly_fields = ("criada_em",)
    # Baias e notebooks ficam sozinhos na linha: o widget de seleção dupla
    # (filter_horizontal) ocupa a largura inteira e não cabe em par.
    fieldsets = (
        ("Identificação", {"fields": (("nome", "unidade"),)}),
        ("Membros", {
            "description": "Máquinas que entram na preventiva deste grupo.",
            "fields": ("baias", "notebooks"),
        }),
        ("Sistema", {"fields": (("criado_por", "criada_em"),)}),
    )


@admin.register(AdiamentoPreventiva)
class AdiamentoPreventivaAdmin(ModelAdmin):
    list_display = ("patrimonio", "status", "nova_data", "solicitante", "decidido_por", "criada_em")
    list_filter = ("status",)
    search_fields = ("justificativa", "baia__computador__patrimonio", "notebook__patrimonio")
    readonly_fields = ("criada_em", "decidido_em", "decidido_por")
    # Quem pede vem antes de quem decide — é a ordem do fluxo, e separa o que
    # o solicitante escreveu do que o responsável respondeu.
    fieldsets = (
        ("Máquina", {
            "description": "O adiamento é de uma mesa (baia) OU de um notebook.",
            "fields": (("baia", "notebook"),),
        }),
        ("Pedido", {"fields": (("solicitante", "nova_data"), "justificativa")}),
        ("Decisão", {"fields": (("status", "motivo"),
                                ("decidido_por", "decidido_em"))}),
        ("Sistema", {"fields": ("criada_em",)}),
    )

    @display(description="patrimônio")
    def patrimonio(self, obj):
        return obj.patrimonio or "—"


@admin.register(Tarefa)
class TarefaAdmin(ModelAdmin):
    """Inspeção da gestão sobre as tarefas de saúde geradas automaticamente."""

    list_display = ("tipo", "patrimonio", "unidade", "status", "responsavel", "criada_em")
    list_filter = ("tipo", "status", "unidade")
    search_fields = (
        "chave", "titulo", "baia__computador__patrimonio",
        "notebook__patrimonio", "baia__computador__serial", "notebook__serial",
    )
    autocomplete_fields = ("baia", "notebook", "unidade", "responsavel")
    readonly_fields = ("chave", "criada_em", "atualizada_em", "fechada_em", "fechada_por")
    list_select_related = ("unidade", "responsavel", "baia__computador", "notebook")
    # A chave e as datas de fechamento são geradas pela rotina de saúde, não
    # digitadas: vão para o grupo Sistema, no fim.
    fieldsets = (
        ("Tarefa", {"fields": (("tipo", "status"), "titulo", "detalhe")}),
        ("Máquina", {
            "description": "A tarefa é de uma mesa (baia) OU de um notebook.",
            "fields": (("baia", "notebook"), ("unidade", "responsavel")),
        }),
        ("Observações", {"fields": ("observacao",)}),
        ("Sistema", {"fields": (("chave", "criada_em"),
                                ("atualizada_em", "fechada_em"), "fechada_por")}),
    )

    @display(description="patrimônio")
    def patrimonio(self, obj):
        return obj.patrimonio or "—"


# ---------------------------------------------------------------------------
# MURAL — moderação
# ---------------------------------------------------------------------------
# O mural já apaga o próprio comentário na tela. Isto aqui é a porta de
# moderação: achar o que alguém escreveu, conferir a foto que subiu e apagar o
# que não devia estar lá. Fora do menu de propósito (o mural é a tela), mas
# alcançável por URL para quem administra.
@admin.register(ComentarioEvento)
class ComentarioEventoAdmin(admin.ModelAdmin):
    list_display = ("criado_em", "autor", "chave", "tipo", "_resumo", "_foto")
    list_filter = ("tipo", "criado_em")
    search_fields = ("chave", "texto", "legenda", "autor__username",
                     "autor__first_name", "autor__last_name")
    date_hierarchy = "criado_em"
    readonly_fields = ("criado_em", "editado_em")
    autocomplete_fields = ("autor",)
    list_select_related = ("autor",)

    @admin.display(description="texto")
    def _resumo(self, obj):
        t = (obj.texto or "").strip().replace("\n", " ")
        return (t[:70] + "…") if len(t) > 70 else (t or "—")

    @admin.display(description="foto", boolean=True)
    def _foto(self, obj):
        return bool(obj.foto)


@admin.register(MarcaEvento)
class MarcaEventoAdmin(admin.ModelAdmin):
    list_display = ("em", "usuario", "marca", "chave", "tipo")
    list_filter = ("marca", "tipo")
    search_fields = ("chave", "usuario__username", "usuario__first_name",
                     "usuario__last_name")
    autocomplete_fields = ("usuario",)
    list_select_related = ("usuario",)
