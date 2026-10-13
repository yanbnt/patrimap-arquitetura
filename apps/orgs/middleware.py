"""
Middlewares do app orgs:
  - AtividadeUsuarioMiddleware: presença ("Usuários online").
  - TrocaSenhaObrigatoriaMiddleware: obriga a definir nova senha quando o usuário
    entrou com uma senha temporária (recuperação por e-mail).
"""


from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

# Grava a atividade no banco no máximo uma vez a cada N segundos por usuário.
INTERVALO_SEGUNDOS = 60
_SESSAO_KEY = "_atividade_em"


class AtividadeUsuarioMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._registrar(request)
        return self.get_response(request)

    def _registrar(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return

        agora = timezone.now()
        ultimo = request.session.get(_SESSAO_KEY)
        if ultimo and (agora.timestamp() - ultimo) < INTERVALO_SEGUNDOS:
            return  # ainda dentro da janela — evita escrita no banco

        # Import tardio: evita acessar o app antes do registry estar pronto.
        from .models import AtividadeUsuario

        AtividadeUsuario.objects.update_or_create(
            usuario=user,
            defaults={"visto_em": agora, "ip": request.META.get("REMOTE_ADDR")},
        )
        request.session[_SESSAO_KEY] = agora.timestamp()


class TrocaSenhaObrigatoriaMiddleware:
    """Enquanto o usuário tiver `perfil.senha_temporaria` ligado, qualquer página
    redireciona para a tela de definir nova senha — exceto a própria tela de troca,
    o logout e os arquivos estáticos/mídia."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._precisa_trocar(request):
            # Sem toast aqui de propósito: a própria tela de troca explica o
            # motivo no título e no texto de apoio. Enfileirar mensagem a cada
            # requisição bloqueada empilhava avisos repetidos, que só apareciam
            # (todos de uma vez) na tela seguinte à troca.
            return redirect("trocar_senha")
        return self.get_response(request)

    def _precisa_trocar(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        # Não atrapalha: a própria troca, sair do sistema e estáticos/mídia.
        caminho = request.path
        liberados = (
            reverse("trocar_senha"),
            reverse("admin:logout"),
        )
        if caminho in liberados or caminho.startswith(("/static/", "/media/")):
            return False

        perfil = getattr(user, "perfil", None)
        return bool(perfil and perfil.senha_temporaria)
