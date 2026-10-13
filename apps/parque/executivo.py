# -*- coding: utf-8 -*-
"""LEITURA EXECUTIVA — o dashboard que CONCLUI, para diretoria e RH.

Por que existe uma tela separada do Dashboard: a de lá responde as perguntas
de quem conserta (preventiva por mês, chamados por unidade, baias críticas).
Diretor pergunta dinheiro e risco; RH pergunta gente e processo. Eram três
telas disputando uma.

O QUE É DERIVADO, E POR QUE ISSO IMPORTA
----------------------------------------
Nada aqui é número digitado. A frase da manchete, a loja que aparece nela, o
multiplicador, a loja que ganha a borda acesa, as ações listadas — tudo sai da
consulta. É o que faz a tela continuar verdadeira amanhã.

O ponto delicado é a MANCHETE. Uma frase fixa ("o problema está em Centro")
mentiria no dia em que o parque melhorasse. Por isso são quatro moldes com uma
regra de escolha, em `leitura_do_dia()` — e a mesma disciplina vale para as
ações, que só entram quando a condição delas é verdade.

RÉGUAS (as do próprio sistema, não inventadas aqui)
---------------------------------------------------
· índice de desempenho 0–100 por máquina (`Baia.indice_desempenho`);
· classe: ≤35 Crítico · ≤55 Baixo · ≤75 Bom · acima Ótimo
  (`_classe_desempenho` em models.py);
· telemetria: `ativo` (coleta recente), `inativo`, `sem`.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import admin as dj_admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.urls import reverse

from apps.orgs.models import Location, Person
from apps.parque.models import Baia, Computador, Notebook, Reparo

# Quem entra: a resposta vem do registro único de telas
# (apps/orgs/acessos.py), que é o mesmo lugar que o menu consulta e que a tela
# /parque/acessos/ edita. A lista literal que morava aqui virou o PADRÃO do
# registro — e a duplicidade entre menu e view acabou.
TELA = "dashboard"

# Mantido só por compatibilidade com quem importava daqui.
GRUPOS_EXECUTIVO = ("Gerente", "Supervisor", "Visão total", "RH")

# Faixa de crítico, igual à do resto do sistema.
LIMITE_CRITICO = 35
LIMITE_BAIXO = 55
LIMITE_BOM = 75

# Uma loja "concentra" quando tem mais que isto vezes o esperado para o tamanho
# dela. 2,0 é o corte a partir do qual a diferença deixa de ser ruído: com 9
# críticas em 6 lojas, 1,5× ainda pode ser sorte.
CORTE_CONCENTRA = 2.0
# Abaixo desta cobertura de telemetria, qualquer conclusão sobre o índice é
# fraca — e a manchete passa a ser sobre isso.
CORTE_COBERTURA_CEGA = 0.5



def pode_ver(user):
    """Quem lê o Dashboard. Uma linha, porque a regra não mora mais aqui."""
    from apps.orgs.acessos import pode_ver_tela
    return pode_ver_tela(user, TELA)


# ===========================================================================
# COLETA
# ===========================================================================
def _baias():
    """As baias com tudo que o índice precisa, sem N+1.

    `indice_desempenho` toca computador, notebook e os reparos da baia. Sem o
    select/prefetch isto viram 140 × 3 consultas.
    """
    return (
        Baia.objects
        .select_related("setor__unidade", "computador", "notebook")
        .prefetch_related("reparos")
    )


def _por_loja():
    """[{nome, postos, ocupados, criticas, ...}] ordenado por postos (desc)."""
    lojas = {}
    for b in _baias():
        nome = (b.setor.unidade.name
                if (b.setor_id and b.setor.unidade_id) else "Sem loja")
        d = lojas.setdefault(nome, {
            "nome": nome, "postos": 0, "ocupados": 0, "criticas": 0,
            # o id da unidade viaja junto porque e' ele que faz o retangulo
            # do treemap ser um LINK para o parque daquela loja
            "uid": (b.setor.unidade_id if (b.setor_id and b.setor.unidade_id) else None),
        })
        d["postos"] += 1
        if b.esta_vazia:
            continue
        d["ocupados"] += 1
        if (b.indice_desempenho or 0) <= LIMITE_CRITICO:
            d["criticas"] += 1

    lista = sorted(lojas.values(), key=lambda d: -d["postos"])
    total_postos = sum(d["postos"] for d in lista) or 1
    total_crit = sum(d["criticas"] for d in lista)

    for d in lista:
        # ESPERADO: a fatia da loja no parque vezes o total de críticas. É o que
        # transforma "Centro tem 5" em "Centro tem 3,9× o que o tamanho previa".
        d["esperado"] = d["postos"] / total_postos * total_crit
        d["vezes"] = (d["criticas"] / d["esperado"]) if d["esperado"] else 0
        d["livres"] = d["postos"] - d["ocupados"]
        # concentração por posto: é ela que decide o tom no treemap
        d["conc"] = (d["criticas"] / d["postos"]) if d["postos"] else 0
        d["cheia"] = d["livres"] == 0
        d["url"], d["dica"] = _destino_loja(d)
    return lista, total_postos, total_crit


def _destino_loja(d):
    """Para onde o clique na loja leva.

    O clique segue o que o retangulo DIZ. Se ele mostra criticas, abre as
    criticas DAQUELA loja; se mostra zero, abre o parque dela. Mandar para uma
    lista vazia e' o jeito mais rapido de a pessoa achar que a tela mentiu.
    """
    if not d["uid"]:
        return reverse("parque_mapa_completo"), "abrir o mapa do parque"
    if d["criticas"]:
        return (reverse("parque_mapa_criticos_unidade", args=[d["uid"]]),
                "ver as %d criticas de %s" % (d["criticas"], d["nome"]))
    return (reverse("parque_mapa", args=[d["uid"]]),
            "abrir o parque de %s" % d["nome"])


def _estado_do_parque():
    """Contagem por faixa do índice, sobre as baias OCUPADAS."""
    faixas = {"Crítico": 0, "Baixo": 0, "Bom": 0, "Ótimo": 0}
    for b in _baias():
        if b.esta_vazia:
            continue
        n = b.indice_desempenho
        if n is None:
            continue
        if n <= LIMITE_CRITICO:
            faixas["Crítico"] += 1
        elif n <= LIMITE_BAIXO:
            faixas["Baixo"] += 1
        elif n <= LIMITE_BOM:
            faixas["Bom"] += 1
        else:
            faixas["Ótimo"] += 1
    # Cada faixa leva a uma tela: a crítica para a lista de críticas, as outras
    # para o mapa por índice — que é onde se vê máquina por máquina.
    ordem = [
        ("Crítico", "crit", faixas["Crítico"], reverse("parque_mapa_criticos")),
        ("Baixo", "warn", faixas["Baixo"], reverse("parque_mapa_score")),
        ("Bom", "ok", faixas["Bom"], reverse("parque_mapa_score")),
        ("Ótimo", "ok", faixas["Ótimo"], reverse("parque_mapa_score")),
    ]
    return [{"nome": n, "cor": c, "n": v, "url": u} for n, c, v, u in ordem]


def _cobertura_telemetria():
    """(com_leitura, total_ativos, fração) — o agente coleta, ou não."""
    comp = Computador.objects.count()
    nb = Notebook.objects.count()
    total = comp + nb
    vivos = sum(
        1 for c in Computador.objects.only("tel_visto_em")
        if c.telemetria_status == "ativo"
    ) + sum(
        1 for n in Notebook.objects.only("tel_visto_em")
        if n.telemetria_status == "ativo"
    )
    return vivos, total, (vivos / total if total else 0)


def _pendencias():
    """O que a tela AINDA não mede, com a contagem exata do que falta.

    Cada linha nomeia o campo e diz quantos registros estão vazios. Sem isso a
    seção seria uma lista de desejos; com isso é uma fila de trabalho.
    """
    rep_total = Reparo.objects.count()
    rep_custo = Reparo.objects.filter(custo__gt=0).count()
    soma = Reparo.objects.aggregate(s=Sum("custo"))["s"] or 0

    ativos = Computador.objects.count() + Notebook.objects.count()
    com_valor = (Computador.objects.filter(valor_compra__gt=0).count()
                 + Notebook.objects.filter(valor_compra__gt=0).count())

    pessoas = Person.objects.count()
    com_desl = Person.objects.exclude(data_desligamento=None).count()

    def pc(n, de):
        return "%.2f" % (max(n / de * 100, 0.5) if de else 0)

    return [
        {
            "titulo": "Custo do reparo",
            "n": rep_custo, "de": rep_total, "pc": pc(rep_custo, rep_total),
            "campo": "Reparo.custo",
            "nota": ("Sem ele não há custo por loja, nem a conta que decide se "
                     "ainda vale consertar a máquina."
                     + (" R$ %s lançados até agora." % _reais(soma) if soma else "")),
        },
        {
            "titulo": "Valor e data de compra",
            "n": com_valor, "de": ativos, "pc": pc(com_valor, ativos),
            "campo": "valor_compra e data_compra",
            "nota": ("Sem eles não há idade do parque, depreciação nem plano de "
                     "troca dos próximos 12 meses."),
        },
        {
            "titulo": "Data de desligamento",
            "n": com_desl, "de": pessoas, "pc": pc(com_desl, pessoas),
            "campo": "Person.data_desligamento",
            "nota": ("É a condição que a diretoria pôs na ata: corte de acesso e "
                     "devolução do equipamento no mesmo dia."),
        },
    ]


def _reais(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ===========================================================================
# A MANCHETE — quatro moldes e uma regra
# ===========================================================================
def leitura_do_dia(lojas, total_postos, total_crit, cobertura):
    """A frase que abre a tela, escolhida pela situação.

    A ordem das perguntas é a ordem da importância:

    1. o índice é confiável? Se a telemetria cobre menos da metade do parque,
       falar de "máquinas críticas" é falar de estimativa — e é ISSO que tem de
       aparecer primeiro, senão a tela empresta autoridade a um número fraco;
    2. existe crítica? Se não, a notícia é essa;
    3. as críticas estão CONCENTRADAS numa loja? Aí há um lugar para atacar;
    4. senão, estão espalhadas — e a conclusão é justamente que não há atalho.
    """
    pior = max(lojas, key=lambda d: d["vezes"]) if lojas else None

    if cobertura < CORTE_COBERTURA_CEGA:
        pc = round(cobertura * 100)
        return {
            "tom": "atencao",
            "titulo": "O índice está estimado em %d%% do parque." % (100 - pc),
            "linhas": [
                "Só <b>%d%%</b> das máquinas mandam telemetria. Nas outras o índice "
                "vem da ficha técnica, sem leitura real de temperatura, disco ou "
                "memória." % pc,
                "Instalar o agente é o que dá base para todo o resto desta tela — "
                "inclusive para as %d máquinas hoje classificadas como críticas."
                % total_crit,
            ],
            "loja_foco": pior["nome"] if pior else None,
        }

    if not total_crit:
        return {
            "tom": "bom",
            "titulo": "Nenhuma máquina em estado crítico.",
            "linhas": [
                "As %d máquinas em uso estão todas acima da faixa crítica." %
                sum(d["ocupados"] for d in lojas),
                "O que pesa agora é manter a preventiva em dia e fechar a "
                "cobertura do índice.",
            ],
            "loja_foco": None,
        }

    if pior and pior["vezes"] >= CORTE_CONCENTRA:
        fatia = pior["postos"] / total_postos * 100
        parte = pior["criticas"] / total_crit * 100
        maior = max(lojas, key=lambda d: d["postos"])
        linhas = [
            "%s tem <b>%d%% do parque</b> e <b>%d das %d</b> máquinas críticas — "
            "<b>%s× o esperado</b> para o tamanho dela."
            % (pior["nome"], round(fatia), pior["criticas"], total_crit,
               _vez(pior["vezes"])),
        ]
        if maior["nome"] != pior["nome"]:
            linhas.append(
                "%s, com <b>%d%% do parque</b>, tem <b>%d</b>."
                % (maior["nome"], round(maior["postos"] / total_postos * 100),
                   maior["criticas"])
            )
        linhas.append(
            "Atacar %s resolve <b>%d%%</b> do problema numa visita."
            % (pior["nome"], round(parte))
        )
        return {
            "tom": "atencao",
            "titulo": "O problema não está espalhado: está em %s." % pior["nome"],
            "linhas": linhas,
            "loja_foco": pior["nome"],
        }

    return {
        "tom": "atencao",
        "titulo": "As %d críticas estão espalhadas: não há uma loja para atacar."
                  % total_crit,
        "linhas": [
            "Nenhuma loja passa de %s× o esperado para o tamanho dela — a pior "
            "está em %s×." % (_vez(CORTE_CONCENTRA), _vez(pior["vezes"] if pior else 0)),
            "Sem concentração, o caminho é máquina por máquina, pelo índice, e "
            "não visita por loja.",
        ],
        "loja_foco": None,
    }


def _vez(v):
    return ("%.1f" % v).replace(".", ",")


# ===========================================================================
# AS AÇÕES — cada uma com a sua condição
# ===========================================================================
def acoes(lojas, total_crit, cobertura, sem_leitura, orcamentos_pendentes):
    """Só entra o que é verdade agora.

    Lista fixa vira mentira no primeiro dia em que a condição deixa de valer —
    e o diretor perde a confiança na tela inteira por causa de uma linha.
    """
    out = []
    pior = max(lojas, key=lambda d: d["vezes"]) if lojas else None

    if pior and pior["vezes"] >= CORTE_CONCENTRA and pior["criticas"]:
        out.append({
            "n": pior["criticas"],
            "titulo": "Visita técnica a %s" % pior["nome"],
            "texto": "Resolve %d%% das críticas da rede numa loja só"
                     % round(pior["criticas"] / total_crit * 100),
            # /parque/mapa-situacao/critico/ NUNCA EXISTIU: os status daquela
            # tela são tem_pc, sem_pc, notebook e defeito, e qualquer outro cai
            # em Http404. Link morto no cartão que a diretoria mais clica.
            # O destino certo é a lista de críticas — desta loja.
            "url": pior["url"],
        })

    if orcamentos_pendentes:
        out.append({
            "n": orcamentos_pendentes,
            "titulo": "Decidir os orçamentos parados",
            "texto": "Enquanto aguarda, a máquina fica fora",
            "url": "/orcamentos/",
        })

    if cobertura < 0.8 and sem_leitura:
        out.append({
            "n": sem_leitura,
            "titulo": "Instalar o agente no resto do parque",
            "texto": "Sem ele o índice é estimativa em %d%% das máquinas"
                     % round((1 - cobertura) * 100),
            "url": "/parque/agente/",
        })

    if total_crit and not (pior and pior["vezes"] >= CORTE_CONCENTRA):
        out.append({
            "n": total_crit,
            "titulo": "Abrir a lista das máquinas críticas",
            "texto": "Sem concentração por loja, o corte é por máquina",
            "url": reverse("parque_mapa_criticos"),
        })
    return out


# ===========================================================================
# A VIEW
# ===========================================================================
@staff_member_required
def leitura_executiva(request):
    from apps.orgs.acessos import exigir
    exigir(request.user, TELA)

    lojas, total_postos, total_crit = _por_loja()
    ocupados = sum(d["ocupados"] for d in lojas)
    livres = total_postos - ocupados
    vivos, total_ativos, cobertura = _cobertura_telemetria()

    try:
        from apps.orcamentos.models import Orcamento
        orc_pend = Orcamento.objects.filter(status="pendente").count()
    except Exception:
        orc_pend = 0

    leitura = leitura_do_dia(lojas, total_postos, total_crit, cobertura)
    lista_acoes = acoes(lojas, total_crit, cobertura,
                        total_ativos - vivos, orc_pend)

    # Escala dos gráficos: o maior valor manda, e a marca do esperado usa a
    # MESMA escala da barra — senão o traço vira enfeite.
    max_crit = max([d["criticas"] for d in lojas] + [d["esperado"] for d in lojas] + [1])
    # ARMADILHA MEDIDA. Estas porcentagens vão para dentro de `style="width:"`,
    # e no template elas passavam por `|floatformat:1` — que RESPEITA a
    # localização: em pt-BR devolve "40,0". `width: 40,0%` é CSS inválido, o
    # navegador descarta a declaração e a barra fica com largura ZERO. O
    # gráfico inteiro aparecia vazio. Formatar aqui, com ponto, resolve na
    # origem (e `|unlocalize` no template resolveria o sintoma).
    def pc(v):
        return "%.2f" % v

    for d in lojas:
        d["pc_barra"] = pc(d["criticas"] / max_crit * 100)
        d["pc_esperado"] = pc(d["esperado"] / max_crit * 100)
        d["pc_ocupado"] = pc((d["ocupados"] / d["postos"] * 100) if d["postos"] else 0)
        d["esperado_txt"] = _vez(d["esperado"])
        d["vezes_txt"] = _vez(d["vezes"])
        # O comparativo em PALAVRAS, e só quando ele diz algo: "esperado 1" ao
        # lado de "5" explica sozinho. O `3,9×` que estava aqui antes exigia que
        # o leitor soubesse o que era o esperado — e não havia onde ler isso.
        d["esperado_int"] = int(round(d["esperado"]))
        d["mostra_esperado"] = (
            d["esperado_int"] != d["criticas"]
            and (d["vezes"] >= 1.5 or d["vezes"] <= 0.7)
            and (d["criticas"] or d["esperado_int"])
        )
        d["destaque"] = (d["vezes"] >= CORTE_CONCENTRA and d["criticas"] > 0)

    estado = _estado_do_parque()
    max_estado = max([e["n"] for e in estado] + [1])
    for e in estado:
        e["pc"] = pc(e["n"] / max_estado * 100)

    # RH
    pessoas = Person.objects.count()
    nb_com_pessoa = Notebook.objects.exclude(colaborador=None).count()

    # O treemap e' desenhado no navegador (o algoritmo squarified precisa medir
    # a caixa), entao as lojas viajam tambem como JSON — so o que o desenho usa.
    lojas_js = [
        {"nome": d["nome"], "postos": d["postos"], "criticas": d["criticas"],
         "conc": round(d["conc"], 6), "vezes": round(d["vezes"], 2),
         # o clique segue o que o retângulo DIZ: as críticas daquela loja, ou o
         # parque dela quando ela tem zero crítica (ver _destino_loja)
         "url": d["url"], "dica": d["dica"]}
        for d in lojas
    ]

    ctx = {
        **dj_admin.site.each_context(request),
        # O nome visível é "Dashboard" (é como a casa chama); o módulo e a
        # URL continuam leitura-executiva, para não quebrar link guardado.
        "title": "Dashboard",
        "lojas_js": lojas_js,
        "leitura": leitura,
        "lojas": lojas,
        "estado": estado,
        "acoes": lista_acoes,
        "pendencias": _pendencias(),
        "total_postos": total_postos,
        "ocupados": ocupados,
        "livres": livres,
        "pc_ocupacao": round(ocupados / total_postos * 100) if total_postos else 0,
        "total_crit": total_crit,
        "total_ativos": total_ativos,
        "n_computadores": Computador.objects.count(),
        "n_notebooks": Notebook.objects.count(),
        "tel_vivos": vivos,
        "tel_sem": total_ativos - vivos,
        "pc_cobertura": round(cobertura * 100),
        "orc_pend": orc_pend,
        "pessoas": pessoas,
        "nb_com_pessoa": nb_com_pessoa,
        "nb_total": Notebook.objects.count(),
        "desligados": Person.objects.exclude(data_desligamento=None).count(),
    }
    return render(request, "parque/executivo.html", ctx)
