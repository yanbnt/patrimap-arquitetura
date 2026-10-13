"""Endpoint temporário de import da planilha (somente em DEBUG).

O navegador autenticado do usuário busca o CSV de cada aba e faz POST aqui.
Em produção (DEBUG=False) o endpoint responde 404.
"""

import calendar as _calendar
import logging
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import urlencode

from django.conf import settings
from django.utils.crypto import constant_time_compare
from django.contrib import admin as dj_admin
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import Http404, HttpResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry

from apps.orgs.models import Location, LogAcesso, Person

from .importer import import_transferencias, import_unidade, parse_rows
from .models import (
    Autorizada, Baia, Computador, EnvioAutorizada, MovimentacaoBaia, MovimentacaoPeca,
    Notebook, NotaCompraEnvio, Peca, PerifStatus, RegistroEnvioAutorizada, RegistroReparo,
    AdiamentoPreventiva, GrupoManutencao,
    Reparo, Remessa, Setor, SOChoices, Tarefa, TelemetriaMaquina, TermoResponsabilidade,
    Transferencia, TransferenciaNotebook,
    PREVENTIVA_DIAS, PREVENTIVA_CHECKLIST, pode_mover_baia, proximo_patrimonio,
)
from .tarefas import unidade_do_usuario, ve_tudo
from .utils import destino_seguro, id_ou_nada, voltar_para

logger = logging.getLogger(__name__)

UNIDADES = {"Bonsucesso", "Taquara", "Vilar", "Centro", "Cabo Frio", "Campo Grande"}


def barcode_svg(texto):
    """Gera o SVG (Code128) de um patrimônio, pronto para embutir em HTML."""
    import barcode
    from barcode.writer import SVGWriter

    buf = BytesIO()
    barcode.get("code128", texto, writer=SVGWriter()).write(
        buf,
        options={
            "module_height": 12.0,
            "module_width": 0.36,
            "write_text": False,   # o patrimônio é a legenda no nosso layout
            "quiet_zone": 1.0,
        },
    )
    svg = buf.getvalue().decode("utf-8")
    inicio = svg.find("<svg")  # remove o prólogo XML para embutir
    svg = svg[inicio:] if inicio != -1 else svg
    # Torna o SVG escalável: tira as unidades 'mm' (vira user units) e cria um
    # viewBox, para a barra preencher a largura da etiqueta sem estourar.
    m = re.search(r'width="([\d.]+)mm"\s+height="([\d.]+)mm"', svg)
    if m:
        w, h = m.group(1), m.group(2)
        svg = svg.replace("mm", "")
        svg = svg.replace(
            f'width="{w}" height="{h}"',
            f'width="100%" height="100%" preserveAspectRatio="xMidYMid meet" '
            f'viewBox="0 0 {w} {h}"',
            1,
        )
    return mark_safe(svg)


def qrcode_svg(texto):
    """Gera o QR Code (SVG) de um texto/patrimônio, pronto para embutir em HTML."""
    import qrcode
    import qrcode.image.svg

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=0
    )
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    inicio = svg.find("<svg")
    return mark_safe(svg[inicio:] if inicio != -1 else svg)


@staff_member_required
def etiquetas_patrimonio(request):
    """Página de impressão das etiquetas (Make + código de barras + patrimônio)."""
    pks = {int(x) for x in request.GET.get("ids", "").split(",") if x.strip().isdigit()}
    # Também aceita ids de BAIAS → usa o computador vinculado de cada uma.
    bpks = [int(x) for x in request.GET.get("baias", "").split(",") if x.strip().isdigit()]
    if bpks:
        pks |= set(
            Baia.objects.filter(pk__in=bpks, computador__isnull=False)
            .values_list("computador_id", flat=True)
        )
    computadores = (
        Computador.objects.filter(pk__in=pks).order_by("patrimonio")
        if pks else Computador.objects.none()
    )
    itens = [
        {
            "patrimonio": c.patrimonio,
            "svg": barcode_svg(c.patrimonio),
            "qr": qrcode_svg(c.patrimonio),
            "marca": c.marca,
            "resumo": c.resumo_specs,
        }
        for c in computadores
        if c.patrimonio
    ]
    # Notebooks (mesma etiqueta): aceita ?nb_ids= com pks de Notebook.
    nb_pks = {int(x) for x in request.GET.get("nb_ids", "").split(",") if x.strip().isdigit()}
    if nb_pks:
        for n in Notebook.objects.filter(pk__in=nb_pks).order_by("patrimonio"):
            if not n.patrimonio:
                continue
            itens.append({
                "patrimonio": n.patrimonio,
                "svg": barcode_svg(n.patrimonio),
                "qr": qrcode_svg(n.patrimonio),
                "marca": " ".join(p for p in [n.marca, n.modelo] if p),
                "resumo": n.resumo_specs,
            })
    return render(request, "parque/etiquetas.html",
                  {"itens": itens, **_voltar("/parque/estoque/")})


def _mapa_estrutura_rica(unidades, ocultar_vazios=False, setores_sel=None):
    """Estrutura RICA do mapa (usada pelo mapa de loja e pelo mapa completo).

    Para cada unidade devolve os setores (com nível crítico p/ tingir de vermelho)
    e os notebooks da loja. Retorna (lista, total_de_pcs).
    Cada item: {"unidade", "setores": [{"setor","baias","qtd_criticas",
    "nivel_critico"}], "notebooks": [...]}.
    `ocultar_vazios` pula setores sem PC e unidades sem PC nem notebook (mapa completo).
    `setores_sel` (lista de nomes) filtra por um ou mais setores cruzando lojas.
    """
    estrut = []
    total = 0
    for u in unidades:
        setores = (
            Setor.objects.filter(unidade=u)
            .prefetch_related("baias__colaborador", "baias__reparos",
                              "baias__computador", "baias__notebook")
            .order_by("nome")
        )
        if setores_sel:
            setores = setores.filter(nome__in=setores_sel)
        grupos = []
        for s in setores:
            # A BAIA é a camada FIXA do mapa: TODAS as baias do setor aparecem na sua
            # posição (com computador, com notebook, ou vazia). O dispositivo é só o que
            # está "em cima" dela. Ordem CRESCENTE por número (wrap-reverse no CSS → 1 embaixo).
            baias = sorted(
                list(s.baias.all()),
                key=lambda b: (b.numero is None, b.numero or 0, b.nome or ""),
            )
            if ocultar_vazios and not baias:
                continue  # só esconde setor SEM nenhuma baia
            com_score = [b for b in baias if b.indice_desempenho is not None]
            criticas = [b for b in com_score if b.classe_desempenho == "Crítico"]
            grupos.append({
                "setor": s, "baias": baias, "qtd_criticas": len(criticas),
                # Inteiro 0–100 (evita vírgula pt-BR quebrar o CSS var --crit).
                "nivel_critico": int(round(len(criticas) / len(com_score) * 100)) if com_score else 0,
            })
            total += len(baias)
        if ocultar_vazios and not grupos:
            continue
        # notebooks fica vazio: os notebooks agora aparecem na própria baia (no setor).
        estrut.append({"unidade": u, "setores": grupos, "notebooks": []})
    return estrut, total


def _resumo_parque(unidades_estrut):
    """Resumo de saúde do parque p/ a barra do topo (Direção 1): contagem por classe
    de desempenho + "precisam de ação". Lê as MESMAS baias já montadas (bate com os
    cards) e usa as propriedades do model. Alimenta filtros rápidos client-side."""
    CLS = [("Ótimo", "otimo", "#00a651"), ("Bom", "bom", "#8fb82e"),
           ("Baixo", "baixo", "#ef8f3c"), ("Crítico", "critico", "#e0533f")]
    n = {k: 0 for _, k, _ in CLS}
    sem_pc = criticos = sem_tel = prev_atras = total = 0
    for u in unidades_estrut:
        for g in u.get("setores", []):
            for b in g["baias"]:
                total += 1
                if b.esta_vazia:
                    sem_pc += 1
                    continue
                cl = b.classe_desempenho
                for label, key, _cor in CLS:
                    if cl == label:
                        n[key] += 1
                if cl == "Crítico":
                    criticos += 1
                if b.telemetria_status != "ativo":
                    sem_tel += 1
                if b.preventiva_status in ("vencida", "pendente"):
                    prev_atras += 1
    classes = [{"key": f"cl:{label}", "label": label, "cor": cor, "n": n[key]}
               for label, key, cor in CLS]
    classes.append({"key": "tp:sem_pc", "label": "Sem PC", "cor": "#93a19a", "n": sem_pc})
    acao = []
    if criticos:
        acao.append({"key": "at:critico", "label": "crítico(s)", "cor": "#e0533f", "n": criticos})
    if sem_tel:
        acao.append({"key": "at:sem_tel", "label": "sem telemetria", "cor": "#ef8f3c", "n": sem_tel})
    if prev_atras:
        acao.append({"key": "at:prev", "label": "preventiva atrasada", "cor": "#e0533f", "n": prev_atras})
    return {"total": total, "classes": classes, "acao": acao}


def _resumo_notebooks(unidades_estrut):
    """Resumo de saúde dos NOTEBOOKS p/ a barra do topo — MESMO formato de
    _resumo_parque, mas lendo a estrutura de notebooks (notebooks + vazios).
    Assim o mapa de notebooks fica com a mesma barra do mapa de computadores."""
    CLS = [("Ótimo", "otimo", "#00a651"), ("Bom", "bom", "#8fb82e"),
           ("Baixo", "baixo", "#ef8f3c"), ("Crítico", "critico", "#e0533f")]
    n = {k: 0 for _, k, _ in CLS}
    sem_nb = criticos = sem_tel = total = 0
    for u in unidades_estrut:
        for g in u.get("setores", []):
            for nb in g.get("notebooks", []):
                total += 1
                cl = nb.classe_desempenho
                for label, key, _cor in CLS:
                    if cl == label:
                        n[key] += 1
                if cl == "Crítico":
                    criticos += 1
                if nb.telemetria_status != "ativo":
                    sem_tel += 1
            v = len(g.get("vazios", []))
            sem_nb += v
            total += v
    classes = [{"key": f"cl:{label}", "label": label, "cor": cor, "n": n[key]}
               for label, key, cor in CLS]
    classes.append({"key": "tp:sem_pc", "label": "Sem notebook", "cor": "#93a19a", "n": sem_nb})
    acao = []
    if criticos:
        acao.append({"key": "at:critico", "label": "crítico(s)", "cor": "#e0533f", "n": criticos})
    if sem_tel:
        acao.append({"key": "at:sem_tel", "label": "sem telemetria", "cor": "#ef8f3c", "n": sem_tel})
    return {"total": total, "classes": classes, "acao": acao}


def _cargos_distintos():
    """Cargos (job_title) distintos e preenchidos, p/ o filtro de cargo nos mapas.
    Hoje quase vazio (campo novo) — o filtro fica pronto e popula conforme preencherem."""
    return list(
        Person.objects.exclude(job_title="").exclude(job_title__isnull=True)
        .values_list("job_title", flat=True).distinct().order_by("job_title"))


def _filtros_ctx(request, unidades, por_nome=False, com_setor=False, sem_unidade_opt=False):
    """Contexto do filtro (Unidade + opcional Setor por nome, cruzando lojas).

    Usado pelo parcial `parque/_filtros.html` (dropdowns customizados). `por_nome=True`
    faz o filtro de unidade valer pelo NOME (mapas/tabelas de notebook); senão pelo ID.
    `com_setor=True` adiciona o dropdown de setor com **multi-seleção** (checkboxes) —
    os valores vêm de `?setor=` (podem ser vários) e o de unidade de `?unidade=`.
    """
    uni_val = (request.GET.get("unidade") or "").strip()
    setor_vals = [s.strip() for s in request.GET.getlist("setor") if s.strip()]
    unidades_filtro = [
        {"val": (u.name if por_nome else u.id), "label": u.name} for u in unidades
    ]
    # Opção sintética p/ localizar máquinas sem unidade (valor = rótulo que
    # _unidade_setor_notebook retorna quando não há loja).
    if sem_unidade_opt:
        unidades_filtro.append({"val": "Sem unidade / setor", "label": "Sem unidade"})
    uni_label = "Todas"
    for it in unidades_filtro:
        if str(it["val"]) == uni_val:
            uni_label = it["label"]
    if not setor_vals:
        setor_label = "Todos"
    elif len(setor_vals) == 1:
        setor_label = setor_vals[0]
    else:
        setor_label = f"{len(setor_vals)} setores"
    # Datas de atalho do filtro por vencimento da preventiva. Ficam prontas aqui
    # para o template não fazer aritmética de data — e `keep_pairs` devolve o
    # querystring atual em pares, para o formulário de data preservar os outros
    # filtros em vez de zerá-los.
    #
    # `keep_pairs` era uma LISTA BRANCA de quatro nomes (unidade/setor/cargo/q).
    # Com o "Aplicar" único do popup, quem envia a tela inteira é este
    # formulário: qualquer parâmetro fora da lista morria no envio — a preventiva
    # perdia `?vista=calendario` e voltava para a visão padrão, a tabela perdia o
    # período de compra. Agora vai TUDO que está na URL, menos:
    #   • `vence_desde`/`vence_ate` — o próprio formulário tem esses campos
    #     (mandar duas vezes envia o valor velho junto com o novo);
    #   • `page`/`p` — filtrar tem de voltar para a primeira página.
    _hoje = timezone.localdate()
    _keep = []
    for k in request.GET.keys():
        if k in ("vence_desde", "vence_ate", "page", "p"):
            continue
        for v in request.GET.getlist(k):
            if v:
                _keep.append((k, v))
    # Rótulo do botão do grupo de data: o dropdown mostra a janela em vigor em
    # vez de um texto fixo, como os outros filtros fazem.
    _v_ate, _v_desde = _janela_de_data(request)
    if not _v_ate and not _v_desde:
        _v_lbl = "Qualquer data"
    elif _v_ate and not _v_desde:
        _v_lbl = "Já vencida" if _v_ate <= _hoje else f"Até {_v_ate.strftime('%d/%m')}"
    elif _v_desde and not _v_ate:
        _v_lbl = f"De {_v_desde.strftime('%d/%m')}"
    elif _v_desde == _hoje and _v_ate == _hoje + timedelta(days=15):
        _v_lbl = "Próximos 15 dias"
    elif _v_desde == _hoje and _v_ate == _hoje + timedelta(days=30):
        _v_lbl = "Próximos 30 dias"
    else:
        _v_lbl = f"{_v_desde.strftime('%d/%m')} a {_v_ate.strftime('%d/%m')}"
    ctx = {
        "unidades_filtro": unidades_filtro,
        "uni_sel_val": uni_val,
        "uni_sel_label": uni_label,
        "setor_sel_vals": setor_vals,
        "setor_sel_label": setor_label,
        "vence_label": _v_lbl,
        "vence_ate": _v_ate.isoformat() if _v_ate else "",
        "vence_desde": _v_desde.isoformat() if _v_desde else "",
        "hoje_iso": _hoje.isoformat(),
        "em_15_iso": (_hoje + timedelta(days=15)).isoformat(),
        "em_30_iso": (_hoje + timedelta(days=30)).isoformat(),
        "keep_pairs": _keep,
    }
    if com_setor:
        nomes = list(
            Setor.objects.values_list("nome", flat=True).distinct().order_by("nome")
        )
        ctx["setores_filtro"] = [
            {"val": n, "label": n, "checked": n in setor_vals} for n in nomes
        ]
    return ctx


# ---------------------------------------------------------------------------
# O MESMO FILTRO EM QUALQUER TELA (não só onde o corte é unidade/setor)
# ---------------------------------------------------------------------------
#
# Pedido do dono: "vamos unificar as visões — cliquei em filtros e olha o que
# apareceu". O popup unificado (botão "Filtrar" + `initFiltrarPopup`) nasceu no
# mapa, onde as dimensões são unidade e setor, e `_filtros_ctx` só sabe montar
# essas duas. Fora do mapa cada tela corta por outra coisa — situação, tipo,
# motivo, autorizada, loja — e era exatamente por isso que cada uma tinha a sua
# barra de chips própria.
#
# `barra_filtros()` fecha esse buraco: a tela DECLARA as dimensões que a view
# sabe filtrar e recebe de volta o contexto do MESMO parcial
# (`parque/_filtros.html`), com os mesmos chips de filtro aplicado.
#
# A regra da §12.4 do DESIGN-SYSTEM continua valendo, e aqui ela é estrutural:
# grupo sem opção é DESCARTADO e, se não sobrar nenhum, o parcial não rende nada
# — a tela fica sem o botão em vez de abrir um popup vazio ("filtrar o quê aqui
# na tela de setores, cara?").
def barra_filtros(request, grupos, keep=(), data=None):
    """Contexto do parcial `parque/_filtros.html` para filtros GENÉRICOS.

    `grupos`: lista de dimensões, cada uma um parâmetro de querystring com
        seleção única::

            [{"param": "situacao", "label": "Situação", "todos": "Todas",
              "opcoes": [(valor, rótulo), ...]}]

        A opção também aceita `(valor, rótulo, rótulo_curto)`: o rótulo longo
        vai na ficha do popup (é onde cabe a contagem, "Desativados (6)") e o
        curto no chip de filtro aplicado, que fica ilegível com número dentro.

    `keep`: nomes de parâmetros da tela que NÃO são filtro e têm de sobreviver ao
        "Aplicar" (`aba`, `vista`, `ano`, `mes`, `q`…).

    `data`: grupo de PERÍODO, opcional::

            {"label": "Período", "de": "de", "ate": "ate",
             "atalhos": [(rótulo, iso_desde, iso_ate), ...]}

        Os campos do calendário continuam se chamando `vence_desde`/`vence_ate`
        no HTML porque é o que o `initCalendarioFiltro()` procura; os nomes reais
        da tela viajam em `data-mkfp-de`/`data-mkfp-ate` e o `initFiltrarPopup`
        traduz na hora de enviar.

    Devolve `filtros_extra` (grupos prontos, href por opção), `filtros_chips` (o
    que está aplicado, com href de remoção), `filtros_limpar` e `keep_pairs`.
    """
    grupos = [g for g in grupos if g.get("opcoes")]
    params = [g["param"] for g in grupos]
    de_param = (data or {}).get("de") or ""
    ate_param = (data or {}).get("ate") or ""

    # Estado atual da URL, só com o que esta barra conhece: assim um parâmetro
    # de outra tela (ou um `page=`) não é carregado adiante sem querer.
    atual = {}
    for k in list(keep) + params + ([de_param, ate_param] if data else []):
        if not k:
            continue
        vals = [v for v in request.GET.getlist(k) if v]
        if vals:
            atual[k] = vals

    def _url(trocar=None, novo=None, tirar=()):
        pares = []
        for k, vals in atual.items():
            if k == trocar or k in tirar:
                continue
            for v in vals:
                pares.append((k, v))
        if trocar and novo:
            pares.append((trocar, novo))
        return "?" + urlencode(pares) if pares else "?"

    grupos_ctx, chips = [], []
    for g in grupos:
        p = g["param"]
        sel = (request.GET.get(p) or "").strip()
        todos = g.get("todos") or "Todos"
        opcoes = [{"val": "", "label": todos, "href": _url(p, ""), "sel": not sel}]
        rotulo = ""
        for opcao in g["opcoes"]:
            # A opção é `(valor, rótulo)` ou `(valor, rótulo, rótulo_curto)`. O
            # rótulo curto existe para a ficha poder mostrar a contagem
            # ("Desativados (6)") sem que o chip fique com ela dentro.
            val, lbl = str(opcao[0]), opcao[1]
            curto = opcao[2] if len(opcao) > 2 else lbl
            if val == sel:
                rotulo = str(curto)
            opcoes.append({"val": val, "label": lbl, "href": _url(p, val), "sel": val == sel})
        grupos_ctx.append({
            "param": p, "label": g["label"], "sel": sel,
            "sel_label": rotulo or todos, "opcoes": opcoes,
        })
        # Chip só quando o valor da URL é uma opção REAL: valor inventado à mão
        # não vira chip (senão o "×" prometeria remover algo que não filtrou).
        if sel and rotulo:
            chips.append({"label": g["label"], "valor": rotulo, "href": _url(p, "")})

    # "Limpar tudo" tira TODOS os parâmetros de filtro (os dos grupos e o
    # período) e mantém só o que não é filtro — aba, mês, busca. Aqui já custou
    # um bug: devolvendo `_url()` puro, o link vinha com os filtros dentro e
    # "limpar" não limpava nada.
    _tudo = tuple(params) + ((de_param, ate_param) if data else ())

    ctx = {
        "filtros_extra": grupos_ctx,
        "filtros_chips": chips,
        "filtros_limpar": _url(tirar=_tudo),
        # Vai TUDO (inclusive os parâmetros dos grupos, marcados com
        # `data-mkfp-keep`): grupo que o usuário não tocou mantém o valor, e o JS
        # remove o par antes de injetar o novo. Sem isso, aplicar um filtro
        # apagaria os outros.
        "keep_pairs": [(k, v) for k, vals in atual.items()
                       for v in vals if k not in (de_param, ate_param)],
    }
    if not grupos_ctx and not data:
        # Nada para filtrar: o parcial não rende barra nenhuma.
        return {"filtros_extra": [], "filtros_chips": [], "keep_pairs": []}

    if data:
        d_de = (request.GET.get(de_param) or "").strip()
        d_ate = (request.GET.get(ate_param) or "").strip()
        atalhos = [{"label": "Qualquer data",
                    "href": _url(tirar=(de_param, ate_param)),
                    "sel": not d_de and not d_ate}]
        rot_data = ""
        for lbl, iso_de, iso_ate in data.get("atalhos") or ():
            pares = [(k, v) for k, vals in atual.items()
                     for v in vals if k not in (de_param, ate_param)]
            if iso_de:
                pares.append((de_param, iso_de))
            if iso_ate:
                pares.append((ate_param, iso_ate))
            ligado = (iso_de or "") == d_de and (iso_ate or "") == d_ate
            if ligado:
                rot_data = lbl
            # O href também carrega `vence_desde`/`vence_ate`: é de lá que o
            # `initFiltrarPopup` lê a data para alimentar o calendário no clique.
            if iso_de:
                pares.append(("vence_desde", iso_de))
            if iso_ate:
                pares.append(("vence_ate", iso_ate))
            atalhos.append({"label": lbl, "href": "?" + urlencode(pares), "sel": ligado})
        if not rot_data and (d_de or d_ate):
            rot_data = " a ".join(x for x in [_data_br(d_de), _data_br(d_ate)] if x)
        ctx.update({
            "com_data": True,
            "data_lbl": data.get("label") or "Período",
            "data_de_param": de_param,
            "data_ate_param": ate_param,
            "data_atalhos": atalhos,
            "vence_label": rot_data or "Qualquer data",
            "vence_desde": d_de,
            "vence_ate": d_ate,
            "hoje_iso": timezone.localdate().isoformat(),
        })
        if d_de or d_ate:
            ctx["filtros_chips"] = chips + [{
                "label": ctx["data_lbl"],
                "valor": rot_data,
                "href": _url(tirar=(de_param, ate_param)),
            }]
    return ctx


def _data_br(iso):
    """`2026-09-04` → `04/09` (rótulo do chip de período). Texto inválido some."""
    try:
        return date.fromisoformat(iso).strftime("%d/%m")
    except (TypeError, ValueError):
        return ""


def _colaboradores_baia():
    """Lista simples de colaboradores p/ atribuir a uma baia (id, nome, cargo, unidade)."""
    pessoas = (
        Person.objects.filter(active=True).select_related("location").order_by("full_name")
    )
    return [{
        "id": p.id,
        "nome": p.full_name,
        "cargo": p.job_title or "",
        "unidade": p.location.name if p.location_id else "",
    } for p in pessoas]


def _computadores_estoque():
    """Computadores disponíveis no estoque, p/ alocar numa mesa (id, patrimônio, specs)."""
    return [{
        "id": c.id,
        "nome": c.patrimonio,
        "resumo": c.resumo_specs,
    } for c in Computador.objects.filter(status=Computador.Status.EM_ESTOQUE).order_by("patrimonio")]


def _notebooks_disponiveis():
    """Notebooks LIVRES p/ alocar numa mesa: sem colaborador e fora de qualquer mesa."""
    itens = []
    for n in Notebook.objects.filter(
        baia__isnull=True, colaborador__isnull=True
    ).order_by("marca", "modelo"):
        itens.append({
            "id": n.id,
            "nome": f"{n.marca} {n.modelo}".strip() or f"Notebook {n.pk}",
            "resumo": getattr(n, "resumo_specs", ""),
        })
    return itens


@staff_member_required
def mapa_loja(request, unidade_id):
    """Mapa interativo de UMA loja (mesmo template rico do mapa completo)."""
    unidade = get_object_or_404(Location, pk=unidade_id)
    unidades_estrut, _ = _mapa_estrutura_rica([unidade], ocultar_vazios=False)
    # Destinos da transferência entre lojas (arrastar a máquina até o caminhão).
    outras = (
        Location.objects.filter(setores__isnull=False)
        .exclude(pk=unidade.pk).distinct().order_by("name")
    )
    destinos = [{"unidade": u, "estrutura": _estrutura_unidade(u)} for u in outras]
    # Filtro de DATA (vencimento da preventiva) — o mesmo do mapa completo, para
    # a loja única se comportar igual. Aplicado ANTES do resumo, para as
    # contagens do topo acompanharem o filtro em vez de mentir.
    vence_ate, vence_desde = _janela_de_data(request)
    if vence_ate or vence_desde:
        unidades_estrut = _filtrar_por_vencimento(unidades_estrut, vence_ate, vence_desde)
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "unica": unidade,
        "unidades_estrut": unidades_estrut,
        "resumo": _resumo_parque(unidades_estrut),
        "vence_ate": vence_ate.isoformat() if vence_ate else "",
        "vence_desde": vence_desde.isoformat() if vence_desde else "",
        "cargos": _cargos_distintos(),
        "destinos": destinos,
        "title": f"Mapa — {unidade.name}",
        "pode_add_baia": request.user.has_perm("parque.add_baia"),
        "pode_add_setor": request.user.has_perm("parque.add_setor"),
        **_stn_ctx(),
        "pode_ver_estoque": request.user.has_perm("parque.view_computador"),
        "pode_mover": pode_mover_baia(request.user),
        "colaboradores": _colaboradores_baia(),
        "computadores_estoque": _computadores_estoque(),
        "notebooks_disponiveis": _notebooks_disponiveis(),
        "pode_atribuir_colab": request.user.has_perm("parque.change_baia"),
    })
    return render(request, "parque/mapa.html", contexto)


@staff_member_required
def estoque_hub(request):
    """Tela inicial do Estoque: escolhe entre Computadores, Notebooks ou Periféricos."""
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Estoque",
        "opcoes": [
            # A tabela do estoque, e nao o mapa: o mapa ja e' item de menu
            # ("Mapa do parque"), e apontar o bloco para la' deixava
            # /parque/tabela-estoque-computadores/ SEM NENHUMA porta na
            # interface — orfa, alcancavel so por quem soubesse a URL.
            {"nome": "Computadores", "icon": "inventory_2", "desc": "Computadores cadastrados",
             "cor": "#00a651", "cta": "Ver computadores",
             "total": Computador.objects.exclude(status=Computador.Status.DESATIVADO).count(),
             "link": "/parque/tabela-estoque-computadores/"},
            # Cor de CATEGORIA (não de status): escala da marca do DESIGN-PRO.md
            # §1. Notebook usa o mesmo verde médio dos badges de notebook.
            {"nome": "Notebooks", "icon": "laptop_mac", "desc": "Notebooks cadastrados",
             "cor": "#32673a", "cta": "Ver notebooks",
             "total": Notebook.objects.count(), "link": "/parque/mapa-notebooks/"},
            {"nome": "Periféricos", "icon": "memory", "desc": "Peças e periféricos",
             "cor": "#8fb82e", "cta": "Ver periféricos",
             "total": Peca.objects.count(), "link": "/parque/tabela-pecas/"},
            {"nome": "Fora de uso", "icon": "inventory", "desc": "Desativadas, em estoque e sem colaborador",
             "cor": "#93a19a", "cta": "Gerenciar",
             "total": _fora_de_uso_total(),
             "link": "/parque/fora-de-uso/"},
        ],
    })
    return render(request, "parque/estoque_hub.html", contexto)


def _tabela_toolbar(view_atual, mapa_url, tabela_url):
    return {"view_atual": view_atual, "view_mapa": mapa_url, "view_tabela": tabela_url}


def _voltar(url):
    """Destino do botão "← Voltar" (drill-down) com o nome da tela pai."""
    from apps.parque.context_processors import nome_tela
    return {"voltar_url": url, "voltar_nome": nome_tela(url) or "Voltar"}


def _exportar_lista_xlsx(nome, colunas, linhas):
    """Gera um .xlsx (openpyxl) com as MESMAS colunas da tabela na tela.

    Reaproveitado por tabela_computadores e tabela_notebooks — ambas montam a linha
    no mesmo formato (ident/local/pessoa/sit_label/score/resumo), então o export sai
    idêntico ao que está sendo exibido (já filtrado por unidade/setor)."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from django.utils import timezone
    from django.utils.text import slugify

    wb = Workbook()
    ws = wb.active
    ws.title = (nome or "Lista")[:31]

    cab_fill = PatternFill("solid", fgColor="00A651")
    cab_font = Font(bold=True, color="FFFFFF")
    for c, titulo in enumerate(colunas, start=1):
        cell = ws.cell(row=1, column=c, value=titulo)
        cell.fill = cab_fill
        cell.font = cab_font
        cell.alignment = Alignment(vertical="center")

    for r in linhas:
        score = r.get("score")
        dc = r.get("data_compra")
        linha = [
            r.get("ident", ""),
            r.get("local", ""),
            r.get("pessoa", ""),
            r.get("sit_label", ""),
            score if score is not None else "",
            r.get("resumo", ""),
        ]
        if len(colunas) >= 7:
            linha.append(dc.strftime("%d/%m/%Y") if dc else "")
        ws.append(linha)

    for i, w in enumerate([16, 32, 26, 14, 8, 50, 14][:len(colunas)], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{len(linhas) + 1}"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    data = timezone.localdate().isoformat()
    fname = f"{slugify(nome) or 'lista'}-{data}.xlsx"
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


def _export_url(request):
    """URL da tela atual + ?export=xlsx (preserva os filtros ativos no querystring)."""
    q = request.GET.copy()
    q["export"] = "xlsx"
    return "?" + q.urlencode()


def _periodo_compra(request, linhas):
    """Filtra `linhas` (cada uma com 'data_compra' = date|None) pelo intervalo
    GET compra_de..compra_ate e devolve (linhas, ctx) para o filtro de período."""
    from datetime import datetime

    def _parse(s):
        try:
            return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    de, ate = _parse(request.GET.get("compra_de")), _parse(request.GET.get("compra_ate"))
    if de or ate:
        filtradas = []
        for l in linhas:
            d = l.get("data_compra")
            if not d or (de and d < de) or (ate and d > ate):
                continue
            filtradas.append(l)
        linhas = filtradas

    hidden = []
    for k in request.GET.keys():
        if k in ("compra_de", "compra_ate", "export"):
            continue
        for v in request.GET.getlist(k):
            hidden.append((k, v))
    ctx = {
        "tem_periodo": True,
        "compra_de": request.GET.get("compra_de", ""),
        "compra_ate": request.GET.get("compra_ate", ""),
        "periodo_hidden": hidden,
    }
    return linhas, ctx


@staff_member_required
def tabela_computadores(request):
    """Modo TABELA dos computadores — mesmo cabeçalho/topo do mapa (uniformidade)."""
    qs = (
        Baia.objects.select_related("setor__unidade", "colaborador", "computador", "notebook")
        .prefetch_related("reparos")
        .order_by("setor__unidade__name", "setor__nome", "-numero", "nome")
    )
    uid = request.GET.get("unidade")
    unidade_sel = int(uid) if (uid and uid.isdigit()) else None
    if unidade_sel:
        qs = qs.filter(setor__unidade_id=unidade_sel)
    setores_sel = [s.strip() for s in request.GET.getlist("setor") if s.strip()]
    if setores_sel:
        qs = qs.filter(setor__nome__in=setores_sel)

    SIT = {"Com PC": "#00a651", "Sem PC": "#93a19a",
           "Notebook": "#32673a", "Com defeito": "#e0533f"}
    CLS = {"Crítico": "#e0533f", "Baixo": "#ef8f3c", "Bom": "#8fb82e", "Ótimo": "#00a651"}
    linhas = []
    for b in qs:
        sl = b.situacao_label
        sc = SIT.get(sl, "#93a19a")
        classe = b.classe_desempenho
        dc = getattr(b.dispositivo, "data_compra", None)
        linhas.append({
            "pk": b.pk,
            "ident": b.nome,
            "data_compra": dc,
            "local": f"{b.setor.unidade.name} › {b.setor.nome}",
            "pessoa": b.colaborador.full_name if b.colaborador_id else "—",
            "sit_label": sl, "sit_cor": sc,
            "score": b.indice_desempenho,
            "classe": classe if classe != "—" else "",
            "cor": CLS.get(classe, "#93a19a"),
            "resumo": b.resumo_pc,
            "busca": " ".join(filter(None, [
                b.nome, b.setor.unidade.name, b.setor.nome,
                b.colaborador.full_name if b.colaborador_id else "",
                sl, b.resumo_pc,
                getattr(b.dispositivo, "patrimonio", "") or "",
                getattr(b.dispositivo, "serial", "") or "",
                b.eff_cpu or "", b.eff_ram or "", b.eff_disco or "",
                dc.strftime("%d/%m/%Y") if dc else "",
            ])).lower(),
            "edit": f"/admin/parque/baia/{b.pk}/change/",
            "transferir": "/parque/transferencia-lojas/",
            "atribuir": "",
        })

    colunas = ["Baia", "Local", "Colaborador", "Situação", "Score", "Resumo", "Data compra"]
    linhas, periodo_ctx = _periodo_compra(request, linhas)
    if request.GET.get("export") == "xlsx":
        return _exportar_lista_xlsx("Computadores", colunas, linhas)

    contexto = dj_admin.site.each_context(request)
    contexto.update(_tabela_toolbar("tabela", "/parque/mapa-completo/", "/parque/tabela-computadores/"))
    contexto.update({
        "title": "Computadores — tabela",
        "titulo": "Computadores",
        "total": len(linhas),
        "colunas": colunas,
        "export_url": _export_url(request),
        "linhas": linhas,
        "modelo": "baia",
        **_voltar("/parque/mapa-completo/"),
        "novo_url": "/admin/parque/baia/add/",
        "transferir_url": "/parque/transferencia-lojas/",
        "atribuir_url": "",
        "etiqueta_url": "/parque/etiquetas/",
        "pode_excluir": request.user.has_perm("parque.delete_baia"),
        **_filtros_ctx(
            request,
            Location.objects.filter(setores__isnull=False).distinct().order_by("name"),
            por_nome=False, com_setor=True,
        ),
        "legenda": [("#00a651", "Com PC"), ("#32673a", "Notebook"),
                    ("#e0533f", "Defeito"), ("#93a19a", "Sem PC")],
        **periodo_ctx,
    })
    return render(request, "parque/tabela_dispositivos.html", contexto)


@staff_member_required
def tabela_notebooks(request):
    """Modo TABELA dos notebooks — mesmo cabeçalho/topo do mapa."""
    qs = (
        Notebook.objects
        .select_related("colaborador__location", "colaborador__department",
                        "baia__setor__unidade")
        .order_by("marca", "modelo", "usuario")
    )
    # Unidade/setor derivados pela MESMA fonte única dos mapas (baia > colaborador > texto).
    unidades_loc = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    unidades_lower = {u.name.lower(): u.name for u in unidades_loc}
    aliases = {"vilar dos teles": "Vilar", "vilar de teles": "Vilar"}
    uni_sel = (request.GET.get("unidade") or "").strip() or None
    setores_lower = {s.strip().lower() for s in request.GET.getlist("setor") if s.strip()}

    SIT = {"ativo": ("Ativo", "#00a651"), "defeito": ("Com defeito", "#e0533f"),
           "obsoleto": ("Obsoleto", "#9ca3af")}
    CLS = {"Crítico": "#e0533f", "Baixo": "#ef8f3c", "Bom": "#8fb82e", "Ótimo": "#00a651"}
    linhas = []
    for n in qs:
        uni_nb, setor_nb = _unidade_setor_notebook(n, unidades_lower, aliases)
        if uni_sel and uni_nb != uni_sel:
            continue
        if setores_lower and setor_nb.lower() not in setores_lower:
            continue
        sl, sc = SIT.get(n.status, ("—", "#93a19a"))
        classe = n.classe_desempenho
        linhas.append({
            "pk": n.pk,
            "data_compra": n.data_compra,
            "ident": f"{n.marca} {n.modelo}".strip() or "Notebook",
            "local": f"{uni_nb} › {setor_nb}",
            "pessoa": n.usuario or "—",
            "sit_label": sl, "sit_cor": sc,
            "score": n.indice_desempenho,
            "classe": classe if classe != "—" else "",
            "cor": CLS.get(classe, "#93a19a"),
            "resumo": n.resumo_specs,
            "busca": " ".join(filter(None, [
                n.marca, n.modelo, n.serial, n.patrimonio, n.usuario,
                n.unidade_setor, uni_nb, setor_nb, n.resumo_specs, sl,
                n.processador, n.memoria_ram, n.armazenamento, n.conta,
                n.data_compra.strftime("%d/%m/%Y") if n.data_compra else "",
            ])).lower(),
            "edit": f"/admin/parque/notebook/{n.pk}/change/",
            "transferir": "/parque/mapa-notebooks/",
            "atribuir": "/parque/mapa-notebooks/",
        })

    colunas = ["Notebook", "Unidade / setor", "Usuário", "Situação", "Score", "Resumo", "Data compra"]
    linhas, periodo_ctx = _periodo_compra(request, linhas)
    if request.GET.get("export") == "xlsx":
        return _exportar_lista_xlsx("Notebooks", colunas, linhas)

    contexto = dj_admin.site.each_context(request)
    contexto.update(_tabela_toolbar("tabela", "/parque/mapa-notebooks/", "/parque/tabela-notebooks/"))
    contexto.update({
        "title": "Notebooks — tabela",
        "titulo": "Notebooks",
        "total": len(linhas),
        "colunas": colunas,
        "export_url": _export_url(request),
        "linhas": linhas,
        "modelo": "notebook",
        **_voltar("/parque/estoque/"),
        "novo_url": "/admin/parque/notebook/add/",
        "transferir_url": "/parque/mapa-notebooks/",
        "atribuir_url": "/parque/mapa-notebooks/",
        "etiqueta_url": "/parque/etiquetas/",
        "pode_excluir": request.user.has_perm("parque.delete_notebook"),
        **_filtros_ctx(request, unidades_loc, por_nome=True, com_setor=True, sem_unidade_opt=True),
        "legenda": [("#00a651", "Ativo"), ("#e0533f", "Com defeito"), ("#9ca3af", "Obsoleto")],
        **periodo_ctx,
    })
    return render(request, "parque/tabela_dispositivos.html", contexto)


@staff_member_required
def tabela_estoque_computadores(request):
    """Modo TABELA do estoque de computadores (modelo Computador) — mesmo tema."""
    _unis = list(Location.objects.filter(setores__isnull=False).distinct().order_by("name"))
    qs = Computador.objects.select_related("baia__setor__unidade").order_by("status", "patrimonio")
    status = request.GET.get("status")
    if status in dict(Computador.Status.choices):
        qs = qs.filter(status=status)
    uid = request.GET.get("unidade")
    sem_unidade = (uid == "sem")
    unidade_sel = int(uid) if (uid and uid.isdigit()) else None
    if unidade_sel:
        nome = Location.objects.filter(pk=unidade_sel).values_list("name", flat=True).first() or ""
        qs = qs.filter(Q(baia__setor__unidade_id=unidade_sel) | Q(ultima_unidade__iexact=nome))
    # "Sem unidade" usa a régua ÚNICA (_unidade_computador): sem baia e sem texto que
    # case com uma unidade real. Filtrado em Python p/ bater com a cobertura/mapas.
    _uni_lower, _aliases = _mapa_aliases_unidades() if sem_unidade else (None, None)

    COR = {"em_estoque": "#32673a", "em_uso": "#00a651", "defeito": "#e0533f", "desativado": "#ef8f3c"}
    linhas = []
    for c in qs:
        try:
            baia = c.baia
        except ObjectDoesNotExist:
            baia = None
        if sem_unidade and _unidade_computador(c, _uni_lower, _aliases) != SEM_UNIDADE:
            continue
        if baia is not None:
            uni, pos = baia.setor.unidade.name, f"{baia.setor.nome} › {baia.nome}"
        else:
            uni, pos = (c.ultima_unidade or "—"), (c.ultima_baia or "—")
        linhas.append({
            "pk": c.pk, "patrimonio": c.patrimonio, "unidade": uni, "pos": pos,
            "resumo": c.resumo_specs, "reparos": c.qtd_reparos,
            "sit_label": c.get_status_display(), "sit_cor": COR.get(c.status, "#93a19a"),
            "edit": f"/admin/parque/computador/{c.pk}/change/",
            "reativar": (f"/parque/reativar/{c.pk}/" if c.status == "desativado" else ""),
        })

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Estoque de computadores",
        "titulo": "Estoque de computadores",
        "total": len(linhas),
        "linhas": linhas,
        "modelo": "computador",
        **_tabela_toolbar("tabela", "/parque/mapa-completo/", "/parque/tabela-estoque-computadores/"),
        # "Estoque de Desativados" é item de MENU → volta p/ Início; senão veio do hub Estoque.
        **(_voltar("/admin/") if status == "desativado" else _voltar("/parque/estoque/")),
        "novo_url": "/admin/parque/computador/add/",
        "etiqueta_url": "/parque/etiquetas/",
        "pode_excluir": request.user.has_perm("parque.delete_computador"),
        "unidades": _unis,
        "unidade_sel": unidade_sel,
        "sem_unidade": sem_unidade,
        "status_sel": status if status in dict(Computador.Status.choices) else "",
        # Unidade e situação no MESMO popup das outras telas de lista. A opção
        # "Sem unidade" continua sendo `?unidade=sem` (é a régua única do
        # `_unidade_computador`), agora como uma ficha do grupo em vez de um chip
        # solto na barra.
        **barra_filtros(request, [
            {"param": "unidade", "label": "Unidade", "todos": "Todas",
             "opcoes": [("sem", "Sem unidade")] + [(u.id, u.name) for u in _unis]},
            {"param": "status", "label": "Situação", "todos": "Todas",
             "opcoes": list(Computador.Status.choices)},
        ]),
    })
    return render(request, "parque/tabela_estoque.html", contexto)


# ---- FORA DE USO: desativadas + em estoque + ociosas (sem colaborador) --------
_FDU_STATUS_COMP = ["desativado", "em_estoque"]  # Computador.Status


def _fora_de_uso_total():
    """Nº total de máquinas fora de uso (para o card do hub Estoque)."""
    comps = Computador.objects.filter(status__in=_FDU_STATUS_COMP).count()
    pc_ocioso = (Baia.objects
                 .filter(computador__isnull=False, colaborador__isnull=True)
                 .exclude(computador__status__in=_FDU_STATUS_COMP).count())
    nb_ocioso = Notebook.objects.filter(colaborador__isnull=True).count()
    return comps + pc_ocioso + nb_ocioso


@staff_member_required
def fora_de_uso(request):
    """Lista UNIFICADA de máquinas FORA DE USO, cada uma com o MOTIVO:
      • Desativado / Em estoque   (Computador por status)
      • Sem colaborador           (Baia com PC, mas ninguém sentado)
      • Notebook sem uso          (Notebook sem colaborador)
    Serve para gerir o que pode ser trocado / realocado."""
    motivo_sel = (request.GET.get("motivo") or "").strip()
    linhas = []

    # 1) Computadores por status (desativado / em estoque)
    for c in Computador.objects.filter(status__in=_FDU_STATUS_COMP).select_related("baia__setor__unidade"):
        desativado = c.status == "desativado"
        try:
            baia = c.baia
        except ObjectDoesNotExist:
            baia = None
        uni = (baia.setor.unidade.name if baia else (c.ultima_unidade or ""))
        local = (f"{baia.setor.unidade.name} › {baia.setor.nome}" if baia
                 else (c.ultima_unidade or "—"))
        linhas.append({
            "tipo": "Computador", "ident": c.patrimonio or f"Computador #{c.pk}",
            "uni": uni,
            "local": local, "resumo": c.resumo_specs,
            "motivo": "Desativado" if desativado else "Em estoque",
            "motivo_key": "desativado" if desativado else "estoque",
            "motivo_cor": "#e0533f" if desativado else "#64748b",
            "edit": f"/admin/parque/computador/{c.pk}/change/",
            "acao_url": (f"/parque/reativar/{c.pk}/" if desativado else ""),
            "acao_txt": "Reativar" if desativado else "",
        })

    # 2) Baias com PC mas SEM colaborador (PC ocioso) — exclui já contados (estoque/desativado)
    for b in (Baia.objects
              .filter(computador__isnull=False, colaborador__isnull=True)
              .exclude(computador__status__in=_FDU_STATUS_COMP)
              .select_related("setor__unidade", "computador")):
        linhas.append({
            "tipo": "Computador", "ident": (b.computador.patrimonio or b.nome),
            "uni": (b.setor.unidade.name if b.setor.unidade_id else ""),
            "local": f"{b.setor.unidade.name} › {b.setor.nome} › {b.nome}", "resumo": b.resumo_pc,
            "motivo": "Sem colaborador", "motivo_key": "sem_colab", "motivo_cor": "#ef8f3c",
            "edit": f"/admin/parque/baia/{b.pk}/change/", "acao_url": "", "acao_txt": "",
        })

    # 3) Notebooks SEM colaborador
    for n in Notebook.objects.filter(colaborador__isnull=True):
        ident = (n.patrimonio or f"{n.marca} {n.modelo}").strip() or f"Notebook #{n.pk}"
        linhas.append({
            "tipo": "Notebook", "ident": ident,
            # Notebook não tem FK de unidade: a localização dele é o texto
            # `unidade_setor` ("Loja › Setor"), então a unidade é o 1º pedaço.
            "uni": (n.unidade_setor or "").split("›")[0].strip(),
            "local": n.unidade_setor or "—", "resumo": n.resumo_specs,
            "motivo": "Notebook sem uso", "motivo_key": "notebook", "motivo_cor": "#e0533f",
            "edit": f"/admin/parque/notebook/{n.pk}/change/", "acao_url": "", "acao_txt": "",
        })

    # contagens por motivo ANTES de filtrar (para o rótulo de cada opção)
    from collections import Counter
    cont = Counter(l["motivo_key"] for l in linhas)
    motivos = [
        ("desativado", f"Desativados ({cont.get('desativado', 0)})", "Desativados"),
        ("sem_colab", f"Sem colaborador ({cont.get('sem_colab', 0)})", "Sem colaborador"),
        ("estoque", f"Em estoque ({cont.get('estoque', 0)})", "Em estoque"),
        ("notebook", f"Notebooks ({cont.get('notebook', 0)})", "Notebooks"),
    ]
    # Unidade é a segunda pergunta desta tela ("o que sobra em Bonsucesso?"), e
    # aqui ela SÓ pode ser filtrada em Python: a lista mistura três consultas e
    # a unidade do notebook é texto, não FK. As opções são as unidades que
    # realmente aparecem na lista — nada de oferecer loja sem máquina parada.
    unis_fdu = sorted({l["uni"] for l in linhas if l["uni"]})
    uni_sel = (request.GET.get("unidade") or "").strip()

    if motivo_sel:
        linhas = [l for l in linhas if l["motivo_key"] == motivo_sel]
    if uni_sel:
        linhas = [l for l in linhas if l["uni"] == uni_sel]
    for l in linhas:
        l["busca"] = " ".join(filter(None, [l["ident"], l["local"], l["resumo"], l["motivo"], l["tipo"]])).lower()
    ordem = {"desativado": 0, "sem_colab": 1, "estoque": 2, "notebook": 3}
    linhas.sort(key=lambda l: (ordem.get(l["motivo_key"], 9), l["ident"]))

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Fora de uso", "titulo": "Fora de uso",
        "total": len(linhas), "linhas": linhas,
        "motivo_sel": motivo_sel,
        **barra_filtros(request, [
            {"param": "motivo", "label": "Motivo", "todos": "Todos", "opcoes": motivos},
            {"param": "unidade", "label": "Unidade", "todos": "Todas",
             "opcoes": [(u, u) for u in unis_fdu]},
        ]),
        **_voltar("/parque/estoque/"),
    })
    return render(request, "parque/fora_de_uso.html", contexto)


@staff_member_required
def tabela_pecas(request):
    """Modo TABELA das peças / periféricos — mesmo tema do mapa/tabela."""
    qs = Peca.objects.select_related("unidade").order_by("tipo", "descricao", "unidade__name")
    uid = request.GET.get("unidade")
    unidade_sel = int(uid) if (uid and uid.isdigit()) else None
    if unidade_sel:
        qs = qs.filter(unidade_id=unidade_sel)

    # Tipo e situação do estoque entram no MESMO popup da unidade (o botão
    # "Filtrar" de toda tela de lista). Peça tem centenas de linhas e é sempre a
    # mesma pergunta: "quanta memória tem em Bonsucesso?", "o que está em falta?".
    unidades_pecas = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    tipo_sel = (request.GET.get("tipo") or "").strip()
    if tipo_sel in dict(Peca.Tipo.choices):
        qs = qs.filter(tipo=tipo_sel)
    estoque_sel = (request.GET.get("estoque") or "").strip()
    if estoque_sel == "falta":
        qs = qs.filter(quantidade__lte=0)      # `Peca.em_falta` é quantidade <= 0
    elif estoque_sel == "ok":
        qs = qs.filter(quantidade__gt=0)

    linhas = []
    for p in qs:
        falta = p.em_falta
        linhas.append({
            "pk": p.pk,
            "tipo": p.get_tipo_display(),
            "descricao": p.descricao,
            "unidade": p.unidade.name if p.unidade_id else "—",
            "quantidade": p.quantidade,
            "estoque_label": "Em falta" if falta else "OK",
            "estoque_cor": "#e0533f" if falta else "#00a651",
            "edit": f"/admin/parque/peca/{p.pk}/change/",
            "transferir": f"/parque/peca/{p.pk}/transferir/",
        })

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Peças / Periféricos",
        "titulo": "Peças / Periféricos",
        "total": len(linhas),
        "linhas": linhas,
        "modelo": "peca",
        **_voltar("/parque/estoque/"),
        "novo_url": "/admin/parque/peca/add/",
        "caixa_url": "/parque/montar-caixa/",
        "pode_excluir": request.user.has_perm("parque.delete_peca"),
        "unidades": unidades_pecas,
        "unidade_sel": unidade_sel,
        **barra_filtros(request, [
            {"param": "unidade", "label": "Unidade", "todos": "Todas",
             "opcoes": [(u.id, u.name) for u in unidades_pecas]},
            {"param": "tipo", "label": "Tipo", "todos": "Todos",
             "opcoes": list(Peca.Tipo.choices)},
            {"param": "estoque", "label": "Estoque", "todos": "Qualquer",
             "opcoes": [("falta", "Em falta"), ("ok", "Com estoque")]},
        ]),
    })
    return render(request, "parque/tabela_pecas.html", contexto)


@staff_member_required
@require_POST
def excluir_dispositivos(request):
    """Exclui em lote os itens marcados na tela de tabela (computadores/notebooks/peças)."""
    modelos = {"baia": (Baia, "parque.delete_baia"), "notebook": (Notebook, "parque.delete_notebook"),
               "peca": (Peca, "parque.delete_peca"), "computador": (Computador, "parque.delete_computador")}
    modelo = request.POST.get("modelo")
    destino = destino_seguro(request, request.POST.get("next"),
                             padrao="/parque/tabela-computadores/")
    par = modelos.get(modelo)
    if not par:
        return redirect(destino)
    Model, perm = par
    if not request.user.has_perm(perm):
        messages.error(request, "Você não tem permissão para excluir estes itens.")
        return redirect(destino)
    ids = [i for i in request.POST.getlist("itens") if i.isdigit()]
    if ids:
        qtd, _ = Model.objects.filter(pk__in=ids).delete()
        messages.success(request, f"{len(ids)} item(ns) excluído(s).")
    return redirect(destino)



def _filtrar_por_vencimento(estrut, ate=None, desde=None):
    """Mantém na estrutura do mapa só as baias cuja PREVENTIVA vence na janela.

    Pedido do dono: "tem que ter a opção de filtrar por data também". No mapa a
    data que importa é a do CICLO DE PREVENTIVA — é a única que responde a uma
    pergunta operacional ("o que vence este mês?", "o que já venceu?"). Data de
    compra e última coleta viram filtro de relatório, não de mapa.

    Filtra em Python, e não no banco, porque `preventiva_vencimento` é
    PROPRIEDADE CALCULADA (última preventiva concluída + PREVENTIVA_DIAS), não
    coluna — não há como filtrar nem ordenar por ela em SQL. Com 140 baias e 32
    notebooks isso é irrelevante; passando de alguns milhares, o vencimento
    precisa virar coluna gravada. Está anotado em docs/AUDITORIA-BACKEND.md.

    Roda ANTES do `_resumo_parque()`, então as contagens do topo acompanham o
    filtro em vez de mentir.
    """
    if not ate and not desde:
        return estrut

    def cabe(b):
        v = getattr(b, "preventiva_vencimento", None)
        if v is None:
            return False          # baia vazia não tem ciclo: sai da janela
        if desde and v < desde:
            return False
        if ate and v > ate:
            return False
        return True

    saida = []
    for u in estrut:
        setores = []
        for s in u.get("setores", []):
            baias = [b for b in s.get("baias", []) if cabe(b)]
            if not baias:
                continue
            novo = dict(s)
            novo["baias"] = baias
            novo["qtd_criticas"] = sum(
                1 for b in baias if getattr(b, "classe_desempenho", "") == "Crítico")
            setores.append(novo)
        nbs = [n for n in u.get("notebooks", []) if cabe(n)]
        if not setores and not nbs:
            continue
        nova = dict(u)
        nova["setores"] = setores
        nova["notebooks"] = nbs
        saida.append(nova)
    return saida


def _janela_de_data(request):
    """Lê `?vence_ate=` e `?vence_desde=` (YYYY-MM-DD). Data inválida é ignorada
    em silêncio — filtro na querystring não deve derrubar a tela."""
    def ler(chave):
        v = (request.GET.get(chave) or "").strip()
        if not v:
            return None
        try:
            a, m, d = (int(x) for x in v.split("-"))
            return date(a, m, d)
        except (ValueError, TypeError):
            return None
    return ler("vence_ate"), ler("vence_desde")

@staff_member_required
def mapa_completo(request):
    """Mapa COMPLETO: todas as lojas › setores › baias (computadores).

    Usa o MESMO mapa rico da loja (mapa.html), percorrendo todas as unidades —
    com arrastar p/ transferir, +Setor/+Baia e notebooks. Clicar numa baia abre o
    monitor. Setores sem PC ficam ocultos (mapa enxuto).
    """
    unidades = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    # Filtro por unidade (chips) — mostra só a loja escolhida, ou todas.
    uni_sel = request.GET.get("unidade")
    uni_obj = next((u for u in unidades if str(u.id) == uni_sel), None)
    exibir = [uni_obj] if uni_obj else unidades
    setores_sel = [s.strip() for s in request.GET.getlist("setor") if s.strip()]
    unidades_estrut, total = _mapa_estrutura_rica(
        exibir, ocultar_vazios=True, setores_sel=setores_sel or None)
    # Filtro de DATA (vencimento da preventiva). Aplicado antes do resumo, para
    # que as contagens do topo reflitam o filtro.
    vence_ate, vence_desde = _janela_de_data(request)
    if vence_ate or vence_desde:
        unidades_estrut = _filtrar_por_vencimento(unidades_estrut, vence_ate, vence_desde)
        total = sum(len(se["baias"]) for u in unidades_estrut for se in u["setores"])
    # Transferência entre lojas (ou interna) no próprio mapa: destinos = todas as lojas.
    destinos = [{"unidade": u, "estrutura": _estrutura_unidade(u)} for u in unidades]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "unica": None,
        # Título reflete o filtro: uma loja selecionada mostra o nome dela.
        "titulo": uni_obj.name if uni_obj else "Mapa completo — todas as lojas",
        "unidades_estrut": unidades_estrut,
        "resumo": _resumo_parque(unidades_estrut),
        "vence_ate": vence_ate.isoformat() if vence_ate else "",
        "vence_desde": vence_desde.isoformat() if vence_desde else "",
        "cargos": _cargos_distintos(),
        **_filtros_ctx(request, unidades, por_nome=False, com_setor=True),
        "total": total,
        "title": uni_obj.name if uni_obj else "Mapa completo",
        "view_atual": "mapa",
        "view_mapa": "/parque/mapa-completo/",
        "view_tabela": "/parque/tabela-computadores/",
        "transferir_url": reverse("parque_transferir_entre_lojas"),
        "destinos": destinos,
        "pode_mover": pode_mover_baia(request.user),
        "pode_add_baia": request.user.has_perm("parque.add_baia"),
        "pode_add_setor": request.user.has_perm("parque.add_setor"),
        **_stn_ctx(),
        "pode_ver_estoque": request.user.has_perm("parque.view_computador"),
        "colaboradores": _colaboradores_baia(),
        "computadores_estoque": _computadores_estoque(),
        "notebooks_disponiveis": _notebooks_disponiveis(),
        "pode_atribuir_colab": request.user.has_perm("parque.change_baia"),
    })
    return render(request, "parque/mapa.html", contexto)


@staff_member_required
@require_POST
def mover_baia(request):
    """Drag-and-drop: move a baia para outro setor (mesma unidade).

    Autorizado (GRUPOS_MOVIMENTACAO) aplica direto; os demais geram uma
    solicitação pendente. Registra tudo em MovimentacaoBaia.
    """
    baia = get_object_or_404(Baia.objects.select_related("setor"), pk=request.POST.get("baia_id"))
    destino = get_object_or_404(Setor.objects.select_related("unidade"), pk=request.POST.get("setor_destino_id"))

    if destino.unidade_id != baia.setor.unidade_id:
        return JsonResponse({"ok": False, "erro": "Só é possível mover dentro da mesma loja."}, status=400)
    if destino.id == baia.setor_id:
        return JsonResponse({"ok": False, "erro": "A baia já está nesse setor."}, status=400)
    if Baia.objects.filter(setor=destino, nome=baia.nome).exclude(pk=baia.pk).exists():
        return JsonResponse(
            {"ok": False, "erro": f"Já existe uma baia \"{baia.nome}\" no setor de destino."},
            status=400,
        )

    mov = MovimentacaoBaia(
        baia=baia, setor_origem=baia.setor, setor_destino=destino, solicitante=request.user,
    )
    mov.capturar_snapshot()
    if pode_mover_baia(request.user):
        mov.aplicar(request.user)
        return JsonResponse({"ok": True, "status": "aplicada", "msg": "Baia movida com sucesso."})
    mov.status = MovimentacaoBaia.Status.PENDENTE
    mov.save()
    return JsonResponse({
        "ok": True, "status": "solicitada",
        "msg": "Solicitação de movimentação enviada para autorização.",
    })


@staff_member_required
def reativar_computador(request, pk):
    """Reativa um computador DESATIVADO, realocando-o numa baia vazia (Unidade › Baia)."""
    if not request.user.has_perm("parque.change_baia"):
        messages.error(request, "Você não tem permissão para reativar computadores.")
        return redirect("admin:parque_computador_changelist")

    comp = get_object_or_404(Computador, pk=pk)
    if comp.status != Computador.Status.DESATIVADO:
        messages.warning(request, "Este computador não está desativado.")
        return redirect("admin:parque_computador_changelist")

    if request.method == "POST":
        baia = get_object_or_404(Baia.objects.select_related("setor"), pk=request.POST.get("baia_id"))
        if baia.computador_id:
            messages.error(request, "Essa baia já tem um computador vinculado. Escolha outra.")
        else:
            # 2 escritas: falha entre elas deixava o computador "em uso" sem
            # baia nenhuma — máquina invisível no mapa e no estoque.
            with transaction.atomic():
                comp.status = Computador.Status.EM_USO
                comp.save(update_fields=["status"])
                baia.computador = comp
                baia.save()  # signals: status do computador / departamento (situação derivada)
            messages.success(request, f"{comp.patrimonio} reativado e instalado em {baia}.")
            return redirect("admin:parque_computador_changelist")

    baias_vazias = (
        Baia.objects.filter(computador__isnull=True)
        .select_related("setor__unidade")
        .order_by("setor__unidade__name", "setor__nome", "nome")
    )
    unidades = Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "comp": comp, "baias_vazias": baias_vazias, "unidades": unidades,
        "title": f"Reativar {comp.patrimonio}",
        **_voltar("/parque/tabela-estoque-computadores/"),
    })
    return render(request, "parque/reativar.html", contexto)


@staff_member_required
def proximo_patrimonio_preview(request):
    """Pré-visualização do patrimônio que será gerado para uma unidade."""
    # `?unidade=abc` estourava ValueError aqui — e é querystring, a coisa mais
    # fácil de errar. id_ou_nada devolve None e a resposta vira {"ok": false}.
    uni = Location.objects.filter(pk=id_ou_nada(request.GET.get("unidade"))).first()
    if not uni:
        return JsonResponse({"ok": False})
    return JsonResponse({"ok": True, "patrimonio": proximo_patrimonio(uni.name)})


@staff_member_required
@require_POST
def trocar_pcs(request):
    """Troca o computador (e specs) entre duas baias — 'mudar o PC entre consultores'.

    Autorizado (GRUPOS_MOVIMENTACAO) troca direto; os demais geram uma
    solicitação pendente (igual ao mover). Registra em MovimentacaoBaia.
    """
    a = get_object_or_404(Baia.objects.select_related("setor"), pk=request.POST.get("baia_a"))
    b = get_object_or_404(Baia.objects.select_related("setor"), pk=request.POST.get("baia_b"))
    if a.pk == b.pk:
        return JsonResponse({"ok": False, "erro": "Selecione duas baias diferentes."}, status=400)

    mov = MovimentacaoBaia(
        tipo=MovimentacaoBaia.Tipo.TROCAR,
        baia=a, baia_parceira=b,
        setor_origem=a.setor, setor_destino=b.setor,
        solicitante=request.user,
    )
    mov.capturar_snapshot()
    if pode_mover_baia(request.user):
        mov.aplicar(request.user)
        return JsonResponse({"ok": True, "status": "aplicada", "msg": "Computadores trocados entre as baias."})
    mov.status = MovimentacaoBaia.Status.PENDENTE
    mov.save()
    return JsonResponse({
        "ok": True, "status": "solicitada",
        "msg": "Solicitação de troca enviada para autorização.",
    })


@staff_member_required
def baia_specs(request, pk):
    """Specs efetivas de uma baia (para auto-preencher o form de Transferência)."""
    b = get_object_or_404(Baia.objects.select_related("computador", "colaborador"), pk=pk)
    return JsonResponse({
        "ok": True,
        "so": b.eff_so or "", "cpu": b.eff_cpu or "", "placa": b.eff_placa or "",
        "ram": b.eff_ram or "", "disco": b.eff_disco or "",
        "colaborador": str(b.colaborador) if b.colaborador_id else "",
    })


@staff_member_required
@require_POST
def finalizar_reparo(request, baia_id):
    """Finaliza o(s) reparo(s) em andamento de uma baia (fecha a tarefa no Bitrix)."""
    if not request.user.has_perm("parque.change_reparo"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para finalizar reparo."}, status=403)
    baia = get_object_or_404(Baia.objects.prefetch_related("reparos"), pk=baia_id)
    # Fecha QUALQUER chamado aberto da máquina (com ou sem previsão), não só os
    # "em manutenção" — era o que impedia finalizar chamados "Abertos" pelo mapa.
    pendentes = baia.reparos_abertos
    if not pendentes:
        return JsonResponse({"ok": False, "erro": "Não há chamado aberto nesta máquina."}, status=400)
    # Em lote: ou fecha TODOS os chamados da máquina, ou nenhum. Sem isto, uma
    # falha no 3º de 5 deixava dois fechados, três abertos e possivelmente um
    # colaborador preso na mesa temporária.
    with transaction.atomic():
        for r in pendentes:
            r.finalizar()
    return JsonResponse({"ok": True, "n": len(pendentes), "msg": "Chamado finalizado."})


def _icone_setor(nome):
    """Ícone Material que representa o departamento, pelo nome do setor."""
    import unicodedata
    base = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    pares = [
        ("caixa", "point_of_sale"), ("intelig", "insights"), ("comercial", "handshake"),
        ("vendas", "handshake"), ("financ", "payments"), ("contab", "receipt_long"),
        ("fiscal", "receipt_long"), ("logistic", "local_shipping"), ("expedi", "local_shipping"),
        ("pos venda", "support_agent"), ("posvenda", "support_agent"),
        ("recursos humanos", "groups"), ("rma", "assignment_return"), ("trein", "school"),
        ("marketing", "campaign"), ("diretor", "corporate_fare"), ("recep", "co_present"),
        ("estoque", "inventory_2"), ("almox", "inventory_2"), ("compras", "shopping_cart"),
        ("atendimento", "headset_mic"), ("sac", "headset_mic"), ("suporte", "headset_mic"),
        ("infra", "dns"), ("tecnolog", "dns"),
    ]
    for chave, icone in pares:
        if chave in base:
            return icone
    if base.strip() in ("rh",) or base.strip().startswith("rh "):
        return "groups"
    if base.strip() in ("ti",) or base.strip().startswith("ti "):
        return "dns"
    return "meeting_room"


@staff_member_required
def setores_lista(request):
    """Setores AGRUPADOS por unidade (a loja vira cabeçalho — não se repete em
    cada linha). Cada setor mostra a contagem de baias. Filtro por unidade."""
    # TODAS as unidades (inclusive sem setores ainda — p/ adicionar o 1º setor
    # logo após criar a unidade).
    unidades = list(Location.objects.all().order_by("name"))
    uni_sel = request.GET.get("unidade")
    uni_obj = next((u for u in unidades if str(u.id) == uni_sel), None)

    por_uni = {}
    for s in (Setor.objects.select_related("unidade").annotate(n_baias=Count("baias")).order_by("nome")):
        s.icone = _icone_setor(s.nome)
        por_uni.setdefault(s.unidade_id, []).append(s)

    lista = [uni_obj] if uni_obj else unidades
    grupos = [{"unidade": u, "setores": por_uni.get(u.id, [])} for u in lista]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Unidades / Setores",
        "grupos": grupos,
        **_filtros_ctx(request, unidades, por_nome=False),
        "total": sum(len(g["setores"]) for g in grupos),
        "pode_add": request.user.has_perm("parque.add_setor"),
        "pode_add_unidade": request.user.has_perm("orgs.add_location"),
        **_stn_ctx(),
    })
    return render(request, "parque/setores_lista.html", contexto)


@staff_member_required
def reparos_kanban(request):
    """Reparos / Manutenções em QUADRO KANBAN — cards flutuantes por situação.

    Colunas: Abertos · Aguardando peça (cotação) · Em manutenção · Finalizados.
    Filtro por unidade (chips), igual às outras telas do parque.
    """
    qs = (
        Reparo.objects.select_related(
            "baia__setor__unidade", "baia__colaborador", "baia__computador",
            "notebook", "tecnico", "orcamento"
        ).order_by("-data", "-created_at")
    )
    unidades = list(Location.objects.filter(setores__isnull=False).distinct().order_by("name"))
    uni_sel = request.GET.get("unidade")
    uni_obj = next((u for u in unidades if str(u.id) == uni_sel), None)
    if uni_obj:
        qs = qs.filter(baia__setor__unidade=uni_obj)

    cols = [
        {"key": "abertos", "titulo": "Abertos", "icone": "inbox", "itens": []},
        {"key": "cotacao", "titulo": "Aguardando peça", "icone": "cart", "itens": []},
        {"key": "manutencao", "titulo": "Em manutenção", "icone": "wrench", "itens": []},
        {"key": "finalizados", "titulo": "Finalizados", "icone": "check", "itens": []},
    ]
    por_key = {c["key"]: c for c in cols}
    for r in qs:
        if r.concluido_em:
            key = "finalizados"
        elif r.realizar_cotacao:
            key = "cotacao"
        elif r.previsao_conclusao:
            key = "manutencao"
        else:
            key = "abertos"
        por_key[key]["itens"].append(r)
    for c in cols:
        c["qtd"] = len(c["itens"])

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Chamados",
        "colunas": cols,
        **_filtros_ctx(request, unidades, por_nome=False),
        "total": sum(c["qtd"] for c in cols),
    })
    return render(request, "parque/reparos_kanban.html", contexto)


def _painel_tarefas(request):
    """Aba TAREFAS da tela de preventivas: painel de saúde por responsável.

    Mostra as tarefas ABERTAS (sem telemetria / uptime alto / score baixo) da
    unidade do usuário (gestão vê todas, com filtro de unidade). Cada card tem
    a métrica relevante + botões Concluir / Dispensar."""
    user = request.user
    unidades_loc = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    qs = (
        Tarefa.objects.filter(status=Tarefa.Status.ABERTA)
        .select_related(
            "baia__setor__unidade", "baia__computador", "baia__colaborador",
            "notebook__colaborador", "unidade", "responsavel")
    )
    gestao = ve_tudo(user)
    minha_unidade = unidade_do_usuario(user)
    if gestao:
        uni_nome = (request.GET.get("unidade") or "").strip()
        if uni_nome:
            qs = qs.filter(unidade__name=uni_nome)
    else:
        qs = qs.filter(unidade=minha_unidade) if minha_unidade else qs.none()

    setores_lower = {s.strip().lower() for s in request.GET.getlist("setor") if s.strip()}

    secoes = {
        Tarefa.Tipo.SEM_TELEMETRIA: {
            "key": "sem_telemetria", "titulo": "Sem telemetria ativa", "icone": "antenna",
            "ajuda": "O agente não está reportando — instale/relance para acompanhar a máquina.",
            "itens": []},
        Tarefa.Tipo.UPTIME_ALTO: {
            "key": "uptime_alto", "titulo": "Ligada há muito tempo", "icone": "flame",
            "ajuda": "Ligada direto há dias — programe um reinício.",
            "itens": []},
        Tarefa.Tipo.SCORE_BAIXO: {
            "key": "score_baixo", "titulo": "Score baixo", "icone": "trend-down",
            "ajuda": "Desempenho em faixa Crítica/Baixa — avalie upgrade ou troca.",
            "itens": []},
    }

    for t in qs.order_by("-criada_em"):
        if t.baia_id:
            b = t.baia
            setor_nome = b.setor.nome if b.setor_id else ""
            score, classe = b.indice_desempenho, b.classe_desempenho
            disp = b.computador
            colaborador = b.colaborador.full_name if b.colaborador_id else ""
            card_baia, resumo = b, b.resumo_pc
        else:
            n = t.notebook
            setor_nome = ""
            score, classe = n.indice_desempenho, n.classe_desempenho
            disp = n
            colaborador = n.usuario or (n.colaborador.full_name if n.colaborador_id else "")
            try:
                card_baia = n.baia
            except ObjectDoesNotExist:
                card_baia = None
            resumo = getattr(n, "resumo_specs", "")
        if setores_lower and setor_nome.lower() not in setores_lower:
            continue

        # Métrica mostrada no card (sem emoji — o ícone é SVG no template).
        if t.tipo == Tarefa.Tipo.UPTIME_ALTO:
            metrica = f"ligada há {getattr(disp, 'tel_uptime_humano', '—')}"
        elif t.tipo == Tarefa.Tipo.SCORE_BAIXO:
            metrica = f"score {score} · {classe}" if score is not None else "score —"
        else:  # sem telemetria
            visto = getattr(disp, "tel_visto_em", None)
            metrica = ("nunca reportou" if not visto
                       else f"última coleta {timezone.localtime(visto):%d/%m %H:%M}")

        secoes[t.tipo]["itens"].append({
            "id": t.pk, "tipo": t.tipo, "titulo": t.titulo, "detalhe": t.detalhe,
            "patrimonio": t.patrimonio, "local": t.local, "colaborador": colaborador,
            "eh_notebook": t.eh_notebook, "metrica": metrica,
            "responsavel": t.responsavel.get_full_name() or t.responsavel.username if t.responsavel_id else "",
            "acao_url": t.acao_url, "verkey": f"{t.tipo}-{t.pk}",
            "card_baia": card_baia, "resumo": resumo or "—", "score": score, "classe": classe,
            "kind": "baia" if t.baia_id else "nb", "maquina_pk": t.baia_id or t.notebook_id,
        })

    secoes_list = [secoes[k] for k in
                   (Tarefa.Tipo.SEM_TELEMETRIA, Tarefa.Tipo.UPTIME_ALTO, Tarefa.Tipo.SCORE_BAIXO)]
    _TONE = {"sem_telemetria": "green", "uptime_alto": "amber", "score_baixo": "purple"}
    for s in secoes_list:
        s["qtd"] = len(s["itens"])
        s["tone"] = _TONE.get(s["key"], "green")
    total = sum(s["qtd"] for s in secoes_list)

    # --- Desempenho do usuário logado (gráfico de boas-vindas + KPIs) ---
    hoje = timezone.localdate()
    meus = Reparo.objects.filter(
        tipo=Reparo.Tipo.PREVENTIVA, concluido_em__isnull=False, tecnico=user)
    _MES = ["", "jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"]
    meses = []
    for i in range(5, -1, -1):
        a, m = hoje.year, hoje.month - i
        while m <= 0:
            m += 12
            a -= 1
        meses.append((a, m))
    chart_labels = [_MES[m] for _, m in meses]
    chart_serie = [
        meus.filter(concluido_em__year=a, concluido_em__month=m)
            .aggregate(s=Sum("pontos"))["s"] or 0
        for a, m in meses
    ]
    tot = meus.aggregate(s=Sum("pontos"), n=Count("id"))
    pontos_total, n_total = tot["s"] or 0, tot["n"] or 0
    pontos_mes = chart_serie[-1]
    mensal_rows = list(Reparo.objects.filter(
        tipo=Reparo.Tipo.PREVENTIVA, concluido_em__year=hoje.year,
        concluido_em__month=hoje.month, tecnico__isnull=False
    ).values("tecnico").annotate(pts=Sum("pontos")).order_by("-pts"))
    posicao = next((i for i, r in enumerate(mensal_rows, 1) if r["tecnico"] == user.pk), None)

    # Nível/medalha do usuário conforme os pontos do MÊS — muda a cor do hero.
    # Limites ajustáveis: Bronze≥1, Prata≥10, Ouro≥25, Diamante≥50.
    _NIVEIS = [(1, "bronze", "Bronze"), (10, "prata", "Prata"),
               (25, "ouro", "Ouro"), (50, "diamante", "Diamante")]
    nivel, nivel_nome, nivel_prox, _prox_min = "zero", "Iniciante", "", None
    for _min, _key, _label in _NIVEIS:
        if pontos_mes >= _min:
            nivel, nivel_nome = _key, _label
        elif _prox_min is None:
            nivel_prox, _prox_min = _label, _min
    nivel_faltam = (_prox_min - pontos_mes) if _prox_min else 0

    _mx = max(chart_serie) or 1
    chart_bars = [{"mes": chart_labels[i], "pct": round(chart_serie[i] * 100 / _mx),
                   "v": chart_serie[i]} for i in range(len(chart_serie))]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Preventiva",
        "vista": "tarefas",
        "secoes": secoes_list,
        "total": total,
        "gestao": gestao,
        "minha_unidade": minha_unidade.name if minha_unidade else "",
        "saudacao_nome": (user.get_full_name() or user.username).split(" ")[0],
        "chart_data": {"labels": chart_labels, "data": chart_serie},
        "chart_bars": chart_bars,
        # Gráfico de volume concluído (topo da tela) — o mesmo das outras vistas.
        "pvg": _grafico_preventiva(),
        "pontos_mes": pontos_mes, "pontos_total": pontos_total,
        "n_total": n_total, "posicao": posicao,
        "nivel": nivel, "nivel_nome": nivel_nome,
        "nivel_prox": nivel_prox, "nivel_faltam": nivel_faltam,
        **_filtros_ctx(request, unidades_loc, por_nome=True, com_setor=True),
        **_voltar("/admin/"),
    })
    return render(request, "parque/preventiva_tarefas.html", contexto)


@staff_member_required
@require_POST
def tarefa_acao(request):
    """Conclui ou dispensa uma tarefa de saúde (painel de preventivas)."""
    tid = request.POST.get("tarefa_id")
    acao = (request.POST.get("acao") or "").strip()
    obs = (request.POST.get("observacao") or "").strip()
    tarefa = get_object_or_404(Tarefa, pk=tid)
    if acao == "concluir":
        tarefa.status = Tarefa.Status.CONCLUIDA
        msg = "Tarefa concluída."
    elif acao == "dispensar":
        tarefa.status = Tarefa.Status.DISPENSADA
        msg = "Tarefa dispensada."
    else:
        raise Http404()
    tarefa.observacao = obs
    tarefa.fechada_em = timezone.now()
    tarefa.fechada_por = request.user
    tarefa.save(update_fields=["status", "observacao", "fechada_em",
                               "fechada_por", "atualizada_em"])
    messages.success(request, msg)
    destino = voltar_para(request, padrao="/parque/preventiva/?vista=tarefas")
    return redirect(destino)


# ---------------------------------------------------------------------------
# GRÁFICO DO TOPO DA PREVENTIVA — volume de trabalho concluído por semana.
#
# Duas séries porque a pergunta que interessa não é "quantas preventivas?", é
# "a equipe está mantendo ou apagando incêndio?". Verde = preventiva concluída,
# coral = corretiva (reparo/upgrade/periférico/desativação). A fonte é a mesma
# da tela de Registros: `Reparo.concluido_em`, ou seja, só trabalho FEITO.
#
# A curva é desenhada no servidor (path SVG pronto no contexto): sem
# biblioteca de gráfico, sem JS, e o desenho já vem certo no primeiro quadro.
# ---------------------------------------------------------------------------
def _curva_svg(vals, larg, base, topo, maxv):
    """Devolve (path da área, path da linha) suavizados para uma série.

    Suavização com Bézier cúbica de controles horizontais (1/3 do passo): a
    curva passa exatamente pelos pontos e chega neles com tangente horizontal,
    que é o desenho de onda macia do modelo — e não estoura para fora do
    intervalo como um Catmull-Rom solto faria num pico isolado.
    """
    n = len(vals)
    if n < 2:
        return "", ""
    passo = larg / (n - 1)
    alt = base - topo
    pts = [(i * passo, base - (v / maxv) * alt) for i, v in enumerate(vals)]
    d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(n - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        c = passo / 3
        d += f" C {x0 + c:.1f},{y0:.1f} {x1 - c:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
    area = f"{d} L {pts[-1][0]:.1f},{base:.1f} L {pts[0][0]:.1f},{base:.1f} Z"
    return area, d


def _grafico_preventiva():
    """Série MENSAL do ano corrente: preventivas x corretivas registradas.

    A fonte é `Reparo.data` (a data do serviço), a MESMA que o painel
    "Manutenção preventiva por mês" do Dashboard usa — e não `concluido_em`.
    Motivo prático: `concluido_em` só existe no chamado que passou pelo fluxo
    de finalização (hoje, 4 registros), enquanto `data` está preenchida em
    todo serviço lançado. Duas telas contando a mesma coisa de formas
    diferentes é pior que uma só, e o gráfico precisa da base cheia.
    """
    hoje = timezone.localdate()
    meses = list(range(1, hoje.month + 1))
    prev = [0] * len(meses)
    corr = [0] * len(meses)
    for tipo, dia in (Reparo.objects
                      .filter(data__year=hoje.year)
                      .values_list("tipo", "data")):
        if not dia:
            continue
        i = dia.month - 1
        if 0 <= i < len(meses):
            if tipo == Reparo.Tipo.PREVENTIVA:
                prev[i] += 1
            else:
                corr[i] += 1

    # Cabeçalho no formato do modelo: número do mês · total do ano · variação.
    no_mes = prev[-1] if prev else 0
    mes_ant = prev[-2] if len(prev) > 1 else 0
    variacao = round((no_mes - mes_ant) * 100 / mes_ant) if mes_ant else None

    larg, base, topo = 1000.0, 190.0, 18.0
    maxv = max(max(prev + corr), 1)
    a_prev, l_prev = _curva_svg(prev, larg, base, topo, maxv)
    a_corr, l_corr = _curva_svg(corr, larg, base, topo, maxv)

    passo = larg / (len(meses) - 1) if len(meses) > 1 else larg
    nomes = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    rotulos = [{
        "x": round(i * passo, 1),
        "txt": nomes[m - 1],
        "anchor": "start" if i == 0 else ("end" if i == len(meses) - 1 else "middle"),
    } for i, m in enumerate(meses)]

    # Ordem de desenho: a série de área MAIOR vai atrás, senão ela tapa a
    # menor e a tela perde metade da informação (foi o que aconteceu quando
    # corretiva passou preventiva no segundo semestre).
    s_prev = {"area": a_prev, "linha": l_prev, "cor": "#00a651", "grad": "pvgPrev",
              "nome": "Preventivas"}
    s_corr = {"area": a_corr, "linha": l_corr, "cor": "#d97757", "grad": "pvgCorr",
              "nome": "Corretivas"}
    camadas = ([s_prev, s_corr] if sum(prev) >= sum(corr) else [s_corr, s_prev])

    return {
        "tem_dados": bool(sum(prev) or sum(corr)),
        "camadas": camadas,
        "no_mes": no_mes,
        "mes_nome": nomes[hoje.month - 1],
        "ano": hoje.year,
        "no_ano": sum(prev),
        "corretivas": sum(corr),
        "variacao": variacao,
        "sobe": (variacao or 0) >= 0,
        "area_prev": a_prev, "linha_prev": l_prev,
        "area_corr": a_corr, "linha_corr": l_corr,
        "rotulos": rotulos,
    }


@staff_member_required
def preventiva_kanban(request):
    """Manutenção PREVENTIVA em LISTA (estilo Google Tarefas): abas por status
    (Pendente · Vencida · Próxima · Em dia), filtro por unidade/setor e a bolinha
    de cada item conclui a preventiva (cria um Reparo preventivo já concluído,
    zerando o ciclo de 60 dias)."""
    # Cada usuário abre na SUA loja, na aba TAREFAS (padrão). Só na entrada "crua"
    # (sem querystring) — escolher "Todas" mantém ?vista=... e não cai de volta aqui.
    if not request.GET:
        pessoa = getattr(request.user, "colaborador", None)
        if pessoa is not None and pessoa.location_id:
            from urllib.parse import quote
            return redirect(
                f"/parque/preventiva/?vista=tarefas&unidade={quote(pessoa.location.name)}")
        return redirect("/parque/preventiva/?vista=tarefas")

    # --- Visões que não precisam do laço de preventiva do ciclo de 60 dias. ---
    _v = (request.GET.get("vista") or "").strip()
    if _v == "tarefas":
        return _painel_tarefas(request)
    if _v == "ranking":
        return _painel_ranking(request)
    if _v == "grupos":
        return _painel_grupos(request)

    uni_sel = (request.GET.get("unidade") or "").strip() or None
    setores_lower = {s.strip().lower() for s in request.GET.getlist("setor") if s.strip()}
    unidades_loc = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    unidades_lower = {u.name.lower(): u.name for u in unidades_loc}
    aliases = {"vilar dos teles": "Vilar", "vilar de teles": "Vilar"}

    cols = [
        {"key": "pendente", "titulo": "Pendente", "icone": "alert", "itens": []},
        {"key": "vencida", "titulo": "Vencida", "icone": "block", "itens": []},
        {"key": "proxima", "titulo": "Próxima", "icone": "⏰", "itens": []},
        {"key": "em_dia", "titulo": "Em dia", "icone": "check", "itens": []},
    ]
    por_key = {c["key"]: c for c in cols}

    # Adiamentos pendentes (1 query cada) para marcar badge nos itens.
    _adiar_baias = set(AdiamentoPreventiva.objects.filter(
        status=AdiamentoPreventiva.Status.PENDENTE, baia__isnull=False
    ).values_list("baia_id", flat=True))
    _adiar_nbs = set(AdiamentoPreventiva.objects.filter(
        status=AdiamentoPreventiva.Status.PENDENTE, notebook__isnull=False
    ).values_list("notebook_id", flat=True))

    def _add(kind, obj, uni, setor, titulo, patrimonio, colaborador, resumo, score, classe):
        st = obj.preventiva_status
        if st not in por_key:
            return
        if uni_sel and uni != uni_sel:
            return
        if setores_lower and (setor or "").lower() not in setores_lower:
            return
        if kind == "baia":
            card_baia = obj
        else:
            try:
                card_baia = obj.baia  # notebook alocado numa baia → usa o card da baia
            except ObjectDoesNotExist:
                card_baia = None
        pendente_adiar = obj.pk in (_adiar_baias if kind == "baia" else _adiar_nbs)
        por_key[st]["itens"].append({
            "card_baia": card_baia,
            "kind": kind, "pk": obj.pk, "titulo": titulo, "patrimonio": patrimonio,
            "local": f"{uni} › {setor}" if setor else uni, "unidade": uni, "setor": setor,
            "colaborador": colaborador, "dias": obj.dias_sem_preventiva,
            "vencimento": obj.preventiva_vencimento, "eh_notebook": kind == "nb",
            "tem_aberta": obj.tem_tarefa_preventiva_aberta, "status": st,
            "status_label": por_key[st]["titulo"],
            "resumo": resumo or "—", "score": score, "classe": classe,
            "adiada_ate": obj.preventiva_adiada_ate, "adiar_pendente": pendente_adiar,
        })

    # Computadores: só baias com DESKTOP (notebooks vêm do laço abaixo, evita duplicar).
    baias = (
        Baia.objects.select_related("setor__unidade", "colaborador", "computador")
        .prefetch_related("reparos")
    )
    for b in baias:
        if not b.computador_id:
            continue
        _add("baia", b, b.setor.unidade.name, b.setor.nome, b.nome,
             getattr(b.dispositivo, "patrimonio", "") or "",
             b.colaborador.full_name if b.colaborador_id else "",
             b.resumo_pc, b.indice_desempenho, b.classe_desempenho)

    # Notebooks (soltos ou em baia) — unidade/setor pela fonte única dos mapas.
    for n in Notebook.objects.select_related(
            "colaborador__location", "colaborador__department",
            "baia__setor__unidade").prefetch_related("reparos"):
        uni, setor = _unidade_setor_notebook(n, unidades_lower, aliases)
        _add("nb", n, uni, setor, f"{n.marca} {n.modelo}".strip() or "Notebook",
             n.patrimonio or "",
             n.usuario or (n.colaborador.full_name if n.colaborador_id else ""),
             n.resumo_specs, n.indice_desempenho, n.classe_desempenho)

    for c in cols:
        c["itens"].sort(key=lambda x: x["dias"], reverse=True)  # mais atrasadas 1º
        c["qtd"] = len(c["itens"])
    itens_all = [it for c in cols for it in c["itens"]]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Preventiva",
        "total": len(itens_all),
        "checklist_itens": PREVENTIVA_CHECKLIST,
        "status_meta": {c["key"]: {"titulo": c["titulo"], "icone": c["icone"]} for c in cols},
        # Gráfico do topo (mesmo objeto nas duas vistas desta view).
        "pvg": _grafico_preventiva(),
        **_filtros_ctx(request, unidades_loc, por_nome=True, com_setor=True),
        **_voltar("/admin/"),
    })

    vista = (request.GET.get("vista") or "calendario").strip()

    # --- Visão TABELA (rica, ordenada por urgência) ---
    if vista == "tabela":
        ordem = {"pendente": 0, "vencida": 1, "proxima": 2, "em_dia": 3}
        itens = sorted(itens_all, key=lambda x: (ordem.get(x["status"], 9), -x["dias"]))
        contexto.update({"vista": "tabela", "itens": itens})
        return render(request, "parque/preventiva_tabela.html", contexto)

    # --- Visão LISTA: removida. Redireciona p/ Tabela (preserva filtros). ---
    if vista == "lista":
        q = request.GET.copy()
        q["vista"] = "tabela"
        q.pop("status", None)
        return redirect(f"{request.path}?{q.urlencode()}")

    # --- Visão CALENDÁRIO mensal (padrão, estilo Google Agenda) ---
    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano") or hoje.year)
        mes = int(request.GET.get("mes") or hoje.month)
        # O ano também precisa de faixa: `?ano=-5` passava por aqui e estourava
        # em monthdatescalendar(-5, 9) — 500 em quem só mexeu na URL. A faixa é
        # a mesma da tela de Registros.
        if not (1 <= mes <= 12) or not (2000 <= ano <= 2100):
            raise ValueError
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month

    # Eventos por dia — cada máquina no DIA do vencimento (só os que vencem no mês).
    ev = {}
    for it in itens_all:
        d = it["vencimento"]
        if d and d.year == ano and d.month == mes:
            ev.setdefault(d, []).append(it)

    cal = _calendar.Calendar(firstweekday=6)  # domingo primeiro (pt-BR)
    semanas = []
    for semana in cal.monthdatescalendar(ano, mes):
        semanas.append([
            {"num": d.day, "data": d, "no_mes": d.month == mes, "hoje": d == hoje,
             "fds": d.weekday() >= 5,
             "eventos": sorted(ev.get(d, []), key=lambda x: (x["titulo"] or "").lower())}
            for d in semana
        ])

    prev_ano, prev_mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    prox_ano, prox_mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    contexto.update({
        "vista": "calendario",
        "primeiro_dia": date(ano, mes, 1),
        "ano": ano, "mes": mes,
        "semanas": semanas,
        "prev": {"ano": prev_ano, "mes": prev_mes},
        "prox": {"ano": prox_ano, "mes": prox_mes},
        "dias_semana": ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"],
        "no_mes_total": sum(len(v) for v in ev.values()),
    })
    return render(request, "parque/preventiva_calendario.html", contexto)


# Pontos por preventiva concluída (bônus por antecipação): quanto mais no prazo,
# mais pontos. em_dia = antecipada (3), proxima = no prazo (2), vencida/pendente = 1.
PONTOS_PREVENTIVA = {"em_dia": 3, "proxima": 2, "vencida": 1, "pendente": 1}


def _concluir_preventiva(alvo_obj, is_baia, user, descricao="", checklist=None):
    """Cria o Reparo-reset da preventiva (zera o ciclo), credita pontos a `user`
    (bônus por antecipação) e limpa o adiamento. Devolve os pontos ganhos."""
    pontos = PONTOS_PREVENTIVA.get(alvo_obj.preventiva_status or "pendente", 1)
    campos = dict(
        tipo=Reparo.Tipo.PREVENTIVA, titulo="Manutenção preventiva registrada",
        afeta_desempenho=False, concluido_em=timezone.localdate(),
        descricao=descricao or "", preventiva_checklist=",".join(checklist or []),
        tecnico=user, pontos=pontos,
    )
    r = Reparo(baia=alvo_obj, **campos) if is_baia else Reparo(notebook=alvo_obj, **campos)
    r.save()
    # Concluir supera qualquer adiamento pendente/aprovado (o ciclo recomeça).
    if alvo_obj.preventiva_adiada_ate:
        alvo_obj.preventiva_adiada_ate = None
        alvo_obj.save(update_fields=["preventiva_adiada_ate"])
    return pontos


@staff_member_required
def registrar_preventiva(request):
    """Registra uma preventiva CONCLUÍDA hoje (baia ou notebook), zerando o ciclo
    e creditando pontos a quem concluiu (ranking)."""
    if request.method != "POST":
        raise Http404()
    if not request.user.has_perm("parque.add_reparo"):
        messages.error(request, "Você não tem permissão para registrar preventivas.")
        return redirect("parque_preventiva_kanban")
    kind = request.POST.get("kind")
    pk = request.POST.get("pk")
    descricao = (request.POST.get("descricao") or "").strip()
    validas = {k for k, _ in PREVENTIVA_CHECKLIST}
    checklist = [c for c in request.POST.getlist("checklist") if c in validas]
    if kind == "baia":
        alvo_obj = get_object_or_404(Baia, pk=pk)
        alvo = alvo_obj.nome
    elif kind == "nb":
        alvo_obj = get_object_or_404(Notebook, pk=pk)
        alvo = str(alvo_obj)
    else:
        raise Http404()
    pontos = _concluir_preventiva(alvo_obj, kind == "baia", request.user, descricao, checklist)
    messages.success(
        request, f"Preventiva registrada para {alvo} (+{pontos} pts). "
                 f"Próxima em {PREVENTIVA_DIAS} dias.")
    return redirect(voltar_para(request, padrao="parque_preventiva_kanban"))


# =========================== RANKING DE PREVENTIVAS ==========================
def _unidade_nome_usuario(user):
    perfil = getattr(user, "perfil", None)
    if perfil is not None and perfil.unidade_id:
        return perfil.unidade.name
    pessoa = getattr(user, "colaborador", None)
    if pessoa is not None and pessoa.location_id:
        return pessoa.location.name
    return ""


def _painel_ranking(request):
    """Aba RANKING: pódio do mês + total acumulado por usuário (pts de preventiva)."""
    from django.contrib.auth.models import User
    hoje = timezone.localdate()
    base = Reparo.objects.filter(
        tipo=Reparo.Tipo.PREVENTIVA, concluido_em__isnull=False, tecnico__isnull=False)

    def agg(qs):
        rows = list(qs.values("tecnico").annotate(
            pts=Sum("pontos"), n=Count("id")).order_by("-pts", "-n"))
        ids = [r["tecnico"] for r in rows]
        users = {u.pk: u for u in User.objects.filter(pk__in=ids)}
        out = []
        for i, r in enumerate(rows, 1):
            u = users.get(r["tecnico"])
            if not u:
                continue
            out.append({
                "pos": i,
                "nome": u.get_full_name() or u.username,
                "unidade": _unidade_nome_usuario(u),
                "pts": r["pts"] or 0, "n": r["n"],
            })
        return out

    mensal = agg(base.filter(concluido_em__year=hoje.year, concluido_em__month=hoje.month))
    total = agg(base)

    _MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Preventiva", "vista": "ranking",
        "podio": mensal[:3], "mensal": mensal, "total": total,
        "mes_nome": _MESES[hoje.month], "ano": hoje.year,
        **_voltar("/admin/"),
    })
    return render(request, "parque/preventiva_ranking.html", contexto)


# =========================== GRUPOS DE MANUTENÇÃO ===========================
def _pode_ver_grupo(user, grupo):
    if ve_tudo(user):
        return True
    minha = unidade_do_usuario(user)
    return bool(minha and grupo.unidade_id == minha.id)


def _painel_grupos(request):
    """Aba GRUPOS: lista os grupos da unidade do usuário (gestão vê todos)."""
    qs = GrupoManutencao.objects.select_related("unidade", "criado_por").order_by("nome")
    if not ve_tudo(request.user):
        minha = unidade_do_usuario(request.user)
        qs = qs.filter(unidade=minha) if minha else qs.none()
    grupos = [{
        "obj": g, "nome": g.nome, "unidade": g.unidade.name if g.unidade_id else "",
        "total": g.total_membros,
    } for g in qs]
    unidades_loc = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name"))
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Preventiva", "vista": "grupos", "grupos": grupos,
        "gestao": ve_tudo(request.user),
        "minha_unidade": unidade_do_usuario(request.user),
        "unidades_novo": unidades_loc,
        **_voltar("/admin/"),
    })
    return render(request, "parque/grupos_lista.html", contexto)


@staff_member_required
@require_POST
def grupo_criar(request):
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Informe um nome para o grupo.")
        return redirect("/parque/preventiva/?vista=grupos")
    if ve_tudo(request.user):
        uid = request.POST.get("unidade_id")
        unidade = get_object_or_404(Location, pk=uid) if uid else unidade_do_usuario(request.user)
    else:
        unidade = unidade_do_usuario(request.user)
    if unidade is None:
        messages.error(request, "Sem unidade definida para criar o grupo.")
        return redirect("/parque/preventiva/?vista=grupos")
    g = GrupoManutencao.objects.create(nome=nome, unidade=unidade, criado_por=request.user)
    messages.success(request, f"Grupo “{g.nome}” criado.")
    return redirect("parque_grupo_detalhe", pk=g.pk)


@staff_member_required
def grupo_detalhe(request, pk):
    g = get_object_or_404(
        GrupoManutencao.objects.select_related("unidade"), pk=pk)
    if not _pode_ver_grupo(request.user, g):
        raise PermissionDenied()

    _ST_PREV = {"em_dia": "Em dia", "proxima": "Próxima",
                "vencida": "Vencida", "pendente": "Pendente"}
    membros = []
    for b in g.baias.select_related("setor__unidade", "computador", "colaborador").all():
        membros.append({
            "kind": "baia", "pk": b.pk, "nome": b.nome,
            "patrimonio": getattr(b.dispositivo, "patrimonio", "") or "",
            "status": b.preventiva_status,
            "status_label": _ST_PREV.get(b.preventiva_status, b.preventiva_status),
            "vencimento": b.preventiva_vencimento,
            "dias": b.dias_sem_preventiva,
            "colaborador": b.colaborador.full_name if b.colaborador_id else "",
        })
    for n in g.notebooks.select_related("colaborador").all():
        membros.append({
            "kind": "nb", "pk": n.pk,
            "nome": f"{n.marca} {n.modelo}".strip() or "Notebook",
            "patrimonio": n.patrimonio or "",
            "status": n.preventiva_status,
            "status_label": _ST_PREV.get(n.preventiva_status, n.preventiva_status),
            "vencimento": n.preventiva_vencimento,
            "dias": n.dias_sem_preventiva,
            "colaborador": n.usuario or (n.colaborador.full_name if n.colaborador_id else ""),
        })

    # Candidatas a adicionar: máquinas da unidade do grupo ainda fora dele.
    ja_baias = set(g.baias.values_list("pk", flat=True))
    ja_nbs = set(g.notebooks.values_list("pk", flat=True))
    cand_baias = [
        {"pk": b.pk, "nome": b.nome,
         "patrimonio": getattr(b.dispositivo, "patrimonio", "") or ""}
        for b in Baia.objects.filter(setor__unidade=g.unidade, computador__isnull=False)
        .select_related("computador").order_by("nome")
        if b.pk not in ja_baias
    ]
    cand_nbs = [
        {"pk": n.pk, "nome": f"{n.marca} {n.modelo}".strip() or "Notebook",
         "patrimonio": n.patrimonio or ""}
        for n in Notebook.objects.filter(colaborador__location=g.unidade).order_by("marca", "modelo")
        if n.pk not in ja_nbs
    ]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": f"Grupo — {g.nome}", "grupo": g, "membros": membros,
        "cand_baias": cand_baias, "cand_nbs": cand_nbs,
        "checklist_itens": PREVENTIVA_CHECKLIST,
        "pode_editar": _pode_ver_grupo(request.user, g),
        **_voltar("/parque/preventiva/?vista=grupos"),
    })
    return render(request, "parque/grupo_detalhe.html", contexto)


@staff_member_required
@require_POST
def grupo_editar_membros(request, pk):
    g = get_object_or_404(GrupoManutencao, pk=pk)
    if not _pode_ver_grupo(request.user, g):
        raise PermissionDenied()
    acao = request.POST.get("acao")  # add | remove
    baias = [int(x) for x in request.POST.getlist("baias") if x.isdigit()]
    nbs = [int(x) for x in request.POST.getlist("notebooks") if x.isdigit()]
    if acao == "add":
        if baias:
            g.baias.add(*baias)
        if nbs:
            g.notebooks.add(*nbs)
        messages.success(request, f"{len(baias) + len(nbs)} máquina(s) adicionada(s).")
    elif acao == "remove":
        if baias:
            g.baias.remove(*baias)
        if nbs:
            g.notebooks.remove(*nbs)
        messages.info(request, "Máquina(s) removida(s) do grupo.")
    return redirect("parque_grupo_detalhe", pk=g.pk)


@staff_member_required
@require_POST
def grupo_concluir_todos(request, pk):
    """Antecipa a preventiva de TODAS as máquinas do grupo (zera dias + pontos)."""
    g = get_object_or_404(GrupoManutencao, pk=pk)
    if not _pode_ver_grupo(request.user, g):
        raise PermissionDenied()
    if not request.user.has_perm("parque.add_reparo"):
        messages.error(request, "Você não tem permissão para registrar preventivas.")
        return redirect("parque_grupo_detalhe", pk=g.pk)
    # ATÔMICO: cria um Reparo por membro do grupo. Sem isto, falhar no membro 7
    # de 20 deixava metade do grupo "concluída" e metade não — e o usuário sem
    # saber quais.
    total_pts = qtd = 0
    with transaction.atomic():
        for b in g.baias.all():
            total_pts += _concluir_preventiva(b, True, request.user)
            qtd += 1
        for n in g.notebooks.all():
            total_pts += _concluir_preventiva(n, False, request.user)
            qtd += 1
    messages.success(
        request, f"Preventiva concluída para {qtd} máquina(s) do grupo (+{total_pts} pts).")
    return redirect("parque_grupo_detalhe", pk=g.pk)


@staff_member_required
@require_POST
def grupo_excluir(request, pk):
    g = get_object_or_404(GrupoManutencao, pk=pk)
    if not _pode_ver_grupo(request.user, g):
        raise PermissionDenied()
    nome = g.nome
    g.delete()
    messages.info(request, f"Grupo “{nome}” excluído.")
    return redirect("/parque/preventiva/?vista=grupos")


# =========================== ADIAR PREVENTIVA ===============================
@staff_member_required
@require_POST
def solicitar_adiamento(request):
    """Cria um pedido de adiamento (pendente) → notifica o supervisor (signal)."""
    kind = request.POST.get("kind")
    pk = request.POST.get("pk")
    justificativa = (request.POST.get("justificativa") or "").strip()
    nova_data_raw = (request.POST.get("nova_data") or "").strip()
    voltar = redirect(voltar_para(request, padrao="parque_preventiva_kanban"))
    if not justificativa or not nova_data_raw:
        messages.error(request, "Informe a nova data e a justificativa do adiamento.")
        return voltar
    try:
        nova_data = date.fromisoformat(nova_data_raw)
    except ValueError:
        messages.error(request, "Data de adiamento inválida.")
        return voltar
    if nova_data <= timezone.localdate():
        messages.error(request, "A nova data precisa ser futura.")
        return voltar
    kwargs = {}
    if kind == "baia":
        kwargs["baia"] = get_object_or_404(Baia, pk=pk)
    elif kind == "nb":
        kwargs["notebook"] = get_object_or_404(Notebook, pk=pk)
    else:
        raise Http404()
    AdiamentoPreventiva.objects.create(
        solicitante=request.user, justificativa=justificativa,
        nova_data=nova_data, **kwargs,
    )
    messages.success(request, "Pedido de adiamento enviado para aprovação do supervisor.")
    return voltar


@staff_member_required
@require_POST
def decidir_adiamento(request, pk, acao):
    """Supervisor aprova/nega um adiamento (só GESTAO). A notificação some via signal.

    Só POST (a decisão altera estado) e Referer validado.
    """
    voltar = redirect(voltar_para(
        request, padrao="/parque/preventiva/?vista=calendario"))
    if not (request.user.is_superuser
            or request.user.groups.filter(name__in=["Gerente", "Supervisor"]).exists()):
        messages.error(request, "Só o supervisor pode decidir adiamentos.")
        return voltar
    a = get_object_or_404(AdiamentoPreventiva, pk=pk)
    if a.status != AdiamentoPreventiva.Status.PENDENTE:
        messages.warning(request, "Este adiamento já foi decidido.")
    elif acao == "aprovar":
        a.aprovar(request.user)
        messages.success(request, f"Adiamento aprovado: {a.patrimonio} até {a.nova_data:%d/%m/%Y}.")
    elif acao == "negar":
        a.negar(request.user, motivo=(request.POST.get("motivo") or "").strip())
        messages.info(request, "Adiamento negado.")
    else:
        raise Http404()
    return voltar


def _maquina_contexto(baia=None, notebook=None):
    """Dados unificados da máquina (baia OU notebook) para as telas de chamado.

    Assim os templates usam `maq.*` sem precisar saber se é mesa ou notebook solto.
    """
    if baia is not None:
        return {
            "crumb": f"{baia.setor.unidade.name} › {baia.setor.nome}",
            "unidade": baia.setor.unidade.name,
            "setor": baia.setor.nome,
            "titulo": baia.colaborador.full_name if baia.colaborador_id else baia.nome,
            "patrimonio": baia.computador.patrimonio if baia.computador_id else "",
            "eh_notebook": baia.eh_notebook,
            "colaborador": baia.colaborador.full_name if baia.colaborador_id else "",
            "so": baia.eff_so, "cpu": baia.eff_cpu, "placa": baia.eff_placa,
            "ram": baia.eff_ram, "disco": baia.eff_disco,
            "indice": baia.indice_desempenho, "classe": baia.classe_desempenho,
            "diagnostico": baia.diagnostico,
        }
    nb = notebook
    nome = (nb.colaborador.full_name if nb.colaborador_id else nb.usuario) or ""
    return {
        "crumb": nb.unidade_setor or "Notebook (sem mesa)",
        "unidade": nb.unidade_setor or "",
        "setor": "",
        "titulo": nome or " ".join(p for p in [nb.marca, nb.modelo] if p) or "Notebook",
        "patrimonio": nb.patrimonio or "",
        "eh_notebook": True,
        "colaborador": nome,
        "so": "", "cpu": nb.processador, "placa": "",
        "ram": nb.memoria_ram, "disco": nb.armazenamento,
        "indice": nb.indice_desempenho, "classe": nb.classe_desempenho,
        "diagnostico": nb.diagnostico,
    }


@staff_member_required
def abrir_chamado(request, baia_id):
    """Abrir chamado de uma máquina que está numa BAIA (mesa)."""
    baia = get_object_or_404(
        Baia.objects.select_related("setor__unidade", "colaborador", "computador", "notebook"),
        pk=baia_id,
    )
    return _abrir_chamado_form(request, baia=baia)


@staff_member_required
def abrir_chamado_notebook(request, pk):
    """Abrir chamado de um NOTEBOOK. Se estiver numa baia, usa o fluxo da mesa;
    senão, abre o chamado direto no notebook (sem mesa)."""
    nb = get_object_or_404(Notebook, pk=pk)
    baia = getattr(nb, "baia", None)
    if baia is not None:
        return _abrir_chamado_form(request, baia=baia)
    return _abrir_chamado_form(request, notebook=nb)


def _abrir_chamado_form(request, baia=None, notebook=None):
    """Lógica compartilhada de abrir chamado — o alvo é uma baia OU um notebook."""
    if not request.user.has_perm("parque.add_reparo"):
        messages.error(request, "Você não tem permissão para abrir chamados.")
        return redirect("/admin/")

    from .admin import tecnicos_queryset
    tecnicos = tecnicos_queryset()
    destino = (f"/parque/mapa/{baia.setor.unidade_id}/" if baia is not None
               else "/parque/mapa-notebooks/")

    if request.method == "POST":
        titulo = (request.POST.get("titulo") or "").strip()
        tipo = request.POST.get("tipo") or Reparo.Tipo.REPARO
        if not titulo:
            messages.error(request, "Informe um título para o chamado.")
        else:
            tecnico = tecnicos.filter(pk=request.POST.get("tecnico") or 0).first()
            # Várias peças (multi-seleção). Guardamos a lista em `pecas`; `peca`
            # recebe a primeira (compatibilidade com telas/relatos legados).
            validas = {v for v, _ in Reparo.Peca.choices}
            pecas_sel = [p for p in request.POST.getlist("pecas")
                         if p in validas and p != Reparo.Peca.NENHUMA]
            r = Reparo(
                baia=baia,
                notebook=notebook,
                tipo=tipo,
                titulo=titulo,
                descricao=(request.POST.get("descricao") or "").strip(),
                previsao_conclusao=(request.POST.get("previsao_conclusao") or "").strip() or None,
                tecnico=tecnico,
                peca=(pecas_sel[0] if pecas_sel else ""),
                pecas=",".join(pecas_sel),
                peca_outro=(request.POST.get("peca_outro") or "").strip(),
                nova_especificacao=(request.POST.get("nova_especificacao") or "").strip(),
                realizar_cotacao=bool(request.POST.get("realizar_cotacao")),
            )
            r.save()  # signals: incrementa qtd_reparos, etc.
            r.garantir_orcamento(request.user)   # abre orçamento se "realizar cotação"
            r.aplicar_desativacao()              # tipo=desativação manda p/ estoque (só baia)
            messages.success(request, f"Chamado aberto para {r.alvo}.")
            # Realocação de colaborador só faz sentido numa mesa (baia).
            if baia is not None and r.tipo != Reparo.Tipo.PERIFERICO and baia.colaborador_id:
                return redirect("parque_chamado_realocar", pk=r.pk)
            return redirect(destino)

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "baia": baia,
        "notebook": notebook,
        "maq": _maquina_contexto(baia=baia, notebook=notebook),
        "tecnicos": tecnicos,
        "tipos": Reparo.Tipo.choices,
        "pecas": Reparo.Peca.choices,
        "tipo_inicial": request.GET.get("tipo") or Reparo.Tipo.REPARO,
        "titulo_inicial": request.GET.get("titulo", ""),
        "hoje": timezone.localdate(),
        "title": "Abrir chamado",
        **_voltar(destino),
    })
    return render(request, "parque/abrir_chamado.html", contexto)


@staff_member_required
def escanear_chamado(request):
    """Página que abre a CÂMERA para escanear o patrimônio (QR da etiqueta) e cair
    direto na tela de abrir chamado da máquina."""
    contexto = dj_admin.site.each_context(request)
    contexto.update({"title": "Escanear máquina", **_voltar("/parque/reparos/")})
    return render(request, "parque/escanear_chamado.html", contexto)


@staff_member_required
def resolver_patrimonio(request):
    """Traduz o patrimônio escaneado (?codigo=) → JSON com a URL de abrir chamado
    da máquina (computador ou notebook)."""
    if not request.user.has_perm("parque.add_reparo"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para abrir chamados."}, status=403)
    codigo = (request.GET.get("codigo") or "").strip()
    if not codigo:
        return JsonResponse({"ok": False, "erro": "Código vazio."}, status=400)

    comp = Computador.objects.filter(patrimonio__iexact=codigo).first()
    if comp:
        baia = getattr(comp, "baia", None)
        if baia is None:
            return JsonResponse({
                "ok": False,
                "erro": f"O computador {comp.patrimonio} não está em nenhuma baia — "
                        "vincule-o a uma mesa para abrir o chamado.",
            }, status=409)
        return JsonResponse({"ok": True, "tipo": "computador", "nome": comp.patrimonio,
                             "url": reverse("parque_abrir_chamado", args=[baia.pk])})

    nb = Notebook.objects.filter(patrimonio__iexact=codigo).first()
    if nb:
        return JsonResponse({"ok": True, "tipo": "notebook", "nome": nb.patrimonio,
                             "url": reverse("parque_abrir_chamado_notebook", args=[nb.pk])})

    return JsonResponse({"ok": False, "erro": f"Nenhuma máquina com patrimônio “{codigo}”."}, status=404)


def _num_dec(v):
    """Converte com segurança para Decimal (ou None)."""
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


# UUIDs/seriais genéricos que placas-mãe baratas repetem de fábrica (mesmo valor em
# várias máquinas). Ao recebê-los, desambiguamos pelo hostname para não colidir.
SERIAIS_GENERICOS = (
    "03000200-0400-0500-0006-000700080009",
    "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "00020003-0004-0005-0006-000700080009",
)


@csrf_exempt
def telemetria_ingest(request):
    """Ingestão da coleta de hardware do AGENTE (POST JSON), a cada ~30 min.

    Autentica por TOKEN no header (Authorization: Bearer <TELEMETRIA_TOKEN> ou
    X-Api-Token). Casa a máquina pelo `serial`; espelha as specs reais em
    Computador/Notebook.tel_* (o score passa a usar o dado real) e faz upsert de
    TelemetriaMaquina (auditoria/heartbeat; sem serial casado = pendente).
    """
    # Sem CORS: o cliente é o agente (PowerShell/curl/systemd), que não faz
    # preflight nem é barrado por origem. Liberar `Allow-Origin: *` só abria o
    # endpoint para qualquer página no navegador de quem tivesse o token.
    if request.method == "OPTIONS":
        return JsonResponse({}, status=405)
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido."}, status=405)

    token_cfg = (getattr(settings, "TELEMETRIA_TOKEN", "") or "").strip()
    if not token_cfg:
        return JsonResponse({"erro": "Telemetria desativada no servidor."}, status=503)
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    enviado = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    enviado = enviado or (request.META.get("HTTP_X_API_TOKEN", "") or "").strip()
    if not enviado or not constant_time_compare(enviado, token_cfg):
        return JsonResponse({"erro": "Token inválido."}, status=401)

    # Guarda de tamanho do corpo (64 KB) antes de parsear.
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > 64 * 1024:
            return JsonResponse({"erro": "Payload muito grande."}, status=413)
    except (TypeError, ValueError):
        pass
    try:
        outer = json.loads(request.body.decode("utf-8", "ignore") or "{}")
    except ValueError:
        return JsonResponse({"erro": "JSON inválido."}, status=400)
    if not isinstance(outer, dict):
        return JsonResponse({"erro": "JSON inválido."}, status=400)

    # E2EE: quando a chave privada está configurada, EXIGE payload cifrado
    # (envelope {k,iv,ct,mac}); decifra e usa o JSON de dentro.
    from . import cripto
    if cripto.ativa():
        if "ct" not in outer or "k" not in outer:
            return JsonResponse({"erro": "Payload precisa ser cifrado (E2EE)."}, status=400)
        try:
            dados = json.loads(cripto.decifrar(outer).decode("utf-8", "ignore") or "{}")
        except Exception:
            logger.warning("Telemetria: falha ao decifrar/validar payload (IP %s).",
                           request.META.get("REMOTE_ADDR"), exc_info=True)
            return JsonResponse({"erro": "Falha ao decifrar/validar o payload."}, status=400)
    else:
        dados = outer
    if not isinstance(dados, dict):
        return JsonResponse({"erro": "JSON inválido."}, status=400)

    serial = str(dados.get("serial") or "").strip()
    if not serial:
        return JsonResponse({"erro": "Campo 'serial' obrigatório."}, status=400)
    # CHAVE DE IDENTIDADE da máquina física. Serial de BIOS/placa/UUID válido é único
    # e basta. Mas placas baratas repetem UUID/serial genérico → aí o MAC (único por
    # máquina) resolve, inclusive quando duas máquinas têm specs idênticas. Sem MAC,
    # cai no hostname. Assim máquinas iguais NÃO colidem e a mesma máquina não duplica.
    _host = str(dados.get("hostname") or "").strip()
    _mac = re.sub(r"[^0-9A-Fa-f]", "", str(dados.get("mac") or "")).upper()[:12]
    _generico = any(g in serial.lower() for g in SERIAIS_GENERICOS)
    if _generico or serial.upper().startswith(("HOST-", "MAC-")):
        if _mac:
            serial = f"MAC-{_mac}"
        elif _host:
            serial = f"HOST-{_host}"

    # Casa por MAC (identidade física, vínculo PERMANENTE) e, como fallback, por serial.
    comp = nb = None
    if _mac:
        comp = Computador.objects.filter(mac=_mac).first()
        nb = None if comp else Notebook.objects.filter(mac=_mac).first()
    if comp is None and nb is None:
        comp = Computador.objects.filter(serial__iexact=serial).first()
        nb = None if comp else Notebook.objects.filter(serial__iexact=serial).first()

    # Strings derivadas p/ reusar a régua de score (_score_cpu/ram/disco).
    cpu_txt = str(dados.get("cpu_modelo") or "").strip()
    ghz = dados.get("cpu_ghz")
    if cpu_txt and ghz:
        cpu_txt = f"{cpu_txt} {ghz}GHz"
    ram_gb = dados.get("ram_gb")
    ram_tipo = str(dados.get("ram_tipo") or "").strip()
    ram_txt = (f"{ram_gb}GB {ram_tipo}".strip() if ram_gb else ram_tipo)
    disco_tipo = str(dados.get("disco_tipo") or "").strip()
    disco_total = dados.get("disco_total_gb")
    particao = str(dados.get("particao") or "").strip().upper()
    disco_base = (f"{disco_tipo} {round(float(disco_total))}GB".strip()
                  if disco_total else disco_tipo)
    disco_txt = f"{disco_base} · {particao}" if (disco_base and particao) else (disco_base or particao)
    so_txt = str(dados.get("so") or "").strip()
    agora = timezone.now()
    nucleos = dados.get("cpu_nucleos")
    try:
        uptime = int(float(dados.get("uptime_seg")))
    except (TypeError, ValueError):
        uptime = None

    defaults = {
        "computador": comp, "notebook": nb, "mac": _mac,
        "hostname": str(dados.get("hostname") or "")[:120],
        "so": so_txt[:120], "cpu_modelo": (str(dados.get("cpu_modelo") or "").strip())[:160],
        "cpu_nucleos": (int(nucleos) if str(nucleos).isdigit() else None),
        "cpu_ghz": _num_dec(ghz), "ram_gb": _num_dec(ram_gb), "ram_tipo": ram_tipo[:20],
        "disco_tipo": disco_tipo[:20], "disco_total_gb": _num_dec(disco_total),
        "disco_livre_gb": _num_dec(dados.get("disco_livre_gb")), "particao": particao[:10],
        "gpu": str(dados.get("gpu") or "").strip()[:160],
        "gpu_tipo": str(dados.get("gpu_tipo") or "").strip()[:12],
        "uptime_seg": uptime,
        "ip_publico": str(dados.get("ip_publico") or "").strip()[:45],
        "ip_local": str(dados.get("ip_local") or "").strip()[:45],
        "geo_cidade": str(dados.get("geo_cidade") or "").strip()[:80],
        "geo_regiao": str(dados.get("geo_regiao") or "").strip()[:80],
        "geo_pais": str(dados.get("geo_pais") or "").strip()[:60],
        "geo_lat": str(dados.get("geo_lat") or "").strip()[:20],
        "geo_lon": str(dados.get("geo_lon") or "").strip()[:20],
        "raw": json.dumps(dados, ensure_ascii=False)[:8000], "visto_em": agora,
    }

    # Localiza a linha da MESMA máquina física — âncora no MAC (único). Se não achar
    # por MAC, adota UMA linha legada (sem MAC) do mesmo hostname (migração única, para
    # não duplicar quando a máquina passa a mandar MAC). Sem MAC, usa serial/hostname.
    existente = None
    if _mac:
        existente = TelemetriaMaquina.objects.filter(mac=_mac).first()
        if existente is None and _host:
            existente = (TelemetriaMaquina.objects.filter(hostname=_host, mac="")
                         .filter(Q(serial__startswith="HOST-") | Q(serial__startswith="MAC-")
                                 | Q(serial__contains="@")).first())
    else:
        existente = TelemetriaMaquina.objects.filter(serial=serial).first()
        # Agente SEM MAC reportando p/ máquina que já virou MAC- (ou @host): casa pelo
        # hostname para NÃO duplicar (inclui linhas MAC-, HOST- e @host).
        if existente is None and _host:
            existente = (TelemetriaMaquina.objects.filter(hostname=_host)
                         .filter(Q(serial__startswith="MAC-") | Q(serial__startswith="HOST-")
                                 | Q(serial__contains="@")).first())

    # ATÔMICO daqui até o fim da gravação: são até 4 escritas (serial da máquina,
    # delete da duplicata, a própria coleta e a aplicação das specs). Falha no
    # meio já deixou coleta órfã e specs pela metade na máquina.
    with transaction.atomic():
        if existente is not None:
            # NÃO rebaixa a identidade: MAC- (físico, único) vence HOST-/@ (fallback).
            if existente.serial.startswith("MAC-") and not serial.startswith("MAC-"):
                serial = existente.serial
            # Preserva o MAC já conhecido quando a coleta atual não trouxe (agente antigo).
            if not defaults.get("mac") and existente.mac:
                defaults["mac"] = existente.mac
            # Robustez p/ agentes MISTOS: coleta sem os campos ricos NÃO apaga o que já veio.
            for campo in ("ram_tipo", "particao", "gpu", "gpu_tipo", "uptime_seg", "ip_publico",
                        "geo_cidade", "geo_regiao", "geo_pais", "geo_lat", "geo_lon"):
                if not defaults.get(campo) and getattr(existente, campo):
                    defaults[campo] = getattr(existente, campo)
            # Preserva o VÍNCULO já feito mesmo que a chave (serial) tenha mudado.
            if not comp and not nb and (existente.computador_id or existente.notebook_id):
                comp, nb = existente.computador, existente.notebook
                defaults["computador"], defaults["notebook"] = comp, nb
            maq = comp or nb
            if maq and (maq.serial or "") != serial:
                maq.serial = serial
                maq.save(update_fields=["serial"])
            # Remove eventual duplicata que já tenha a chave canônica (evita conflito unique).
            TelemetriaMaquina.objects.filter(serial=serial).exclude(pk=existente.pk).delete()
            for campo, valor in defaults.items():
                setattr(existente, campo, valor)
            existente.serial = serial
            existente.save()
            tel_obj = existente
        else:
            tel_obj, _ = TelemetriaMaquina.objects.update_or_create(serial=serial, defaults=defaults)

        alvo = comp or nb
        if alvo is not None:
            tel_obj.aplicar_na_maquina()
            alvo_label = comp.patrimonio if comp else (nb.patrimonio or str(nb))
        else:
            alvo_label = "pendente"

    return JsonResponse({"ok": True, "vinculado": alvo is not None, "alvo": alvo_label})


def _maquina_do_cookie(ref):
    """Resolve o cookie de vínculo por máquina ('c<pk>'/'n<pk>') → Computador/Notebook."""
    ref = (ref or "").strip()
    if len(ref) < 2 or not ref[1:].isdigit():
        return None
    pk = int(ref[1:])
    if ref[0] == "c":
        return Computador.objects.filter(pk=pk).first()
    if ref[0] == "n":
        return Notebook.objects.filter(pk=pk).first()
    return None


@staff_member_required
@require_POST
def agente_este_computador(request):
    """Grava (ou limpa) o vínculo POR MÁQUINA no cookie do navegador — identifica qual
    computador é ESTE. Cada máquina/navegador guarda o seu, então a mesma conta em
    máquinas diferentes exibe patrimônios diferentes."""
    ref = (request.POST.get("maq") or "").strip()
    resp = redirect("/parque/agente/")
    if ref == "limpar":
        resp.delete_cookie("itam_maq")
        messages.success(request, "Identificação deste computador removida.")
    elif _maquina_do_cookie(ref) is not None:
        resp.set_cookie("itam_maq", ref, max_age=60 * 60 * 24 * 365,
                        samesite="Lax")
        messages.success(request, "Computador identificado neste navegador.")
    return resp


@staff_member_required
def agente_pagina(request):
    """Tela única: agente de coleta (download + instruções) + telemetria
    (todas as coletas com seus dados). `?filtro=pendentes` mostra só as não vinculadas."""
    from . import cripto, geoloc
    # Recalcula a localização por IP (barato) para o painel refletir o estado atual.
    divergentes = geoloc.recalcular()
    divergencias = []
    for t in divergentes:
        cad = t.unidade_cadastrada
        if t.notebook_id:
            corrigir_url = "/parque/transferencia-notebooks/"
        elif cad:
            corrigir_url = f"/parque/transferencia-lojas/{cad.id}/"
        else:
            corrigir_url = "/parque/transferencia-lojas/"
        divergencias.append({
            "tel": t, "alvo": t.alvo,
            "cadastrada": cad.name if cad else "—",
            "detectada": t.unidade_detectada.name if t.unidade_detectada else "—",
            "corrigir_url": corrigir_url,
        })

    # "Este computador" — identificação da máquina física, em ordem de confiança:
    #  1) AUTOMÁTICO por MAC via IP local (LAN): a requisição traz o IP interno da
    #     máquina → casa com a coleta (ip_local) → patrimônio. Exato, sem cookie.
    #  2) FALLBACK (acesso externo/túnel): vínculo salvo no navegador (cookie, 1x).
    # (Navegador não lê o MAC; por isso o IP local — que ele traz na LAN — é a ponte.)
    minha_maquina = None
    coleta_local = None
    pick = None
    maq_bind = None
    ident_auto = False
    client_ip = (request.META.get("REMOTE_ADDR") or "").strip()
    if client_ip and not client_ip.startswith(("127.", "::1")):
        tref = (TelemetriaMaquina.objects.filter(ip_local=client_ip)
                .exclude(ip_local="").order_by("-visto_em").first())
        if tref is not None and (tref.computador_id or tref.notebook_id):
            maq_bind = tref.computador or tref.notebook
            ident_auto = True
        elif tref is not None:
            # Máquina identificada pela rede, mas a coleta ainda NÃO foi vinculada:
            # mostra as infos dela + botão "Vincular esta máquina" (1 clique).
            coleta_local = {
                "tel": tref, "pk": tref.pk, "hostname": tref.hostname,
                "serial": tref.serial, "mac": tref.mac_label,
            }
    if maq_bind is None and coleta_local is None:
        maq_bind = _maquina_do_cookie(request.COOKIES.get("itam_maq", ""))
    if maq_bind is not None:
        baia = getattr(maq_bind, "baia", None)
        uni = baia.setor.unidade.name if (baia and baia.setor_id) else "—"
        setor = baia.setor.nome if (baia and baia.setor_id) else "—"
        colaborador = str(baia.colaborador) if (baia and baia.colaborador_id) else "—"
        tel = maq_bind.telemetrias.order_by("-visto_em").first()
        minha_maquina = {
            "comp": maq_bind, "tel": tel, "unidade": uni, "setor": setor,
            "colaborador": colaborador, "patrimonio": maq_bind.patrimonio,
            "auto": ident_auto,
            "ref": ("c" if isinstance(maq_bind, Computador) else "n") + str(maq_bind.pk),
        }
    elif coleta_local is None:
        # Ainda não identificado neste navegador: monta a lista para escolher UMA vez.
        # Detecta a unidade pelo IP p/ sugerir as máquinas da loja; permite busca.
        ip = ""
        for h in ("HTTP_CF_CONNECTING_IP", "HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"):
            v = request.META.get(h)
            if v:
                ip = v.split(",")[0].strip()
                break
        uni_acesso = None
        if ip and not ip.startswith(("127.", "::1")):
            tref = (TelemetriaMaquina.objects.filter(
                        ip_publico=ip, unidade_detectada__isnull=False)
                    .select_related("unidade_detectada").order_by("-visto_em").first())
            uni_acesso = tref.unidade_detectada if tref else None
        termo = (request.GET.get("meu") or "").strip()
        pcs = Computador.objects.exclude(status=Computador.Status.DESATIVADO)
        if termo:
            pcs = pcs.filter(Q(patrimonio__icontains=termo) | Q(serial__icontains=termo))
        elif uni_acesso is not None:
            pcs = pcs.filter(baia__setor__unidade=uni_acesso)
        else:
            pcs = pcs.none()
        opcoes = [{"ref": f"c{m.pk}", "patrimonio": m.patrimonio,
                   "colaborador": (str(m.baia.colaborador) if getattr(m, "baia", None)
                                   and m.baia.colaborador_id else "—"),
                   "setor": (m.baia.setor.nome if getattr(m, "baia", None)
                             and m.baia.setor_id else "—"),
                   "specs": m.resumo_specs} for m in pcs.select_related()[:30]]
        pick = {"unidade": uni_acesso.name if uni_acesso else "",
                "termo": termo, "opcoes": opcoes}

    filtro = (request.GET.get("filtro") or "").strip()
    busca = (request.GET.get("q") or "").strip()
    qs = TelemetriaMaquina.objects.select_related(
        "computador", "notebook", "unidade_detectada").order_by("-visto_em")
    if filtro == "pendentes":
        qs = qs.filter(computador__isnull=True, notebook__isnull=True)
    elif filtro == "vinculadas":
        qs = qs.filter(Q(computador__isnull=False) | Q(notebook__isnull=False))
    # Unidade DETECTADA (pelo IP público) é a segunda pergunta desta tela — "o
    # agente está instalado em Bonsucesso?" —, e é FK, então filtra no banco. As
    # opções são só as unidades que aparecem em alguma coleta.
    # (`unidade_detectada` tem `related_name="+"`, então não há caminho reverso:
    # os ids saem da própria tabela de telemetria.)
    uni_ag = (request.GET.get("unidade") or "").strip()
    _ids_ag = (TelemetriaMaquina.objects.exclude(unidade_detectada__isnull=True)
               .values_list("unidade_detectada_id", flat=True).distinct())
    unis_ag = list(Location.objects.filter(pk__in=_ids_ag).order_by("name"))
    if uni_ag.isdigit():
        qs = qs.filter(unidade_detectada_id=int(uni_ag))
    # BUSCA desta tela. Procurava em QUATRO campos (serial, hostname,
    # cpu_modelo, geo_cidade) e a tabela mostra TREZE colunas — então quem
    # digitava o PATRIMÔNIO, que é o número da etiqueta e a primeira coluna
    # da tabela ("Máquina"), não achava nada. O patrimônio não mora na coleta:
    # mora no Computador/Notebook vinculado a ela. Mesmo caso de colaborador,
    # loja, setor, IP e MAC — todos na tela, nenhum na busca.
    #
    # A régua agora é a MESMA da tela de vincular (`telemetria_vincular`, logo
    # abaixo), que já procurava por patrimônio, colaborador, setor e unidade.
    # Duas buscas na mesma jornada com alcances diferentes é o que fazia esta
    # parecer quebrada.
    #
    # Cada palavra tem de casar (E entre as palavras, OU entre os campos):
    # "dell bonsucesso" traz a Dell de Bonsucesso, não tudo que é Dell mais
    # tudo que é de Bonsucesso.
    if busca:
        for termo in busca.split():
            alvo = (Q(serial__icontains=termo) | Q(hostname__icontains=termo)
                    | Q(cpu_modelo__icontains=termo) | Q(so__icontains=termo)
                    | Q(gpu__icontains=termo)
                    | Q(ip_local__icontains=termo) | Q(ip_publico__icontains=termo)
                    | Q(geo_cidade__icontains=termo) | Q(geo_regiao__icontains=termo)
                    | Q(unidade_detectada__name__icontains=termo)
                    # o que a pessoa tem na mão: a etiqueta de patrimônio
                    | Q(computador__patrimonio__icontains=termo)
                    | Q(notebook__patrimonio__icontains=termo)
                    | Q(notebook__marca__icontains=termo)
                    | Q(notebook__modelo__icontains=termo)
                    # quem usa a máquina e onde ela fica
                    | Q(computador__baia__colaborador__full_name__icontains=termo)
                    | Q(notebook__colaborador__full_name__icontains=termo)
                    | Q(notebook__baia__colaborador__full_name__icontains=termo)
                    | Q(computador__baia__setor__nome__icontains=termo)
                    | Q(computador__baia__setor__unidade__name__icontains=termo)
                    | Q(notebook__baia__setor__nome__icontains=termo)
                    | Q(notebook__baia__setor__unidade__name__icontains=termo)
                    | Q(notebook__unidade_setor__icontains=termo))
            # MAC é guardado só com os dígitos (12 hex), mas a tela mostra com
            # dois-pontos e é assim que a pessoa copia e cola. Sem tirar os
            # separadores, procurar o MAC que está na tela nunca casa.
            mac_termo = re.sub(r"[^0-9A-Za-z]", "", termo).upper()
            if len(mac_termo) >= 4:
                alvo = alvo | Q(mac__icontains=mac_termo)
            qs = qs.filter(alvo)
        # os JOINs de baia/colaborador podem repetir a mesma coleta
        qs = qs.distinct()
    total = TelemetriaMaquina.objects.count()
    pendentes = TelemetriaMaquina.objects.filter(
        computador__isnull=True, notebook__isnull=True).count()

    # --- Cobertura do agente: máquinas com coleta vinculada × total, por unidade ---
    from collections import Counter as _Counter
    _vinc_pc = set(TelemetriaMaquina.objects.filter(computador__isnull=False)
                   .values_list("computador_id", flat=True))
    _vinc_nb = set(TelemetriaMaquina.objects.filter(notebook__isnull=False)
                   .values_list("notebook_id", flat=True))

    # Régua ÚNICA de unidade (mesma dos filtros de estoque e dos mapas): baia →
    # texto que casa com unidade real → senão SEM_UNIDADE. Computador e notebook
    # caem no MESMO balde "Sem unidade", então o número bate entre as telas.
    _uni_lower, _aliases = _mapa_aliases_unidades()

    def _cob_uni_nb(m):
        u = _unidade_setor_notebook(m, _uni_lower, _aliases)[0]
        return SEM_UNIDADE if u == "Sem unidade / setor" else u

    _tv, _tt = _Counter(), _Counter()   # vinculadas / total por unidade
    for m in Computador.objects.exclude(status=Computador.Status.DESATIVADO).select_related(
            "baia__setor__unidade"):
        u = _unidade_computador(m, _uni_lower, _aliases)
        _tt[u] += 1
        if m.pk in _vinc_pc:
            _tv[u] += 1
    for m in Notebook.objects.select_related(
            "baia__setor__unidade", "colaborador__location", "colaborador__department"):
        u = _cob_uni_nb(m)
        _tt[u] += 1
        if m.pk in _vinc_nb:
            _tv[u] += 1
    _cob_total = sum(_tt.values())
    _cob_vinc = sum(_tv.values())
    cobertura = {
        "total": _cob_total,
        "vinc": _cob_vinc,
        "faltam": _cob_total - _cob_vinc,
        "pct": round(_cob_vinc * 100 / _cob_total) if _cob_total else 0,
        # piores (menos cobertura) primeiro — mostra onde falta instalar o agente
        "por_unidade": sorted(
            ({"nome": u, "vinc": _tv[u], "total": _tt[u],
              "pct": round(_tv[u] * 100 / _tt[u]) if _tt[u] else 0} for u in _tt),
            key=lambda x: (x["pct"], -x["total"])),
    }

    ctx = dj_admin.site.each_context(request)
    ctx.update({
        "title": "Agente de coleta e telemetria",
        "e2ee": cripto.ativa(),
        "token_ok": bool((getattr(settings, "TELEMETRIA_TOKEN", "") or "").strip()),
        "total_coletas": total,
        "pendentes": pendentes,
        "vinculadas": total - pendentes,
        "coletas": qs[:300],
        # Quantas a busca/filtro devolveram. Os números do topo (total,
        # pendentes, cobertura) são do parque inteiro e NÃO se movem com a
        # busca — então, sem este contador, uma busca que funcionou parecia
        # não ter rodado: a tabela encurtava e nada na tela confirmava por quê.
        "achados": qs.count() if (busca or filtro or uni_ag.isdigit()) else total,
        "divergencias": divergencias,
        "cobertura": cobertura,
        "minha_maquina": minha_maquina,
        "coleta_local": coleta_local,
        "pick": pick,
        "filtro": filtro,
        "busca": busca,
        "ativa_horas": getattr(settings, "TELEMETRIA_ATIVA_HORAS", 2),
        # As três fichas soltas (Todas / Vinculadas / Pendentes) viraram um grupo
        # do MESMO popup das outras listas, com o `filtro=` de sempre — link
        # antigo continua valendo. A unidade detectada entra como 2º grupo.
        **barra_filtros(
            request,
            [{"param": "filtro", "label": "Coleta", "todos": "Todas", "opcoes": [
                ("vinculadas", f"Vinculadas ({total - pendentes})", "Vinculadas"),
                ("pendentes", f"Pendentes ({pendentes})", "Pendentes")]},
             {"param": "unidade", "label": "Unidade detectada", "todos": "Todas",
              "opcoes": [(u.id, u.name) for u in unis_ag]}],
            keep=("q", "meu"),
        ),
        **_voltar("/admin/"),
    })
    return render(request, "parque/agente.html", ctx)


@staff_member_required
def agente_baixar(request):
    """Entrega o pacote .zip do agente de coleta com a URL e o token já
    preenchidos (config.json). O Técnico só extrai e cola na Inicialização."""
    import zipfile
    from . import cripto
    base = settings.BASE_DIR / "deploy" / "agente"
    url = request.build_absolute_uri(reverse("telemetria_ingest"))
    token = getattr(settings, "TELEMETRIA_TOKEN", "") or ""
    config = json.dumps(
        {"url": url, "token": token, "pubkey_xml": cripto.publica_xml()},
        ensure_ascii=False, indent=2)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ("coletar_score.ps1", "iniciar_agente.vbs", "diagnostico.bat",
                     "instalar_tarefa.bat", "README.txt"):
            fp = base / nome
            if fp.exists():
                z.writestr(nome, fp.read_text(encoding="utf-8"))
        z.writestr("config.json", config)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="agente-itam.zip"'
    return resp


@staff_member_required
def agente_baixar_linux(request):
    """Entrega o pacote .zip do agente de coleta para LINUX (Mint/Ubuntu), com a
    URL e o token em config.sh e a chave pública em pubkey.pem. O técnico extrai e
    roda `bash instalar.sh` (agenda no cron a cada 30 min, sem root)."""
    import zipfile
    from . import cripto
    base = settings.BASE_DIR / "deploy" / "agente-linux"
    url = request.build_absolute_uri(reverse("telemetria_ingest"))
    token = getattr(settings, "TELEMETRIA_TOKEN", "") or ""
    config_sh = (f'# Config do agente do Patrimap (gerado pelo download).\n'
                 f'URL="{url}"\nTOKEN="{token}"\n')
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ("coletar_score.sh", "instalar.sh", "README.txt"):
            fp = base / nome
            if fp.exists():
                # Garante quebras de linha Unix (LF) mesmo empacotando no Windows.
                z.writestr(nome, fp.read_text(encoding="utf-8").replace("\r\n", "\n"))
        z.writestr("config.sh", config_sh)
        z.writestr("pubkey.pem", cripto.publica_pem())
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="agente-itam-linux.zip"'
    return resp


@staff_member_required
def telemetria_vincular(request, pk):
    """Vincula uma coleta pendente a um patrimônio, sugerindo os candidatos mais
    prováveis por PROXIMIDADE DE HARDWARE (CPU/RAM/disco). POST efetiva o vínculo."""
    from . import sugestao
    tel = get_object_or_404(
        TelemetriaMaquina.objects.select_related("computador", "notebook"), pk=pk)

    confirmacao = None  # banner de "mover coleta já vinculada" (anti-erro)

    if request.method == "POST":
        acao = request.POST.get("acao")

        # --- CRIAR MÁQUINA NOVA (não existe cadastro): gera patrimônio pela unidade
        # do setor escolhido, cria a baia nesse setor e vincula a coleta. ------------
        if acao == "criar":
            from django.db import transaction
            novo_tipo = request.POST.get("novo_tipo")
            setor = Setor.objects.select_related("unidade").filter(
                pk=request.POST.get("setor_id")).first()
            if novo_tipo not in ("computador", "notebook") or setor is None:
                messages.error(request, "Escolha o tipo, a unidade e o setor da nova máquina.")
                return redirect("parque_telemetria_vincular", pk=pk)
            colab = None
            cid = request.POST.get("colaborador_id")
            if cid and str(cid).isdigit():
                colab = Person.objects.filter(pk=cid).first()
            try:
                with transaction.atomic():
                    # 1) Cria o dispositivo (patrimônio sai sozinho no save; a sigla
                    #    do computador vem de ultima_unidade). Specs entram via
                    #    aplicar_na_maquina (hardware real da coleta).
                    if novo_tipo == "computador":
                        maq = Computador(
                            ultima_unidade=setor.unidade.name,
                            status=Computador.Status.EM_USO,
                            mac=tel.mac, serial=tel.serial)
                        maq.save()
                    else:
                        maq = Notebook(
                            mac=tel.mac, serial=tel.serial,
                            status=Notebook.Status.ATIVO)
                        # Notebook + colaborador: define o colaborador ANTES da baia
                        # (evita o signal trocar o notebook da mesa).
                        if colab is not None:
                            maq.colaborador = colab
                        maq.save()
                    # 2) Numera a baia (sequência do setor) e monta o nome.
                    ultimo = Baia.objects.filter(setor=setor).aggregate(m=Max("numero"))["m"] or 0
                    numero = ultimo + 1
                    nome = f"{numero} - {colab.full_name}" if colab else str(numero)
                    # 3) Cria a baia JÁ com o dispositivo (sem specs legadas → sem fantasma).
                    dados_baia = {"setor": setor, "nome": nome, "colaborador": colab}
                    if novo_tipo == "computador":
                        dados_baia["computador"] = maq
                    else:
                        dados_baia["notebook"] = maq
                    Baia.objects.create(**dados_baia)
                    # 4) Vincula a coleta e espelha specs+MAC reais.
                    tel.computador = maq if novo_tipo == "computador" else None
                    tel.notebook = maq if novo_tipo == "notebook" else None
                    tel.save(update_fields=["computador", "notebook"])
                    tel.aplicar_na_maquina()
            except Exception as e:  # nada é criado (atomic)
                logger.exception("Falha ao criar máquina a partir da coleta %s.", pk)
                messages.error(request, f"Não foi possível criar a máquina: {e}")
                return redirect("parque_telemetria_vincular", pk=pk)
            messages.success(
                request, f"Máquina {maq.patrimonio} criada em {setor.unidade.name} › "
                         f"{setor.nome} e vinculada à coleta.")
            ref = ("c" if novo_tipo == "computador" else "n") + str(maq.pk)
            resp = redirect("/parque/agente/")
            resp.set_cookie("itam_maq", ref, max_age=60 * 60 * 24 * 365, samesite="Lax")
            return resp

        # --- VINCULAR a um patrimônio EXISTENTE ------------------------------------
        tipo = request.POST.get("tipo")
        mid = request.POST.get("maq_id")
        maq = None
        if tipo == "computador":
            maq = Computador.objects.filter(pk=mid).first()
        elif tipo == "notebook":
            maq = Notebook.objects.filter(pk=mid).first()
        if maq is None:
            messages.error(request, "Selecione uma máquina para vincular.")
            return redirect("parque_telemetria_vincular", pk=pk)

        # TRAVA anti-erro: se ESTA coleta já está vinculada a OUTRA máquina, não move
        # calado — pede confirmação. Evita "grudar" a mesma máquina física em vários
        # patrimônios (o sintoma do IP local repetido em telas diferentes).
        ja = tel.computador or tel.notebook
        mesma = ja is not None and ja.__class__ is maq.__class__ and ja.pk == maq.pk
        if ja is not None and not mesma and request.POST.get("confirmar_mover") != "1":
            confirmacao = {"de": ja, "para": maq, "tipo": tipo, "maq_id": mid}
            # cai no render normal exibindo o banner de confirmação (não vincula ainda).
        else:
            if tipo == "computador":
                tel.computador, tel.notebook = maq, None
            else:
                tel.notebook, tel.computador = maq, None
            # Não copia o serial se isso duplicaria o serial de outra máquina.
            if tel.serial and not type(maq).objects.filter(
                    serial=tel.serial).exclude(pk=maq.pk).exists():
                maq.serial = tel.serial
                maq.save(update_fields=["serial"])
            tel.save(update_fields=["computador", "notebook"])
            tel.aplicar_na_maquina()
            messages.success(
                request, f"Coleta {tel.hostname or tel.serial} vinculada a {maq.patrimonio}.")
            # Marca ESTA máquina como "este computador" neste navegador (cookie).
            ref = ("c" if tipo == "computador" else "n") + str(maq.pk)
            resp = redirect("/parque/agente/")
            resp.set_cookie("itam_maq", ref, max_age=60 * 60 * 24 * 365, samesite="Lax")
            return resp

    candidatos = sugestao.sugerir(tel, limite=8)
    busca = (request.GET.get("q") or "").strip()
    resultados = []
    if busca:
        pcs = (Computador.objects.filter(
                Q(patrimonio__icontains=busca) | Q(serial__icontains=busca)
                | Q(processador__icontains=busca)
                | Q(baia__colaborador__full_name__icontains=busca)
                | Q(baia__setor__nome__icontains=busca)
                | Q(baia__setor__unidade__name__icontains=busca))
               .select_related("baia__setor__unidade", "baia__colaborador").distinct()[:25])
        for m in pcs:
            resultados.append(("computador", m, sugestao.pontuar(tel, m)))
        nbs = (Notebook.objects.filter(
                Q(patrimonio__icontains=busca) | Q(serial__icontains=busca)
                | Q(modelo__icontains=busca) | Q(marca__icontains=busca)
                | Q(colaborador__full_name__icontains=busca)
                | Q(baia__colaborador__full_name__icontains=busca)
                | Q(unidade_setor__icontains=busca)
                | Q(baia__setor__nome__icontains=busca)
                | Q(baia__setor__unidade__name__icontains=busca))
               .select_related("baia__setor__unidade", "baia__colaborador", "colaborador").distinct()[:25])
        for m in nbs:
            resultados.append(("notebook", m, sugestao.pontuar(tel, m)))
        # Melhor casamento de hardware primeiro.
        resultados.sort(key=lambda r: r[2], reverse=True)

    def _linha(tipo, m, score):
        baia = getattr(m, "baia", None)
        # Colaborador: notebook tem FK própria; computador vem pela baia.
        if tipo == "notebook" and getattr(m, "colaborador_id", None):
            colaborador = str(m.colaborador)
        elif baia and baia.colaborador_id:
            colaborador = str(baia.colaborador)
        else:
            colaborador = "—"
        # Setor / unidade: pela baia; notebook sem baia usa o texto livre.
        if baia and baia.setor_id:
            setor, unidade = baia.setor.nome, baia.setor.unidade.name
        elif tipo == "notebook" and m.unidade_setor:
            setor, unidade = m.unidade_setor, "—"
        else:
            setor, unidade = "—", "—"
        return {
            "tipo": tipo, "id": m.pk, "patrimonio": m.patrimonio,
            "specs": m.resumo_specs, "score": score,
            "unidade": unidade, "setor": setor, "colaborador": colaborador,
        }
    # Para o formulário "Criar nova máquina": unidades + setores (com data-unidade
    # p/ filtrar no front) + colaboradores (opcional).
    unidades_novo = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name"))
    setores_novo = list(
        Setor.objects.select_related("unidade").order_by("unidade__name", "nome"))
    ctx = dj_admin.site.each_context(request)
    ctx.update({
        "title": f"Vincular coleta — {tel.hostname or tel.serial}",
        "tel": tel,
        "confirmacao": confirmacao,
        "candidatos": [_linha(t, m, s) for t, m, s in candidatos],
        "resultados": [_linha(t, m, s) for t, m, s in resultados],
        "busca": busca,
        "unidades_novo": unidades_novo,
        "setores_novo": setores_novo,
        "colaboradores_novo": _colaboradores_baia(),
        **_voltar("/parque/agente/"),
    })
    return render(request, "parque/vincular.html", ctx)


@staff_member_required
@require_POST
def local_ignorar(request, pk):
    """Marca/desmarca a divergência de localização de uma coleta como ignorada
    (exceções legítimas, ex.: notebook em home office)."""
    t = get_object_or_404(TelemetriaMaquina, pk=pk)
    t.local_ignorado = not t.local_ignorado
    t.save(update_fields=["local_ignorado"])
    messages.success(
        request,
        f"Divergência de localização {'ignorada' if t.local_ignorado else 'reativada'} "
        f"para {t.alvo}.")
    return redirect("/parque/agente/#divergencias")


@staff_member_required
@require_POST
def finalizar_reparo_admin(request, pk):
    """Finaliza um reparo específico (pela lista de Reparos) e fecha a tarefa Bitrix.

    Só POST: finalizar é escrita, e por GET dava para fechar chamado por link.
    """
    if not request.user.has_perm("parque.change_reparo"):
        messages.error(request, "Sem permissão para finalizar reparo.")
        return redirect("admin:parque_reparo_changelist")
    r = get_object_or_404(Reparo, pk=pk)
    if r.concluido_em:
        messages.warning(request, "Este reparo já está finalizado.")
    else:
        r.finalizar()
        messages.success(request, f"Reparo finalizado: {r.titulo}.")
    return redirect("admin:parque_reparo_changelist")


@staff_member_required
def chamado_detalhe(request, pk):
    """Tela VISUAL do chamado: a máquina desenhada + execução (quem faz / prazo) +
    relatório/registros da manutenção. Substitui o formulário cru do admin ao clicar
    num chamado no Kanban."""
    reparo = get_object_or_404(
        Reparo.objects.select_related(
            "baia__setor__unidade", "baia__colaborador", "baia__computador",
            "baia__notebook", "tecnico",
        ),
        pk=pk,
    )
    from .admin import tecnicos_queryset
    tecnicos = tecnicos_queryset()
    pode_editar = request.user.has_perm("parque.change_reparo")

    if request.method == "POST" and pode_editar:
        acao = request.POST.get("acao")
        if acao == "registro":
            texto = (request.POST.get("texto") or "").strip()
            if texto:
                RegistroReparo.objects.create(reparo=reparo, texto=texto, autor=request.user)
                messages.success(request, "Registro adicionado ao relatório.")
        elif acao == "dados":
            reparo.tecnico = tecnicos.filter(pk=request.POST.get("tecnico") or 0).first()
            reparo.previsao_conclusao = (request.POST.get("previsao_conclusao") or "").strip() or None
            reparo.save(update_fields=["tecnico", "previsao_conclusao"])
            messages.success(request, "Chamado atualizado.")
        elif acao == "avancado":
            from decimal import Decimal, InvalidOperation
            titulo = (request.POST.get("titulo") or "").strip()
            if titulo:
                reparo.titulo = titulo
            reparo.tipo = request.POST.get("tipo") or reparo.tipo
            reparo.descricao = (request.POST.get("descricao") or "").strip()
            reparo.nova_especificacao = (request.POST.get("nova_especificacao") or "").strip()
            # "Afeta o desempenho" é DERIVADO do tipo (troca de periférico não conta) —
            # deixou de ser um campo confuso no formulário.
            reparo.afeta_desempenho = reparo.tipo != Reparo.Tipo.PERIFERICO
            reparo.realizar_cotacao = bool(request.POST.get("realizar_cotacao"))
            custo = (request.POST.get("custo") or "").strip().replace(",", ".")
            try:
                reparo.custo = Decimal(custo) if custo else None
            except InvalidOperation:
                pass
            validas = {v for v, _ in Reparo.Peca.choices}
            pecas_sel = [p for p in request.POST.getlist("pecas")
                         if p in validas and p != Reparo.Peca.NENHUMA]
            reparo.pecas = ",".join(pecas_sel)
            reparo.peca = pecas_sel[0] if pecas_sel else ""
            if not pecas_sel:
                # Sem peça envolvida → sem "qual peça", sem cotação/custo.
                reparo.peca_outro = ""
                reparo.realizar_cotacao = False
                reparo.custo = None
            elif Reparo.Peca.OUTRO in pecas_sel:
                reparo.peca_outro = (request.POST.get("peca_outro") or "").strip()
            else:
                reparo.peca_outro = ""
            reparo.save()
            reparo.garantir_orcamento(request.user)  # abre orçamento se marcou "precisa comprar"
            messages.success(request, "Detalhes salvos.")
        return redirect("parque_chamado_detalhe", pk=reparo.pk)

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "reparo": reparo,
        "baia": reparo.baia,
        "maq": _maquina_contexto(baia=reparo.baia, notebook=reparo.notebook),
        "tecnicos": tecnicos,
        "tipos": Reparo.Tipo.choices,
        "pecas": Reparo.Peca.choices,
        "registros": reparo.registros.select_related("autor").all(),
        "pode_editar": pode_editar,
        "hoje": timezone.localdate(),
        "title": f"Chamado — {reparo.titulo}",
        **_voltar("/parque/reparos/"),
    })
    return render(request, "parque/chamado_detalhe.html", contexto)


def _mover_colaborador_baia(origem, destino):
    """Move o colaborador da baia `origem` para `destino`, ajustando os nomes."""
    pessoa = origem.colaborador
    if pessoa is None:
        return
    destino.colaborador = pessoa
    destino.nome = f"{destino.numero} - {pessoa.full_name}" if destino.numero else pessoa.full_name
    destino.save(update_fields=["colaborador", "nome"])
    origem.colaborador = None
    origem.nome = str(origem.numero) if origem.numero else ""
    origem.save(update_fields=["colaborador", "nome"])


@staff_member_required
def chamado_realocar(request, pk):
    """Após abrir um chamado (não-periférico), realoca o colaborador para uma mesa
    LIVRE (com PC e sem colaborador) da MESMA loja, para ele continuar trabalhando
    durante o reparo. Ao finalizar o chamado, ele volta à mesa original."""
    reparo = get_object_or_404(
        Reparo.objects.select_related("baia__setor__unidade", "baia__colaborador"), pk=pk,
    )
    origem = reparo.baia
    voltar_mapa = f"/parque/mapa/{origem.setor.unidade_id}/"

    livres = (
        Baia.objects.filter(
            setor__unidade_id=origem.setor.unidade_id,
            computador__isnull=False, colaborador__isnull=True,
        ).exclude(pk=origem.pk)
        .select_related("setor", "computador")
        .order_by("setor__nome", "numero", "nome")
    )

    if request.method == "POST" and request.user.has_perm("parque.change_baia"):
        if request.POST.get("acao") == "pular":
            return redirect("parque_chamado_detalhe", pk=reparo.pk)
        destino = livres.filter(pk=request.POST.get("baia")).first()
        if not destino:
            messages.error(request, "Escolha uma mesa livre válida da mesma loja.")
        elif not origem.colaborador_id:
            messages.warning(request, "A mesa não tem colaborador para realocar.")
            return redirect("parque_chamado_detalhe", pk=reparo.pk)
        else:
            nome_colab = origem.colaborador.full_name
            _mover_colaborador_baia(origem, destino)
            reparo.baia_realocacao = destino
            reparo.save(update_fields=["baia_realocacao"])
            messages.success(request, f"{nome_colab} realocado(a) para {destino.nome} durante o reparo.")
            return redirect("parque_chamado_detalhe", pk=reparo.pk)

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "reparo": reparo,
        "origem": origem,
        "colaborador": origem.colaborador,
        "livres": livres,
        "title": "Realocar colaborador",
        **_voltar(voltar_mapa),
    })
    return render(request, "parque/chamado_realocar.html", contexto)


@staff_member_required
def chamado_de_computador(request, pk, tipo):
    """Abre o formulário de Reparo já preenchido a partir de um Computador em uso.

    Resolve a baia do computador e redireciona para o add de Reparo (tipo
    reparo/desativacao). Se o computador não está em baia, avisa.
    """
    comp = get_object_or_404(Computador, pk=pk)
    baia = getattr(comp, "baia", None)
    if not baia:
        messages.error(request, f"{comp.patrimonio} não está instalado em uma baia — sem chamado de reparo.")
        return redirect("admin:parque_computador_changelist")
    titulo = "Chamado+de+reparo" if tipo == "reparo" else "Desativacao+para+troca"
    url = f"{reverse('admin:parque_reparo_add')}?baia={baia.pk}&tipo={tipo}&titulo={titulo}"
    return redirect(url)


@staff_member_required
@require_POST
def decidir_solicitacao(request, pk, acao):
    """Autoriza ou nega uma solicitação de movimentação (só GRUPOS_MOVIMENTACAO).

    Só POST: num GET, bastava um `<img src=".../autorizar/">` numa página
    qualquer para MOVER baias com a sessão da vítima (CSRF). O destino do
    "voltar" passa pelo `voltar_para`, que rejeita Referer de fora do site.
    """
    voltar = redirect(voltar_para(
        request, padrao="/admin/parque/movimentacaobaia/"))
    if not pode_mover_baia(request.user):
        messages.error(request, "Você não tem autorização para decidir movimentações.")
        return voltar
    mov = get_object_or_404(MovimentacaoBaia, pk=pk)
    if mov.status != MovimentacaoBaia.Status.PENDENTE:
        messages.warning(request, "Esta solicitação já foi decidida.")
    elif acao == "autorizar":
        conflito = (
            mov.tipo == MovimentacaoBaia.Tipo.MOVER
            and Baia.objects.filter(setor=mov.setor_destino, nome=mov.baia.nome)
            .exclude(pk=mov.baia_id).exists()
        )
        if conflito:
            messages.error(request, f"Já existe \"{mov.baia.nome}\" no setor de destino — não foi possível mover.")
        else:
            mov.aplicar(request.user)
            if mov.tipo == MovimentacaoBaia.Tipo.TROCAR:
                messages.success(request, f"Troca autorizada: {mov.baia.nome} ↔ {mov.baia_parceira.nome}.")
            else:
                messages.success(request, f"Movimentação autorizada: {mov.baia.nome} → {mov.setor_destino}.")
    elif acao == "negar":
        mov.negar(request.user)
        messages.info(request, "Solicitação negada.")
    return voltar


@staff_member_required
@require_POST
def decidir_transferencia(request, pk, acao):
    """Autoriza ou nega uma transferência pendente (só GRUPOS_MOVIMENTACAO).

    Só POST: era a pior das mudanças-de-estado-por-GET — um GET autorizava a
    transferência de patrimônio ENTRE LOJAS.
    """
    voltar = redirect(voltar_para(
        request, padrao="/admin/parque/transferencia/"))
    if not pode_mover_baia(request.user):
        messages.error(request, "Você não tem autorização para decidir transferências.")
        return voltar
    obs = (request.POST.get("observacao") or "").strip()
    t = get_object_or_404(Transferencia, pk=pk)
    if t.status != Transferencia.Status.PENDENTE:
        messages.warning(request, "Esta transferência já foi decidida.")
    elif acao == "autorizar":
        if obs:
            t.observacao = f"{t.observacao}\n{obs}".strip() if t.observacao else obs
        t.autorizar(request.user)
        messages.success(request, f"Transferência autorizada: {t}.")
    elif acao == "negar":
        t.negar(request.user, motivo=obs)
        messages.info(request, "Transferência negada.")
    return voltar


@staff_member_required
@require_POST
def decidir_transferencia_notebook(request, pk, acao):
    """Autoriza ou nega uma transferência de NOTEBOOK pendente (só GRUPOS_MOVIMENTACAO).

    Só POST (CSRF) e destino de retorno validado — ver `decidir_transferencia`.
    """
    voltar = redirect(voltar_para(request, padrao="/parque/transferencias/"))
    if not pode_mover_baia(request.user):
        messages.error(request, "Você não tem autorização para decidir transferências.")
        return voltar
    obs = (request.POST.get("observacao") or "").strip()
    t = get_object_or_404(TransferenciaNotebook, pk=pk)
    if t.status != TransferenciaNotebook.Status.PENDENTE:
        messages.warning(request, "Esta transferência já foi decidida.")
    elif acao == "autorizar":
        if obs:
            t.observacao = f"{t.observacao}\n{obs}".strip() if t.observacao else obs
            t.save(update_fields=["observacao"])
        t.autorizar(request.user)
        messages.success(request, f"Transferência de notebook autorizada: {t}.")
    elif acao == "negar":
        t.negar(request.user, motivo=obs)
        messages.info(request, "Transferência negada.")
    return voltar


@staff_member_required
def aprovacoes_pendentes(request):
    """Inbox unificado: transferências + movimentações de baia pendentes."""
    if not pode_mover_baia(request.user):
        raise PermissionDenied
    transferencias = (
        Transferencia.objects.filter(status=Transferencia.Status.PENDENTE)
        .select_related("baia_origem", "baia_destino", "registrado_por")
        .order_by("-created_at")
    )
    movimentacoes = (
        MovimentacaoBaia.objects.filter(status=MovimentacaoBaia.Status.PENDENTE)
        .select_related("baia", "baia_parceira", "setor_origem", "setor_destino", "solicitante")
        .order_by("-criado_em")
    )
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Aprovações pendentes",
        "transferencias": transferencias,
        "movimentacoes": movimentacoes,
        "total": transferencias.count() + movimentacoes.count(),
        # Sem isto o link "← voltar" do template renderizava vazio (href="").
        **_voltar("/admin/"),
    })
    return render(request, "parque/aprovacoes.html", contexto)


def _ctx_transferencia(request):
    """Habilita o arrastar-para-transferir (caminhão) em qualquer mapa de PCs.

    É HELPER de contexto, não view: quem protege o acesso é a view que chama.
    (Tinha @staff_member_required aqui — com visitante anônimo o decorator
    devolvia um redirect e o `dict.update(**redirect)` da view estourava 500.)
    """
    unidades = Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    return {
        "transferir_url": reverse("parque_transferir_entre_lojas"),
        "destinos": [{"unidade": u, "estrutura": _estrutura_unidade(u)} for u in unidades],
        "pode_mover": pode_mover_baia(request.user),
    }


@staff_member_required
def mapa_situacao(request, status):
    """Mapa filtrado pela situação DERIVADA do dispositivo (ex.: defeito), por unidade › setor."""
    rotulos = {"tem_pc": "Com PC", "sem_pc": "Sem PC",
               "notebook": "Notebook", "defeito": "Com defeito"}
    if status not in rotulos:
        raise Http404()
    baias = (
        Baia.objects
        .select_related("setor__unidade", "colaborador", "computador", "notebook")
        .prefetch_related("reparos")
        .order_by("setor__unidade__name", "setor__nome", "nome")
    )
    if status == "tem_pc":
        baias = baias.filter(computador__isnull=False)
    elif status == "sem_pc":
        baias = baias.filter(computador__isnull=True, notebook__isnull=True)
    elif status == "notebook":
        baias = baias.filter(notebook__isnull=False)
    elif status == "defeito":
        baias = baias.filter(computador__status=Computador.Status.DEFEITO)
    uid = request.GET.get("unidade")
    unidade_sel = int(uid) if (uid and uid.isdigit()) else None
    if unidade_sel:
        baias = baias.filter(setor__unidade_id=unidade_sel)
    # Agrupa: unidade -> setor -> [baias] (mantendo a ordem)
    grupos = {}
    for b in baias:
        grupos.setdefault(b.setor.unidade, {}).setdefault(b.setor, []).append(b)
    unidades_estrut = [
        {"unidade": uni, "setores": [{"setor": s, "baias": bl} for s, bl in setores.items()]}
        for uni, setores in grupos.items()
    ]
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "titulo": f"Computadores: {rotulos[status]}",
        "unidades_estrut": unidades_estrut,
        "total": baias.count(),
        "title": f"Mapa — {rotulos[status]}",
        **_filtros_ctx(
            request,
            Location.objects.filter(setores__isnull=False).distinct().order_by("name"),
            por_nome=False,
        ),
        **_ctx_transferencia(request),
    })
    return render(request, "parque/mapa_filtro.html", contexto)


# Periféricos considerados na transferência (atributo → rótulo p/ o protocolo).
PERIFERICOS = [
    ("monitor", "Monitor"),
    ("teclado", "Teclado"),
    ("mouse", "Mouse"),
    ("headset", "Headset"),
    ("webcam", "Webcam"),
    ("leitor_cod_barras", "Leitor de código de barras"),
]


def _estrutura_unidade(unidade):
    """Setores → baias de uma unidade, para o mapa de destino (escolha de vaga)."""
    setores = (
        Setor.objects.filter(unidade=unidade)
        .prefetch_related("baias__computador", "baias__colaborador")
        .order_by("nome")
    )
    return [
        {
            "setor": s,
            "baias": [
                {
                    "pk": b.pk,
                    "nome": b.nome,
                    # Vaga = mesa livre para receber uma máquina: sem dispositivo algum.
                    "vaga": b.computador_id is None and b.notebook_id is None,
                    "colaborador": str(b.colaborador) if b.colaborador_id else "",
                }
                for b in s.baias.all()
            ],
        }
        for s in setores
    ]


@staff_member_required
def transferencia_lojas(request, unidade_id=None):
    """Tela do fluxo de transferência entre lojas (mapa de origem + caminhão)."""
    unidades = (
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    contexto = dj_admin.site.each_context(request)

    if unidade_id is None:
        # Seletor da unidade de ORIGEM (cards das lojas).
        contexto.update({
            "title": "Transferência entre lojas",
            "unidades": unidades,
            "escolher_origem": True,
        })
        return render(request, "parque/transfer_lojas.html", contexto)

    unidade = get_object_or_404(Location, pk=unidade_id)
    setores = (
        Setor.objects.filter(unidade=unidade)
        .prefetch_related("baias__colaborador", "baias__reparos", "baias__computador")
        .order_by("nome")
    )
    # Outras unidades (destinos possíveis) com seus setores/baias.
    destinos = [
        {"unidade": u, "estrutura": _estrutura_unidade(u)}
        for u in unidades if u.pk != unidade.pk
    ]
    contexto.update({
        "title": f"Transferência entre lojas — {unidade.name}",
        "unidade": unidade,
        "unidades": unidades,
        "setores": setores,
        "destinos": destinos,
        "pode_mover": pode_mover_baia(request.user),
    })
    return render(request, "parque/transfer_lojas.html", contexto)


@staff_member_required
@require_POST
def transferir_entre_lojas(request):
    """Cria a transferência entre lojas (move o PC p/ outra unidade).

    Autorizados (pode_mover_baia) aplicam direto e recebem a URL do protocolo;
    os demais (ex.: Estagiário) geram uma transferência PENDENTE.
    """
    origem = get_object_or_404(
        Baia.objects.select_related("setor__unidade", "computador", "colaborador"),
        pk=request.POST.get("baia_origem"),
    )
    setor_destino = get_object_or_404(
        Setor.objects.select_related("unidade"), pk=request.POST.get("setor_destino")
    )

    # Mesma loja = movimentação interna (move o PC para outra vaga/setor);
    # loja diferente = transferência entre lojas (exige tarefa do Bitrix).
    interno = setor_destino.unidade_id == origem.setor.unidade_id
    if not (origem.computador_id or origem.eff_cpu):
        return JsonResponse(
            {"ok": False, "erro": "Esta baia não tem um computador para transferir."},
            status=400,
        )

    bitrix = (request.POST.get("bitrix_task_id") or "").strip()
    if not interno and not bitrix:
        return JsonResponse(
            {"ok": False, "erro": "Informe o código da tarefa do Bitrix para concluir a transferência."},
            status=400,
        )

    # Destino: baia vaga existente OU nova baia no setor.
    baia_destino = None
    nome_baia_destino = ""
    bd_id = request.POST.get("baia_destino")
    if bd_id and bd_id.isdigit():
        baia_destino = get_object_or_404(Baia, pk=bd_id)
        if baia_destino.setor_id != setor_destino.pk:
            return JsonResponse({"ok": False, "erro": "A baia escolhida não é desse setor."}, status=400)
        if baia_destino.computador_id or baia_destino.notebook_id:
            return JsonResponse({"ok": False, "erro": "Essa baia já tem um dispositivo. Escolha uma vaga."}, status=400)
    else:
        nome_baia_destino = (request.POST.get("nome_baia_destino") or "").strip()
        if not nome_baia_destino:
            return JsonResponse({"ok": False, "erro": "Informe o nome da nova baia de destino."}, status=400)
        if Baia.objects.filter(setor=setor_destino, nome=nome_baia_destino).exists():
            return JsonResponse(
                {"ok": False, "erro": f'Já existe uma baia "{nome_baia_destino}" nesse setor.'},
                status=400,
            )

    hoje = timezone.localdate()
    t = Transferencia(
        entre_lojas=not interno,
        bitrix_task_id=bitrix,
        baia_origem=origem,
        data_saida=hoje,
        colaborador_saida=str(origem.colaborador) if origem.colaborador_id else "",
        so_antigo=origem.eff_so or "",
        processador_antigo=origem.eff_cpu or "",
        placa_mae_antigo=origem.eff_placa or "",
        ram_antigo=origem.eff_ram or "",
        armazenamento_antigo=origem.eff_disco or "",
        baia_destino=baia_destino,
        setor_destino=setor_destino,
        nome_baia_destino=nome_baia_destino,
        data_entrada=hoje,
        # A máquina carrega as mesmas specs para o destino.
        so_novo=origem.eff_so or "",
        processador_novo=origem.eff_cpu or "",
        placa_mae_novo=origem.eff_placa or "",
        ram_novo=origem.eff_ram or "",
        armazenamento_novo=origem.eff_disco or "",
        computador=origem.computador,
        registrado_por=request.user,
    )

    if pode_mover_baia(request.user):
        # ATÔMICO: grava a transferência E move o computador. Falha no meio
        # deixava a transferência registrada com a máquina parada na origem.
        with transaction.atomic():
            t.status = Transferencia.Status.AUTORIZADA
            t.save()
            t.aplicar_transferencia_loja()
            if not interno:
                # HTTP fora da transação: só abre a tarefa se gravou de verdade.
                transaction.on_commit(t.abrir_tarefa_transferencia_bitrix)
        return JsonResponse({
            "ok": True, "status": "aplicada",
            "msg": ("Movimentação interna realizada. Gerando o protocolo…" if interno
                    else "Transferência realizada. Gerando o protocolo…"),
            "protocolo_url": reverse("parque_protocolo_transferencia", args=[t.pk]),
        })

    t.status = Transferencia.Status.PENDENTE
    t.save()
    return JsonResponse({
        "ok": True, "status": "solicitada",
        "msg": ("Solicitação de movimentação interna enviada para autorização." if interno
                else "Solicitação de transferência enviada para autorização."),
    })


@staff_member_required
def protocolo_transferencia(request, pk):
    """Comprovante de transferência (saída e destino) — página de impressão."""
    t = get_object_or_404(
        Transferencia.objects.select_related(
            "baia_origem__setor__unidade", "baia_destino__setor__unidade",
            "setor_destino__unidade", "computador",
        ),
        pk=pk,
    )
    # Vale tanto p/ transferência entre lojas quanto p/ movimentação interna
    # (mesma loja, outra baia/setor) — ambas preenchem origem/destino/computador.

    origem = t.baia_origem
    destino = t.baia_destino
    uni_origem = origem.setor.unidade.name if origem else ""
    if destino:
        uni_destino = destino.setor.unidade.name
        setor_destino_nome = destino.setor.nome
    elif t.setor_destino_id:
        uni_destino = t.setor_destino.unidade.name
        setor_destino_nome = t.setor_destino.nome
    else:
        uni_destino = setor_destino_nome = ""

    # Item 1: o computador (patrimônio + specs). Demais itens: periféricos presentes.
    comp = t.computador
    if comp:
        desc_pc = f"Computador {comp.patrimonio}"
        specs = comp.resumo_specs
    else:
        desc_pc = "Computador"
        specs = " · ".join(p for p in [t.so_novo, t.processador_novo, t.armazenamento_novo] if p)
    if specs and specs != "—":
        desc_pc = f"{desc_pc} — {specs}"

    itens = [{"descricao": desc_pc, "qtd": "1 un"}]
    if origem:
        for attr, rotulo in PERIFERICOS:
            val = getattr(origem, attr, "")
            if val in (PerifStatus.SIM, PerifStatus.DEFEITO):
                sufixo = " (com defeito)" if val == PerifStatus.DEFEITO else ""
                itens.append({"descricao": f"{rotulo}{sufixo}", "qtd": "1 un"})

    # Tabela com no mínimo 8 linhas numeradas (como o modelo da planilha).
    total_linhas = max(8, len(itens))
    linhas = []
    for i in range(total_linhas):
        it = itens[i] if i < len(itens) else {"descricao": "", "qtd": ""}
        linhas.append({"n": i + 1, "descricao": it["descricao"], "qtd": it["qtd"]})

    contexto = {
        "t": t,
        "uni_origem": uni_origem,
        "uni_destino": uni_destino,
        "setor_destino_nome": setor_destino_nome,
        "colab_saida": t.colaborador_saida,
        "colab_destino": t.colaborador_destino,
        "data_saida": t.data_saida,
        "data_entrada": t.data_entrada,
        "linhas": linhas,
    }
    # O botão "voltar" do documento aponta para a tela de origem —
    # nunca para o histórico (ver o comentário no template).
    contexto.update(_voltar("/parque/transferencias/"))
    return render(request, "parque/protocolo.html", contexto)


@staff_member_required
def mapa_criticos(request, unidade_id=None):
    """Mapa das máquinas em estado CRÍTICO (índice de desempenho), por unidade › setor.

    Sem unidade_id: todas as unidades. Com unidade_id: só aquela loja.
    """
    baias = (
        Baia.objects.select_related("setor__unidade", "colaborador", "computador")
        .prefetch_related("reparos")
        .order_by("setor__unidade__name", "setor__nome", "nome")
    )
    if unidade_id:
        # Loja que não existe é 404, não "0 críticas". Com id inventado a tela
        # abria vazia e a lista vazia lê como boa notícia — o oposto da
        # verdade, que é "essa loja não existe". Gente troca número na URL.
        get_object_or_404(Location, pk=unidade_id)
        baias = baias.filter(setor__unidade_id=unidade_id)

    criticas = [b for b in baias if b.classe_desempenho == "Crítico"]
    grupos = {}
    for b in criticas:
        grupos.setdefault(b.setor.unidade, {}).setdefault(b.setor, []).append(b)
    unidades_estrut = [
        {"unidade": uni, "setores": [{"setor": s, "baias": bl} for s, bl in setores.items()]}
        for uni, setores in grupos.items()
    ]

    escopo = ""
    if unidade_id:
        uni = Location.objects.filter(pk=unidade_id).first()
        escopo = f" — {uni.name}" if uni else ""
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "titulo": f"Computadores em estado crítico{escopo}",
        "unidades_estrut": unidades_estrut,
        "total": len(criticas),
        "title": "Mapa — Máquinas críticas",
        **_ctx_transferencia(request),
    })
    return render(request, "parque/mapa_filtro.html", contexto)


@staff_member_required
def mapa_preventiva(request):
    """Mapa das máquinas com manutenção preventiva PENDENTE ou VENCIDA (60 dias)."""
    baias = (
        Baia.objects.select_related("setor__unidade", "colaborador", "computador")
        .prefetch_related("reparos")
        .order_by("setor__unidade__name", "setor__nome", "-numero", "nome")
    )
    alvo = [b for b in baias if b.preventiva_status in ("pendente", "vencida")]
    # Mais tempo sem manutenção primeiro.
    alvo.sort(key=lambda b: b.dias_sem_preventiva, reverse=True)

    grupos = {}
    for b in alvo:
        grupos.setdefault(b.setor.unidade, {}).setdefault(b.setor, []).append(b)
    unidades_estrut = [
        {"unidade": uni, "setores": [{"setor": s, "baias": bl} for s, bl in setores.items()]}
        for uni, setores in grupos.items()
    ]

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "titulo": "Manutenção preventiva pendente / vencida",
        "unidades_estrut": unidades_estrut,
        "total": len(alvo),
        "title": "Mapa — Preventiva pendente",
        **_ctx_transferencia(request),
    })
    return render(request, "parque/mapa_filtro.html", contexto)


@staff_member_required
def mapa_score(request):
    """Mapa por SCORE: PCs (baias) + notebooks dentro da faixa escolhida.

    Vem dos gráficos do explorador de score (na Início). Query (tudo opcional):
        ?min=&max=  → faixa de score (0–100)
        ?classe=    → Crítico / Baixo / Bom / Ótimo
        ?unidade=   → nome da unidade
    """
    def _faixa(v, padrao):
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return padrao

    lo = _faixa(request.GET.get("min"), 0)
    hi = _faixa(request.GET.get("max"), 100)
    if lo > hi:
        lo, hi = hi, lo
    classe = (request.GET.get("classe") or "").strip() or None
    unidade = (request.GET.get("unidade") or "").strip() or None
    tipo = (request.GET.get("tipo") or "").strip().lower() or None  # "pc" | "nb"

    estrut = {}  # unidade -> setor -> [(score, kind, obj)]

    def _add(uni, setor, score, kind, obj):
        estrut.setdefault(uni, {}).setdefault(setor, []).append((score, kind, obj))

    def _cabe(idx, cl, uni):
        return idx is not None and lo <= idx <= hi \
            and (not classe or cl == classe) and (not unidade or uni == unidade)

    # PCs (baias) — reaproveitam o card _baia.html (clique abre o monitor animado)
    if tipo != "nb":
        baias = (
            Baia.objects.select_related("setor__unidade", "colaborador", "computador")
            .prefetch_related("reparos")
            .order_by("setor__unidade__name", "setor__nome", "-numero", "nome")
        )
        for b in baias:
            idx, cl, uni = b.indice_desempenho, b.classe_desempenho, b.setor.unidade.name
            if _cabe(idx, cl, uni):
                _add(uni, b.setor.nome, idx, "pc", b)

    # Notebooks — card equivalente (clique abre a animação de laptop)
    if tipo != "pc":
        uni_canon = list(
            Location.objects.filter(setores__isnull=False).distinct()
            .order_by("name").values_list("name", flat=True)
        )
        uni_lower = {n.lower(): n for n in uni_canon}
        aliases = {"vilar dos teles": "Vilar", "vilar de teles": "Vilar"}
        for nb in Notebook.objects.select_related("colaborador__location", "colaborador__department", "baia__setor__unidade"):
            idx, cl = nb.indice_desempenho, nb.classe_desempenho
            uni, setor = _unidade_setor_notebook(nb, uni_lower, aliases)
            if _cabe(idx, cl, uni):
                _add(uni, setor, idx, "nb", nb)

    unidades_estrut, total = [], 0
    for uni in sorted(estrut.keys()):
        setores = []
        for s in sorted(estrut[uni].keys(), key=lambda x: (x != "Geral", x.lower())):
            devs = sorted(estrut[uni][s], key=lambda t: t[0])
            setores.append({
                "setor": s,
                "dispositivos": [{"kind": k, "obj": o} for _, k, o in devs],
            })
            total += len(devs)
        unidades_estrut.append({"unidade": uni, "setores": setores})

    partes = [f"score {lo}–{hi}"]
    if classe:
        partes.append(f"classe {classe}")
    if unidade:
        partes.append(unidade)

    unidades_loc = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "titulo": "Dispositivos — " + " · ".join(partes),
        "unidades_estrut": unidades_estrut,
        "total": total,
        "title": "Mapa por Score",
        **_filtros_ctx(request, unidades_loc, por_nome=True),
        **_ctx_transferencia(request),
    })
    return render(request, "parque/mapa_score.html", contexto)


@staff_member_required
def transferir_peca(request, pk):
    """Transfere uma quantidade de peças de uma unidade para outra."""
    if not request.user.has_perm("parque.change_peca"):
        messages.error(request, "Você não tem permissão para transferir peças.")
        return redirect("admin:parque_peca_changelist")

    peca = get_object_or_404(Peca.objects.select_related("unidade"), pk=pk)
    unidades = (
        Location.objects.filter(setores__isnull=False)
        .exclude(pk=peca.unidade_id).distinct().order_by("name")
    )

    colaboradores = Person.objects.filter(active=True).order_by("full_name")

    if request.method == "POST":
        destino = get_object_or_404(Location, pk=request.POST.get("unidade_destino"))
        try:
            qtd = int(request.POST.get("quantidade", "0"))
        except ValueError:
            qtd = 0
        colaborador = Person.objects.filter(pk=request.POST.get("colaborador_destino")).first()
        data_chegada = (request.POST.get("data_chegada") or "").strip() or None
        bitrix = (request.POST.get("bitrix_task_id") or "").strip()
        if destino.pk == peca.unidade_id:
            messages.error(request, "Escolha uma unidade diferente da origem.")
        elif qtd <= 0 or qtd > peca.quantidade:
            messages.error(request, f"Quantidade inválida (disponível: {peca.quantidade}).")
        elif not bitrix:
            messages.error(request, "Informe o código da tarefa do Bitrix para concluir a transferência.")
        else:
            with transaction.atomic():
                # LOST UPDATE: a checagem `qtd > peca.quantidade` acima usa o
                # valor lido ANTES da transação. Duas transferências simultâneas
                # da mesma peça passavam as duas e o estoque ficava negativo.
                # `select_for_update` trava a linha até o commit; a quantidade é
                # relida e revalidada aqui dentro.
                peca = Peca.objects.select_for_update().get(pk=peca.pk)
                if qtd > peca.quantidade:
                    messages.error(
                        request,
                        f"Estoque mudou enquanto você preenchia: disponível agora "
                        f"é {peca.quantidade}. Confira e tente de novo.",
                    )
                    return redirect("parque_transferir_peca", pk=peca.pk)
                peca.quantidade -= qtd
                peca.save(update_fields=["quantidade"])
                destino_peca, _ = (
                    Peca.objects.select_for_update()
                    .get_or_create(unidade=destino, tipo=peca.tipo,
                                   descricao=peca.descricao)
                )
                destino_peca.quantidade += qtd
                destino_peca.save(update_fields=["quantidade"])
                mov = MovimentacaoPeca.objects.create(
                    tipo=peca.tipo, descricao=peca.descricao, unidade_origem=peca.unidade,
                    unidade_destino=destino, quantidade=qtd, por_usuario=request.user,
                    colaborador_destino=colaborador, data_chegada=data_chegada,
                    bitrix_task_id=bitrix,
                )
            messages.success(request, f"{qtd}× {peca.descricao} transferida(s) para {destino}. Protocolo gerado.")
            # Abre o comprovante (protocolo) da transferência de peças.
            return redirect("parque_protocolo_peca", pk=mov.pk)

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "peca": peca, "unidades": unidades, "colaboradores": colaboradores,
        "title": f"Transferir {peca.descricao}",
        **_voltar("/parque/tabela-pecas/"),
    })
    return render(request, "parque/transferir_peca.html", contexto)


@staff_member_required
def protocolo_peca(request, pk):
    """Comprovante de transferência de PEÇAS entre lojas — página de impressão."""
    mov = get_object_or_404(
        MovimentacaoPeca.objects.select_related("unidade_origem", "unidade_destino", "por_usuario"),
        pk=pk,
    )
    desc = f"{mov.get_tipo_display()} — {mov.descricao}"
    itens = [{"descricao": desc, "qtd": f"{mov.quantidade} un"}]
    total_linhas = max(8, len(itens))
    linhas = []
    for i in range(total_linhas):
        it = itens[i] if i < len(itens) else {"descricao": "", "qtd": ""}
        linhas.append({"n": i + 1, "descricao": it["descricao"], "qtd": it["qtd"]})

    contexto = {
        "t": mov,
        "uni_origem": mov.unidade_origem.name if mov.unidade_origem_id else "—",
        "uni_destino": mov.unidade_destino.name if mov.unidade_destino_id else "—",
        "setor_destino_nome": "",
        "colab_saida": mov.por_usuario.get_full_name() or mov.por_usuario.get_username() if mov.por_usuario_id else "",
        "colab_destino": mov.colaborador_destino.full_name if mov.colaborador_destino_id else "",
        "data_saida": mov.em,
        "data_entrada": mov.data_chegada,
        "linhas": linhas,
    }
    # O botão "voltar" do documento aponta para a tela de origem —
    # nunca para o histórico (ver o comentário no template).
    contexto.update(_voltar("/parque/tabela-pecas/"))
    return render(request, "parque/protocolo.html", contexto)


@staff_member_required
def montar_caixa(request):
    """Monta uma CAIXA com vários itens (peças) e gera 1 protocolo de envio."""
    if not request.user.has_perm("parque.change_peca"):
        messages.error(request, "Você não tem permissão para transferir peças.")
        return redirect("admin:parque_peca_changelist")

    unidades = list(
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    pecas = list(
        Peca.objects.filter(quantidade__gte=1).select_related("unidade").order_by("unidade__name", "descricao")
    )
    colaboradores = Person.objects.filter(active=True).order_by("full_name")

    if request.method == "POST":
        origem = get_object_or_404(Location, pk=request.POST.get("unidade_origem"))
        destino = get_object_or_404(Location, pk=request.POST.get("unidade_destino"))
        colaborador = Person.objects.filter(pk=request.POST.get("colaborador_destino")).first()
        data_chegada = (request.POST.get("data_chegada") or "").strip() or None
        # itens: pares peca_<id> = quantidade
        selecionados = []
        for chave, valor in request.POST.items():
            if not chave.startswith("peca_"):
                continue
            try:
                pid = int(chave[5:]); qtd = int(valor)
            except (ValueError, TypeError):
                continue
            if qtd <= 0:
                continue
            p = Peca.objects.filter(pk=pid, unidade=origem).first()
            if p and qtd <= p.quantidade:
                selecionados.append((p, qtd))

        # itens AVULSOS (fora do estoque): listas paralelas nome/tipo/qtd.
        # Só entram no PROTOCOLO — não mexem no estoque de peças.
        avulsos = []
        nomes = request.POST.getlist("avulso_nome")
        tipos = request.POST.getlist("avulso_tipo")
        qtds = request.POST.getlist("avulso_qtd")
        for i, nome in enumerate(nomes):
            nome = (nome or "").strip()
            if not nome:
                continue
            try:
                q = int(qtds[i]) if i < len(qtds) else 0
            except (ValueError, TypeError):
                q = 0
            if q <= 0:
                continue
            tp = tipos[i] if i < len(tipos) else Peca.Tipo.OUTRO
            if tp not in Peca.Tipo.values:
                tp = Peca.Tipo.OUTRO
            avulsos.append((tp, nome[:120], q))

        if origem.pk == destino.pk:
            messages.error(request, "O destino precisa ser diferente da origem.")
        elif not selecionados and not avulsos:
            messages.error(request, "Selecione ao menos um item — do estoque ou avulso — com quantidade válida.")
        else:
            from django.db import transaction
            with transaction.atomic():
                remessa = Remessa.objects.create(
                    unidade_origem=origem, unidade_destino=destino,
                    colaborador_destino=colaborador, data_chegada=data_chegada,
                    por_usuario=request.user,
                )
                for p, qtd in selecionados:
                    p.quantidade -= qtd
                    p.save(update_fields=["quantidade"])
                    dst, _ = Peca.objects.get_or_create(
                        unidade=destino, tipo=p.tipo, descricao=p.descricao,
                    )
                    dst.quantidade += qtd
                    dst.save(update_fields=["quantidade"])
                    MovimentacaoPeca.objects.create(
                        remessa=remessa, tipo=p.tipo, descricao=p.descricao,
                        unidade_origem=origem, unidade_destino=destino, quantidade=qtd,
                        colaborador_destino=colaborador, data_chegada=data_chegada,
                        por_usuario=request.user,
                    )
                # Itens avulsos: entram no protocolo SEM baixar/gerar estoque.
                for tp, desc, qtd in avulsos:
                    MovimentacaoPeca.objects.create(
                        remessa=remessa, tipo=tp, descricao=desc,
                        unidade_origem=origem, unidade_destino=destino, quantidade=qtd,
                        colaborador_destino=colaborador, data_chegada=data_chegada,
                        por_usuario=request.user,
                    )
            total = len(selecionados) + len(avulsos)
            messages.success(request, f"Caixa com {total} item(ns) enviada para {destino}. Protocolo gerado.")
            return redirect("parque_protocolo_remessa", pk=remessa.pk)

    # Itens pré-selecionados (vindos da ação "Montar caixa" da lista de Peças).
    pre_ids = []
    for x in (request.GET.get("ids") or "").split(","):
        if x.strip().isdigit():
            pre_ids.append(int(x))
    # A origem padrão é a loja dos itens pré-selecionados (a 1ª com itens válidos).
    origem_sel = None
    if pre_ids:
        primeiro = next((p for p in pecas if p.id in pre_ids and p.quantidade >= 1), None)
        if primeiro:
            origem_sel = primeiro.unidade_id
    if origem_sel is None and unidades:
        origem_sel = unidades[0].id

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Montar caixa de envio",
        "unidades": unidades,
        "pecas": pecas,
        "colaboradores": colaboradores,
        "pre_ids": pre_ids,
        "origem_sel": origem_sel,
        "tipos_peca": Peca.Tipo.choices,
        # Modo "protocolo genérico": foco em itens avulsos (estoque fica recolhido).
        "generico": request.GET.get("generico") == "1",
        **_voltar("/parque/tabela-pecas/"),
    })
    return render(request, "parque/montar_caixa.html", contexto)


@staff_member_required
def protocolo_remessa(request, pk):
    """Comprovante de uma CAIXA (remessa) com vários itens — impressão."""
    r = get_object_or_404(
        Remessa.objects.select_related(
            "unidade_origem", "unidade_destino", "colaborador_destino", "por_usuario"
        ),
        pk=pk,
    )
    itens = [
        {"descricao": f"{m.get_tipo_display()} — {m.descricao}", "qtd": f"{m.quantidade} un"}
        for m in r.itens.all()
    ]
    total_linhas = max(8, len(itens))
    linhas = []
    for i in range(total_linhas):
        it = itens[i] if i < len(itens) else {"descricao": "", "qtd": ""}
        linhas.append({"n": i + 1, "descricao": it["descricao"], "qtd": it["qtd"]})

    contexto = {
        "t": r,
        "uni_origem": r.unidade_origem.name if r.unidade_origem_id else "—",
        "uni_destino": r.unidade_destino.name if r.unidade_destino_id else "—",
        "setor_destino_nome": "",
        "colab_saida": (r.por_usuario.get_full_name() or r.por_usuario.get_username()) if r.por_usuario_id else "",
        "colab_destino": r.colaborador_destino.full_name if r.colaborador_destino_id else "",
        "data_saida": r.em,
        "data_entrada": r.data_chegada,
        "linhas": linhas,
    }
    # O botão "voltar" do documento aponta para a tela de origem —
    # nunca para o histórico (ver o comentário no template).
    contexto.update(_voltar("/parque/estoque/"))
    return render(request, "parque/protocolo.html", contexto)


@staff_member_required
def transferencias_todas(request):
    """Lista UNIFICADA de transferências: computadores + notebooks + peças/caixas."""
    def _por(u):
        if not u:
            return ""
        return u.get_full_name() or u.get_username()

    linhas = []

    # --- Computadores: entre lojas + movimentação interna (fluxo novo tem
    #     setor_destino; exclui transferências legadas importadas sem destino). ---
    for t in (Transferencia.objects.filter(Q(entre_lojas=True) | Q(setor_destino__isnull=False))
              .select_related("baia_origem__setor__unidade", "baia_destino__setor__unidade",
                              "setor_destino__unidade", "registrado_por")):
        interno = not t.entre_lojas
        o = t.baia_origem
        uni_o = o.setor.unidade.name if o and o.setor_id else ""
        origem = f"{uni_o} › {o.setor.nome} › {o.nome}" if o and o.setor_id else "—"
        if t.baia_destino_id:
            d = t.baia_destino
            uni_d = d.setor.unidade.name
            destino = f"{uni_d} › {d.setor.nome} › {d.nome}"
        elif t.setor_destino_id:
            uni_d = t.setor_destino.unidade.name
            destino = f"{uni_d} › {t.setor_destino.nome}" + (f" › {t.nome_baia_destino}" if t.nome_baia_destino else "")
        else:
            uni_d, destino = "", "—"
        pend = t.status == Transferencia.Status.PENDENTE
        linhas.append({
            "tipo": "Mov. interna" if interno else "Computador",
            "icone": "swap" if interno else "monitor", "data": t.data_entrada,
            "origem": origem, "destino": destino,
            "csaida": t.colaborador_saida, "cdest": t.colaborador_destino,
            "situacao": t.get_status_display(), "status": t.status, "por": _por(t.registrado_por),
            "protocolo": (reverse("parque_protocolo_transferencia", args=[t.pk])
                          if t.status == Transferencia.Status.AUTORIZADA else None),
            "unidades": [uni_o, uni_d], "tipo_key": "computador", "pk": t.pk,
            "decide_aut": reverse("parque_decidir_transferencia", args=[t.pk, "autorizar"]) if pend else None,
            "decide_neg": reverse("parque_decidir_transferencia", args=[t.pk, "negar"]) if pend else None,
        })

    # --- Notebooks ---
    for t in TransferenciaNotebook.objects.select_related("unidade_destino", "registrado_por"):
        uni_d = t.unidade_destino.name if t.unidade_destino_id else ""
        pend = t.status == TransferenciaNotebook.Status.PENDENTE
        linhas.append({
            "tipo": "Notebook", "icone": "laptop", "data": t.data,
            "origem": t.unidade_origem or "—", "destino": uni_d or "—",
            "csaida": t.usuario, "cdest": t.usuario_destino,
            "situacao": t.get_status_display(), "status": t.status, "por": _por(t.registrado_por),
            "protocolo": (reverse("parque_protocolo_notebook", args=[t.pk])
                          if t.status == TransferenciaNotebook.Status.AUTORIZADA else None),
            "unidades": [t.unidade_origem or "", uni_d], "tipo_key": "notebook", "pk": t.pk,
            "decide_aut": reverse("parque_decidir_transferencia_notebook", args=[t.pk, "autorizar"]) if pend else None,
            "decide_neg": reverse("parque_decidir_transferencia_notebook", args=[t.pk, "negar"]) if pend else None,
        })

    # --- Peças em caixa (remessa) ---
    for r in Remessa.objects.select_related("unidade_origem", "unidade_destino",
                                            "colaborador_destino", "por_usuario").prefetch_related("itens"):
        uni_o = r.unidade_origem.name if r.unidade_origem_id else ""
        uni_d = r.unidade_destino.name if r.unidade_destino_id else ""
        linhas.append({
            "tipo": f"Peças (caixa · {r.itens.count()} itens)", "icone": "box", "data": r.em.date(),
            "origem": uni_o or "—", "destino": uni_d or "—",
            "csaida": _por(r.por_usuario),
            "cdest": r.colaborador_destino.full_name if r.colaborador_destino_id else "",
            "situacao": "Enviada", "status": "autorizada", "por": _por(r.por_usuario),
            "protocolo": reverse("parque_protocolo_remessa", args=[r.pk]),
            "unidades": [uni_o, uni_d], "tipo_key": "remessa", "pk": r.pk,
        })

    # --- Peças avulsas (sem caixa) ---
    for m in (MovimentacaoPeca.objects.filter(remessa__isnull=True)
              .select_related("unidade_origem", "unidade_destino", "colaborador_destino", "por_usuario")):
        uni_o = m.unidade_origem.name if m.unidade_origem_id else ""
        uni_d = m.unidade_destino.name if m.unidade_destino_id else ""
        linhas.append({
            "tipo": f"Peça ({m.descricao})", "icone": "puzzle", "data": m.em.date(),
            "origem": uni_o or "—", "destino": uni_d or "—",
            "csaida": _por(m.por_usuario),
            "cdest": m.colaborador_destino.full_name if m.colaborador_destino_id else "",
            "situacao": "Enviada", "status": "autorizada", "por": _por(m.por_usuario),
            "protocolo": reverse("parque_protocolo_peca", args=[m.pk]),
            "unidades": [uni_o, uni_d], "tipo_key": "peca", "pk": m.pk,
        })

    # --- Envios para autorizada / assistência externa ---
    for e in EnvioAutorizada.objects.select_related("autorizada", "registrado_por"):
        linhas.append({
            "tipo": "Assistência externa", "icone": "factory", "data": e.criado_em.date(),
            "origem": e.patrimonio or e.equipamento_display, "destino": str(e.autorizada),
            "csaida": "", "cdest": "",
            "situacao": e.get_status_display(), "status": e.status, "por": _por(e.registrado_por),
            "protocolo": reverse("parque_protocolo_autorizada", args=[e.pk]),
            "unidades": [], "tipo_key": "autorizada", "pk": e.pk,
            "detalhe": reverse("parque_envio_autorizada_detalhe", args=[e.pk]),
        })

    # Filtro por unidade (origem OU destino).
    unidades = list(Location.objects.filter(setores__isnull=False).distinct().order_by("name"))
    uni_sel = request.GET.get("unidade")
    uni_obj = next((u for u in unidades if str(u.id) == uni_sel), None)
    if uni_obj:
        linhas = [r for r in linhas if uni_obj.name in (r["unidades"] or [])]

    # Tipo e situação: esta tela junta CINCO fontes (computador, movimentação
    # interna, notebook, peça/caixa e assistência) e o dono chega nela querendo
    # uma delas — "o que está pendente de autorizar?", "as caixas de peça".
    # Filtra em Python porque a lista é a união de cinco consultas; os rótulos
    # de situação são os que as próprias linhas publicam, então nenhuma opção
    # aparece sem existir na lista.
    TIPOS = [("computador", "Computador"), ("movimentacao", "Mov. interna"),
             ("notebook", "Notebook"), ("remessa", "Peças (caixa)"),
             ("peca", "Peça avulsa"), ("autorizada", "Assistência externa")]
    # "Mov. interna" não tem `tipo_key` próprio (compartilha "computador" com a
    # transferência entre lojas): o que separa as duas é o rótulo.
    for r in linhas:
        r["filtro_key"] = ("movimentacao" if r["tipo"] == "Mov. interna" else r["tipo_key"])
    tipo_sel = (request.GET.get("tipo") or "").strip()
    if tipo_sel:
        linhas = [r for r in linhas if r["filtro_key"] == tipo_sel]
    sits = sorted({(r["status"], r["situacao"]) for r in linhas if r.get("status")})
    sit_sel = (request.GET.get("situacao") or "").strip()
    if sit_sel:
        linhas = [r for r in linhas if r["status"] == sit_sel]

    linhas.sort(key=lambda r: (r["data"] or timezone.localdate()), reverse=True)

    # Visualizou → zera o badge de "novas" no menu.
    request.session["transferencias_visto_em"] = timezone.now().isoformat()

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Transferências / Movimentações internas",
        "linhas": linhas,
        "total": len(linhas),
        "unidades": unidades,
        "uni_sel": uni_obj.id if uni_obj else None,
        "pode_decidir": pode_mover_baia(request.user),
        **barra_filtros(request, [
            {"param": "unidade", "label": "Unidade", "todos": "Todas",
             "opcoes": [(u.id, u.name) for u in unidades]},
            {"param": "tipo", "label": "Tipo", "todos": "Todos", "opcoes": TIPOS},
            {"param": "situacao", "label": "Situação", "todos": "Todas", "opcoes": sits},
        ]),
    })
    return render(request, "parque/transferencias.html", contexto)


# ======================= ENVIO PARA AUTORIZADA / ASSISTÊNCIA =======================

# Colunas do quadro Kanban (na ordem do fluxo). key == EnvioAutorizada.Status.
_AUT_COLS = [
    {"key": "enviado", "titulo": "Enviado", "icone": "outbox"},
    {"key": "em_analise", "titulo": "Em análise", "icone": "search"},
    {"key": "aguardando", "titulo": "Aguardando aprovação", "icone": "money"},
    {"key": "em_reparo", "titulo": "Em reparo", "icone": "wrench"},
    {"key": "retornando", "titulo": "Retornando", "icone": "box"},
    {"key": "finalizado", "titulo": "Finalizado", "icone": "check"},
]


def _equipamentos_para_envio():
    """Opções de equipamento para o formulário de envio (value = 'c:<id>' / 'n:<id>')."""
    comps = [
        {"val": f"c:{c.pk}", "label": f"{c.patrimonio} · {c.resumo_specs}".strip(" ·")}
        for c in Computador.objects.order_by("patrimonio")
    ]
    nbs = [
        {"val": f"n:{n.pk}", "label": f"{n.patrimonio} · {n.marca} {n.modelo}".strip(" ·")}
        for n in Notebook.objects.order_by("patrimonio")
    ]
    return comps, nbs


@staff_member_required
def enviar_autorizada(request, pk=None):
    """Registra (ou EDITA, quando vem `pk`) um envio de equipamento para uma
    autorizada. Exige o código da tarefa do Bitrix. Editar reabre este formulário
    pré-preenchido para corrigir dados inseridos errados."""
    perm = "parque.change_envioautorizada" if pk else "parque.add_envioautorizada"
    if not request.user.has_perm(perm):
        messages.error(request, "Você não tem permissão para essa ação.")
        return redirect("parque_transferencias")

    envio = get_object_or_404(EnvioAutorizada, pk=pk) if pk else None
    autorizadas = Autorizada.objects.filter(ativo=True).order_by("nome")
    comps, nbs = _equipamentos_para_envio()

    if request.method == "POST":
        equip = (request.POST.get("equipamento") or "").strip()
        autorizada = Autorizada.objects.filter(pk=request.POST.get("autorizada") or 0).first()
        bitrix = (request.POST.get("bitrix_task_id") or "").strip()
        problema = (request.POST.get("problema") or "").strip()
        avulso_desc = (request.POST.get("equipamento_desc") or "").strip()
        erro = None
        if not autorizada:
            erro = "Escolha a autorizada / assistência."
        elif not equip:
            erro = "Escolha o equipamento a enviar."
        elif equip == "outro" and not avulso_desc:
            erro = "Descreva o item avulso (fora do estoque)."
        elif equip != "outro" and ":" not in equip:
            erro = "Escolha o equipamento a enviar."
        elif not bitrix:
            erro = "Informe o código da tarefa do Bitrix."
        if erro:
            messages.error(request, erro)
        else:
            obj = envio or EnvioAutorizada(registrado_por=request.user)
            obj.autorizada = autorizada
            obj.bitrix_task_id = bitrix
            obj.problema = problema
            nf_erro = None
            nfs = []
            # Documentos (NF de compra e/ou Ordem de Serviço) — anexo único p/ vários arquivos.
            for f in request.FILES.getlist("nf_compra"):
                ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
                if ext not in EnvioAutorizada.FORMATOS:
                    nf_erro = f"Documento “{f.name}”: formato não permitido (PDF/JPG/JPEG/PNG)."
                    break
                nfs.append(f)
            if equip == "outro":
                # Item FORA do estoque — descrição livre, sem computador/notebook.
                obj.computador = None
                obj.notebook = None
                obj.equipamento_desc = avulso_desc
                try:
                    obj.quantidade = max(1, int(request.POST.get("quantidade") or 1))
                except (TypeError, ValueError):
                    obj.quantidade = 1
                obj.patrimonio = (request.POST.get("patrimonio") or "").strip()
                obj.serial = (request.POST.get("serial") or "").strip()
            else:
                tipo, _, pkd = equip.partition(":")
                if tipo == "c":
                    obj.computador = Computador.objects.filter(pk=pkd).first()
                    obj.notebook = None
                else:
                    obj.notebook = Notebook.objects.filter(pk=pkd).first()
                    obj.computador = None
                obj.quantidade = 1
                obj.preencher_snapshot()
            if nf_erro:
                messages.error(request, nf_erro)
            elif not obj.equipamento_desc and obj.dispositivo is None:
                messages.error(request, "Equipamento não encontrado.")
            else:
                obj.save()
                for f in nfs:
                    NotaCompraEnvio.objects.create(envio=obj, arquivo=f)
                if envio:
                    RegistroEnvioAutorizada.objects.create(
                        envio=obj, autor=request.user, texto="Dados do envio corrigidos/atualizados.")
                    messages.success(request, "Dados do envio atualizados.")
                else:
                    RegistroEnvioAutorizada.objects.create(
                        envio=obj, autor=request.user,
                        texto=f"Enviado para {autorizada} (Bitrix {bitrix}).")
                    messages.success(request, f"Envio criado para {autorizada}.")
                return redirect("parque_envio_autorizada_detalhe", pk=obj.pk)

    # Valor atual do <select> de equipamento (para pré-selecionar na edição).
    equip_atual = ""
    if envio:
        if envio.computador_id:
            equip_atual = f"c:{envio.computador_id}"
        elif envio.notebook_id:
            equip_atual = f"n:{envio.notebook_id}"
        else:
            equip_atual = "outro"

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Editar envio" if envio else "Enviar para autorizada",
        "autorizadas": autorizadas,
        "computadores": comps,
        "notebooks": nbs,
        "envio": envio,
        "equip_atual": equip_atual,
        **_voltar(reverse("parque_envio_autorizada_detalhe", args=[envio.pk]) if envio else "/parque/autorizadas/"),
    })
    return render(request, "parque/enviar_autorizada.html", contexto)


@staff_member_required
def autorizadas_kanban(request):
    """Quadro Kanban dos envios para autorizada, por status."""
    qs = EnvioAutorizada.objects.select_related("autorizada").order_by("-criado_em")
    autorizadas = list(Autorizada.objects.order_by("nome"))
    aut_sel = request.GET.get("autorizada")
    aut_obj = next((a for a in autorizadas if str(a.id) == aut_sel), None)
    if aut_obj:
        qs = qs.filter(autorizada=aut_obj)

    cols = [{**c, "itens": []} for c in _AUT_COLS]
    por_key = {c["key"]: c for c in cols}
    for e in qs:
        por_key.get(e.status, por_key["enviado"])["itens"].append(e)
    for c in cols:
        c["qtd"] = len(c["itens"])

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Assistência externa",
        "colunas": cols,
        "autorizadas": autorizadas,
        "aut_sel": aut_obj.id if aut_obj else None,
        "total": sum(c["qtd"] for c in cols),
        "pode_add": request.user.has_perm("parque.add_envioautorizada"),
        # Um grupo só, e de propósito: no Kanban a ETAPA já é a coluna (filtrar
        # por etapa esconderia o quadro), então a única dimensão que sobra é a
        # autorizada. É o mesmo caso do quadro de chamados, que também entra no
        # popup com um grupo. Se não houver autorizada cadastrada, o parcial não
        # rende nada e a tela fica sem o botão.
        **barra_filtros(request, [
            {"param": "autorizada", "label": "Autorizada", "todos": "Todas",
             "opcoes": [(a.id, a.nome) for a in autorizadas]},
        ]),
        **_voltar("/parque/transferencias/"),
    })
    return render(request, "parque/autorizadas_kanban.html", contexto)


@staff_member_required
def envio_autorizada_detalhe(request, pk):
    """Detalhe do envio: avança a máquina de estados (com anexos exigidos por etapa)
    e recebe comentários de andamento (timeline)."""
    envio = get_object_or_404(EnvioAutorizada.objects.select_related("autorizada"), pk=pk)
    pode_editar = request.user.has_perm("parque.change_envioautorizada")
    S = EnvioAutorizada.Status

    if request.method == "POST" and pode_editar:
        acao = request.POST.get("acao")
        if acao == "registro":
            texto = (request.POST.get("texto") or "").strip()
            if texto:
                RegistroEnvioAutorizada.objects.create(envio=envio, autor=request.user, texto=texto)
                messages.success(request, "Comentário adicionado.")
        elif acao == "avancar":
            destino = request.POST.get("destino")
            ok, msg = _avancar_envio(envio, destino, request)
            messages.success(request, msg) if ok else messages.error(request, msg)
        elif acao == "add_nota":
            n = 0
            for f in request.FILES.getlist("nf_compra"):
                ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
                if ext in EnvioAutorizada.FORMATOS:
                    NotaCompraEnvio.objects.create(envio=envio, arquivo=f)
                    n += 1
            (messages.success(request, f"{n} NF(s) anexada(s).") if n
             else messages.error(request, "Nenhum arquivo válido (use PDF/JPG/JPEG/PNG)."))
        elif acao == "del_nota":
            nota = envio.notas_compra.filter(pk=request.POST.get("nota") or 0).first()
            if nota:
                nota.arquivo.delete(save=False)
                nota.delete()
                messages.success(request, "NF removida.")
        elif acao == "problema":
            envio.problema = (request.POST.get("problema") or "").strip()
            envio.save(update_fields=["problema", "atualizado_em"])
            messages.success(request, "Observações atualizadas.")
        elif acao == "descricao" and envio.eh_avulso:
            nova = (request.POST.get("equipamento_desc") or "").strip()
            if nova:
                envio.equipamento_desc = nova
                envio.save(update_fields=["equipamento_desc", "atualizado_em"])
                messages.success(request, "Descrição do item atualizada.")
            else:
                messages.error(request, "A descrição não pode ficar vazia.")
        return redirect("parque_envio_autorizada_detalhe", pk=envio.pk)

    # Etapas para exibição (marca a atual e as concluídas).
    ordem = [c["key"] for c in _AUT_COLS]
    idx_atual = ordem.index(envio.status) if envio.status in ordem else 0

    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": f"Envio · {envio.equipamento_display}",
        "envio": envio,
        "registros": envio.registros.select_related("autor").all(),
        "etapas": _AUT_COLS,
        "idx_atual": idx_atual,
        "pode_editar": pode_editar,
        "S": {s.name: s.value for s in S},
        **_voltar("/parque/autorizadas/"),
    })
    return render(request, "parque/envio_autorizada_detalhe.html", contexto)


def _avancar_envio(envio, destino, request):
    """Aplica uma transição da máquina de estados, validando o anexo/dado exigido.
    Retorna (ok, mensagem). Grava um registro automático na timeline."""
    from decimal import Decimal, InvalidOperation
    S = EnvioAutorizada.Status
    st = envio.status
    files = request.FILES
    P = request.POST
    user = request.user

    # Valida extensão no servidor (o FileExtensionValidator só roda em full_clean/form).
    for f in files.values():
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in EnvioAutorizada.FORMATOS:
            return False, f"Formato não permitido (.{ext}). Aceitos: PDF, JPG, JPEG, PNG."

    def _log(txt):
        RegistroEnvioAutorizada.objects.create(envio=envio, autor=user, texto=txt)

    # Enviado → Em análise (exige OS)
    if destino == S.EM_ANALISE and st == S.ENVIADO:
        if files.get("os_arquivo"):
            envio.os_arquivo = files["os_arquivo"]
        if not envio.os_arquivo:
            return False, "Anexe a OS da autorizada para ir para Em análise."
        envio.status = S.EM_ANALISE
        envio.save()
        _log("Em análise — OS da autorizada anexada.")
        return True, "Movido para Em análise."

    # Em análise → decisões
    if st == S.EM_ANALISE and destino == S.EM_REPARO:
        # devolutiva positiva SEM cobrança: sem custo OU em garantia
        garantia = P.get("garantia") == "1"
        envio.devolutiva = EnvioAutorizada.Devolutiva.POSITIVA
        if garantia:
            envio.valor_reparo = Decimal("0")
        envio.status = S.EM_REPARO
        envio.save()
        _log("Devolutiva positiva — em GARANTIA (sem cobrança). Em reparo." if garantia
             else "Devolutiva positiva — sem custo. Em reparo.")
        return True, "Devolutiva positiva: em reparo."

    if st == S.EM_ANALISE and destino == S.FINALIZADO:
        # Reparo em GARANTIA já concluído e material de volta: finaliza DIRETO,
        # sem custo e sem exigir a etapa de retirada/foto.
        envio.devolutiva = EnvioAutorizada.Devolutiva.POSITIVA
        envio.valor_reparo = Decimal("0")
        envio.status = S.FINALIZADO
        envio.data_finalizado = timezone.now()
        envio.save()
        _log("Finalizado direto — reparo em GARANTIA (sem cobrança).")
        return True, "Finalizado (em garantia, sem cobrança)."

    if st == S.EM_ANALISE and destino == S.AGUARDANDO:
        valor = (P.get("valor_reparo") or "").strip().replace(",", ".")
        try:
            envio.valor_reparo = Decimal(valor) if valor else None
        except InvalidOperation:
            envio.valor_reparo = None
        if envio.valor_reparo is None:
            return False, "Informe o valor do reparo para aguardar aprovação."
        if files.get("orcamento_arquivo"):
            envio.orcamento_arquivo = files["orcamento_arquivo"]
        envio.devolutiva = EnvioAutorizada.Devolutiva.POSITIVA
        envio.status = S.AGUARDANDO
        envio.save()
        _log(f"Orçamento de R$ {envio.valor_reparo} — aguardando aprovação/pagamento.")
        return True, "Aguardando aprovação do orçamento."

    if st == S.EM_ANALISE and destino == S.RETORNANDO:
        # devolutiva negativa (sem conserto)
        motivo = (P.get("motivo") or "").strip()
        if not motivo:
            return False, "Descreva o motivo da devolutiva negativa."
        envio.devolutiva = EnvioAutorizada.Devolutiva.NEGATIVA
        envio.sem_conserto = True
        envio.status = S.RETORNANDO
        envio.save()
        _log(f"Devolutiva NEGATIVA (sem conserto): {motivo}")
        return True, "Devolutiva negativa: retornando (sem conserto)."

    # Aguardando aprovação → Em reparo (exige comprovante de pagamento)
    if st == S.AGUARDANDO and destino == S.EM_REPARO:
        if files.get("comprovante_pagamento"):
            envio.comprovante_pagamento = files["comprovante_pagamento"]
        if not envio.comprovante_pagamento:
            return False, "Anexe o comprovante de pagamento para liberar o reparo."
        envio.status = S.EM_REPARO
        envio.save()
        _log("Pagamento comprovado — em reparo.")
        return True, "Pagamento comprovado: em reparo."

    # Em reparo → Retornando (exige autorização de retirada: print OU texto)
    if st == S.EM_REPARO and destino == S.RETORNANDO:
        if files.get("autorizacao_arquivo"):
            envio.autorizacao_arquivo = files["autorizacao_arquivo"]
        texto = (P.get("autorizacao_texto") or "").strip()
        if texto:
            envio.autorizacao_texto = texto
        if not (envio.autorizacao_arquivo or envio.autorizacao_texto):
            return False, "Anexe o print da autorização de retirada ou escreva o texto."
        envio.status = S.RETORNANDO
        envio.save()
        _log("Material pronto — aguardando retirada (retornando).")
        return True, "Retornando (aguardando retirada)."

    # Retornando → Finalizado (exige foto do material recebido)
    if st == S.RETORNANDO and destino == S.FINALIZADO:
        if files.get("foto_recebido"):
            envio.foto_recebido = files["foto_recebido"]
        if not envio.foto_recebido:
            return False, "Anexe a foto do material físico recebido para finalizar."
        envio.status = S.FINALIZADO
        envio.data_finalizado = timezone.now()
        envio.save()
        _log("Material recebido — envio finalizado.")
        return True, "Envio finalizado."

    return False, "Transição inválida para a etapa atual."


@staff_member_required
def protocolo_autorizada(request, pk):
    """Protocolo de envio p/ autorizada (reusa o protocolo.html genérico)."""
    e = get_object_or_404(EnvioAutorizada.objects.select_related("autorizada"), pk=pk)
    dest_extra = " · ".join(filter(None, [e.autorizada.cidade, e.autorizada.telefone]))
    desc = e.equipamento_display + (f" · Patrimônio {e.patrimonio}" if e.patrimonio else "")
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "e": e,
        "uni_origem": "Make Distribuidora",
        "uni_destino": str(e.autorizada),
        "setor_destino_nome": dest_extra,
        "colab_saida": _por_nome(e.registrado_por),
        "data_saida": e.criado_em.date(),
        "item_desc": desc,
        "item_ns": e.serial,
        "item_qtd": f"{e.quantidade} un",
        "observacoes": e.problema,
        **_voltar("/parque/autorizadas/"),
    })
    # O botão "voltar" do documento aponta para a tela de origem —
    # nunca para o histórico (ver o comentário no template).
    contexto.update(_voltar("/parque/autorizadas/"))
    return render(request, "parque/protocolo_autorizada.html", contexto)


def _por_nome(user):
    if not user:
        return ""
    return user.get_full_name() or user.get_username()


@staff_member_required
@require_POST
def excluir_transferencia(request):
    """Exclui um registro de transferência. Peças voltam à unidade de origem (estorno)."""
    if not pode_mover_baia(request.user):
        messages.error(request, "Você não tem permissão para excluir transferências.")
        return redirect("parque_transferencias")
    modelos = {
        "computador": Transferencia,
        "notebook": TransferenciaNotebook,
        "remessa": Remessa,
        "peca": MovimentacaoPeca,
    }
    modelo = modelos.get(request.POST.get("tipo"))
    obj = modelo.objects.filter(pk=request.POST.get("pk")).first() if modelo else None
    if obj is not None:
        obj.delete()  # remessa/peça disparam o estorno (devolvem à origem)
        if request.POST.get("tipo") in ("remessa", "peca"):
            messages.success(request, "Transferência excluída — itens devolvidos à unidade de origem.")
        else:
            messages.success(request, "Registro de transferência excluído.")
    else:
        messages.error(request, "Registro não encontrado.")
    return redirect(destino_seguro(request, request.POST.get("next"),
                                   padrao="parque_transferencias"))


@staff_member_required
@require_POST
def excluir_transferencias_lote(request):
    """Exclui VÁRIOS registros selecionados (peças voltam à origem)."""
    if not pode_mover_baia(request.user):
        messages.error(request, "Você não tem permissão para excluir transferências.")
        return redirect("parque_transferencias")
    modelos = {
        "computador": Transferencia, "notebook": TransferenciaNotebook,
        "remessa": Remessa, "peca": MovimentacaoPeca,
    }
    n = devolvidos = 0
    for item in request.POST.getlist("itens"):
        tipo, _, pk = item.partition(":")
        modelo = modelos.get(tipo)
        obj = modelo.objects.filter(pk=pk).first() if (modelo and pk.isdigit()) else None
        if obj is not None:
            obj.delete()
            n += 1
            if tipo in ("remessa", "peca"):
                devolvidos += 1
    if n:
        msg = f"{n} transferência(s) excluída(s)."
        if devolvidos:
            msg += f" {devolvidos} com itens devolvidos à origem."
        messages.success(request, msg)
    else:
        messages.warning(request, "Nenhum registro selecionado.")
    return redirect(destino_seguro(request, request.POST.get("next"),
                                   padrao="parque_transferencias"))


@staff_member_required
@staff_member_required
def assistente_perguntar(request):
    """Assistente de ajuda: casa a pergunta do usuário com a base de tópicos.

    Responde JSON para o widget flutuante (static/js/make-assistente.js). É
    LEITURA pura: não grava nada, não altera estado. A base de conhecimento e a
    busca ficam em apps/parque/assistente.py.
    """
    from . import assistente as _assistente

    # O menu "Ajuda" saiu do sistema: o assistente é a porta única, então ele
    # precisa conseguir listar TODOS os assuntos, não só sugerir alguns.
    if request.GET.get("todos"):
        return JsonResponse({"indice": _assistente.indice()})

    pergunta = (request.GET.get("q") or "").strip()[:200]
    if not pergunta:
        return JsonResponse({
            "pergunta": "", "topicos": [],
            "sugestoes": _assistente.sugestoes(), "resposta_livre": None,
        })
    return JsonResponse(_assistente.responder(pergunta))


# A view `ajuda` foi removida em 09/2026 junto com a Central de Ajuda. Toda a
# ajuda do sistema e' o assistente (`assistente_perguntar`, abaixo), que
# responde em qualquer tela pelo "?" da barra ou por Alt+H.


#: Rótulo único de "sem loja de verdade" — usado por TODAS as telas para o balde
#: de máquinas sem unidade (cobertura, filtros de estoque, mapas).
SEM_UNIDADE = "Sem unidade"


def _mapa_aliases_unidades():
    """Mapas nome→canônico (lower) + apelidos p/ casar texto livre de unidade.

    FONTE ÚNICA da régua "sem unidade": um texto (`ultima_unidade` do computador ou
    `unidade_setor` do notebook) só vira unidade se casar aqui; senão a máquina é
    considerada SEM unidade. Assim todas as telas contam do mesmo jeito.
    """
    nomes = list(
        Location.objects.filter(setores__isnull=False).distinct()
        .order_by("name").values_list("name", flat=True))
    unidades_lower = {n.lower(): n for n in nomes}
    aliases = {"vilar dos teles": "Vilar", "vilar de teles": "Vilar"}
    return unidades_lower, aliases


def _unidade_computador(c, unidades_lower, aliases):
    """Unidade de um computador pela MESMA régua do notebook (sem loja de verdade):
      1. A BAIA onde está (camada fixa) — manda sobre tudo.
      2. O texto `ultima_unidade`, só se casar com uma unidade real.
    Sem baia e sem texto reconhecido → SEM_UNIDADE (retorna o rótulo único)."""
    baia = getattr(c, "baia", None)
    if baia is not None and baia.setor_id:
        return baia.setor.unidade.name
    texto = (getattr(c, "ultima_unidade", "") or "").strip()
    if texto:
        nome = unidades_lower.get(texto.lower()) or aliases.get(texto.lower())
        if nome:
            return nome
    return SEM_UNIDADE


def _unidade_setor_notebook(nb, unidades_lower, aliases):
    """Deriva (unidade, setor) de um notebook — FONTE ÚNICA p/ TODOS os mapas.

    Ordem de verdade (garante que o mesmo notebook apareça igual em qualquer mapa):
      1. A BAIA onde o notebook está (camada fixa) — manda sobre tudo.
      2. O vínculo do colaborador (location / department).
      3. O texto livre `unidade_setor`, casando a parte que bate com uma unidade real.
    Texto sem unidade reconhecida NÃO vira setor (evita 'setores fantasmas' como
    'Financeiro' / 'Centro de Distribuicao' aparecendo sob 'Sem unidade / setor').
    """
    baia = getattr(nb, "baia", None)
    if baia is not None and baia.setor_id:
        return baia.setor.unidade.name, baia.setor.nome
    c = nb.colaborador
    if c is not None and c.location_id:
        return c.location.name, (c.department.name if c.department_id else "Geral")
    texto = (nb.unidade_setor or "").strip()
    if not texto:
        return "Sem unidade / setor", "Geral"
    partes = [p.strip() for p in re.split(r"[/|]", texto) if p.strip()]
    uni, resto = None, []
    for p in partes:
        nome = unidades_lower.get(p.lower()) or aliases.get(p.lower())
        if nome and uni is None:
            uni = nome
        else:
            resto.append(p)
    if uni is None:
        return "Sem unidade / setor", "Geral"
    return uni, (" / ".join(resto) if resto else "Geral")


@staff_member_required
def mapa_notebooks(request):
    """Mapa dos notebooks (equipamentos móveis), agrupados por Unidade → Setor.

    Aceita ?marca=<marca> para filtrar por uma marca (vindo do gráfico do dashboard).
    """
    notebooks = (
        Notebook.objects
        .select_related("colaborador__location", "colaborador__department",
                        "baia__setor__unidade")
        .order_by("unidade_setor", "marca", "modelo")
    )
    marca = (request.GET.get("marca") or "").strip()
    if marca:
        notebooks = notebooks.filter(marca__iexact=marca)

    # Agrupa Unidade → Setor pela MESMA função canônica dos demais mapas
    # (_unidade_setor_notebook), garantindo atribuição idêntica em todo o sistema.
    unidades_canon = list(
        Location.objects.filter(setores__isnull=False).distinct()
        .order_by("name").values_list("name", flat=True)
    )
    unidades_lower = {n.lower(): n for n in unidades_canon}
    aliases = {"vilar dos teles": "Vilar", "vilar de teles": "Vilar"}
    uni_sel = (request.GET.get("unidade") or "").strip() or None
    setores_lower = {s.strip().lower() for s in request.GET.getlist("setor") if s.strip()}
    estrut = {}
    for n in notebooks:
        uni, setor = _unidade_setor_notebook(n, unidades_lower, aliases)
        if uni_sel and uni != uni_sel:
            continue
        if setores_lower and setor.lower() not in setores_lower:
            continue
        estrut.setdefault(uni, {}).setdefault(setor, {"notebooks": [], "vazios": []})
        estrut[uni][setor]["notebooks"].append(n)

    # Visão unificada: colaboradores ATIVOS com loja e SEM notebook aparecem como
    # "assento vazio" no setor deles (mesma regra do mapa de PC).
    com_nb = set(
        Notebook.objects.filter(colaborador__isnull=False)
        .values_list("colaborador_id", flat=True)
    )
    for p in (Person.objects.filter(active=True, location__isnull=False)
              .select_related("location", "department").order_by("full_name")):
        if p.id in com_nb:
            continue
        uni = p.location.name
        setor = (p.department.name if p.department_id else "") or "Geral"
        if uni_sel and uni != uni_sel:
            continue
        if setores_lower and setor.lower() not in setores_lower:
            continue
        estrut.setdefault(uni, {}).setdefault(setor, {"notebooks": [], "vazios": []})
        estrut[uni][setor]["vazios"].append(p)

    ordem_uni = unidades_canon + ["Sem unidade / setor"]

    def _uni_key(u):
        return (ordem_uni.index(u) if u in ordem_uni else 998, u.lower())

    unidades_estrut = []
    for uni in sorted(estrut.keys(), key=_uni_key):
        setores, total = [], 0
        for s in sorted(estrut[uni].keys(), key=lambda x: (x != "Geral", x.lower())):
            nbs = estrut[uni][s]["notebooks"]
            vaz = estrut[uni][s]["vazios"]
            setores.append({"setor": s, "notebooks": nbs, "vazios": vaz,
                            "total": len(nbs) + len(vaz)})
            total += len(nbs) + len(vaz)
        unidades_estrut.append({
            "unidade": uni,
            "setores": setores,
            "total": total,
        })
    titulo = f"Notebooks — {marca}" if marca else "Notebooks"
    # Destinos (envio entre lojas) + colaboradores (carrossel de atribuição) —
    # o próprio mapa é a superfície de arrastar (caminhão + atribuir a colaborador).
    destinos = (
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    pessoas = (
        Person.objects.filter(active=True)
        .prefetch_related("notebooks")
        .select_related("location")
        .order_by("full_name")
    )
    colaboradores = []
    for p in pessoas:
        nbs = list(p.notebooks.all())
        atual = nbs[0] if nbs else None
        colaboradores.append({
            "id": p.id,
            "nome": p.full_name,
            "cargo": p.job_title,
            "unidade": p.location.name if p.location_id else "",
            "sexo": p.sexo,
            "tem_notebook": atual is not None,
            "notebook_id": atual.id if atual else "",
            "notebook_nome": (f"{atual.marca} {atual.modelo}".strip() if atual else ""),
        })
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "titulo": titulo,
        "unidades_estrut": unidades_estrut,
        "resumo": _resumo_notebooks(unidades_estrut),
        "cargos": _cargos_distintos(),
        "total": notebooks.count(),
        "marca_filtro": marca,
        "destinos": destinos,
        "colaboradores": colaboradores,
        "pode_mover": pode_mover_baia(request.user),
        "title": "Mapa — Notebooks",
        **_filtros_ctx(
            request,
            Location.objects.filter(setores__isnull=False).distinct().order_by("name"),
            por_nome=True, com_setor=True, sem_unidade_opt=True,
        ),
    })
    return render(request, "parque/mapa_notebooks.html", contexto)


@staff_member_required
def transferencia_notebooks(request):
    """Rota antiga: a transferência agora acontece no próprio mapa de notebooks."""
    return redirect("parque_mapa_notebooks")


@staff_member_required
@require_POST
def transferir_notebook_entre_lojas(request):
    """Cria a transferência de um notebook para outra loja.

    Autorizados (pode_mover_baia) aplicam direto e recebem a URL do protocolo;
    os demais (ex.: Estagiário) geram uma transferência PENDENTE.
    """
    notebook = get_object_or_404(Notebook, pk=request.POST.get("notebook"))
    destino = get_object_or_404(Location, pk=request.POST.get("unidade_destino"))

    if (notebook.unidade_setor or "").strip().lower() == destino.name.strip().lower():
        return JsonResponse(
            {"ok": False, "erro": "O notebook já está nessa loja. Escolha um destino diferente."},
            status=400,
        )

    bitrix = (request.POST.get("bitrix_task_id") or "").strip()
    if not bitrix:
        return JsonResponse(
            {"ok": False, "erro": "Informe o código da tarefa do Bitrix para concluir a transferência."},
            status=400,
        )

    t = TransferenciaNotebook(
        notebook=notebook,
        unidade_origem=notebook.unidade_setor or "",
        usuario=notebook.usuario or "",
        marca=notebook.marca or "",
        modelo=notebook.modelo or "",
        serial=notebook.serial or "",
        specs=notebook.resumo_specs,
        unidade_destino=destino,
        usuario_destino=(request.POST.get("usuario_destino") or "").strip(),
        bitrix_task_id=bitrix,
        data=timezone.localdate(),
        registrado_por=request.user,
    )

    if pode_mover_baia(request.user):
        # ATÔMICO: grava a transferência E move o notebook de loja.
        with transaction.atomic():
            t.status = TransferenciaNotebook.Status.AUTORIZADA
            t.save()
            t.aplicar()
            transaction.on_commit(t.abrir_tarefa_transferencia_bitrix)
        return JsonResponse({
            "ok": True, "status": "aplicada",
            "msg": "Transferência realizada. Gerando o protocolo…",
            "protocolo_url": reverse("parque_protocolo_notebook", args=[t.pk]),
        })

    t.status = TransferenciaNotebook.Status.PENDENTE
    t.save()
    return JsonResponse({
        "ok": True, "status": "solicitada",
        "msg": "Solicitação de transferência enviada para autorização.",
    })


@staff_member_required
def protocolo_notebook(request, pk):
    """Comprovante de transferência de notebook (saída e destino) — impressão."""
    t = get_object_or_404(
        TransferenciaNotebook.objects.select_related("unidade_destino", "notebook"), pk=pk
    )

    # Item 1: o notebook (marca/modelo + specs). Série como item complementar.
    nome_nb = " ".join(p for p in [t.marca, t.modelo] if p) or "Notebook"
    desc_nb = f"Notebook {nome_nb}"
    if t.specs and t.specs != "—":
        desc_nb = f"{desc_nb} — {t.specs}"
    itens = [{"descricao": desc_nb, "qtd": "1 un"}]
    if t.serial:
        itens.append({"descricao": f"Nº de série: {t.serial}", "qtd": ""})

    total_linhas = max(8, len(itens))
    linhas = []
    for i in range(total_linhas):
        it = itens[i] if i < len(itens) else {"descricao": "", "qtd": ""}
        linhas.append({"n": i + 1, "descricao": it["descricao"], "qtd": it["qtd"]})

    contexto = {
        "t": t,
        "uni_origem": t.unidade_origem or "—",
        "uni_destino": t.unidade_destino.name if t.unidade_destino_id else "",
        "setor_destino_nome": "",
        "colab_saida": t.usuario,
        "colab_destino": t.usuario_destino,
        "data_saida": t.data,
        "data_entrada": t.data,
        "linhas": linhas,
    }
    # O botão "voltar" do documento aponta para a tela de origem —
    # nunca para o histórico (ver o comentário no template).
    contexto.update(_voltar("/parque/mapa-notebooks/"))
    return render(request, "parque/protocolo.html", contexto)


@staff_member_required
@require_POST
def atribuir_notebook(request):
    """Aloca um notebook a um colaborador (Person). Carrossel de avatares."""
    if not request.user.has_perm("parque.change_notebook"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alocar notebooks."}, status=403)

    notebook = get_object_or_404(Notebook, pk=request.POST.get("notebook"))
    pessoa = get_object_or_404(Person, pk=request.POST.get("colaborador"))

    if pessoa.notebooks.exclude(pk=notebook.pk).exists():
        return JsonResponse(
            {"ok": False, "erro": f"{pessoa.full_name} já está com um notebook."}, status=400
        )

    notebook.colaborador = pessoa
    notebook.usuario = pessoa.full_name
    if pessoa.location_id:
        notebook.unidade_setor = pessoa.location.name
    campos = ["colaborador", "usuario", "unidade_setor", "atualizado_em"]
    # Alocado a alguém = em uso → fica Ativo (a menos que esteja com defeito).
    if notebook.status != Notebook.Status.DEFEITO:
        notebook.status = Notebook.Status.ATIVO
        campos.append("status")
    notebook.save(update_fields=campos)
    return JsonResponse({
        "ok": True,
        "msg": f"Notebook alocado para {pessoa.full_name}.",
        "colaborador_id": pessoa.id,
    })


@staff_member_required
@require_POST
def remover_notebook_colaborador(request):
    """Retira o notebook de um colaborador (fica sem dono → avatar triste)."""
    if not request.user.has_perm("parque.change_notebook"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar notebooks."}, status=403)

    notebook = get_object_or_404(Notebook, pk=request.POST.get("notebook"))
    pessoa = notebook.colaborador if notebook.colaborador_id else None
    nome = pessoa.full_name if pessoa else notebook.usuario
    notebook.colaborador = None
    notebook.usuario = ""
    campos = ["colaborador", "usuario", "atualizado_em"]
    # Sem dono = sem uso (mantém "Com defeito" se for o caso).
    if notebook.status != Notebook.Status.DEFEITO:
        notebook.status = Notebook.Status.OBSOLETO
        campos.append("status")
    notebook.save(update_fields=campos)

    # TERMO DE DEVOLUÇÃO. Entregar deixava rastro assinado; devolver não
    # deixava nada — e é justamente a devolução que o RH precisa provar
    # ("entreguei o notebook de volta"). O termo nasce PENDENTE: o papel ainda
    # vai ser impresso e assinado, e aparece na fila do arquivo até isso
    # acontecer (/parque/arquivo/).
    #
    # NUNCA bloqueia a retirada. Se falhar, o notebook já saiu do colaborador
    # — que é o que o parque precisa que seja verdade — e o erro vai para o log.
    extra = ""
    try:
        if nome:
            ja_pendente = TermoResponsabilidade.objects.filter(
                notebook=notebook, tipo=TermoResponsabilidade.Tipo.DEVOLUCAO,
                status=TermoResponsabilidade.Status.PENDENTE,
            ).exists()
            if not ja_pendente:
                equip = " ".join(x for x in [notebook.marca, notebook.modelo] if x) or "Notebook"
                if notebook.serial:
                    equip = f"{equip} (série {notebook.serial})"
                TermoResponsabilidade.objects.create(
                    notebook=notebook,
                    colaborador=pessoa,
                    tipo=TermoResponsabilidade.Tipo.DEVOLUCAO,
                    colaborador_nome=nome,
                    equipamento_desc=equip,
                    criado_por=request.user if request.user.is_authenticated else None,
                )
                extra = " Termo de devolução gerado — aguardando assinatura."
    except Exception:
        logger.exception("Falha ao gerar termo de devolução do notebook %s", notebook.pk)

    return JsonResponse({"ok": True,
                         "msg": f"Notebook retirado de {nome or 'colaborador'}.{extra}"})


@staff_member_required
@require_POST
def gerar_termo_notebook(request):
    """Gera um Termo de Responsabilidade para o notebook alocado a um colaborador.

    O colaborador vem do vínculo `notebook.colaborador` (ou do texto `usuario`).
    Sem colaborador não há a quem responsabilizar → erro claro. Grava um snapshot
    (nome + descrição do equipamento) e devolve a URL de impressão.
    """
    if not request.user.has_perm("parque.add_termoresponsabilidade"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para gerar termos."}, status=403)

    notebook = get_object_or_404(Notebook, pk=request.POST.get("notebook"))
    pessoa = notebook.colaborador
    # O nome do colaborador é preenchido À MÃO no termo impresso (nem sempre se sabe
    # o nome completo), então NÃO exigimos colaborador — o termo é do equipamento.
    nome = pessoa.full_name if pessoa else (notebook.usuario or "")

    equip = " ".join(p for p in [notebook.marca, notebook.modelo] if p) or "Notebook"
    if notebook.serial:
        equip = f"{equip} (série {notebook.serial})"

    termo = TermoResponsabilidade.objects.create(
        notebook=notebook,
        colaborador=pessoa,
        colaborador_nome=nome,
        equipamento_desc=equip,
        criado_por=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse({
        "ok": True,
        "msg": f"Termo gerado para {nome}. Abrindo para impressão…",
        "url": reverse("parque_termo_imprimir", args=[termo.pk]),
    })


@staff_member_required
def termo_imprimir(request, pk):
    """Renderiza o Termo de Responsabilidade para impressão (folha A4)."""
    t = get_object_or_404(
        TermoResponsabilidade.objects.select_related("notebook", "colaborador"), pk=pk
    )
    nb, pessoa = t.notebook, t.colaborador
    contexto = {
        "t": t,
        "colaborador_nome": t.colaborador_nome or (pessoa.full_name if pessoa else ""),
        "cargo": pessoa.job_title if pessoa else "",
        "setor": pessoa.department.name if pessoa and pessoa.department_id else "",
        "unidade": pessoa.location.name if pessoa and pessoa.location_id else "",
        "equip_marca_modelo": (" ".join(p for p in [nb.marca, nb.modelo] if p) if nb else ""),
        "equip_serial": nb.serial if nb else "",
        "equip_specs": nb.resumo_specs if nb else "",
    }
    # O botão "voltar" do documento aponta para a tela de origem —
    # nunca para o histórico (ver o comentário no template).
    contexto.update(_voltar("/parque/mapa-notebooks/"))
    return render(request, "parque/termo_responsabilidade.html", contexto)


@staff_member_required
def media_protegida(request, path):
    """Serve arquivos de MEDIA (uploads: termos, documentos de equipamento) exigindo
    login. Necessário porque, com DEBUG=False (modo túnel/produção), o runserver não
    serve /media/ sozinho — e assim os arquivos ficam protegidos por autenticação."""
    from django.views.static import serve as _serve
    try:
        return _serve(request, path, document_root=settings.MEDIA_ROOT)
    except Http404:
        # Registro existe no banco, mas o arquivo não está no disco (ex.: removido ou
        # ainda não sincronizado). Mostra um aviso claro em vez do "Not Found" cru.
        return HttpResponseNotFound(
            "<div style=\"font-family:system-ui;max-width:520px;margin:60px auto;"
            "padding:24px;border:1px solid #e5e7eb;border-radius:14px;color:#334155\">"
            "<h2 style=\"margin:0 0 8px;color:#b45309\">Arquivo não encontrado</h2>"
            "<p style=\"margin:0\">Este documento não está disponível no servidor — "
            "pode ter sido removido ou ainda não foi sincronizado. Se precisar dele, "
            "reanexe o arquivo na tela do envio.</p></div>")


@staff_member_required
@require_POST
def remover_colaborador_baia(request):
    """Tira o colaborador da baia MANTENDO o computador e as specs.

    A pessoa mora em dois lugares na baia: o FK `colaborador` E o texto do nome
    ("3 - Leandro"). Limpamos os dois — o nome volta a ser só o número — senão o
    signal `numerar_e_conectar_baia` re-vincula a pessoa a partir do nome ao salvar.
    """
    if not request.user.has_perm("parque.change_baia"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar baias."}, status=403)

    baia = get_object_or_404(Baia, pk=request.POST.get("baia"))
    nome_antigo = baia.colaborador.full_name if baia.colaborador_id else ""
    tinha_pc = bool(baia.computador_id)
    baia.colaborador = None
    # Nome volta a ser só o número. Sem número (baia com nome próprio, ex.: "Caixa 1"),
    # apenas removemos o sufixo do colaborador para o signal não re-vincular.
    if baia.numero:
        baia.nome = str(baia.numero)
    elif nome_antigo:
        nome = baia.nome or ""
        for suf in (f" - {nome_antigo}", f"- {nome_antigo}", nome_antigo):
            if nome.endswith(suf):
                nome = nome[: len(nome) - len(suf)].rstrip(" -")
                break
        baia.nome = nome
    campos = ["colaborador", "nome"]
    levou_notebook = False
    if baia.notebook_id:
        # O notebook é da PESSOA → sai com ela da mesa (o computador, se houver, fica).
        baia.notebook = None
        campos.append("notebook")
        levou_notebook = True
    baia.save(update_fields=campos)
    msg = f"Colaborador {nome_antigo or ''} retirado da mesa.".strip()
    if levou_notebook:
        msg += "O notebook foi com ele(a)."
    elif tinha_pc:
        msg += "O computador continua na mesa."
    return JsonResponse({"ok": True, "msg": msg})


@staff_member_required
@require_POST
def atribuir_colaborador_baia(request):
    """Aloca a baia (e o computador dela) a um colaborador. Espelha o fluxo dos
    notebooks: o nome da baia vira "<número> - <Colaborador>" e o FK é preenchido."""
    if not request.user.has_perm("parque.change_baia"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar baias."}, status=403)

    baia = get_object_or_404(Baia, pk=request.POST.get("baia"))
    pessoa = get_object_or_404(Person, pk=request.POST.get("colaborador"))
    baia.colaborador = pessoa
    numero = baia.numero
    baia.nome = f"{numero} - {pessoa.full_name}" if numero else pessoa.full_name
    baia.save(update_fields=["colaborador", "nome"])
    msg = f"Mesa alocada para {pessoa.full_name}."
    # O notebook é da PESSOA: se a mesa está SEM dispositivo e o colaborador tem um
    # notebook (não alocado em outra mesa), ele vai junto para a mesa.
    if not baia.computador_id and not baia.notebook_id:
        nb = pessoa.notebooks.first()
        if nb and not Baia.objects.filter(notebook=nb).exclude(pk=baia.pk).exists():
            baia.notebook = nb
            baia.save(update_fields=["notebook"])
            nome_nb = f"{nb.marca} {nb.modelo}".strip() or "Notebook"
            msg += f"O notebook {nome_nb} foi junto."
    return JsonResponse({"ok": True, "msg": msg.strip(), "colaborador_id": pessoa.id})


@staff_member_required
@require_POST
def alocar_computador_baia(request):
    """Aloca um computador do estoque a uma mesa (baia)."""
    if not request.user.has_perm("parque.change_baia"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar baias."}, status=403)
    baia = get_object_or_404(Baia, pk=request.POST.get("baia"))
    comp = get_object_or_404(Computador, pk=request.POST.get("computador"))
    if not baia.esta_vazia:
        return JsonResponse({"ok": False, "erro": "Esta mesa já tem um dispositivo. Remova-o antes."}, status=400)
    if Baia.objects.filter(computador=comp).exclude(pk=baia.pk).exists():
        return JsonResponse({"ok": False, "erro": f"{comp.patrimonio} já está em outra mesa."}, status=400)
    baia.computador = comp
    baia.save()  # signals: computador vira "em uso"; situação derivada
    return JsonResponse({"ok": True, "msg": f"{comp.patrimonio} alocado à mesa."})


@staff_member_required
@require_POST
def alocar_notebook_baia(request):
    """Aloca um notebook (livre) a uma mesa (baia)."""
    if not request.user.has_perm("parque.change_baia"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar baias."}, status=403)
    baia = get_object_or_404(Baia, pk=request.POST.get("baia"))
    nb = get_object_or_404(Notebook, pk=request.POST.get("notebook"))
    if not baia.esta_vazia:
        return JsonResponse({"ok": False, "erro": "Esta mesa já tem um dispositivo. Remova-o antes."}, status=400)
    if Baia.objects.filter(notebook=nb).exclude(pk=baia.pk).exists():
        return JsonResponse({"ok": False, "erro": "Esse notebook já está em outra mesa."}, status=400)
    baia.notebook = nb
    baia.save()  # signal sincroniza notebook <-> baia (colaborador/unidade/status)
    nome = f"{nb.marca} {nb.modelo}".strip() or "Notebook"
    return JsonResponse({"ok": True, "msg": f"{nome} alocado à mesa."})


@staff_member_required
@require_POST
def remover_dispositivo_baia(request):
    """Remove o dispositivo da mesa (computador volta ao estoque; notebook fica livre)."""
    if not request.user.has_perm("parque.change_baia"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar baias."}, status=403)
    baia = get_object_or_404(Baia, pk=request.POST.get("baia"))
    if baia.computador_id:
        baia.computador = None
        msg = "Computador removido da mesa (voltou ao estoque)."
    elif baia.notebook_id:
        baia.notebook = None
        msg = "Notebook removido da mesa."
    else:
        return JsonResponse({"ok": False, "erro": "A mesa não tem dispositivo."}, status=400)
    # Limpa specs legadas da baia (senão a mesa vazia mostraria specs-zumbi).
    baia.sistema_operacional = baia.processador = baia.placa_mae = ""
    baia.memoria_ram = baia.armazenamento = ""
    baia.save()  # signals liberam o dispositivo
    return JsonResponse({"ok": True, "msg": msg})


@staff_member_required
@require_POST
def desativar_para_troca(request):
    """Desativa o computador da mesa PARA TROCA: ele vai ao estoque de Desativados
    guardando DE ONDE saiu (unidade/baia), e a mesa fica livre para receber a
    substituta. O front, em seguida, abre o seletor de máquinas do estoque."""
    if not request.user.has_perm("parque.change_baia"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para alterar baias."}, status=403)
    baia = get_object_or_404(Baia, pk=request.POST.get("baia"))
    if not baia.computador_id:
        return JsonResponse({"ok": False, "erro": "A mesa não tem computador para desativar."}, status=400)
    comp_pk = baia.computador_id
    patrimonio = baia.computador.patrimonio
    uni = baia.setor.unidade.name
    local = f"{baia.setor.nome} › {baia.nome}"
    # ATÔMICO: são duas escritas. Falha entre elas fazia a máquina DESAPARECER —
    # já fora da baia, mas ainda sem o status "desativado", então não aparecia
    # nem no mapa nem no estoque de desativados.
    with transaction.atomic():
        # Desvincula + limpa specs legadas (sem specs-zumbi; o signal não recria fantasma).
        baia.computador = None
        baia.sistema_operacional = baia.processador = baia.placa_mae = ""
        baia.memoria_ram = baia.armazenamento = ""
        baia.save()
        # Manda a máquina p/ Desativados guardando DE ONDE saiu (NÃO cria Chamado/Reparo:
        # desativação-para-troca não é um chamado; o rastro fica no próprio computador).
        Computador.objects.filter(pk=comp_pk).update(
            status=Computador.Status.DESATIVADO, ultima_unidade=uni, ultima_baia=local,
        )
    return JsonResponse({
        "ok": True,
        "baia": baia.pk,
        "msg": f"{patrimonio} foi para o estoque de Desativados. Escolha a máquina substituta.",
    })


@staff_member_required
def import_sheet(request):
    """Import da planilha — ferramenta de desenvolvimento (só com DEBUG=True).

    Exige superusuário logado. Antes esta view era `@csrf_exempt`, sem login e
    respondia com `Access-Control-Allow-Origin: *` + `Allow-Private-Network`:
    qualquer página aberta no navegador do usuário podia reescrever o parque
    inteiro. Para import de verdade use o comando, que não depende de DEBUG:

        python manage.py import_planilha
    """
    if not settings.DEBUG or not request.user.is_superuser:
        raise Http404()
    if request.method == "OPTIONS":
        resp = JsonResponse({})
    elif request.method != "POST":
        resp = JsonResponse({"erro": "use POST"}, status=405)
    else:
        sheet = request.GET.get("sheet", "").strip()
        csv_text = request.body.decode("utf-8", "ignore")
        try:
            rows = parse_rows(csv_text)
            if sheet.lower().startswith("transfer"):
                stats = import_transferencias(rows)
            elif sheet in UNIDADES:
                stats = import_unidade(sheet, rows)
            else:
                stats = {"ignorado": sheet}
            resp = JsonResponse({"sheet": sheet, "ok": True, **stats})
        except Exception as e:  # noqa: BLE001
            logger.exception("Falha ao importar a aba %r da planilha.", sheet)
            resp = JsonResponse({"sheet": sheet, "ok": False, "erro": str(e)}, status=500)

    # Sem cabeçalhos de CORS: o import roda a partir do próprio sistema (sessão
    # logada). Liberar origem "*" + Private Network deixava qualquer site
    # chamar este endpoint pelo navegador do usuário.
    return resp


# ======================= REGISTROS (visão de calendário) =======================
# Tela pedida pelo dono: "a tela de preventiva tem que ter essa visão aqui,
# aparecendo os registros das preventivas e movimentações que foram realizadas.
# Vai basicamente ser uma tela especial pro RH verificar."
#
# Referência que ele mandou era um calendário SEMANAL com grade de horas. Aqui é
# um calendário de MÊS, e a razão é o dado: preventiva concluída guarda
# `concluido_em` como DATA (Reparo.concluido_em é DateField), sem hora. Uma
# grade de horas ficaria 90% vazia e mentiria sobre a precisão do registro. O
# mês mostra o que existe — quantos e quais por dia — e a agenda lateral traz o
# detalhe em ordem.
#
# É tela de LEITURA. Nada aqui altera dado: quem confere não decide.

# Quem pode conferir. O RH não existe como grupo hoje — crie um grupo chamado
# "RH" no admin e ele passa a ver a tela sem mais nenhuma mudança de código.
GRUPOS_REGISTROS = ["RH", "Gerente", "Supervisor"]


def _pode_ver_registros(user):
    """Quem confere os Registros.

    A lista literal (GRUPOS_REGISTROS, acima) virou o PADRÃO do registro único
    de telas — apps/orgs/acessos.py —, que é o mesmo lugar que o menu consulta
    e que a tela /parque/acessos/ edita. Aqui só se pergunta.
    """
    from apps.orgs.acessos import pode_ver_tela
    return pode_ver_tela(user, "registros")


def _mes_anterior(ano, mes):
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def _mes_seguinte(ano, mes):
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


@staff_member_required
def preventiva_registros(request):
    """Calendário de tudo que FOI FEITO: preventivas concluídas, transferências
    entre lojas e movimentações de baia. Um mês por vez, com agenda ao lado."""
    if not _pode_ver_registros(request.user):
        raise PermissionDenied(
            "Esta tela é restrita a RH, Gerente e Supervisor."
        )

    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano") or hoje.year)
        mes = int(request.GET.get("mes") or hoje.month)
        if not 1 <= mes <= 12 or not 2000 <= ano <= 2100:
            raise ValueError
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month

    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, _calendar.monthrange(ano, mes)[1])

    # Filtro por unidade: o RH costuma conferir uma loja por vez.
    uni_sel = (request.GET.get("unidade") or "").strip()
    tipo_sel = (request.GET.get("tipo") or "").strip()
    # Busca dentro do mês que está na tela. Não busca no ano inteiro de
    # propósito: o calendário é o que navega no tempo, e uma busca que pula de
    # mês faria a grade e a lista deixarem de bater com a data do cabeçalho.
    busca = (request.GET.get("q") or "").strip()

    def _na_unidade(qs, caminho):
        if not uni_sel:
            return qs
        return qs.filter(**{f"{caminho}__iexact": uni_sel})

    eventos = []

    # ---- 1. Preventivas concluídas -------------------------------------------
    if tipo_sel in ("", "preventiva"):
        prev = (
            Reparo.objects
            .filter(tipo=Reparo.Tipo.PREVENTIVA,
                    concluido_em__gte=primeiro, concluido_em__lte=ultimo)
            # `Notebook` NÃO tem FK de unidade — a localização dele é o texto
            # `unidade_setor` (models.py). Pedir `notebook__unidade` no
            # select_related levanta FieldError na hora da consulta.
            .select_related("baia__setor__unidade", "notebook", "tecnico")
        )
        prev = _na_unidade(prev, "baia__setor__unidade__name")
        for r in prev:
            alvo = r.baia or r.notebook
            unidade = ""
            if r.baia_id and r.baia.setor_id:
                unidade = r.baia.setor.unidade.name if r.baia.setor.unidade_id else ""
            elif r.notebook_id:
                unidade = r.notebook.unidade_setor or ""
            eventos.append({
                "dia": r.concluido_em,
                "tipo": "preventiva",
                "rotulo": "Preventiva",
                "titulo": r.titulo or "Manutenção preventiva",
                "onde": unidade,
                "alvo": str(alvo) if alvo else "",
                "quem": (r.tecnico.get_full_name() or r.tecnico.get_username()) if r.tecnico_id else "",
                "url": f"/parque/chamado-detalhe/{r.pk}/",
            })

    # ---- 2. Transferências entre lojas (as que entraram) ---------------------
    if tipo_sel in ("", "transferencia"):
        transf = (
            Transferencia.objects
            .filter(data_entrada__gte=primeiro, data_entrada__lte=ultimo)
            .select_related("baia_origem__setor__unidade", "baia_destino__setor__unidade")
        )
        transf = _na_unidade(transf, "baia_destino__setor__unidade__name")
        for t in transf:
            origem = t.baia_origem.setor.unidade.name if (t.baia_origem_id and t.baia_origem.setor_id and t.baia_origem.setor.unidade_id) else ""
            destino = t.baia_destino.setor.unidade.name if (t.baia_destino_id and t.baia_destino.setor_id and t.baia_destino.setor.unidade_id) else ""
            eventos.append({
                "dia": t.data_entrada,
                "tipo": "transferencia",
                "rotulo": "Transferência",
                "titulo": f"{origem or '—'} → {destino or '—'}",
                "onde": destino,
                "alvo": t.colaborador_destino or t.colaborador_saida or "",
                "quem": "",
                "url": f"/parque/protocolo-transferencia/{t.pk}/",
            })

    # ---- 3. Movimentações de baia (aplicadas) --------------------------------
    if tipo_sel in ("", "movimentacao"):
        movs = (
            MovimentacaoBaia.objects
            .filter(decidido_em__date__gte=primeiro, decidido_em__date__lte=ultimo)
            .select_related("baia__setor__unidade", "setor_origem", "setor_destino")
        )
        movs = _na_unidade(movs, "baia__setor__unidade__name")
        for m in movs:
            unidade = m.baia.setor.unidade.name if (m.baia_id and m.baia.setor_id and m.baia.setor.unidade_id) else ""
            eventos.append({
                "dia": timezone.localtime(m.decidido_em).date() if m.decidido_em else None,
                "tipo": "movimentacao",
                "rotulo": "Movimentação",
                "titulo": m.get_tipo_display() if hasattr(m, "get_tipo_display") else "Movimentação de baia",
                "onde": unidade,
                "alvo": m.colaborador_nome or m.info_pc or m.patrimonio or "",
                "quem": "",
                # Movimentação não tem tela de detalhe própria; o destino que
                # responde "onde foi isso?" é o mapa da loja. Era o único tipo
                # sem URL, e num mês só de movimentações isso deixava a tela
                # inteira sem nada clicável.
                # `?baia=` faz o mapa abrir JÁ com o painel daquela máquina.
                # Sem isso, o clique levava ao mapa da loja e a pessoa tinha de
                # caçar qual era a máquina — o dono resumiu: "não acontece
                # nada, ele simplesmente me leva até o mapa".
                "url": (f"/parque/mapa/{m.baia.setor.unidade_id}/?baia={m.baia_id}"
                        if (m.baia_id and m.baia.setor_id and m.baia.setor.unidade_id) else ""),
            })

    eventos = [e for e in eventos if e["dia"]]

    # Busca: casa em qualquer um dos textos que a tela mostra, sem acento e sem
    # caixa. É o que a pessoa espera ao digitar "gabriel" ou "bonsu".
    if busca:
        import unicodedata

        def _sem_acento(t):
            t = unicodedata.normalize("NFKD", str(t or ""))
            return "".join(c for c in t if not unicodedata.combining(c)).lower()

        alvo_busca = _sem_acento(busca)
        eventos = [
            e for e in eventos
            if alvo_busca in _sem_acento(
                " ".join([e.get("titulo", ""), e.get("alvo", ""),
                          e.get("quem", ""), e.get("onde", ""), e.get("rotulo", "")])
            )
        ]
    eventos.sort(key=lambda e: (e["dia"], e["rotulo"]))

    # ---- grade do mês, começando no domingo ---------------------------------
    por_dia = {}
    for e in eventos:
        por_dia.setdefault(e["dia"], []).append(e)

    cal = _calendar.Calendar(firstweekday=6)   # 6 = domingo, como na referência
    semanas = []
    for semana in cal.monthdatescalendar(ano, mes):
        linha = []
        for d in semana:
            do_dia = por_dia.get(d, [])
            linha.append({
                "data": d,
                "fora": d.month != mes,
                "hoje": d == hoje,
                "eventos": do_dia,
                "extra": max(0, len(do_dia) - 3),
                "primeiros": do_dia[:3],
            })
        semanas.append(linha)

    ant_a, ant_m = _mes_anterior(ano, mes)
    seg_a, seg_m = _mes_seguinte(ano, mes)
    MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]

    contagem = {
        "preventiva": sum(1 for e in eventos if e["tipo"] == "preventiva"),
        "transferencia": sum(1 for e in eventos if e["tipo"] == "transferencia"),
        "movimentacao": sum(1 for e in eventos if e["tipo"] == "movimentacao"),
    }

    ctx = {
        **dj_admin.site.each_context(request),
        "title": "Registros",
        "titulo": "Registros de preventiva e movimentação",
        "ano": ano,
        "mes": mes,
        "mes_nome": MESES[mes - 1],
        "semanas": semanas,
        "eventos": eventos,
        "total": len(eventos),
        "contagem": contagem,
        "busca": busca,
        "hoje": hoje,
        "uni_sel": uni_sel,
        "tipo_sel": tipo_sel,
        "unidades": Location.objects.order_by("name"),
        # Os dois `<select onchange=submit>` desta tela viraram o MESMO popup
        # "Filtrar" das outras. `ano`/`mes` entram no keep porque a tela é um
        # calendário: aplicar filtro não pode jogar o RH de volta para o mês
        # corrente. A unidade vale pelo NOME (é assim que `_na_unidade` filtra).
        **barra_filtros(
            request,
            [{"param": "unidade", "label": "Unidade", "todos": "Todas",
              "opcoes": [(u.name, u.name) for u in Location.objects.order_by("name")]},
             {"param": "tipo", "label": "Tipo de registro", "todos": "Todos",
              "opcoes": [("preventiva", "Preventivas"),
                         ("transferencia", "Transferências"),
                         ("movimentacao", "Movimentações")]}],
            keep=("ano", "mes"),
        ),
        "url_ant": f"?ano={ant_a}&mes={ant_m}" + (f"&unidade={uni_sel}" if uni_sel else "") + (f"&tipo={tipo_sel}" if tipo_sel else ""),
        "url_seg": f"?ano={seg_a}&mes={seg_m}" + (f"&unidade={uni_sel}" if uni_sel else "") + (f"&tipo={tipo_sel}" if tipo_sel else ""),
        "url_hoje": f"?ano={hoje.year}&mes={hoje.month}" + (f"&unidade={uni_sel}" if uni_sel else "") + (f"&tipo={tipo_sel}" if tipo_sel else ""),
        "voltar_url": "/parque/preventiva/",
        "voltar_nome": "Preventiva",
    }
    return render(request, "parque/preventiva_registros.html", ctx)


# ===========================================================================
# AGENDA DO TOPO — calendário + eventos, sob demanda
#
# Pedido do dono: uma área de notificação no alto do sistema, com um objeto
# pequeno de calendário sempre visível e, ao clicar, o mês inteiro ao lado dos
# avisos e solicitações (a referência que ele mandou foi a central do GNOME).
#
# POR QUE ENDPOINT, e não contexto: o topo aparece em TODA tela. Calcular
# vencimento de preventiva de todo o parque em cada requisição sairia caro —
# `preventiva_vencimento` é propriedade calculada, não coluna. Aqui os eventos
# só são buscados quando a pessoa abre o painel, e sempre limitados a um mês.
# ===========================================================================
# Quem vê a agenda de TODAS as lojas. É um GRUPO, e não `is_superuser`, porque
# a lista de quem deve ver tudo não coincide com a de superusuários: o dono
# quer Jonas, Raniele e Yan, e a Raniele não é superusuária. Como grupo, ele
# muda a lista sozinho no admin.
GRUPO_AGENDA_TODAS = "Visão total"


def _agenda_ve_todas_lojas(user):
    return user.groups.filter(name=GRUPO_AGENDA_TODAS).exists()


def _normaliza_loja(texto):
    """Minúsculo, sem acento e sem espaço nas pontas — para comparar nomes."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.strip().lower()


def _mesma_loja(onde, loja):
    """Verdadeiro quando `onde` se refere à mesma loja que `loja`.

    Frouxo de propósito: a baia entrega "Bonsucesso" e o notebook entrega
    "Bonsucesso / Comercial". Exigir igualdade apagaria os notebooks do painel.
    """
    a, b = _normaliza_loja(onde), _normaliza_loja(loja)
    if not a or not b:
        return True          # sem loja atribuída: não é de outra loja
    return a == b or a.startswith(b) or b in a


@staff_member_required
def agenda_eventos(request):
    """JSON dos eventos de um mês: o que vence, o que espera decisão, o que foi feito."""
    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano") or hoje.year)
        mes = int(request.GET.get("mes") or hoje.month)
        if not 1 <= mes <= 12 or not 2000 <= ano <= 2100:
            raise ValueError
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month

    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, _calendar.monthrange(ano, mes)[1])
    eventos = []

    # --- escopo de quem está olhando ---------------------------------------
    # Três casos:
    #   1. grupo "Visão total"        -> todas as lojas
    #   2. loja no cadastro           -> só aquela loja
    #   3. sem grupo e sem loja       -> todas as lojas, com o aviso na tela
    #
    # O caso 3 é decisão do dono, tomada com o efeito colateral na mesa: um
    # usuário novo, antes de alguém preencher a loja dele, vê o dia de todas as
    # lojas. O rótulo do painel diz isso ("sem loja no seu cadastro"), para que
    # o cadastro faltando apareça em vez de ficar silencioso.
    ve_todas = _agenda_ve_todas_lojas(request.user)
    minha_loja = "" if ve_todas else _unidade_nome_usuario(request.user)
    sem_cadastro = not ve_todas and not minha_loja

    def _add(dia, tipo, titulo, onde="", url=""):
        if not dia or not (primeiro <= dia <= ultimo):
            return
        # O filtro mora aqui, num lugar só: toda origem de evento passa por
        # `_add`, então nenhuma das consultas precisa saber de escopo.
        if minha_loja and not _mesma_loja(onde, minha_loja):
            return
        eventos.append({
            "dia": dia.isoformat(), "tipo": tipo,
            "titulo": titulo, "onde": onde, "url": url,
        })

    # 1. Preventivas que VENCEM no mês (baias com máquina + notebooks).
    for b in (Baia.objects
              .select_related("setor__unidade", "colaborador", "computador")
              .prefetch_related("reparos")):
        if not b.computador_id:
            continue
        d = b.preventiva_vencimento
        if not d or not (primeiro <= d <= ultimo):
            continue
        quem = b.colaborador.full_name if b.colaborador_id else b.nome
        loja = b.setor.unidade.name if (b.setor_id and b.setor.unidade_id) else ""
        _add(d, "preventiva", f"Preventiva de {quem}", loja, "/parque/preventiva/?vista=calendario")

    for n in Notebook.objects.select_related("colaborador").prefetch_related("reparos"):
        d = n.preventiva_vencimento
        if not d or not (primeiro <= d <= ultimo):
            continue
        quem = n.usuario or (n.colaborador.full_name if n.colaborador_id else "")
        titulo = f"Preventiva de {quem}".strip() if quem else "Preventiva de notebook"
        _add(d, "preventiva", titulo, n.unidade_setor or "", "/parque/mapa-notebooks/")

    # 2. Solicitações esperando decisão — é o que o dono chama de "solicitações".
    for t in (Transferencia.objects
              .filter(status=Transferencia.Status.PENDENTE)
              .select_related("baia_origem__setor__unidade", "baia_destino__setor__unidade")):
        destino = ""
        if t.baia_destino_id and t.baia_destino.setor_id:
            destino = t.baia_destino.setor.unidade.name if t.baia_destino.setor.unidade_id else ""
        _add(t.data_entrada or hoje, "solicitacao",
             "Transferência aguardando autorização", destino, "/parque/aprovacoes/")

    for m in (MovimentacaoBaia.objects
              .filter(status=MovimentacaoBaia.Status.PENDENTE)
              .select_related("baia__setor__unidade")):
        onde = ""
        if m.baia_id and m.baia.setor_id and m.baia.setor.unidade_id:
            onde = m.baia.setor.unidade.name
        dia = getattr(m, "criada_em", None)
        dia = dia.date() if hasattr(dia, "date") else (dia or hoje)
        _add(dia, "solicitacao", "Movimentação aguardando autorização", onde, "/parque/aprovacoes/")

    # 3. Chamados com prazo no mês e preventivas concluídas (o que foi feito).
    for r in (Reparo.objects
              .filter(previsao_conclusao__gte=primeiro, previsao_conclusao__lte=ultimo,
                      concluido_em__isnull=True)
              .select_related("baia__setor__unidade")):
        onde = ""
        if r.baia_id and r.baia.setor_id and r.baia.setor.unidade_id:
            onde = r.baia.setor.unidade.name
        _add(r.previsao_conclusao, "chamado", r.titulo or "Chamado com prazo",
             onde, f"/parque/chamado-detalhe/{r.pk}/")

    for r in (Reparo.objects
              .filter(tipo=Reparo.Tipo.PREVENTIVA,
                      concluido_em__gte=primeiro, concluido_em__lte=ultimo)
              .select_related("baia__setor__unidade")):
        onde = ""
        if r.baia_id and r.baia.setor_id and r.baia.setor.unidade_id:
            onde = r.baia.setor.unidade.name
        _add(r.concluido_em, "feito", r.titulo or "Preventiva concluída",
             onde, f"/parque/chamado-detalhe/{r.pk}/")

    # Contagem por dia (para o ponto no calendário) e a lista do dia de hoje.
    por_dia = {}
    for e in eventos:
        por_dia[e["dia"]] = por_dia.get(e["dia"], 0) + 1
    eventos.sort(key=lambda e: (e["dia"], e["tipo"]))

    if minha_loja:
        escopo = minha_loja
    elif sem_cadastro:
        escopo = "todas as lojas · sem loja no seu cadastro"
    else:
        escopo = "todas as lojas"

    return JsonResponse({
        "ano": ano, "mes": mes,
        "hoje": hoje.isoformat(),
        # O painel MOSTRA o escopo: quem vê uma loja só precisa saber disso,
        # quem vê todas precisa saber que vê todas, e quem não vê nada precisa
        # saber por quê.
        "escopo": escopo,
        "so_minha_loja": bool(minha_loja),
        "por_dia": por_dia,
        "eventos": eventos,
        "hoje_eventos": [e for e in eventos if e["dia"] == hoje.isoformat()],
    })


# ===========================================================================
# LOGS EM UM LUGAR SÓ — acessos + ações
#
# Pedido do dono: "quero juntar todos os logs em um lugar só. Log de acessos e
# ações". Eram duas telas do admin (`orgs.LogAcesso` e `admin.LogEntry`), cada
# uma com sua própria lista e seus próprios filtros.
#
# As duas fontes têm formatos diferentes e NÃO podem ser unidas em SQL (models
# distintos, bancos de campos distintos). A união é feita em Python sobre a
# JANELA pedida — nunca sobre a tabela inteira: cada fonte traz no máximo
# `TETO_POR_FONTE` registros já filtrados e ordenados, e a mistura final é
# cortada em `POR_PAGINA`.
# ===========================================================================
GRUPOS_LOGS = ("Gerente", "Supervisor")
TETO_POR_FONTE = 400
POR_PAGINA = 60


def _pode_ver_logs(user):
    return bool(
        user.is_superuser
        or user.groups.filter(name__in=GRUPOS_LOGS).exists()
    )


@staff_member_required
def logs_unificados(request):
    """Acessos e ações numa linha do tempo só, com filtro de tipo, busca e período."""
    if not _pode_ver_logs(request.user):
        raise PermissionDenied("Esta tela é restrita a Gerente, Supervisor e administrador.")

    tipo = (request.GET.get("tipo") or "").strip()          # "" | acesso | acao
    busca = (request.GET.get("q") or "").strip()
    de_txt = (request.GET.get("de") or "").strip()
    ate_txt = (request.GET.get("ate") or "").strip()

    def _data(txt):
        try:
            return date.fromisoformat(txt) if txt else None
        except ValueError:
            return None

    de, ate = _data(de_txt), _data(ate_txt)
    linhas = []

    # ---- 1. Acessos (login, logout, falha, recuperação, troca de senha) ----
    if tipo in ("", "acesso"):
        qs = LogAcesso.objects.select_related("usuario").all()
        if de:
            qs = qs.filter(em__date__gte=de)
        if ate:
            qs = qs.filter(em__date__lte=ate)
        if busca:
            qs = qs.filter(
                Q(usuario__username__icontains=busca)
                | Q(usuario__first_name__icontains=busca)
                | Q(usuario__last_name__icontains=busca)
                | Q(username_tentado__icontains=busca)
                | Q(ip__icontains=busca)
            )
        for a in qs.order_by("-em")[:TETO_POR_FONTE]:
            quem = ""
            if a.usuario_id:
                quem = a.usuario.get_full_name() or a.usuario.get_username()
            elif a.username_tentado:
                quem = a.username_tentado
            linhas.append({
                "quando": a.em,
                "tipo": "acesso",
                "tipo_rotulo": "Acesso",
                "evento": a.get_evento_display(),
                "evento_key": a.evento,
                "quem": quem or "—",
                "sobre": a.username_tentado if (a.evento == "falha" and a.username_tentado) else "",
                "detalhe": a.ip or "",
                "url": "",
            })

    # ---- 2. Ações (o que foi criado, alterado ou apagado no sistema) -------
    if tipo in ("", "acao"):
        qs = (LogEntry.objects.select_related("user", "content_type").all())
        if de:
            qs = qs.filter(action_time__date__gte=de)
        if ate:
            qs = qs.filter(action_time__date__lte=ate)
        if busca:
            qs = qs.filter(
                Q(user__username__icontains=busca)
                | Q(user__first_name__icontains=busca)
                | Q(user__last_name__icontains=busca)
                | Q(object_repr__icontains=busca)
                | Q(change_message__icontains=busca)
            )
        acao_rotulo = {ADDITION: "Cadastrou", CHANGE: "Alterou", DELETION: "Apagou"}
        for e in qs.order_by("-action_time")[:TETO_POR_FONTE]:
            quem = ""
            if e.user_id:
                quem = e.user.get_full_name() or e.user.get_username()
            url = ""
            # Link para o objeto — só quando ele ainda existe.
            if e.action_flag != DELETION and e.content_type_id and e.object_id:
                url = (f"/admin/{e.content_type.app_label}/"
                       f"{e.content_type.model}/{e.object_id}/change/")
            linhas.append({
                "quando": e.action_time,
                "tipo": "acao",
                "tipo_rotulo": "Ação",
                "evento": acao_rotulo.get(e.action_flag, "Mexeu"),
                "evento_key": {ADDITION: "add", CHANGE: "change", DELETION: "delete"}
                              .get(e.action_flag, ""),
                "quem": quem or "—",
                "sobre": f"{e.content_type.name if e.content_type_id else ''} · {e.object_repr}".strip(" ·"),
                "detalhe": (e.get_change_message() or "")[:120],
                "url": url,
            })

    linhas.sort(key=lambda x: x["quando"], reverse=True)
    total_janela = len(linhas)
    linhas = linhas[:POR_PAGINA]

    hoje = timezone.localdate()
    contexto = dj_admin.site.each_context(request)
    contexto.update({
        "title": "Logs do sistema",
        "linhas": linhas,
        "total_janela": total_janela,
        "cortado": total_janela > POR_PAGINA,
        "por_pagina": POR_PAGINA,
        "tipo": tipo,
        "busca": busca,
        "de": de_txt,
        "ate": ate_txt,
        "hoje_iso": hoje.isoformat(),
        "em_7_iso": (hoje - timedelta(days=7)).isoformat(),
        "em_30_iso": (hoje - timedelta(days=30)).isoformat(),
        # A barra própria desta tela (fichas de tipo + duas datas + "Aplicar",
        # que no celular estourava a página em 162px) virou o MESMO botão
        # "Filtrar" das outras listas. O período usa `de`/`ate`, que já eram os
        # nomes da tela — o popup traduz do calendário (ver `data-mkfp-de`).
        **barra_filtros(
            request,
            [{"param": "tipo", "label": "Tipo", "todos": "Tudo",
              "opcoes": [("acesso", "Acessos"), ("acao", "Ações")]}],
            keep=("q",),
            data={"label": "Período", "de": "de", "ate": "ate", "atalhos": [
                ("Hoje", hoje.isoformat(), hoje.isoformat()),
                ("Últimos 7 dias", (hoje - timedelta(days=7)).isoformat(), hoje.isoformat()),
                ("Últimos 30 dias", (hoje - timedelta(days=30)).isoformat(), hoje.isoformat()),
            ]},
        ),
        **_voltar("/admin/"),
    })
    return render(request, "parque/logs.html", contexto)


# ===========================================================================
# NOVO SETOR EM POPUP
#
# Pedido do dono: "adicionar setor pode ser abrir um popup. Nada de abrir uma
# tela só com esses 2 elementos". Abrir o formulário do admin para digitar
# unidade + nome era sair da tela, perder o contexto (a loja que ele estava
# olhando) e voltar por um "voltar".
#
# Esta view só GRAVA — o desenho é o `<dialog>` de `_setor_novo.html`. Ela
# aceita POST, valida o mínimo e devolve para a tela de origem.
# ===========================================================================
def _stn_ctx():
    """Unidades para o popup de novo setor (`parque/_setor_novo.html`).

    Fica num helper porque as duas telas que criam setor (mapa e lista de
    setores) precisam da mesma lista, e esquecer de passar deixaria o popup com
    um select vazio — falha silenciosa, do tipo que só aparece no uso.
    """
    return {"stn_unidades": Location.objects.filter(setores__isnull=False)
            .distinct().order_by("name")}

# ---------------------------------------------------------------------------
# CENTRAL DE CADASTROS — uma tela para todos os cadastros
# ---------------------------------------------------------------------------
#
# Pedido do dono, repetido: "vamos unificar as visões de gerenciamento de
# cadastro… quando eu clicar em um item, vai puxar a tabela de cada um
# individual — do banco de dados". Antes eram cinco itens de menu levando a
# cinco changelists do admin, cada um com a sua barra e o seu jeito.
#
# Aqui é UMA tela: as abas trocam a tabela (server-side, com busca), e clicar
# numa linha abre a ficha daquele registro ao lado — tudo lido do banco na
# hora, nada de dado embutido no template.
#
# Por que sem AJAX: a troca de aba já é uma navegação com estado (aba + busca +
# selecionado), e link com querystring dá de graça o que o fetch custaria —
# voltar, recarregar, abrir em outra guia e compartilhar a URL da ficha.

# Cada aba declara tudo que a tela precisa dela: rótulo, ícone, campos da
# tabela, como buscar, e como montar a ficha. Assim a view não tem cinco
# caminhos diferentes — tem um, com uma tabela de configuração.
CAD_ABAS = ["colab", "setor", "loja", "pc", "nb"]


def _cad_texto(valor):
    """Texto para a célula: vazio virou o traço que a tela usa como 'falta'."""
    return str(valor).strip() if valor not in (None, "") else ""


def _cad_doc(numero, tamanho):
    """Formata CNPJ (14) e CPF (11) guardados só com dígitos."""
    n = "".join(c for c in str(numero or "") if c.isdigit())
    if len(n) != tamanho:
        return _cad_texto(numero)
    if tamanho == 14:
        return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"


def _cad_fone(numero):
    n = "".join(c for c in str(numero or "") if c.isdigit())
    if len(n) == 11:
        return f"({n[:2]}) {n[2:7]}-{n[7:]}"
    if len(n) == 10:
        return f"({n[:2]}) {n[2:6]}-{n[6:]}"
    return _cad_texto(numero)


@staff_member_required
def cadastros_hub(request):
    """Colaboradores, setores, lojas, computadores e notebooks numa tela."""
    aba = request.GET.get("aba") or "colab"
    if aba not in CAD_ABAS:
        aba = "colab"
    busca = (request.GET.get("q") or "").strip()
    try:
        sel = int(request.GET.get("sel") or 0) or None
    except (TypeError, ValueError):
        sel = None

    # ---- contadores das abas (uma consulta de COUNT cada, sem carregar linha)
    contagens = {
        "colab": Person.objects.count(),
        "setor": Setor.objects.count(),
        "loja": Location.objects.count(),
        "pc": Computador.objects.count(),
        "nb": Notebook.objects.count(),
    }

    linhas, colunas, ficha, add_url, add_rotulo, placeholder = [], [], None, "", "", ""
    TETO = 300   # a tela é de conferência, não de exportação

    # ---- FILTRO POR ABA -----------------------------------------------------
    # A tela tinha só busca. O filtro do sistema entra aqui, mas os grupos são
    # POR ABA: cada aba é uma tabela diferente, e oferecer "situação" na aba de
    # lojas ou "loja" na de notebooks seria filtro que não filtra. `grupos_aba`
    # é preenchido dentro do ramo de cada aba, junto do resto da configuração
    # dela — é o que garante que a §12.4 continue valendo (filtro só onde a
    # view sabe filtrar).
    grupos_aba = []
    loja_sel = (request.GET.get("loja") or "").strip()
    sit_sel = (request.GET.get("sit") or "").strip()
    _lojas_opt = [(str(o.pk), o.name) for o in Location.objects.order_by("name")]

    if aba == "colab":
        colunas = ["Colaborador", "Cargo", "Loja / setor", "CPF", "Telefone"]
        placeholder = "Buscar colaborador por nome, cargo, CPF ou matrícula…"
        add_url, add_rotulo = "/admin/orgs/person/add/", "Novo colaborador"
        qs = Person.objects.select_related("location", "department").order_by("full_name")
        if busca:
            qs = qs.filter(
                Q(full_name__icontains=busca) | Q(job_title__icontains=busca)
                | Q(cpf__icontains=busca) | Q(employee_no__icontains=busca)
                | Q(email__icontains=busca)
            )
        grupos_aba = [
            {"param": "loja", "label": "Loja", "todos": "Todas", "opcoes": _lojas_opt},
            {"param": "sit", "label": "Situação", "todos": "Todas", "opcoes": [
                ("ativo", "Ativos"), ("desligado", "Desligados")]},
        ]
        if loja_sel.isdigit():
            qs = qs.filter(location_id=int(loja_sel))
        if sit_sel == "ativo":
            qs = qs.filter(data_desligamento__isnull=True)
        elif sit_sel == "desligado":
            qs = qs.filter(data_desligamento__isnull=False)
        for o in qs[:TETO]:
            linhas.append({
                "pk": o.pk,
                "titulo": o.full_name,
                "sub": ("desligado" if o.data_desligamento else "ativo") if o.active is not None else "",
                "cels": [_cad_texto(o.job_title),
                         _cad_texto(o.location.name if o.location_id else ""),
                         _cad_doc(o.cpf, 11), _cad_fone(o.telefone)],
                "alerta": bool(o.data_desligamento),
            })
        if sel:
            o = (Person.objects
                 .select_related("location", "department", "user")
                 .filter(pk=sel).first())
            if o:
                # Conta de acesso é OPCIONAL (`Person.user` é nulo de propósito:
                # quem só recebe equipamento não precisa entrar no sistema).
                # Sem conta não há senha para redefinir — e o botão não aparece,
                # em vez de aparecer e falhar depois.
                conta = o.user
                ficha = {
                    "titulo": o.full_name,
                    "sub": _cad_texto(o.job_title) or "Colaborador",
                    "editar": f"/admin/orgs/person/{o.pk}/change/",
                    "conta": conta.get_username() if conta else "",
                    "conta_ativa": bool(conta and conta.is_active),
                    "senha_url": (
                        f"/cadastros/colaborador/{o.pk}/senha/" if conta else ""
                    ),
                    "campos": [
                        ("Matrícula", _cad_texto(o.employee_no)),
                        ("CPF", _cad_doc(o.cpf, 11)),
                        ("Telefone", _cad_fone(o.telefone)),
                        ("E-mail", _cad_texto(o.email)),
                        ("Loja", _cad_texto(o.location.name if o.location_id else "")),
                        ("Departamento", _cad_texto(o.department.name if o.department_id else "")),
                        ("Situação", "Desligado em " + o.data_desligamento.strftime("%d/%m/%Y")
                         if o.data_desligamento else ("Ativo" if o.active else "Inativo")),
                        # Diz sobre QUAL conta o botão de senha age. Sem isso a
                        # ação mexeria em algo que a ficha não mostra.
                        #
                        # Vazio aqui viraria "falta" (o placeholder da ficha), e
                        # não faltar é o caso NORMAL: o modelo separa Person de
                        # User de propósito — "quem segura um equipamento não
                        # precisa acessar o sistema". Texto explícito em vez de
                        # acusar pendência que não existe.
                        ("Conta de acesso",
                         (conta.get_username() + ("" if conta.is_active else " (inativa)"))
                         if conta else "Sem conta — não acessa o sistema"),
                    ],
                }

    elif aba == "setor":
        colunas = ["Setor", "Loja", "Baias", "Com máquina", ""]
        placeholder = "Buscar setor por nome ou loja…"
        # A URL do admin de propósito: o `initSetorPopup()` intercepta
        # exatamente este destino e abre o popup `_setor_novo.html` (incluído
        # no fim desta tela). Apontar para /parque/setores/ fazia o botão
        # trocar de tela em vez de abrir o popup.
        add_url, add_rotulo = "/admin/parque/setor/add/", "Novo setor"
        qs = (Setor.objects.select_related("unidade")
              .annotate(n_baias=Count("baias", distinct=True))
              .order_by("unidade__name", "nome"))
        if busca:
            qs = qs.filter(Q(nome__icontains=busca) | Q(unidade__name__icontains=busca))
        grupos_aba = [
            {"param": "loja", "label": "Loja", "todos": "Todas", "opcoes": _lojas_opt},
        ]
        if loja_sel.isdigit():
            qs = qs.filter(unidade_id=int(loja_sel))
        setores = list(qs[:TETO])
        # Baias COM máquina por setor: agregado no banco (um GROUP BY), não
        # trazendo as 140 linhas de Baia para contar em Python.
        com_maq = dict(
            Baia.objects
            .filter(setor__in=setores)
            .filter(Q(computador__isnull=False) | Q(notebook__isnull=False))
            .values_list("setor_id")
            .annotate(n=Count("id"))
        )
        for o in setores:
            linhas.append({
                "pk": o.pk,
                "titulo": o.nome,
                "sub": "",
                "cels": [_cad_texto(o.unidade.name if o.unidade_id else ""),
                         str(o.n_baias), str(com_maq.get(o.pk, 0)), ""],
                "alerta": o.n_baias == 0,
            })
        if sel:
            o = Setor.objects.select_related("unidade").filter(pk=sel).first()
            if o:
                baias = list(Baia.objects.filter(setor=o)
                             .select_related("computador", "notebook").order_by("numero")[:60])
                ficha = {
                    "titulo": o.nome,
                    "sub": (o.unidade.name if o.unidade_id else "Setor"),
                    "editar": f"/admin/parque/setor/{o.pk}/change/",
                    "campos": [
                        ("Loja", _cad_texto(o.unidade.name if o.unidade_id else "")),
                        ("Baias", str(len(baias))),
                        ("Com máquina", str(sum(1 for b in baias if b.computador_id or b.notebook_id))),
                        ("Vazias", str(sum(1 for b in baias if not (b.computador_id or b.notebook_id)))),
                    ],
                    "lista_tit": "Baias do setor",
                    "lista": [{"t": str(b), "s": ("com máquina" if (b.computador_id or b.notebook_id) else "vazia"),
                               "url": f"/parque/mapa/{o.unidade_id}/" if o.unidade_id else ""}
                              for b in baias[:20]],
                }

    elif aba == "loja":
        colunas = ["Loja", "Cidade / UF", "CNPJ", "Telefone", "Baias"]
        placeholder = "Buscar loja por nome, cidade, CNPJ ou código…"
        add_url, add_rotulo = "/admin/orgs/location/add/", "Nova loja"
        qs = Location.objects.order_by("name")
        if busca:
            qs = qs.filter(
                Q(name__icontains=busca) | Q(city__icontains=busca)
                | Q(cnpj__icontains=busca) | Q(codigo__icontains=busca)
                | Q(razao_social__icontains=busca)
            )
        grupos_aba = [
            {"param": "sit", "label": "Situação", "todos": "Todas", "opcoes": [
                ("ativa", "Ativas"), ("inativa", "Inativas")]},
        ]
        if sit_sel == "ativa":
            qs = qs.filter(ativo=True)
        elif sit_sel == "inativa":
            qs = qs.filter(ativo=False)
        lojas = list(qs[:TETO])
        # Idem: GROUP BY no banco em vez de contagem em Python.
        n_baias = dict(
            Baia.objects
            .filter(setor__unidade__in=lojas)
            .values_list("setor__unidade_id")
            .annotate(n=Count("id"))
        )
        for o in lojas:
            cidade = " / ".join(x for x in [_cad_texto(o.city), _cad_texto(o.state)] if x)
            linhas.append({
                "pk": o.pk,
                "titulo": o.name,
                "sub": " · ".join(x for x in [o.get_tipo_display() if o.tipo else "",
                                              ("código " + o.codigo) if o.codigo else ""] if x),
                "cels": [cidade, _cad_doc(o.cnpj, 14), _cad_fone(o.telefone),
                         str(n_baias.get(o.pk, 0))],
                "alerta": not o.ativo,
            })
        if sel:
            o = Location.objects.filter(pk=sel).first()
            if o:
                setores = list(Setor.objects.filter(unidade=o).order_by("nome")[:30])
                endereco = ", ".join(x for x in [
                    _cad_texto(o.address), _cad_texto(o.numero), _cad_texto(o.bairro)] if x)
                ficha = {
                    "titulo": o.name,
                    "sub": _cad_texto(o.razao_social) or (o.get_tipo_display() if o.tipo else "Unidade"),
                    "editar": f"/admin/orgs/location/{o.pk}/change/",
                    "campos": [
                        ("CNPJ", _cad_doc(o.cnpj, 14)),
                        ("Código", _cad_texto(o.codigo)),
                        ("Telefone", _cad_fone(o.telefone)),
                        ("Endereço", endereco),
                        ("Cidade / UF", " / ".join(x for x in [_cad_texto(o.city), _cad_texto(o.state)] if x)),
                        ("CEP", _cad_texto(o.cep)),
                        ("Situação", "Ativa" if o.ativo else "Inativa"),
                        ("Colaboradores", str(Person.objects.filter(location=o).count())),
                    ],
                    "lista_tit": "Setores desta loja",
                    "lista": [{"t": x.nome, "s": "", "url": f"/parque/mapa/{o.pk}/"} for x in setores],
                    "ir": (f"/parque/mapa/{o.pk}/", "Abrir o mapa da loja"),
                }

    elif aba == "pc":
        colunas = ["Computador", "Patrimônio", "Onde está", "Situação", "Reparos"]
        placeholder = "Buscar computador por série, patrimônio, marca ou local…"
        add_url, add_rotulo = "/admin/parque/computador/add/", "Novo computador"
        qs = Computador.objects.order_by("-atualizado_em")
        if busca:
            qs = qs.filter(
                Q(serial__icontains=busca) | Q(patrimonio__icontains=busca)
                | Q(marca__icontains=busca) | Q(ultima_unidade__icontains=busca)
                | Q(mac__icontains=busca)
            )
        grupos_aba = [
            {"param": "sit", "label": "Situação", "todos": "Todas",
             "opcoes": list(Computador.Status.choices)},
        ]
        if sit_sel in dict(Computador.Status.choices):
            qs = qs.filter(status=sit_sel)
        for o in qs[:TETO]:
            onde = " › ".join(x for x in [_cad_texto(o.ultima_unidade), _cad_texto(o.ultima_baia)] if x)
            linhas.append({
                "pk": o.pk,
                "titulo": _cad_texto(o.serial) or f"Computador {o.pk}",
                "sub": _cad_texto(o.marca),
                "cels": [_cad_texto(o.patrimonio), onde,
                         o.get_status_display() if o.status else "", str(o.qtd_reparos or 0)],
                "alerta": (o.qtd_reparos or 0) >= 3,
            })
        if sel:
            o = Computador.objects.filter(pk=sel).first()
            if o:
                ficha = {
                    "titulo": _cad_texto(o.serial) or f"Computador {o.pk}",
                    "sub": " · ".join(x for x in [_cad_texto(o.marca),
                                                  o.get_status_display() if o.status else ""] if x),
                    "editar": f"/admin/parque/computador/{o.pk}/change/",
                    "campos": [
                        ("Patrimônio", _cad_texto(o.patrimonio)),
                        ("Nº de série", _cad_texto(o.serial)),
                        ("MAC", _cad_texto(o.mac)),
                        ("Sistema", _cad_texto(o.sistema_operacional)),
                        ("Processador", _cad_texto(o.processador)),
                        ("Memória", _cad_texto(o.memoria_ram)),
                        ("Armazenamento", _cad_texto(o.armazenamento)),
                        ("Onde está", " › ".join(x for x in [_cad_texto(o.ultima_unidade),
                                                             _cad_texto(o.ultima_baia)] if x)),
                        ("Reparos", str(o.qtd_reparos or 0)),
                        ("Telemetria", "recebida em " + timezone.localtime(o.tel_visto_em).strftime("%d/%m/%Y %H:%M")
                         if o.tel_visto_em else "sem coleta"),
                    ],
                }

    else:  # nb
        colunas = ["Notebook", "Patrimônio", "Com quem", "Local", "Situação"]
        placeholder = "Buscar notebook por série, patrimônio, modelo ou pessoa…"
        add_url, add_rotulo = "/admin/parque/notebook/add/", "Novo notebook"
        qs = Notebook.objects.select_related("colaborador").order_by("-atualizado_em")
        if busca:
            qs = qs.filter(
                Q(serial__icontains=busca) | Q(patrimonio__icontains=busca)
                | Q(modelo__icontains=busca) | Q(marca__icontains=busca)
                | Q(usuario__icontains=busca) | Q(unidade_setor__icontains=busca)
            )
        grupos_aba = [
            {"param": "sit", "label": "Situação", "todos": "Todas",
             "opcoes": list(Notebook.Status.choices)},
            {"param": "com", "label": "Uso", "todos": "Qualquer", "opcoes": [
                ("sim", "Com colaborador"), ("nao", "Sem colaborador")]},
        ]
        if sit_sel in dict(Notebook.Status.choices):
            qs = qs.filter(status=sit_sel)
        com_sel = (request.GET.get("com") or "").strip()
        if com_sel == "sim":
            qs = qs.filter(colaborador__isnull=False)
        elif com_sel == "nao":
            qs = qs.filter(colaborador__isnull=True)
        for o in qs[:TETO]:
            quem = _cad_texto(o.colaborador.full_name if o.colaborador_id else o.usuario)
            linhas.append({
                "pk": o.pk,
                "titulo": _cad_texto(o.modelo) or _cad_texto(o.serial) or f"Notebook {o.pk}",
                "sub": _cad_texto(o.marca),
                "cels": [_cad_texto(o.patrimonio), quem, _cad_texto(o.unidade_setor),
                         o.get_status_display() if o.status else ""],
                "alerta": False,
            })
        if sel:
            o = Notebook.objects.select_related("colaborador").filter(pk=sel).first()
            if o:
                ficha = {
                    "titulo": _cad_texto(o.modelo) or _cad_texto(o.serial) or f"Notebook {o.pk}",
                    "sub": " · ".join(x for x in [_cad_texto(o.marca),
                                                  o.get_status_display() if o.status else ""] if x),
                    "editar": f"/admin/parque/notebook/{o.pk}/change/",
                    "campos": [
                        ("Patrimônio", _cad_texto(o.patrimonio)),
                        ("Nº de série", _cad_texto(o.serial)),
                        ("Com quem", _cad_texto(o.colaborador.full_name if o.colaborador_id else o.usuario)),
                        ("Local", _cad_texto(o.unidade_setor)),
                        ("Sistema", _cad_texto(o.sistema_operacional)),
                        ("Processador", _cad_texto(o.processador)),
                        ("Memória", _cad_texto(o.memoria_ram)),
                        ("AnyDesk", _cad_texto(o.anydesk)),
                        ("Telemetria", "recebida em " + timezone.localtime(o.tel_visto_em).strftime("%d/%m/%Y %H:%M")
                         if o.tel_visto_em else "sem coleta"),
                    ],
                }

    ctx = {
        "titulo": "Cadastros",
        "aba": aba,
        "busca": busca,
        "sel": sel,
        "contagens": contagens,
        "colunas": colunas,
        "linhas": linhas,
        "ficha": ficha,
        "add_url": add_url,
        "add_rotulo": add_rotulo,
        "placeholder": placeholder,
        "total_mostrado": len(linhas),
        "teto": TETO,
        "estourou": len(linhas) >= TETO,
        # `aba` e `q` no keep: aplicar filtro não pode trocar a aba nem apagar a
        # busca que a pessoa digitou. `sel` fica FORA do keep de propósito — a
        # ficha aberta ao lado é de um registro que o novo filtro pode excluir.
        **barra_filtros(request, grupos_aba, keep=("aba", "q")),
        **_stn_ctx(),
        # O `each_context` do admin é o que traz MENU, cabeçalho e o painel de
        # avisos do topo. Sem ele esta tela abria sem `#nav-sidebar` e sem
        # `#mk-agenda`: nenhum caminho de volta e nenhuma mensagem de ação
        # visível (a mensagem ia para a fonte escondida e ninguém a adotava).
        # Toda tela que estende `admin/base_site.html` precisa disto.
        **dj_admin.site.each_context(request),
        # Depois do each_context de propósito: ele define "title", e o
        # cabeçalho desta tela é o nosso.
        "title": "Cadastros",
    }
    return render(request, "parque/cadastros.html", ctx)


@staff_member_required
@require_POST
def setor_criar(request):
    """Cria um setor a partir do popup e volta para a tela de onde veio."""
    if not request.user.has_perm("parque.add_setor"):
        raise PermissionDenied("Você não tem permissão para criar setor.")

    destino = voltar_para(request, padrao="/parque/setores/")
    nome = (request.POST.get("nome") or "").strip()
    uni_id = (request.POST.get("unidade") or "").strip()

    if not nome or not uni_id:
        messages.error(request, "Informe a unidade e o nome do setor.")
        return redirect(destino)

    unidade = Location.objects.filter(pk=uni_id).first()
    if not unidade:
        messages.error(request, "Unidade não encontrada.")
        return redirect(destino)

    # `UniqueConstraint(unidade, nome)` no modelo: aqui a checagem é só para
    # devolver uma frase em vez de um erro de banco.
    if Setor.objects.filter(unidade=unidade, nome__iexact=nome).exists():
        messages.warning(request, f"A unidade {unidade.name} já tem um setor “{nome}”.")
        return redirect(destino)

    Setor.objects.create(unidade=unidade, nome=nome)
    messages.success(request, f"Setor “{nome}” criado em {unidade.name}.")
    return redirect(destino)
