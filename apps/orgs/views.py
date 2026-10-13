"""Recuperação de senha por e-mail (fluxo de SENHA TEMPORÁRIA).

Em vez de um link de redefinição, o usuário recebe por e-mail uma senha
temporária aleatória. Ele entra com ela e o sistema o obriga a definir uma
nova senha logo após o login (ver TrocaSenhaObrigatoriaMiddleware).

Proteções: a senha temporária expira (SENHA_TEMP_VALIDADE_HORAS) e os pedidos
são limitados por identificador/IP (SENHA_TEMP_MAX_PEDIDOS na janela). O e-mail
é enviado ANTES de invalidar a senha atual — se o envio falhar, nada muda.

A tela aceita **usuário OU e-mail** (igual ao login): quem não decora o e-mail
cadastrado consegue pedir a recuperação pelo nome de usuário, e o envio vai
sempre para o e-mail DA CONTA (nunca para o que foi digitado, se for outro).
"""

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST

from .models import LogAcesso, Person, PerfilUsuario

# Alfabeto sem caracteres ambíguos (0/O, 1/l/I) para a senha temporária ser
# fácil de digitar a partir do e-mail.
_ALFABETO_SENHA = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def gerar_senha_temporaria(tamanho=10):
    """Gera uma senha aleatória legível (sem caracteres ambíguos)."""
    return get_random_string(tamanho, _ALFABETO_SENHA)


def _ip(request):
    """IP de origem do pedido, para o registro em LogAcesso.

    Atrás do túnel (Cloudflare/ngrok) o REMOTE_ADDR é o loopback do próprio
    servidor; nesse caso o IP real vem no cabeçalho do proxy. Como cabeçalho é
    forjável, isso só é usado quando `SENHA_TEMP_CONFIA_NO_PROXY` estiver
    ligado (o `tunnel.py` liga) — e **nunca** entra na chave do rate limit.
    """
    if not request:
        return None
    direto = request.META.get("REMOTE_ADDR")
    if direto not in ("127.0.0.1", "::1", None, ""):
        return direto
    if not getattr(settings, "SENHA_TEMP_CONFIA_NO_PROXY", False):
        return direto
    encaminhado = (
        request.META.get("HTTP_CF_CONNECTING_IP")
        or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
    ).strip()
    return encaminhado or direto


def _ua(request):
    return (request.META.get("HTTP_USER_AGENT", "")[:300]) if request else ""


def _validade_horas():
    return getattr(settings, "SENHA_TEMP_VALIDADE_HORAS", 24)


class RecuperarSenhaForm(forms.Form):
    """Aceita o usuário OU o e-mail corporativo (mesmo campo do login)."""

    identificador = forms.CharField(
        label="Usuário ou e-mail",
        max_length=254,
        strip=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Usuário ou e-mail corporativo",
            "autocomplete": "username",
            "autofocus": True,
        }),
        error_messages={"required": "Informe seu usuário ou o e-mail corporativo."},
    )


def _excedeu_limite(request, identificador):
    """Conta pedidos na janela e diz se estourou o limite.

    A chave é o **identificador** digitado, não o IP: atrás do túnel o IP vem
    de cabeçalho (forjável), e variá-lo a cada pedido zerava o contador. Pelo
    identificador o teto vale de verdade — é a conta que precisa de proteção
    contra enxurrada de e-mail e contra troca de senha em série.
    """
    maximo = getattr(settings, "SENHA_TEMP_MAX_PEDIDOS", 3)
    janela = getattr(settings, "SENHA_TEMP_JANELA_MINUTOS", 15) * 60
    chave = "recup:id:{}".format(identificador.lower())
    atual = cache.get(chave, 0)
    if atual >= maximo:
        return True
    # incr só funciona com chave existente; garante o valor inicial primeiro.
    if atual == 0:
        cache.set(chave, 1, timeout=janela)
    else:
        try:
            cache.incr(chave)
        except ValueError:
            cache.set(chave, atual + 1, timeout=janela)
    return False


def _contas_do_identificador(identificador):
    """Contas ativas que casam com o usuário OU o e-mail digitado.

    Só devolve contas COM e-mail cadastrado — sem e-mail não há para onde
    enviar (a tela de "enviado" explica esse caso sem revelar nada).
    """
    return (
        User.objects.filter(is_active=True)
        .filter(Q(username__iexact=identificador) | Q(email__iexact=identificador))
        .exclude(email="")
    )


def recuperar_senha(request):
    """Recebe usuário/e-mail, gera uma senha temporária e a envia por e-mail.

    Por segurança (evitar enumeração de contas), sempre redireciona para a tela
    de "enviado", exista ou não uma conta com aquele identificador.
    """
    if request.method == "POST":
        form = RecuperarSenhaForm(request.POST)
        if form.is_valid():
            identificador = form.cleaned_data["identificador"]
            # Limite atingido: não revela nada, segue para a tela de "enviado".
            if _excedeu_limite(request, identificador):
                return redirect("password_reset_done")

            falhou = False
            for usuario in _contas_do_identificador(identificador):
                if not _emitir_senha_temporaria(request, usuario, usuario.email):
                    falhou = True
            if falhou:
                messages.error(
                    request,
                    "Não foi possível enviar o e-mail agora. Tente novamente em "
                    "alguns minutos ou procure a TI.",
                )
                return render(request, "registration/password_reset_form.html", {"form": form})
            return redirect("password_reset_done")
    else:
        form = RecuperarSenhaForm()

    return render(request, "registration/password_reset_form.html", {"form": form})


def _emitir_senha_temporaria(request, usuario, email):
    """Envia a senha temporária por e-mail e SÓ ENTÃO invalida a senha atual.

    Retorna True em caso de sucesso, False se o envio do e-mail falhar (nesse
    caso a senha do usuário permanece intacta)."""
    senha = gerar_senha_temporaria()
    horas = _validade_horas()
    contexto = {
        "usuario": usuario.get_username(),
        "nome": usuario.get_short_name() or usuario.get_username(),
        "senha": senha,
        "validade_horas": horas,
        "expira_em": timezone.localtime(timezone.now() + timezone.timedelta(hours=horas)),
        "login_url": request.build_absolute_uri(str(reverse_lazy("admin:login"))),
    }
    corpo = render(request, "registration/password_reset_email.html", contexto).content.decode()

    try:
        send_mail(
            subject="Sua senha temporária — Patrimap",
            message=corpo,
            from_email=None,  # usa DEFAULT_FROM_EMAIL
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        # Envio falhou: não troca a senha (o usuário ficaria sem acesso).
        return False

    usuario.set_password(senha)
    usuario.save(update_fields=["password"])
    PerfilUsuario.objects.update_or_create(
        usuario=usuario,
        defaults={"senha_temporaria": True, "senha_temporaria_em": timezone.now()},
    )
    LogAcesso.objects.create(
        usuario=usuario, evento=LogAcesso.Evento.RECUPERACAO,
        ip=_ip(request), user_agent=_ua(request),
    )
    return True


class TrocarSenhaView(PasswordChangeView):
    """Tela de definição de nova senha.

    Quem chegou aqui com **senha temporária** não repete a senha antiga (acabou
    de entrar com ela e vai substituí-la). Qualquer outro usuário que abrir esta
    URL **precisa informar a senha atual** — senão uma sessão esquecida aberta
    permitiria trocar a senha da conta sem conhecê-la.
    """

    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("admin:index")

    def _com_senha_temporaria(self):
        perfil = getattr(self.request.user, "perfil", None)
        return bool(perfil and perfil.senha_temporaria)

    def get_form_class(self):
        return SetPasswordForm if self._com_senha_temporaria() else PasswordChangeForm

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["senha_temporaria"] = self._com_senha_temporaria()
        contexto["validade_horas"] = _validade_horas()
        return contexto

    def form_valid(self, form):
        usuario = form.save()
        update_session_auth_hash(self.request, usuario)
        PerfilUsuario.objects.filter(usuario=usuario).update(
            senha_temporaria=False, senha_temporaria_em=None,
        )
        # Tira da fila o aviso "defina uma nova senha" (senão ele reaparece).
        self.request.session.pop("_aviso_senha_temp", None)
        LogAcesso.objects.create(
            usuario=usuario, evento=LogAcesso.Evento.TROCA_SENHA,
            ip=_ip(self.request), user_agent=_ua(self.request),
        )
        messages.success(self.request, "Senha alterada com sucesso! Bem-vindo(a) ao sistema.")
        return redirect(self.get_success_url())


# ---------------------------------------------------------------------------
# REDEFINIR A SENHA DE OUTRA PESSOA, a partir da ficha de Cadastros
# ---------------------------------------------------------------------------
#
# Por que gerar uma senha temporária em vez de deixar a TI digitar uma:
#
# O formulário do admin (`SenhaComAntigaForm`) exige a senha ATUAL de propósito
# — proteção contra quem encontra uma sessão aberta. Isso deixa de fora o caso
# mais comum de todos: a pessoa esqueceu e precisa voltar a trabalhar. Atender
# esse caso digitando uma senha nova significaria a TI conhecer a senha de
# outra pessoa, que é justamente o que a regra evita.
#
# A saída já existia no projeto, como ação em lote do admin de usuários
# ("Gerar senha temporária"). Aqui ela é a MESMA operação, alcançável de onde o
# problema aparece. A senha é aleatória, aparece uma vez para ser entregue, e o
# middleware obriga a troca no próximo acesso — então ninguém, nem a TI, fica
# sabendo a senha definitiva.
@require_POST
def redefinir_senha_colaborador(request, pk):
    """Gera senha temporária para a conta ligada a um colaborador."""
    if not request.user.is_authenticated or not request.user.has_perm("auth.change_user"):
        raise PermissionDenied()

    pessoa = get_object_or_404(Person.objects.select_related("user"), pk=pk)
    usuario = pessoa.user
    if usuario is None:
        return JsonResponse(
            {"ok": False, "erro": "Este colaborador não tem conta de acesso vinculada."},
            status=400,
        )
    if not usuario.is_active:
        return JsonResponse(
            {"ok": False, "erro": "A conta deste colaborador está inativa."},
            status=400,
        )

    senha = gerar_senha_temporaria()
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
    return JsonResponse({
        "ok": True,
        "usuario": usuario.get_username(),
        "senha": senha,
        "nome": pessoa.full_name,
    })
