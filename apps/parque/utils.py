"""Utilitários compartilhados do app parque.

Nasceu para acabar com o open redirect: `redirect(request.META["HTTP_REFERER"])`
aparecia em 11 pontos sem nenhuma validação, e o `Referer` é controlado por quem
manda o link. A validação certa já existia no projeto (`config/urls.py`) — aqui
ela vira função única, usada por todo mundo.
"""

import logging

from django.shortcuts import resolve_url
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


def destino_seguro(request, *candidatos, padrao="/admin/"):
    """Primeira URL da lista que aponta para ESTE site; senão, `padrao`.

    Aceita None/"" entre os candidatos (fica fácil passar
    `request.POST.get("next"), request.META.get("HTTP_REFERER")` direto).

    >>> destino_seguro(request, request.POST.get("next"), padrao="/parque/")
    """
    hosts = {request.get_host()}
    for url in candidatos:
        if not url:
            continue
        if url_has_allowed_host_and_scheme(
            url, allowed_hosts=hosts, require_https=request.is_secure()
        ):
            return url
        logger.warning(
            "Redirecionamento externo bloqueado: %r (host permitido: %s)",
            url[:200], request.get_host(),
        )
    return resolve_url(padrao)


def voltar_para(request, padrao="/admin/"):
    """Destino do 'voltar' de uma ação: `next` do POST, senão o Referer."""
    return destino_seguro(
        request,
        request.POST.get("next") or request.GET.get("next"),
        request.META.get("HTTP_REFERER"),
        padrao=padrao,
    )


# Maior inteiro que o SQLite aceita (8 bytes com sinal). Acima disso, a consulta
# nem chega ao banco: o driver estoura com OverflowError.
LIMITE_ID = 9223372036854775807


def id_ou_nada(valor):
    """Converte um id que veio de fora (querystring, formulário) em int.

    Devolve None quando não dá — texto, vazio, negativo, ou grande demais para
    o banco. Sem isto, `filter(pk="abc")` estoura ValueError e a pessoa que
    digitou errado leva um 500 na cara.

    A varredura do usuário leigo achou quatro rotas assim; este helper existe
    para que a quinta não apareça.
    """
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    if n <= 0 or n > LIMITE_ID:
        return None
    return n
