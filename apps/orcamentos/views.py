"""Tela custom de Orçamentos — lista com aprovação direto na tela (estilo do
restante do sistema), no lugar do changelist do admin."""

from django.contrib import admin as dj_admin
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.parque.utils import voltar_para
# O contexto da barra de filtro do sistema mora junto do parcial que a desenha
# (`templates/parque/_filtros.html`), em apps/parque/views.py. Importar daqui é
# o que faz Orçamentos ganhar o MESMO botão "Filtrar" das telas do parque, em
# vez de mais uma barra própria.
from apps.parque.views import barra_filtros

from .models import Orcamento

GESTAO = ["Gerente", "Supervisor"]


def _pode_decidir(user):
    return bool(
        user and user.is_authenticated and (
            user.is_superuser or user.groups.filter(name__in=GESTAO).exists()
        )
    )


@staff_member_required
def orcamentos_lista(request):
    """Lista de orçamentos em cards, com abas por situação e ações na tela."""
    situacao = (request.GET.get("situacao") or "pendente").strip()
    validas = {s.value for s in Orcamento.Status}
    if situacao not in validas:
        situacao = "pendente"
    busca = (request.GET.get("q") or "").strip()

    base = Orcamento.objects.select_related("aprovado_por")
    if busca:
        from django.db.models import Q
        base = base.filter(
            Q(titulo__icontains=busca) | Q(descricao__icontains=busca)
            | Q(fornecedor__icontains=busca) | Q(solicitante__icontains=busca)
        )

    contagem = {s: 0 for s in validas}
    for row in Orcamento.objects.values("status"):
        contagem[row["status"]] = contagem.get(row["status"], 0) + 1

    # ---- Filtro do sistema -------------------------------------------------
    # A SITUAÇÃO continua sendo a aba (é o fluxo da tela: pendente → decidido),
    # então o popup não a repete. O que sobra de dimensão real aqui é o
    # FORNECEDOR — e ele vem dos registros que existem, não de uma lista fixa:
    # sem orçamento cadastrado o grupo fica vazio, `barra_filtros` o descarta e
    # a tela não ganha um botão que abre popup vazio.
    base_sit = base.filter(status=situacao)
    fornecedores = sorted(
        {(o.fornecedor or "").strip() for o in base_sit if (o.fornecedor or "").strip()}
    )
    forn_sel = (request.GET.get("fornecedor") or "").strip()
    if forn_sel:
        base_sit = base_sit.filter(fornecedor=forn_sel)

    itens = list(base_sit.order_by("-data_solicitacao", "-criado_em"))

    abas = [
        {"key": "pendente", "titulo": "Pendentes", "icone": "⏳", "qtd": contagem.get("pendente", 0)},
        {"key": "aprovado", "titulo": "Aprovados", "icone": "check", "qtd": contagem.get("aprovado", 0)},
        {"key": "negado", "titulo": "Negados", "icone": "block", "qtd": contagem.get("negado", 0)},
    ]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Orçamentos",
        "abas": abas, "situacao": situacao, "itens": itens, "busca": busca,
        "pode_decidir": _pode_decidir(request.user),
        "voltar_url": "/admin/", "voltar_nome": "Início",
        # `situacao` e `q` no keep: aplicar o filtro não pode trocar a aba nem
        # apagar a busca.
        **barra_filtros(
            request,
            [{"param": "fornecedor", "label": "Fornecedor", "todos": "Todos",
              "opcoes": [(f, f) for f in fornecedores]}],
            keep=("situacao", "q"),
        ),
    })
    return render(request, "orcamentos/orcamentos_lista.html", contexto)


@staff_member_required
@require_POST
def decidir_orcamento(request, pk, acao):
    """Aprova ou nega um orçamento pendente (só Gerente/Supervisor).

    SÓ POST (auditoria 4.2). Antes aceitava GET "para os links do sino", o que
    fazia de `<img src=".../orcamentos/12/aprovar/">` num e-mail um aprovador de
    orçamento silencioso: o navegador da vítima manda o GET com a sessão dela e
    o CSRF middleware não olha GET. Quem chamava por link — o sino
    (`templates/unfold/helpers/header.html`) e a tela de orçamentos — virou
    formulário POST com `{% csrf_token %}`.

    O destino do "voltar" passa pelo `voltar_para` (auditoria 4.3): o `Referer`
    é escolhido por quem manda o link, então redirecionar nele sem validar era
    open redirect."""
    voltar = redirect(voltar_para(request, padrao="/orcamentos/"))
    if not _pode_decidir(request.user):
        messages.error(request, "Só Gerente/Supervisor pode decidir orçamentos.")
        return voltar
    orc = get_object_or_404(Orcamento, pk=pk)
    if orc.status != Orcamento.Status.PENDENTE:
        messages.warning(request, "Este orçamento já foi decidido.")
    elif acao == "aprovar":
        orc.aprovar(request.user)
        messages.success(request, f"Orçamento aprovado: {orc.titulo}.")
    elif acao == "negar":
        orc.negar(request.user, motivo=(request.POST.get("motivo") or "").strip())
        messages.info(request, "Orçamento negado.")
    else:
        raise Http404()
    return voltar
