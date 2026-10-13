"""Navegação: `voltar_url`/`voltar_nome` para o botão "← {tela}".

Regra: a tela inicial do sistema é a **Início**. Telas abertas por um item do
MENU voltam para a Início (padrão abaixo). Telas abertas a partir de outra tela
(drill-down) definem o próprio pai na view (helper `_voltar`)."""

import logging
from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError

logger = logging.getLogger(__name__)

# path (sem barra final) → nome amigável da tela.
NOMES = {
    "/admin": "Início",
    "/dashboard": "Dashboard",
    "/ajuda": "Ajuda",
    "/parque/estoque": "Estoque",
    "/parque/mapa-completo": "Mapa de computadores",
    "/parque/mapa-notebooks": "Notebooks",
    "/parque/mapa-score": "Análise por score",
    "/parque/tabela-computadores": "Computadores",
    "/parque/tabela-notebooks": "Notebooks",
    "/parque/tabela-pecas": "Periféricos",
    "/parque/tabela-estoque-computadores": "Estoque de computadores",
    "/parque/transferencias": "Transferências",
    "/parque/autorizadas": "Assistência externa",
    "/parque/aprovacoes": "Aprovações",
    "/parque/montar-caixa": "Montar caixa",
}


def nome_tela(url):
    """Nome amigável de uma URL/path (ou None se desconhecida)."""
    from urllib.parse import urlparse
    p = urlparse(url).path.rstrip("/") if url else ""
    return NOMES.get(p)


def _maquina_do_usuario(user):
    """Computador da máquina do usuário (via colaborador→baia ou perfil.baia)."""
    from .models import Baia
    person = getattr(user, "colaborador", None)
    baia = None
    if person is not None:
        baia = (Baia.objects.filter(colaborador=person, computador__isnull=False)
                .select_related("computador").first())
    if baia is None:
        perfil = getattr(user, "perfil", None)
        if perfil is not None and perfil.baia_id:
            baia = (Baia.objects.filter(pk=perfil.baia_id, computador__isnull=False)
                    .select_related("computador").first())
    return baia.computador if (baia and baia.computador_id) else None


def navegacao(request):
    ctx = {"voltar_url": "/admin/", "voltar_nome": "Início"}
    # Aviso "agente de coleta não detectado" — só quando o recurso está ligado
    # (TELEMETRIA_TOKEN definido) e a máquina do usuário não envia há > 2h.
    try:
        from django.conf import settings
        from django.utils import timezone

        user = getattr(request, "user", None)
        if (user and user.is_authenticated
                and (getattr(settings, "TELEMETRIA_TOKEN", "") or "").strip()):
            comp = _maquina_do_usuario(user)
            if comp is not None:
                limite = timezone.now() - timedelta(hours=2)
                if comp.tel_visto_em is None or comp.tel_visto_em < limite:
                    ctx["agente_aviso"] = True
                    ctx["agente_baixar_url"] = "/parque/agente/"
    except (DatabaseError, ObjectDoesNotExist, AttributeError):
        # Nunca quebra o render por causa do aviso — mas agora deixa rastro:
        # antes, qualquer falha aqui sumia sem nenhum sinal (auditoria 1.9).
        logger.exception("Falha ao montar o aviso do agente de telemetria.")
    return ctx

# --- UNIDADES no pé da gaveta (protótipo aprovado em 04/09/2026) -------------
# O dono: "as lojas ali na parte de baixo pra explodir a visão de cada uma
# individual depois". Cada linha leva ao mapa DAQUELA loja, que é a visão
# individual que já existe (`parque_mapa`, por unidade).
#
# A cor do ponto vem do índice na lista, não do banco: é só para distinguir uma
# loja da outra no menu, e um campo de cor no cadastro seria pedir manutenção
# para um enfeite.
_CORES_UNIDADE = [
    "var(--md-st-ok)", "var(--md-st-attn)", "var(--md-primary)",
    "var(--md-st-warn)", "var(--md-st-crit)",
]


def unidades_menu(request):
    """Lojas com contagem de baias, para o pé da gaveta."""
    u = getattr(request, "user", None)
    if not (u and u.is_authenticated and u.is_staff):
        return {}
    from django.db.models import Count
    from django.urls import reverse
    from apps.orgs.models import Location
    try:
        qs = (Location.objects
              .filter(setores__isnull=False)
              .annotate(n_baias=Count("setores__baias", distinct=True))
              .order_by("name")
              .distinct())
        itens = []
        for i, loc in enumerate(qs):
            try:
                url = reverse("parque_mapa", args=[loc.pk])
            except Exception:
                url = "/parque/mapa-completo/"
            itens.append({
                "nome": loc.name,
                "baias": loc.n_baias,
                "cor": _CORES_UNIDADE[i % len(_CORES_UNIDADE)],
                "url": url,
            })
    except Exception:
        # Menu não pode derrubar página: sem dado, o bloco só não aparece.
        return {}
    return {"unidades_menu": itens}
