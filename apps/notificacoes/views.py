"""Endpoints do sino: marcar uma como lida (e ir ao link) ou marcar todas."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import Notificacao


@login_required
def abrir(request, pk):
    """Marca a notificação como lida e redireciona ao seu link (ou ao admin)."""
    notif = get_object_or_404(Notificacao, pk=pk, destinatario=request.user)
    if not notif.lida:
        notif.lida = True
        notif.save(update_fields=["lida"])
    return redirect(notif.url or "/admin/")


@login_required
@require_POST
def marcar_todas(request):
    """Marca todas as não lidas como lidas — exceto as FIXAS (aprovar/negar),
    que só saem quando resolvidas."""
    n = (Notificacao.objects
         .filter(destinatario=request.user, lida=False, fixa=False)
         .update(lida=True))
    return JsonResponse({"ok": True, "marcadas": n})


@login_required
@require_POST
def excluir(request, pk):
    """Exclui UMA notificação do usuário (não permite excluir as FIXAS, que
    dependem de aprovar/negar)."""
    Notificacao.objects.filter(pk=pk, destinatario=request.user, fixa=False).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def limpar(request):
    """Limpa TODAS as notificações do usuário — exceto as FIXAS (aprovar/negar)."""
    n, _ = (Notificacao.objects
            .filter(destinatario=request.user, fixa=False)
            .delete())
    return JsonResponse({"ok": True, "removidas": n})
