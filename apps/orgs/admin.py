from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import F
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from unfold.admin import StackedInline
from unfold.forms import UserChangeForm, UserCreationForm

from apps.admin_base import MakeModelAdmin as ModelAdmin

from .forms import CadastroComMascaraForm, SenhaComAntigaForm
from .models import (
    MINUTOS_ONLINE, Department, LogAcesso, Location, PerfilUsuario, Person,
    UsuarioOnline,
)

# Quem pode VER os logs do sistema.
GRUPOS_LOG = ["Gerente", "Supervisor"]


def _pode_ver_log(user):
    return bool(user and user.is_active and (
        user.is_superuser or user.groups.filter(name__in=GRUPOS_LOG).exists()
    ))


class _LogReadOnlyAdmin(ModelAdmin):
    """Base só-leitura e restrita (Gerente/Supervisor/superuser) para logs."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return _pode_ver_log(request.user)

    def has_module_permission(self, request):
        return _pode_ver_log(request.user)


@admin.register(Location)
class LocationAdmin(ModelAdmin):
    # Aceita CNPJ/CPF/telefone/CEP com pontuação (ver o form).
    form = CadastroComMascaraForm
    """Cadastro de loja/unidade.

    Formato dos grupos: Identificação → Documentos → Endereço → Contato →
    Observações. É o mesmo desenho pedido para TODO cadastro do sistema, para
    a pessoa não ter de reaprender a tela a cada assunto.
    """

    list_display = ("name", "codigo", "tipo", "city", "state", "cnpj_fmt", "telefone_fmt", "ativo")
    list_filter = ("tipo", "ativo", "state", "city")
    search_fields = ("name", "razao_social", "cnpj", "city", "codigo")
    exclude = ("parent",)
    # Campo curto anda em PAR na mesma linha. Grupo com um campo só vira
    # cartão vazio — foi o que o dono viu no cadastro de autorizada.
    fieldsets = (
        ("Identificação", {"fields": (("name", "razao_social"), ("codigo", "tipo"), ("cnpj", "telefone"), "ativo")}),
        ("Endereço", {"fields": ("address", ("numero", "bairro"), ("city", "state"), "cep")}),
        ("Observações", {"fields": ("notes",)}),
    )

    @admin.display(description="CNPJ", ordering="cnpj")
    def cnpj_fmt(self, obj):
        d = obj.cnpj or ""
        if len(d) != 14:
            return "—"
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"

    @admin.display(description="telefone", ordering="telefone")
    def telefone_fmt(self, obj):
        d = obj.telefone or ""
        if len(d) == 11:
            return f"({d[:2]}) {d[2:7]}-{d[7:]}"
        if len(d) == 10:
            return f"({d[:2]}) {d[2:6]}-{d[6:]}"
        return "—"


@admin.register(Department)
class DepartmentAdmin(ModelAdmin):
    list_display = ("name", "location", "manager")
    list_filter = ("location",)
    search_fields = ("name",)
    autocomplete_fields = ("location", "manager")
    fieldsets = (
        ("Identificação", {"fields": ("name",)}),
        ("Vínculo", {"fields": (("location", "manager"),)}),
    )


@admin.register(Person)
class PersonAdmin(ModelAdmin):
    # Aceita CNPJ/CPF/telefone/CEP com pontuação (ver o form).
    form = CadastroComMascaraForm
    """Cadastro de colaborador, nos mesmos grupos da loja."""

    list_display = ("full_name", "cpf_fmt", "email", "department", "location", "conta_acesso", "active")
    list_filter = ("active", "sexo", "department", "location")
    search_fields = ("full_name", "email", "employee_no", "cpf", "user__username")
    autocomplete_fields = ("department", "location", "user")
    readonly_fields = ("equipamentos_em_uso",)
    fieldsets = (
        ("Identificação", {"fields": (("full_name", "cpf"), ("sexo", "employee_no"), "foto")}),
        ("Vínculo", {"fields": (("job_title", "department"), ("location", "user"))}),
        ("Contato", {"fields": (("email", "telefone"),)}),
        ("Equipamentos em uso", {
            "description": "O que está com esta pessoa hoje. Vem da baia que ela "
                           "ocupa — para mudar, mexa na baia, não aqui.",
            "fields": ("equipamentos_em_uso",),
        }),
        ("Situação", {"fields": (("active", "data_desligamento"),)}),
    )

    @admin.display(description="Equipamentos")
    def equipamentos_em_uso(self, obj):
        """O outro lado da regra: a ficha do computador diz quem usa, e a ficha
        da pessoa tem de dizer o que ela usa. Sem isto, responder "o que o Fulano
        tem?" obriga a abrir o parque inteiro e procurar.

        Links, não texto: é daqui que se chega ao equipamento para mexer nele.
        """
        if not obj or not obj.pk:
            return "Salve o colaborador para ver os equipamentos."

        linhas = []
        for pc in obj.computadores.all():
            linhas.append(("parque_computador", pc.pk, f"Computador {pc.patrimonio}"))
        for nb in obj.notebooks.all():
            linhas.append(("parque_notebook", nb.pk, f"Notebook {nb.patrimonio or nb.serial or nb.pk}"))
        for baia in obj.baias_ocupadas.select_related("setor", "setor__unidade"):
            rotulo = f"Baia {baia.nome} — {baia.setor.unidade.name} › {baia.setor.nome}"
            linhas.append(("parque_baia", baia.pk, rotulo))

        if not linhas:
            return "Nenhum equipamento vinculado."

        return format_html_join(
            mark_safe("<br>"),
            '<a href="{}">{}</a>',
            ((reverse(f"admin:{rota}_change", args=[pk]), texto)
             for rota, pk, texto in linhas),
        )

    @admin.display(description="CPF", ordering="cpf")
    def cpf_fmt(self, obj):
        d = obj.cpf or ""
        if len(d) != 11:
            return "—"
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"

    @admin.display(description="conta de acesso", ordering="user__username")
    def conta_acesso(self, obj):
        return obj.user.get_username() if obj.user_id else "—"


# --- Telas de Usuários e Grupos com o mesmo tema (unfold) ---
admin.site.unregister(User)
admin.site.unregister(Group)


class SoSuperusuarioAdmin:
    """Não-superusuário não vê 403: é redirecionado ao dashboard com um aviso
    (toast "Acesso negado" via ?negado=usuarios, exibido pelo make-admin.js)."""

    def _negar(self, request):
        return redirect(reverse("admin:index") + "?negado=usuarios")

    def changelist_view(self, request, extra_context=None):
        if not request.user.is_superuser:
            return self._negar(request)
        return super().changelist_view(request, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        if not request.user.is_superuser:
            return self._negar(request)
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if not request.user.is_superuser:
            return self._negar(request)
        return super().change_view(request, object_id, form_url, extra_context)

    def history_view(self, request, object_id, extra_context=None):
        if not request.user.is_superuser:
            return self._negar(request)
        return super().history_view(request, object_id, extra_context)


class PerfilUsuarioInline(StackedInline):
    """Vínculo do usuário com a loja (visão unificada) e a baia/máquina (patrimônio)."""
    model = PerfilUsuario
    can_delete = False
    extra = 0
    fields = ("unidade", "baia")
    autocomplete_fields = ("baia",)
    verbose_name_plural = "Loja e baia / máquina do usuário"


@admin.register(User)
class UserAdmin(SoSuperusuarioAdmin, BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = SenhaComAntigaForm
    inlines = (PerfilUsuarioInline,)
    # Não expõe o filtro de "superusuário" na lista (status fica oculto);
    # a opção de marcar superusuário continua no formulário (fieldsets abaixo).
    list_filter = ("is_active", "is_staff", "groups")

    # Remove o hash da senha e a lista de permissões individuais.
    # As permissões vêm do CARGO (grupo). A senha é trocada por um botão.
    #
    # `senha_acao` fica sozinho na linha de propósito: é botão + aviso de texto
    # longo, não campo curto. `groups` também, porque o widget de seleção
    # dupla (filter_horizontal) ocupa a largura inteira.
    fieldsets = (
        ("Identificação", {
            "fields": (("first_name", "last_name"), ("username", "email"),
                       "senha_acao"),
        }),
        ("Cargo e acesso", {
            "fields": (("is_active", "is_staff"), "is_superuser", "groups"),
            "description": "As permissões são definidas pelo cargo (grupo). "
                           "Marque 'Membro da equipe' para liberar o acesso ao painel.",
        }),
        ("Sistema", {"fields": (("last_login", "date_joined"),)}),
    )
    # Cadastro NOVO: já pede nome, e-mail e cargo (o e-mail vai para o
    # Colaborador criado automaticamente pelo signal).
    add_fieldsets = (
        ("Identificação", {
            "classes": ("wide",),
            "fields": (("first_name", "last_name"), ("username", "email")),
        }),
        ("Senha", {
            "description": "A senha só aparece aqui, no cadastro. Depois de "
                           "salvo, ela é trocada por um botão de redefinir.",
            "fields": (("password1", "password2"),),
        }),
        ("Cargo e acesso", {
            "fields": (("is_staff", "is_superuser"), "groups"),
            "description": "Marque 'Membro da equipe' (ou escolha um cargo) para "
                           "liberar o acesso e criar o cadastro de colaborador.",
        }),
    )
    readonly_fields = ("senha_acao", "last_login", "date_joined")
    actions = ("gerar_senha_temporaria",)

    @admin.display(description="Senha")
    def senha_acao(self, obj):
        if obj and obj.pk:
            url = reverse("admin:auth_user_password_change", args=[obj.pk])
            aviso = ""
            if not (obj.email or "").strip():
                # Sem e-mail o "Esqueci a senha" não tem para onde enviar: o
                # usuário pediria a recuperação e nunca receberia nada.
                aviso = (
                    '<div class="make-pass-hint" style="color:#b4501f;font-weight:600">'
                    "Sem e-mail cadastrado: este usuário não consegue usar "
                    "“Esqueceu sua senha?”. Preencha o e-mail acima ou use a ação "
                    "“Gerar senha temporária” na lista de usuários.</div>"
                )
            return format_html(
                '<a class="make-pass-btn" href="{}">Alterar a senha</a>'
                '<div class="make-pass-hint">A senha é guardada de forma '
                "criptografada e não pode ser exibida.</div>{}",
                url, mark_safe(aviso),
            )
        return format_html(
            '<span class="make-pass-hint">A senha será definida no cadastro.</span>'
        )

    @admin.action(description="Gerar senha temporária (entregar ao usuário)")
    def gerar_senha_temporaria(self, request, queryset):
        """Atalho da TI para desbloquear quem não tem e-mail cadastrado.

        Gera a senha, liga a obrigação de trocá-la no próximo acesso e MOSTRA a
        senha aqui — para a TI entregar pessoalmente. Nada é enviado por e-mail.
        """
        from .views import gerar_senha_temporaria as _nova_senha

        geradas = []
        for usuario in queryset:
            senha = _nova_senha()
            usuario.set_password(senha)
            usuario.save(update_fields=["password"])
            PerfilUsuario.objects.update_or_create(
                usuario=usuario,
                defaults={"senha_temporaria": True, "senha_temporaria_em": timezone.now()},
            )
            LogAcesso.objects.create(
                usuario=usuario, evento=LogAcesso.Evento.RECUPERACAO,
                ip=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            )
            geradas.append((usuario.get_username(), senha))

        if not geradas:
            return
        linhas = " · ".join(f"{u}: {s}" for u, s in geradas)
        self.message_user(
            request,
            format_html(
                "Senha temporária gerada para {} usuário(s). Anote agora — "
                "não será exibida de novo: <strong>{}</strong>. "
                "O usuário definirá a senha definitiva no próximo acesso.",
                len(geradas), linhas,
            ),
        )


@admin.register(Group)
class GroupAdmin(SoSuperusuarioAdmin, BaseGroupAdmin, ModelAdmin):
    # Cargo = nome + o que ele pode fazer. As permissões ficam em grupo próprio
    # porque o widget de seleção dupla ocupa a largura inteira da tela.
    fieldsets = (
        ("Identificação", {"fields": ("name",)}),
        ("Permissões do cargo", {
            "description": "Valem para todos os usuários deste cargo.",
            "fields": ("permissions",),
        }),
    )


# --- LOGS DO SISTEMA (só-leitura, restritos a Gerente/Supervisor) ---
_ACOES_LOG = {1: "Adição", 2: "Alteração", 3: "Exclusão"}


@admin.register(LogEntry)
class LogEntryAdmin(_LogReadOnlyAdmin):
    """Log de ações no sistema (criação/alteração/exclusão de registros)."""

    list_display = ("action_time", "user", "content_type", "object_repr", "acao")
    list_filter = ("action_flag", "content_type", "user")
    search_fields = ("object_repr", "change_message", "user__username")
    date_hierarchy = "action_time"
    list_select_related = ("user", "content_type")

    @admin.display(description="ação")
    def acao(self, obj):
        return _ACOES_LOG.get(obj.action_flag, "—")


@admin.register(LogAcesso)
class LogAcessoAdmin(_LogReadOnlyAdmin):
    """Log de acessos (login, logout e falhas) com data/hora e IP."""

    list_display = ("em", "evento", "usuario", "username_tentado", "ip")
    list_filter = ("evento", "em")
    search_fields = ("usuario__username", "username_tentado", "ip")
    date_hierarchy = "em"
    list_select_related = ("usuario",)


# --- USUÁRIOS ONLINE (painel só-leitura, restrito a Gerente/Supervisor) ---
def _humaniza_minutos(dt):
    """'agora', 'há 3 min', 'há 2 h', 'há 5 dias' a partir de um datetime."""
    if not dt:
        return "—"
    delta = timezone.now() - dt
    seg = int(delta.total_seconds())
    if seg < 60:
        return "agora mesmo"
    minutos = seg // 60
    if minutos < 60:
        return f"há {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"há {horas} h"
    dias = horas // 24
    return f"há {dias} dia{'s' if dias > 1 else ''}"


@admin.register(UsuarioOnline)
class UsuarioOnlineAdmin(_LogReadOnlyAdmin):
    """Quem está online agora (atividade nos últimos minutos) e quem não está."""

    list_display = ("status", "username", "nome", "cargo", "ultima_atividade", "patrimonio")
    search_fields = ("username", "first_name", "last_name")

    def get_queryset(self, request):
        qs = (
            super().get_queryset(request)
            .select_related("atividade", "perfil__baia__computador")
            .prefetch_related("groups")
        )
        # Online primeiro; depois por atividade mais recente (sem atividade ao fim).
        return qs.order_by(F("atividade__visto_em").desc(nulls_last=True))

    @admin.display(description="situação")
    def status(self, obj):
        ativ = getattr(obj, "atividade", None)
        online = bool(ativ and ativ.online)
        cor = "#00a651" if online else "#9ca3af"
        texto = "Online" if online else "Offline"
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:6px;font-weight:600">'
            '<span style="width:9px;height:9px;border-radius:50%;background:{}"></span>{}'
            "</span>",
            cor, texto,
        )

    @admin.display(description="nome")
    def nome(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description="cargo")
    def cargo(self, obj):
        # Exibe o CARGO (grupo); o status de superusuário não é revelado aqui.
        return ", ".join(g.name for g in obj.groups.all()) or "—"

    @admin.display(description="última atividade")
    def ultima_atividade(self, obj):
        ativ = getattr(obj, "atividade", None)
        return _humaniza_minutos(ativ.visto_em if ativ else None)

    @admin.display(description="patrimônio")
    def patrimonio(self, obj):
        perfil = getattr(obj, "perfil", None)
        pat = perfil.patrimonio if perfil else ""
        return pat or "—"
