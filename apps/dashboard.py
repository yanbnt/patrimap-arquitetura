"""
Dashboard inicial do admin (unfold DASHBOARD_CALLBACK).

Calcula KPIs e os dados dos gráficos (formato Chart.js, que o unfold renderiza
com o Chart.js embutido). Retorna tudo no contexto consumido por
templates/admin/index.html.
"""

import calendar
import json
import re
from datetime import date, timedelta
from urllib.parse import quote

from django.utils import timezone

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render

from apps.inventory.models import Asset
from apps.maintenance.models import MaintenanceLog
from apps.orgs.models import Location, Person
from apps.orcamentos.models import Orcamento
from apps.parque.models import (
    Baia, Computador, MovimentacaoBaia, Notebook, Peca, Reparo, Transferencia,
    PREVENTIVA_DIAS,
)

# Peças consideradas "periférico" para o consumo (trocas em reparos).
PECAS_PERIF = ["mouse", "teclado", "webcam", "headset", "monitor", "leitor_cod_barras"]

# --- Paleta de gráfico (DESIGN-SYSTEM.md §2) ---------------------------------
# Série categórica SEMPRE na ESCALA TONAL do verde da marca — os mesmos tons dos
# papéis `--md-*` (primary, primary-container, tertiary), nesta ordem. Chapado:
# nenhum degradê, porque no M3 a hierarquia é tom e tamanho, não brilho.
# Nada de azul / roxo / rosa; vermelho e âmbar só como status semântico.
VERDE = "#00a651"          # verde da marca (o tom de série mais usado)
VERDE_ESC = "#00713a"      # --md-primary (claro)
VERDE_CLARO = "#71db96"    # --md-primary (escuro) / primary-fixed-dim
VERDE_PALIDO = "#8df8b0"   # --md-primary-container (claro)
LIMA_ESC = "#55650a"       # --md-tertiary (claro)
LIMA = "#bfd071"           # --md-tertiary (escuro)
PALETA_MARCA = [VERDE_ESC, VERDE, VERDE_CLARO, VERDE_PALIDO, LIMA_ESC, LIMA]
# Tom de hover das barras: um passo na MESMA escala, não uma cor nova.
VERDE_MED = "#00913f"

# Cores de STATUS — a escala `--md-st-*` do contrato (§2). Como as opções do
# Chart.js são JSON estático (uma cor só serve os dois temas), cada status usa o
# tom MÉDIO da sua rampa: legível sobre `surface` no claro e no escuro.
ST_PENDENTE = "#de3730"    # st-crit  (erro T50)
ST_VENCIDA = "#b06000"     # st-warn  (âmbar T50)
ST_PROXIMA = "#8a7b00"     # st-attn  (amarelo T50)
ST_EMDIA = "#00a651"       # st-ok    (verde da marca)
# Neutro do M3 para "sem dado": `--md-outline` no tom médio das duas versões.
NEUTRO = "#7d8681"

# Cor de cada classe de desempenho (mesma régua de Baia.classe_desempenho):
# rampa crítico → ótimo — status semântico nas classes ruins, escala tonal do
# verde da marca nas boas (claro → cheio).
COR_CLASSE = {"Crítico": ST_PENDENTE, "Baixo": ST_VENCIDA,
              "Bom": VERDE_CLARO, "Ótimo": VERDE}


def _pentes_ram(texto):
    """Nº de pentes de RAM a partir da spec, em módulos de 4GB (8GB → 2 pentes)."""
    m = re.search(r"(\d+[.,]?\d*)\s*gb", (texto or "").lower())
    if not m:
        return 0
    gb = float(m.group(1).replace(",", "."))
    return max(1, round(gb / 4)) if gb else 0


def _drives(texto):
    """Nº de unidades de armazenamento na máquina (SSD + HD contam separado)."""
    t = (texto or "").lower()
    n = (1 if ("ssd" in t or "nvme" in t or "m.2" in t) else 0) + (1 if "hd" in t else 0)
    if n == 0 and t.strip():
        n = 1  # tem algo escrito, mas sem tipo claro → conta 1
    return n

# --- Acabamento dos gráficos (DESIGN-SYSTEM.md §2 e §3) ----------------------
# Papéis do M3 traduzidos para o canvas. As opções são JSON ESTÁTICO (o Chart.js
# recebe um valor só, e canvas não resolve `var(--md-…)`), então cada tinta é o
# equivalente do papel que serve os DOIS temas:
#
#   · grade e eixo  = --md-outline-variant. Um cinza-verde com alfa reproduz o
#     papel quase exato nos dois temas: sobre `surface` claro dá ~#c0c9c0
#     (o valor do :root) e sobre o escuro dá ~#404942 (o valor do .dark).
#   · tick e legenda = --md-on-surface-variant, no tom médio entre #404942
#     (claro) e #c0c9c0 (escuro) — o mesmo lugar onde vive o --md-outline.
#   · tooltip = inverse-surface / inverse-on-surface, raio 4px (§1: sombra e
#     flutuação só em quem realmente flutua).
#
# Tipografia na escala do M3: legenda em label-medium (12/500) e tick em
# label-small (11/500). Nada de peso 700 — §5, item 4.
# Fonte do texto DENTRO do canvas. Cravada nas opções além do default do
# Chart.js, porque cada bloco de opções (ticks, legenda, tooltip) pode trazer
# a sua e sobrescrever o default. Pilha simples: `ctx.font` do canvas descarta
# valor que não parseia e cai na fonte serifada padrão.
# Fonte do texto DENTRO do canvas.
#
# Estava "Roboto" nestas três constantes — fonte que NÃO existe no Windows e
# que o projeto nem carrega (a tipografia do sistema é Figtree, escolha do
# dono; a Roboto do M3 foi reprovada). Sem a família instalada, o `ctx.font`
# do canvas cai na fonte padrão do navegador, que é SERIFADA: era daí que vinha
# a letra estranha na legenda, nos eixos e no tooltip de todos os gráficos.
#
# Pilha curta de propósito: `ctx.font` descarta valor que não parseia.
CH_FONTE_FAM = "Figtree, sans-serif"

CH_TINTA = "#7d8681"
CH_GRADE = "rgba(122,133,126,.42)"
CH_LEGENDA = {
    "boxWidth": 8, "padding": 16,
              "font": {"size": 12, "weight": "500", "family": CH_FONTE_FAM},
              "color": CH_TINTA, "usePointStyle": True}
CH_TOOLTIP = {
    "backgroundColor": "#2c322d", "titleColor": "#edf2ea",
              "bodyColor": "#edf2ea", "padding": 8, "cornerRadius": 4,
              "titleFont": {"weight": "500", "size": 12, "family": CH_FONTE_FAM},
              "bodyFont": {"size": 12, "family": CH_FONTE_FAM}}
CH_TICKS = {
    "color": CH_TINTA,
            "font": {"size": 11, "weight": "500", "family": CH_FONTE_FAM}}
# Eixo Y padrão: grade em outline-variant, sem a linha de borda (§5: borda que
# só separa, sai).
CH_EIXO_Y = {"beginAtZero": True, "ticks": dict(CH_TICKS, precision=0),
             "grid": {"color": CH_GRADE},
             "border": {"display": False, "color": CH_GRADE}}

OPCOES = json.dumps({
    "maintainAspectRatio": False,
    "plugins": {
        "legend": {"display": False},
        "tooltip": dict(CH_TOOLTIP, displayColors=False),
    },
    "scales": {
        "x": {"grid": {"display": False}, "ticks": CH_TICKS},
        "y": CH_EIXO_Y,
    },
})
OPCOES_LINHA = json.dumps({
    "maintainAspectRatio": False,
    "plugins": {"legend": {"display": False}, "tooltip": CH_TOOLTIP},
    "scales": {"x": {"grid": {"display": False}, "ticks": CH_TICKS}, "y": CH_EIXO_Y},
})
# Rosca: anel fino (cutout de 65%) e `borderWidth: 0` no dataset — o anel branco
# entre fatias virava um risco claro atravessando a rosca no tema escuro.
OPCOES_ROSCA = json.dumps({
    "maintainAspectRatio": False,
    "cutout": "65%",
    "plugins": {
        "legend": {"display": True, "position": "right", "labels": CH_LEGENDA},
        "tooltip": CH_TOOLTIP,
    },
})
# A "pizza" da situação das baias usa o MESMO anel: no M3 as duas leituras
# circulares da tela têm de ter a mesma forma.
OPCOES_PIZZA = json.dumps({
    "maintainAspectRatio": False,
    "cutout": "65%",
    "plugins": {
        "legend": {"display": True, "position": "right", "labels": CH_LEGENDA},
        "tooltip": CH_TOOLTIP,
    },
})
OPCOES_EMPILHADO = json.dumps({
    "maintainAspectRatio": False,
    "interaction": {"mode": "index", "intersect": False},
    "plugins": {
        "legend": {"display": True, "position": "top", "labels": CH_LEGENDA},
        "tooltip": dict(CH_TOOLTIP, mode="index", intersect=False),
    },
    "scales": {
        "x": {"stacked": True, "grid": {"display": False}, "ticks": CH_TICKS},
        "y": dict(CH_EIXO_Y, stacked=True),
    },
})

OPCOES_QTD = json.dumps({
    "maintainAspectRatio": False,
    "interaction": {"mode": "index", "intersect": False},
    "plugins": {
        # Legenda no ALTO à direita: no lugar de comer 1/3 da largura do gráfico
        # de linha (era "position: right"), ela vira uma faixa fina sobre o eixo.
        "legend": {"display": True, "position": "top", "align": "end",
                   "labels": CH_LEGENDA},
        "tooltip": dict(CH_TOOLTIP, mode="index", intersect=False),
    },
    "scales": {
        "x": {"title": {"display": True, "text": "Mês", "color": CH_TINTA},
              "grid": {"display": False}, "ticks": CH_TICKS},
        "y": dict(CH_EIXO_Y,
                  title={"display": True, "text": "Quantidade", "color": CH_TINTA}),
    },
})

# Opções do gráfico de PREVENTIVA POR MÊS no estilo pedido pelo dono (modelo
# que ele mandou): duas áreas macias empilhadas, sem grade, sem título de eixo
# e sem marcador de ponto — o eixo Y sai de cena porque o número que interessa
# está no cabeçalho do painel e no tooltip. É só apresentação: a série é a
# mesma (realizadas x pendentes).
OPCOES_AREA = json.dumps({
    "maintainAspectRatio": False,
    "interaction": {"mode": "index", "intersect": False},
    "plugins": {
        "legend": {"display": True, "position": "top", "align": "end",
                   "labels": dict(CH_LEGENDA, usePointStyle=True, pointStyle="circle")},
        "tooltip": dict(CH_TOOLTIP, mode="index", intersect=False),
    },
    "scales": {
        "x": {"grid": {"display": False},
              "border": {"display": False},
              "ticks": CH_TICKS},
        "y": {"beginAtZero": True,
              "grid": {"display": False},
              "border": {"display": False},
              "ticks": {"display": False}},
    },
    "elements": {"line": {"borderJoinStyle": "round"}},
})

MESES_ABBR =["jan", "fev", "mar", "abr", "mai", "jun",
              "jul", "ago", "set", "out", "nov", "dez"]


def _ultimos_12_meses():
    """Lista [(ano, mes)] dos últimos 12 meses, do mais antigo ao atual."""
    from django.utils import timezone
    hoje = timezone.localdate()
    yy, mm = hoje.year, hoje.month
    seq = []
    for _ in range(12):
        seq.append((yy, mm))
        mm -= 1
        if mm == 0:
            mm, yy = 12, yy - 1
    seq.reverse()
    return seq


def _bar(labels, data, cores, hover=None):
    """Barra CHAPADA (nenhum degradê) com o raio pequeno da escala de forma."""
    return json.dumps({
        "labels": labels,
        "datasets": [{
            "data": data,
            "backgroundColor": cores,
            "hoverBackgroundColor": hover or cores,
            "borderRadius": 4,
            "maxBarThickness": 56,
            "categoryPercentage": 0.62,
            "barPercentage": 0.9,
        }],
    })


def _linha(labels, data):
    """Linha CHAPADA: traço em `primary`, sem área preenchida e sem degradê."""
    return json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "Transferências",
            "data": data,
            "borderColor": VERDE,
            "backgroundColor": VERDE,
            "fill": False,
            "borderWidth": 2,
            "tension": 0.3,
            "pointBackgroundColor": VERDE,
        }],
    })


def dashboard_callback(request, context):
    # Caminho de volta. Quem abre o Mural chega a este painel pelo "Painel
    # completo" da tela inicial e ficava sem porta de saída — só o menu, que
    # não é onde a pessoa procura. Para quem NÃO abre o Mural o link não
    # aparece: o painel É a tela inicial dessa pessoa, e "voltar ao Início"
    # daria nele mesmo. O `request` no fim é cache — `pode_ver_tela` é chamado
    # muitas vezes por requisição.
    from apps.orgs.acessos import pode_ver_tela
    context["voltar_ao_inicio"] = pode_ver_tela(request.user, "registros", request)

    baias = Baia.objects.all()
    total_baias = baias.count()
    # Situação DERIVADA do dispositivo (preenchida no loop de baias_perf abaixo).
    situacao_counts = {"tem_pc": 0, "sem_pc": 0, "notebook": 0, "defeito": 0}

    # --- Máquinas em estado CRÍTICO por unidade (índice de desempenho) ---
    unidades_qs = (
        Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    )
    criticos_por_unidade = {u.id: 0 for u in unidades_qs}
    criticas_lista = []  # (baia, índice) das máquinas críticas, p/ o ranking
    score_itens = []     # dados por máquina p/ o explorador de score (slider ao vivo)

    # Componentes REAIS implantados no parque (derivados do hardware das máquinas).
    COMP_LABEL = {
        "processador": "Processador", "memoria_ram": "Memória RAM",
        "armazenamento": "Armazenamento (HD / SSD)", "placa_mae": "Placa-mãe",
        "fonte": "Fonte", "monitor": "Monitor", "teclado": "Teclado",
        "mouse": "Mouse", "headset": "Headset", "webcam": "Webcam",
        "leitor_cod_barras": "Leitor de código de barras",
    }
    comp = {k: 0 for k in COMP_LABEL}

    # Manutenção preventiva: contagem por status (ciclo de 60 dias).
    prev_counts = {"em_dia": 0, "proxima": 0, "vencida": 0, "pendente": 0}

    # Números novos da tela inicial remodelada, colhidos NESTE laço (que já
    # percorre as baias com prefetch): não custa consulta a mais.
    #  · `vence_15`  — o que vira problema nos próximos 15 dias. É o dado que
    #    faltava na tela: hoje ela só mostrava o que JÁ venceu.
    #  · `uni_stats` — por loja: baias, quantas têm PC, quantas estão críticas
    #    e quantas têm preventiva a vencer. A barra sozinha não respondia nada
    #    disso.
    _hoje_d = timezone.localdate()
    _limite_15 = _hoje_d + timedelta(days=15)
    vence_15 = 0
    uni_stats = {u.id: {"id": u.id, "nome": u.name, "baias": 0, "com_pc": 0,
                        "criticas": 0, "vence": 0} for u in unidades_qs}

    baias_perf = (
        Baia.objects.select_related("setor__unidade", "computador", "notebook")
        .prefetch_related("reparos")
    )
    for b in baias_perf:
        situacao_counts[b.situacao_key] = situacao_counts.get(b.situacao_key, 0) + 1
        st = b.preventiva_status
        if st in prev_counts:
            prev_counts[st] += 1

        _uni = uni_stats.get(b.setor.unidade_id) if b.setor_id else None
        if _uni is not None:
            _uni["baias"] += 1
            if b.computador_id or b.notebook_id:
                _uni["com_pc"] += 1
        _venc = b.preventiva_vencimento
        if _venc and _hoje_d <= _venc <= _limite_15:
            vence_15 += 1
            if _uni is not None:
                _uni["vence"] += 1
        # --- Desempenho / score ---
        idx = b.indice_desempenho
        if idx is not None:
            classe = b.classe_desempenho
            score_itens.append({
                "s": idx, "c": classe, "u": b.setor.unidade.name,
                "l": f"{b.setor.nome} › {b.nome}", "uid": b.setor.unidade_id,
            })
            if classe == "Crítico":
                criticos_por_unidade[b.setor.unidade_id] = (
                    criticos_por_unidade.get(b.setor.unidade_id, 0) + 1
                )
                criticas_lista.append((b, idx))
                if _uni is not None:
                    _uni["criticas"] += 1

        # --- Componentes implantados (qualquer mesa COM dispositivo) ---
        if not b.esta_vazia:
            if b.eff_cpu:
                comp["processador"] += 1
            if b.eff_placa:
                comp["placa_mae"] += 1
            comp["memoria_ram"] += _pentes_ram(b.eff_ram)
            comp["armazenamento"] += _drives(b.eff_disco)
            if b.computador_id:
                comp["fonte"] += 1  # só desktop tem fonte separada
        # Periféricos presentes (status "sim" ou "defeito") — independem de ter PC.
        for campo in ("mouse", "teclado", "webcam", "headset", "monitor", "leitor_cod_barras"):
            if getattr(b, campo) in ("sim", "defeito"):
                comp[campo] += 1

    total_criticos = sum(criticos_por_unidade.values())
    criticas_lista.sort(key=lambda x: x[1])  # pior (menor índice) primeiro

    # --- Notebooks no score (entram no explorador e no mapa por score) ---
    from apps.parque.views import _unidade_setor_notebook
    _uni_canon = list(unidades_qs.values_list("name", flat=True))
    _uni_lower = {n.lower(): n for n in _uni_canon}
    _aliases = {"vilar dos teles": "Vilar", "vilar de teles": "Vilar"}
    nb_classe = {"Crítico": 0, "Baixo": 0, "Bom": 0, "Ótimo": 0, "Sem specs": 0}
    for nb in Notebook.objects.select_related("colaborador__location", "colaborador__department"):
        idx = nb.indice_desempenho
        if idx is None:
            nb_classe["Sem specs"] += 1
            continue
        nb_classe[nb.classe_desempenho] += 1
        uni, _setor = _unidade_setor_notebook(nb, _uni_lower, _aliases)
        score_itens.append({
            "s": idx, "c": nb.classe_desempenho, "u": uni, "l": str(nb), "uid": None,
        })

    # --- KPIs ---
    context["kpis"] = [
        {"rotulo": "Computadores", "valor": Computador.objects.exclude(status=Computador.Status.DESATIVADO).count(), "icon": "desktop_windows", "link": "/parque/mapa-completo/"},
        {"rotulo": "Baias", "valor": total_baias, "icon": "grid_view", "link": "/parque/tabela-computadores/"},
        {"rotulo": "Unidades", "valor": Location.objects.filter(setores__isnull=False).distinct().count(), "icon": "location_on", "link": "/parque/setores/"},
        {"rotulo": "Colaboradores", "valor": Person.objects.count(), "icon": "groups", "link": "/admin/orgs/person/"},
        {"rotulo": "Notebooks", "valor": Notebook.objects.count(), "icon": "laptop_mac", "link": "/parque/mapa-notebooks/"},
        {"rotulo": "Transferências", "valor": Transferencia.objects.count(), "icon": "swap_horiz", "link": "/parque/transferencias/"},
        {"rotulo": "Preventivas pendentes", "valor": prev_counts["pendente"] + prev_counts["vencida"], "icon": "build", "alerta": True, "link": "/parque/preventiva/"},
        {"rotulo": "Máquinas críticas", "valor": total_criticos, "icon": "priority_high", "alerta": True, "link": "/parque/mapa-criticos/"},
    ]

    # --- Estado do dia (faixa "Exige ação agora" remodelada) ---
    # Solicitações esperando decisão: transferência e movimentação de baia.
    _aprov = (
        Transferencia.objects.filter(status=Transferencia.Status.PENDENTE).count()
        + MovimentacaoBaia.objects.filter(status=MovimentacaoBaia.Status.PENDENTE).count()
    )
    # Datas prontas para o link da ficha "vencem em 15 dias" (o mapa filtra
    # por `?vence_desde=&vence_ate=`). O template não faz conta de data.
    context["hoje_iso"] = _hoje_d.isoformat()
    context["em_15_iso"] = _limite_15.isoformat()
    context["estado_hoje"] = {
        "criticas": total_criticos,
        "vencidas": prev_counts["pendente"] + prev_counts["vencida"],
        "vence_15": vence_15,
        "aprovacoes": _aprov,
        "tudo_em_dia": not (total_criticos or prev_counts["pendente"]
                            or prev_counts["vencida"] or _aprov),
    }

    # Cabeçalho de boas-vindas (hero) — reaproveita os números já calculados nos KPIs.
    _kpi = {k["rotulo"]: k["valor"] for k in context["kpis"]}
    context["hero"] = {
        "computadores": _kpi.get("Computadores", 0),
        "notebooks": _kpi.get("Notebooks", 0),
        "criticas": total_criticos,
        "preventivas": _kpi.get("Preventivas pendentes", 0),
    }

    # --- Gráfico (PIZZA): situação dos computadores, clicável → mapa filtrado ---
    ordem = ["tem_pc", "sem_pc", "notebook", "defeito"]
    rotulos = {"tem_pc": "Com PC", "sem_pc": "Sem PC",
               "notebook": "Notebook", "defeito": "Com defeito"}
    context["chart_situacao"] = json.dumps({
        "labels": [rotulos[k] for k in ordem],
        "datasets": [{
            "data": [situacao_counts.get(k, 0) for k in ordem],
            # Três categorias na escala tonal do verde + o status de defeito.
            "backgroundColor": [VERDE_ESC, VERDE_CLARO, LIMA, ST_PENDENTE],
            # Separação por VÃO, não por anel branco: o anel branco era um risco
            # claro atravessando a rosca no tema escuro. O vão mostra o painel.
            "borderWidth": 0,
            "spacing": 2,
            "hoverOffset": 10,
        }],
    })
    context["chart_opcoes_pizza"] = OPCOES_PIZZA
    context["nav_situacao"] = json.dumps(
        [f"/parque/mapa-situacao/{k}/" for k in ordem]
    )

    # --- Explorador de SCORE (slider ao vivo no template) ---
    score_itens.sort(key=lambda d: d["s"])
    context["score_itens"] = score_itens
    context["tem_score"] = bool(score_itens)
    context["score_cores"] = COR_CLASSE

    context["total_criticos"] = total_criticos
    context["criticos_link"] = "/parque/mapa-criticos/"

    # --- Gráfico (ROSCA): manutenção preventiva por status (ciclo de 60 dias) ---
    prev_ordem = ["em_dia", "proxima", "vencida", "pendente"]
    prev_rotulo = {"em_dia": "Em dia", "proxima": "Próxima (≤14d)",
                   "vencida": "Vencida", "pendente": "Pendente (nunca feita)"}
    prev_cor = {"em_dia": ST_EMDIA, "proxima": ST_PROXIMA,
                "vencida": ST_VENCIDA, "pendente": ST_PENDENTE}
    prev_itens = [k for k in prev_ordem if prev_counts[k]]
    context["chart_preventiva"] = json.dumps({
        "labels": [prev_rotulo[k] for k in prev_itens],
        "datasets": [{
            "data": [prev_counts[k] for k in prev_itens],
            "backgroundColor": [prev_cor[k] for k in prev_itens],
            "borderWidth": 0, "spacing": 2, "hoverOffset": 8,
        }],
    })
    context["nav_preventiva"] = json.dumps(["/parque/preventiva/" for _ in prev_itens])
    context["total_preventiva_pendente"] = prev_counts["pendente"] + prev_counts["vencida"]
    context["tem_preventiva"] = bool(prev_itens)

    # --- Gráfico (LINHAS): QUANTIDADE de reparos por tempo (Preventiva/Corretiva/Total) ---
    # Eixo X = meses do ANO corrente (janeiro até o mês atual).
    ano = timezone.localdate().year
    mes_atual = timezone.localdate().month
    meses = [(ano, m) for m in range(1, mes_atual + 1)]
    n_meses = len(meses)
    idx_mes = {(y, m): i for i, (y, m) in enumerate(meses)}
    labels_meses = [f"{MESES_ABBR[m - 1]}/{str(y)[2:]}" for (y, m) in meses]

    prev = [0] * n_meses  # preventivas REALIZADAS por mês
    for r in Reparo.objects.filter(tipo=Reparo.Tipo.PREVENTIVA):
        if r.data and (r.data.year, r.data.month) in idx_mes:
            prev[idx_mes[(r.data.year, r.data.month)]] += 1

    # Pendentes por mês: backlog de máquinas fora do ciclo de 60 dias no fim de cada mês.
    fim_mes = [date(y, m, calendar.monthrange(y, m)[1]) for (y, m) in meses]
    pendentes = [0] * n_meses
    for b in Baia.objects.select_related("computador", "notebook").prefetch_related("reparos"):
        if b.esta_vazia:
            continue  # sem máquina física
        pdatas = sorted(
            r.data for r in b.reparos.all()
            if r.tipo == Reparo.Tipo.PREVENTIVA and r.data
        )
        for i, d in enumerate(fim_mes):
            if b.criado_em > d:
                continue  # ainda não estava em serviço
            anteriores = [pd for pd in pdatas if pd <= d]
            ref = anteriores[-1] if anteriores else b.criado_em
            if (d - ref).days >= 60:
                pendentes[i] += 1

    def _linha_qtd(label, data, cor, fundo):
        """Área macia: é o desenho do modelo que o dono mandou.

        `tension` faz a curva; `fill: "origin"` fecha a área até o zero;
        `pointRadius: 0` limpa os marcadores (eles voltam no hover). O fundo
        vem em rgba porque a área precisa deixar ver a série de baixo.
        """
        return {
            "label": label, "data": data,
            "borderColor": cor, "backgroundColor": fundo,
            "borderWidth": 2.5, "tension": 0.45,
            "pointRadius": 0, "pointHoverRadius": 5,
            "pointBackgroundColor": cor, "pointBorderColor": "#fff",
            "fill": "origin",
        }

    context["chart_qtd"] = json.dumps({
        "labels": labels_meses,
        "datasets": [
            _linha_qtd("Realizadas", prev, VERDE, "rgba(0,166,81,.22)"),
            _linha_qtd("Pendentes", pendentes, "#d97757", "rgba(217,119,87,.26)"),
        ],
    })
    context["chart_opcoes_qtd"] = OPCOES_AREA
    context["total_reparos_12m"] = pendentes[-1]
    context["tem_reparos"] = (sum(prev) + sum(pendentes)) > 0

    # --- Ranking de UNIDADES por nº de máquinas críticas (hover lista as baias) ---
    crit_uni = {}  # unidade -> [(baia, índice)], já em ordem pior→melhor
    for b, idx in criticas_lista:
        crit_uni.setdefault(b.setor.unidade, []).append((b, idx))
    unidades_rank = sorted(crit_uni.items(), key=lambda kv: len(kv[1]), reverse=True)
    context["ranking_data"] = {
        "labels": [u.name for u, _ in unidades_rank],
        "data": [len(lst) for _, lst in unidades_rank],
        "baias": [
            [f"{b.setor.nome} › {b.nome} (índice {idx})" for b, idx in lst]
            for _, lst in unidades_rank
        ],
        "nav": [f"/parque/mapa-criticos/{u.id}/" for u, _ in unidades_rank],
    }
    context["tem_ranking"] = bool(unidades_rank)

    context["chart_opcoes"] = OPCOES

    # --- Chamados por unidade ("onde dá mais problema" / nº de chamados) ---
    chamados = list(
        Reparo.objects.values("baia__setor__unidade__id", "baia__setor__unidade__name")
        .annotate(n=Count("id")).order_by("-n")
    )
    chamados = [c for c in chamados if c["baia__setor__unidade__name"]]
    context["chart_chamados"] = _bar(
        [c["baia__setor__unidade__name"] for c in chamados],
        [c["n"] for c in chamados],
        [VERDE for _ in chamados],
        hover=VERDE_ESC,
    )
    context["nav_chamados"] = json.dumps(
        [f"/admin/parque/reparo/?baia__setor__unidade__id__exact={c['baia__setor__unidade__id']}"
         for c in chamados]
    )
    context["tem_chamados"] = bool(chamados)

    # --- Consumo de periférico por unidade (trocas de periférico em reparos) ---
    perif = list(
        Reparo.objects.filter(Q(tipo="periferico") | Q(peca__in=PECAS_PERIF))
        .values("baia__setor__unidade__id", "baia__setor__unidade__name")
        .annotate(n=Count("id")).order_by("-n")
    )
    perif = [c for c in perif if c["baia__setor__unidade__name"]]
    context["chart_perif"] = _bar(
        [c["baia__setor__unidade__name"] for c in perif],
        [c["n"] for c in perif],
        # Série única → uma cor só, a da marca (§5, item 6). O hover é um passo
        # na MESMA escala tonal, nunca uma cor nova.
        [VERDE for _ in perif],
        hover=VERDE_MED,
    )
    context["nav_perif"] = json.dumps(
        [f"/admin/parque/reparo/?baia__setor__unidade__id__exact={c['baia__setor__unidade__id']}"
         for c in perif]
    )
    context["tem_perif"] = bool(perif)

    # --- Notebooks por SCORE / classe de desempenho (rosca) ---
    nb_ordem = ["Crítico", "Baixo", "Bom", "Ótimo", "Sem specs"]
    nb_cor = dict(COR_CLASSE, **{"Sem specs": NEUTRO})
    nb_itens = [k for k in nb_ordem if nb_classe[k]]
    context["chart_notebooks"] = json.dumps({
        "labels": nb_itens,
        "datasets": [{
            "data": [nb_classe[k] for k in nb_itens],
            "backgroundColor": [nb_cor[k] for k in nb_itens],
            "borderWidth": 0, "spacing": 2, "hoverOffset": 8,
        }],
    })
    context["chart_opcoes_rosca"] = OPCOES_ROSCA
    # Clique numa classe → mapa por score só com notebooks daquela classe.
    context["nav_notebooks"] = json.dumps([
        ("/parque/mapa-notebooks/" if k == "Sem specs"
         else f"/parque/mapa-score/?tipo=nb&classe={quote(k)}")
        for k in nb_itens
    ])
    context["total_notebooks"] = Notebook.objects.count()
    context["tem_notebooks"] = bool(nb_itens)

    # --- Componentes REAIS no parque por tipo (derivados do hardware) ---
    # Em vez do estoque cadastrado, conta o que está implantado nas máquinas:
    # 1 processador/placa/fonte por máquina, RAM em pentes de 4GB (8GB → 2),
    # SSD/HD por unidade de disco e periféricos presentes.
    comp_itens = sorted(
        [(k, v) for k, v in comp.items() if v], key=lambda kv: kv[1], reverse=True
    )
    paleta_comp = PALETA_MARCA
    context["chart_pecas"] = _bar(
        [COMP_LABEL[k] for k, _ in comp_itens],
        [v for _, v in comp_itens],
        [paleta_comp[i % len(paleta_comp)] for i in range(len(comp_itens))],
    )
    context["nav_pecas"] = json.dumps(
        [f"/admin/parque/peca/?tipo__exact={k}" for k, _ in comp_itens]
    )
    context["total_pecas"] = sum(v for _, v in comp_itens)
    context["tem_pecas"] = bool(comp_itens)

    # --- Unidades para o mapa interativo da loja ---
    context["unidades_mapa"] = [
        {"id": u.id, "nome": u.name,
         "baias": baias.filter(setor__unidade=u).count()}
        for u in Location.objects.filter(setores__isnull=False).distinct().order_by("name")
    ]
    # Maior nº de baias — usado p/ as mini-barras de proporção no mapa da Início.
    context["max_baias"] = max((u["baias"] for u in context["unidades_mapa"]), default=0)

    # Tabela de unidades da tela inicial: cada coluna responde uma pergunta
    # (quantas baias, quantas com PC, quantas críticas, quantas a vencer).
    _linhas = [v for v in uni_stats.values()]
    _linhas.sort(key=lambda x: (-x["baias"], x["nome"]))
    context["unidades_tabela"] = _linhas
    context["unidades_totais"] = {
        "lojas": len(_linhas),
        "baias": sum(x["baias"] for x in _linhas),
        "com_pc": sum(x["com_pc"] for x in _linhas),
        "criticas": sum(x["criticas"] for x in _linhas),
        "vence": sum(x["vence"] for x in _linhas),
    }

    return context


@staff_member_required
def dashboard_completo(request):
    """Tela 'Dashboard' (separada da 'Início'): só os gráficos analíticos.

    Reaproveita o mesmo cálculo de dados do dashboard_callback e o chrome do
    admin (sidebar, branding) via admin.site.each_context.
    """
    context = admin.site.each_context(request)
    dashboard_callback(request, context)
    # `each_context` traz o title da tela de Início do admin ("Welcome <user>"),
    # que aparecia na trilha da barra superior. Aqui a tela é o Dashboard.
    context["title"] = "Dashboard"
    context["subtitle"] = None
    return render(request, "admin/dashboard_full.html", context)


# =========================== QUADRO DA TELA INICIAL ===========================
# Três colunas por URGÊNCIA — precisa de você · em andamento · feito hoje — no
# lugar de um painel de números. É o protótipo que o dono aprovou.
#
# A diferença em relação ao kanban de Chamados é de propósito: lá as colunas são
# o CICLO DE VIDA de um chamado (Abertos · Aguardando peça · Em manutenção ·
# Finalizados) e a tela é ferramenta de trabalho. Aqui as colunas são URGÊNCIA e
# o cartão pode vir de qualquer domínio — chamado, preventiva, movimentação,
# orçamento. É leitura de manhã.
#
# Cada cartão tem as quatro camadas de leitura do protótipo:
#   etiqueta (tipo) · título · descrição · rodapé (avatar, registros, patrimônio)

GRUPOS_DECISAO = ["Técnico de Pós Venda", "Supervisor", "Gerente"]


def _pode_decidir(user):
    return user.is_superuser or user.groups.filter(name__in=GRUPOS_DECISAO).exists()


def _quem(pessoa_nome):
    """Iniciais para a pilha de avatares. Sem nome, devolve None e o cartão
    simplesmente não mostra avatar — melhor que um círculo com '?'."""
    nome = (pessoa_nome or "").strip()
    if not nome:
        return None
    partes = [p for p in nome.split() if p]
    if not partes:
        return None
    ini = partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")
    return {"ini": ini.upper(), "nome": nome}


def _quadro_inicio(request):
    """Monta as três colunas. Uma consulta por fonte, com `select_related` —
    o cartão mostra loja e setor, e sem isso seria uma consulta por cartão."""
    hoje = timezone.localdate()
    pode_decidir = _pode_decidir(request.user)

    precisa, andando, feito = [], [], []

    # ---------- coluna 1: precisa de você ------------------------------------
    # Decisões pendentes: só para quem PODE decidir. Mostrar para quem não pode
    # seria oferecer um botão que devolve 403.
    if pode_decidir:
        for t in (Transferencia.objects
                  .filter(status=Transferencia.Status.PENDENTE)
                  .select_related("baia_origem__setor__unidade",
                                  "baia_destino__setor__unidade")[:4]):
            o = t.baia_origem.setor.unidade.name if (t.baia_origem_id and t.baia_origem.setor_id and t.baia_origem.setor.unidade_id) else "—"
            d = t.baia_destino.setor.unidade.name if (t.baia_destino_id and t.baia_destino.setor_id and t.baia_destino.setor.unidade_id) else "—"
            precisa.append({
                "tag": "Decisão", "tag_cor": "crit",
                "titulo": "Transferência entre lojas",
                "desc": f"{o} → {d}. Aguarda autorização.",
                "quem": _quem(t.colaborador_destino or t.colaborador_saida),
                "pat": t.baia_destino.computador.patrimonio if (t.baia_destino_id and t.baia_destino.computador_id) else "",
                "url": "/parque/aprovacoes/",
            })
        for m in (MovimentacaoBaia.objects
                  .filter(status=MovimentacaoBaia.Status.PENDENTE)
                  .select_related("baia__setor__unidade", "setor_origem", "setor_destino")[:4]):
            o = m.setor_origem.nome if m.setor_origem_id else "—"
            d = m.setor_destino.nome if m.setor_destino_id else "—"
            precisa.append({
                "tag": "Decisão", "tag_cor": "crit",
                "titulo": "Mover baia entre setores",
                "desc": f"{o} → {d}. Aguarda autorização.",
                "quem": _quem(m.colaborador_nome),
                "pat": m.patrimonio or "",
                "url": "/parque/aprovacoes/",
            })

    # Preventiva atrasada: um cartão agregado com barra de proporção. Um cartão
    # por máquina viraria uma lista de 6+ itens iguais na coluna mais urgente.
    baias_prev = list(
        Baia.objects.filter(computador__isnull=False)
        .select_related("computador")
        .prefetch_related("reparos")
    )
    vencidas = [b for b in baias_prev if b.preventiva_status in ("vencida", "pendente")]
    if vencidas:
        precisa.append({
            "tag": "Vencida", "tag_cor": "warn",
            "titulo": "Preventiva atrasada",
            "desc": f"{len(vencidas)} de {len(baias_prev)} máquinas passaram do ciclo de {PREVENTIVA_DIAS} dias.",
            "barra": round(100 * len(vencidas) / max(1, len(baias_prev))),
            "barra_cor": "warn",
            "meta": f"{len(vencidas)} de {len(baias_prev)} no ciclo",
            "url": "/parque/preventiva/",
        })

    sem_tel = sum(1 for b in baias_prev if b.telemetria_status in ("inativo", "sem"))
    if sem_tel:
        precisa.append({
            "tag": "Sem sinal", "tag_cor": "crit",
            "titulo": "Sem telemetria",
            "desc": "Sem sinal do agente, o desempenho da máquina não é medido.",
            "meta": f"{sem_tel} máquinas",
            "url": "/parque/mapa-completo/",
        })

    # ---------- coluna 2: em andamento --------------------------------------
    for r in (Reparo.objects.filter(concluido_em__isnull=True)
              .select_related("baia__setor__unidade", "baia__computador",
                              "baia__colaborador", "tecnico")
              .annotate(n_reg=Count("registros"))
              .order_by("-data")[:8]):
        if r.realizar_cotacao:
            tag, cor = "Aguardando peça", "info"
        elif r.previsao_conclusao:
            tag, cor = "Em manutenção", "attn"
        else:
            tag, cor = r.get_tipo_display(), "attn"
        colab = r.baia.colaborador.full_name if (r.baia_id and r.baia.colaborador_id) else ""
        # A descrição do cartão. No protótipo cada cartão tinha uma frase de
        # verdade; a primeira versão punha "Sem descrição." em TODOS, porque os
        # chamados de exemplo vêm sem texto — e a coluna virou uma pilha de
        # cartões idênticos. Sem descrição, o cartão diz ONDE a máquina está,
        # que é o que diferencia um do outro e é informação útil.
        onde_r = ""
        if r.baia_id and r.baia.setor_id:
            uni_r = r.baia.setor.unidade.name if r.baia.setor.unidade_id else ""
            onde_r = "%s › %s › %s" % (uni_r, r.baia.setor.nome, r.baia.nome) if uni_r else r.baia.setor.nome
        prazo_r = ""
        if r.previsao_conclusao:
            faltam = (r.previsao_conclusao - hoje).days
            prazo_r = ("prazo vencido há %d dia(s)" % -faltam) if faltam < 0 else (
                "prazo hoje" if faltam == 0 else "prazo em %d dia(s)" % faltam)
        desc_r = (r.descricao or "").strip()[:110]
        if not desc_r:
            desc_r = " · ".join(x for x in (onde_r, prazo_r) if x) or "Sem detalhe registrado."
        elif prazo_r:
            desc_r = "%s · %s" % (desc_r, prazo_r)
        andando.append({
            "tag": tag, "tag_cor": cor,
            "titulo": r.titulo or r.get_tipo_display(),
            "desc": desc_r,
            "quem": _quem(colab),
            "quem2": _quem(r.tecnico.get_full_name() or r.tecnico.get_username()) if r.tecnico_id else None,
            "registros": r.n_reg,
            "pat": r.baia.computador.patrimonio if (r.baia_id and r.baia.computador_id) else "",
            "url": f"/parque/chamado-detalhe/{r.pk}/",
        })

    # ---------- coluna 3: feito hoje ----------------------------------------
    for r in (Reparo.objects.filter(concluido_em=hoje)
              .select_related("baia__setor__unidade", "baia__computador", "baia__colaborador")
              .annotate(n_reg=Count("registros"))[:8]):
        ehprev = r.tipo == Reparo.Tipo.PREVENTIVA
        onde = ""
        if r.baia_id and r.baia.setor_id:
            uni = r.baia.setor.unidade.name if r.baia.setor.unidade_id else ""
            onde = f"{uni} › {r.baia.setor.nome}"
        colab = r.baia.colaborador.full_name if (r.baia_id and r.baia.colaborador_id) else ""
        feito.append({
            "tag": "Concluído", "tag_cor": "ok",
            "titulo": r.titulo or ("Manutenção preventiva" if ehprev else r.get_tipo_display()),
            "desc": onde or "Concluído hoje.",
            "quem": _quem(colab),
            "registros": r.n_reg,
            "pat": r.baia.computador.patrimonio if (r.baia_id and r.baia.computador_id) else "",
            "url": f"/parque/chamado-detalhe/{r.pk}/",
        })

    for m in (MovimentacaoBaia.objects
              .filter(decidido_em__date=hoje, status=MovimentacaoBaia.Status.AUTORIZADA)
              .select_related("setor_origem", "setor_destino")[:4]):
        o = m.setor_origem.nome if m.setor_origem_id else "—"
        d = m.setor_destino.nome if m.setor_destino_id else "—"
        feito.append({
            "tag": "Autorizada", "tag_cor": "ok",
            "titulo": "Movimentação de baia",
            "desc": f"{o} → {d}.",
            "quem": _quem(m.colaborador_nome),
            "pat": m.patrimonio or "",
            "url": "/parque/mapa-completo/",
        })

    for t in (Transferencia.objects.filter(data_entrada=hoje)
              .select_related("baia_destino__setor__unidade")[:4]):
        d = t.baia_destino.setor.unidade.name if (t.baia_destino_id and t.baia_destino.setor_id and t.baia_destino.setor.unidade_id) else "—"
        feito.append({
            "tag": "Recebida", "tag_cor": "ok",
            "titulo": "Transferência entre lojas",
            "desc": f"Entrou em {d}.",
            "quem": _quem(t.colaborador_destino),
            "url": f"/parque/protocolo-transferencia/{t.pk}/",
        })

    for o in Orcamento.objects.filter(data_aprovacao=hoje)[:4]:
        feito.append({
            "tag": "Aprovado", "tag_cor": "ok",
            "titulo": "Orçamento aprovado",
            "desc": (o.titulo if hasattr(o, "titulo") else "") or "Aprovado hoje.",
            "url": "/orcamentos/",
        })

    return [
        {"key": "precisa", "titulo": "Precisa de você", "cor": "crit", "itens": precisa},
        {"key": "andando", "titulo": "Em andamento", "cor": "attn", "itens": andando},
        {"key": "feito", "titulo": "Feito hoje", "cor": "ok", "itens": feito},
    ]
