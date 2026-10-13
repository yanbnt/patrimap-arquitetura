# -*- coding: utf-8 -*-
"""MURAL DO PARQUE — a tela de Registros virou feed.

O QUE ELA SUBSTITUI
-------------------
Era um calendário de seis semanas com três fontes (preventiva concluída,
transferência de loja, movimentação de baia). No mês atual isso dava UM
registro para a tela inteira, e o sistema guardava dez tipos de acontecimento
que a tela ignorava. Aqui todo acontecimento é um post: quem fez, o que
escreveu, quem autorizou, qual máquina, o que ainda falta — e para onde clicar
dentro do sistema.

Junto com ela morrem dois itens de menu:
  · "Usuários online"  -> a faixa de rostos no alto (AtividadeUsuario)
  · "Logs"             -> a aba "Acessos e ações" (LogAcesso + admin.LogEntry)

ACESSO — A PARTE QUE NÃO PODE ERRAR
-----------------------------------
O mural junta dez fontes. Se ele mostrasse tudo para quem abre a tela, seria
uma porta nova: o estagiário passaria a ver termo e documento, que hoje só o
Arquivo mostra. A regra aqui é a única que não muda a visão de ninguém:

    um acontecimento só entra no feed se a pessoa PODE ABRIR A TELA que já o
    mostrava hoje.

Isso vem de apps/orgs/acessos.py — o mesmo registro que o menu consulta. Se
amanhã o Arquivo virar aberto, o mural acompanha sozinho. As duas faixas novas
(presença e logs) seguem as telas "online" e "logs", que continuam no
registro exatamente com os grupos que tinham.

O QUE É NOVO NO BANCO
---------------------
Só a conversa: ComentarioEvento (texto + foto do serviço) e MarcaEvento (quem
assumiu, quem acompanha). Autor, texto escrito e trilha de quem-pediu-e-quem-
autorizou já estavam no banco.
"""
import re
from collections import Counter
from datetime import timedelta

from django.contrib import admin as dj_admin
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.orgs.acessos import exigir, pode_ver_tela
from apps.orgs.models import AtividadeUsuario, Location, LogAcesso

from .models import (ComentarioEvento, Computador, DocumentoEquipamento,
                     EnvioAutorizada, MarcaEvento, MensagemDireta,
                     MovimentacaoBaia, MovimentacaoPeca, Notebook,
                     PublicacaoMural, Reparo, Tarefa, TermoResponsabilidade,
                     Transferencia, TransferenciaNotebook)
from .utils import id_ou_nada

try:
    from apps.orcamentos.models import Orcamento
except Exception:  # pragma: no cover - app opcional
    Orcamento = None

TELA = "registros"
DOC = DocumentoEquipamento.Tipo
U = get_user_model()

# Cada tipo de post aponta para a tela que JÁ o mostrava. É isto que garante
# que o mural não abre porta nova — ver o docstring.
TELA_DO_TIPO = {
    # A publicacao e' escrita DENTRO do mural: quem abre o mural ve. Nao ha'
    # tela de origem para consultar, e ela nao expoe dado de outra tela.
    "aviso": "registros",
    "chamado": "chamados",
    "chamado_fim": "chamados",
    "preventiva": "preventiva",
    "tarefa": "preventiva",
    "tarefa_aberta": "preventiva",
    "transferencia": "transferencias",
    "movimentacao": "mapa",
    "peca": "estoque",
    "autorizada": "autorizadas",
    "termo": "arquivo",
    "documento": "arquivo",
    "orcamento": "orcamentos",
}

TIPOS = [
    ("aviso", "Publicação", "balao"),
    ("chamado", "Chamado", "handyman"),
    ("chamado_fim", "Chamado concluído", "check"),
    ("preventiva", "Preventiva", "event_repeat"),
    ("transferencia", "Transferência", "swap"),
    ("movimentacao", "Movimentação de baia", "grid"),
    ("peca", "Peça", "inventory"),
    ("autorizada", "Autorizada", "tools"),
    ("termo", "Termo", "assina"),
    ("documento", "Documento", "doc"),
    ("tarefa", "Tarefa concluída", "task"),
    ("tarefa_aberta", "Tarefa aberta", "alerta"),
    ("orcamento", "Orçamento", "money"),
]

# Os rótulos que a tela mostra. Sem invenção minha: é o que a pessoa diria.
PRECISA = [
    ("papel", "Falta o documento"),
    ("assinatura", "Termo sem assinatura"),
    ("conclusao", "Em aberto"),
    ("decisao", "Esperando decisão"),
    ("revisao", "Foi negado"),
]

# Modelos cuja alteração é assunto de segurança, não de rotina.
SENSIVEL = {"user", "group", "permission", "telagrupo", "perfilusuario"}


# --------------------------------------------------------------- utilidades
def _dia(d):
    return d.strftime("%Y-%m-%d") if d else ""


def _hora(d):
    return d.strftime("%H:%M") if hasattr(d, "hour") else ""


def _nome(x):
    if not x:
        return ""
    for a in ("get_full_name", "full_name", "name", "nome"):
        v = getattr(x, a, None)
        if callable(v):
            v = v()
        if v:
            return str(v).strip()
    return str(x).strip()


def _loja(baia):
    try:
        return baia.setor.unidade.name
    except Exception:
        return ""


def _idade(d, hoje):
    if not d:
        return None
    d = getattr(d, "date", lambda: d)() if hasattr(d, "hour") else d
    try:
        return (hoje - d).days
    except TypeError:
        return None


def _passo(quem, oque, d):
    if not quem:
        return None
    return {"quem": quem, "oque": oque, "quando": _dia(d), "hora": _hora(d)}


def _iniciais(nome):
    partes = [x for x in str(nome or "").split() if x]
    if not partes:
        return "?"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


def tag(texto):
    """Normaliza uma tag: sem acento, minúscula, espaço vira hífen.

    "#Movimentação de PC" e "#movimentacao-de-pc" têm que ser a MESMA tag, ou
    o filtro vira loteria e a lista de temas enche de repetido.
    """
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:32]


# Palavra que não ajuda a achar nada: "Outro" é o valor de escape de metade
# dos choices, e uma tag #outro em 20 posts diferentes não agrupa coisa alguma.
TAG_INUTIL = {"outro", "outros", "na", "nao-informado", "n-a", "-"}
# Ligação que não carrega significado numa tag curta.
TAG_LIGACAO = {"de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos",
               "nas", "entre", "para", "por", "com", "a", "o", "ou"}


def _encurta(bruto):
    """Rótulo de sistema vira tag curta; tag já escrita como slug passa direto.

    `get_tipo_display()` devolve frase — "Trocar computadores entre baias",
    "Score de desempenho baixo" — e frase inteira não serve de hashtag. A
    regra: se tem espaço, parêntese ou barra, é rótulo humano, então tira as
    ligações e fica com as duas primeiras palavras. Se não tem, é literal meu
    ("entre-lojas", "sem-documento") e não se mexe — senão "entre-lojas"
    viraria "lojas", porque "entre" é ligação.
    """
    texto = str(bruto or "")
    if " " not in texto and "(" not in texto and "/" not in texto:
        return tag(texto)
    palavras = [p for p in tag(texto).split("-") if p and p not in TAG_LIGACAO]
    return "-".join(palavras[:2])


def _tags(*partes):
    """Junta, normaliza, encurta e tira repetido, mantendo a ordem de entrada."""
    fora = []
    for x in partes:
        for pedaco in (x if isinstance(x, (list, tuple, set)) else [x]):
            t = _encurta(pedaco)
            if t and t not in fora and t not in TAG_INUTIL:
                fora.append(t)
    return fora[:8]


def _tag_maquina(patrimonio):
    """NB-0029 -> notebook, PC-B0031 -> pc. O prefixo do patrimônio é a única
    pista de tipo de equipamento que serve para os dez modelos."""
    pat = (patrimonio or "").upper()
    if pat.startswith("NB"):
        return "notebook"
    if pat.startswith("PC"):
        return "pc"
    return ""


def _tags_do_texto(texto):
    """As tags que a pessoa escreveu com # no texto da publicação."""
    fora = []
    for bruto in re.findall(r"#([0-9A-Za-zÀ-ÿ_-]{2,32})", texto or ""):
        t = tag(bruto)
        if t and t not in fora:
            fora.append(t)
    return fora[:8]


def _chave_nome(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _patrimonios(teto=400):
    """Os patrimônios que a publicação pode citar. Serve o autocomplete: sem
    ele a pessoa digita PC-CG011 (um zero a menos) e a publicação não entra na
    ficha de máquina nenhuma."""
    fora = []
    for M in (Computador, Notebook):
        fora += [x for x in M.objects.exclude(patrimonio="").exclude(
            patrimonio=None).values_list("patrimonio", flat=True)]
    return sorted({x for x in fora if x})[:teto]


def _mencoes(texto):
    """Quem foi chamado com @ no texto.

    Casa pelo nome completo e pelo usuário — "@Igor Martins" e "@yan" dão a
    mesma pessoa. E `@all` (ou `@todos`) chama o time inteiro: quem escreve
    "amanhã a rede cai" não vai citar treze nomes um por um.

    Só usuário ATIVO entra. Marcar quem saiu da empresa enche a tabela de
    menção com gente que nunca vai abrir a tela.
    """
    if not texto or "@" not in texto:
        return []
    baixo = texto.lower()
    ativos = list(U.objects.filter(is_active=True))
    if "@all" in baixo or "@todos" in baixo:
        return ativos
    achados = []
    for u in ativos:
        nome = _nome(u)
        for alvo in filter(None, [nome, u.get_username()]):
            if ("@" + alvo).lower() in baixo:
                achados.append(u)
                break
    return achados


# ------------------------------------------------------------- o feed em si
def montar_eventos(user):
    """Todos os acontecimentos que ESTE usuário já podia ver, como posts."""
    hoje = timezone.localdate()
    liberado = {t for t, tela in TELA_DO_TIPO.items() if pode_ver_tela(user, tela)}
    eventos = []

    def add(**kw):
        if kw["tipo"] not in liberado or not kw.get("data"):
            return
        kw.setdefault("papel", None)
        kw.setdefault("status", "")
        kw.setdefault("maquina", "")
        kw.setdefault("maquinas", [])
        kw.setdefault("onde", "")
        kw.setdefault("autor", "")
        kw.setdefault("fala", "")
        kw.setdefault("precisa", "")
        kw.setdefault("lote", 1)
        kw.setdefault("hora", "")
        # As duas tags transversais entram aqui: o tipo de equipamento (pelo
        # prefixo do patrimônio) e a pendência de documento.
        kw["tags"] = _tags(kw.pop("_tags", []),
                           _tag_maquina(kw.get("maquina")),
                           "sem-documento" if kw.get("precisa") in
                           ("papel", "assinatura") else "")
        kw["trilha"] = [p for p in kw.get("trilha") or [] if p]
        kw["dias"] = _idade(kw.pop("_d", None), hoje)
        eventos.append(kw)

    # ------------------------------------------------------------ chamados
    if "chamado" in liberado:
        for r in Reparo.objects.select_related(
                "baia__setor__unidade", "baia__computador", "notebook", "tecnico"):
            # O patrimônio do chamado está no COMPUTADOR da baia, não na baia.
            maq = ""
            if r.baia_id and getattr(r.baia, "computador_id", None):
                maq = getattr(r.baia.computador, "patrimonio", "") or ""
            if not maq and r.baia_id:
                maq = getattr(r.baia, "patrimonio", "") or ""
            if not maq and r.notebook_id:
                maq = r.notebook.patrimonio or ""
            onde = _loja(r.baia) if r.baia_id else ""
            abriu = r.data or getattr(r, "created_at", None)
            tec = _nome(r.tecnico)
            aberto = not r.concluido_em
            # "atrasado" é TAG, não tipo novo: o feed já sabe filtrar por tema
            # (est.tema), então a faixa do topo pode apontar para cá sem que se
            # invente mecanismo. Sem entrada nova no TELA_DO_TIPO — o post é o
            # mesmo chamado de sempre, com um rótulo a mais.
            atrasado = (aberto and r.data
                        and r.data < hoje - timedelta(days=ATRASO_DIAS))
            add(id="rep%s" % r.pk, tipo="chamado", data=_dia(abriu), _d=abriu,
                _tags=["chamado", r.get_tipo_display(),
                       "em-aberto" if aberto else "concluido",
                       "atrasado" if atrasado else "",
                       (r.get_peca_display() if r.peca else "")],
                titulo=(r.titulo or r.get_tipo_display()),
                fala=(r.descricao or "").strip(), onde=onde, autor=tec, maquina=maq,
                status="Em aberto" if aberto else "Concluído",
                precisa="conclusao" if aberto else "",
                trilha=[_passo(tec or "equipe de TI", "abriu o chamado", abriu),
                        _passo(tec, "concluiu", r.concluido_em) if r.concluido_em else None],
                url="/parque/chamado-detalhe/%s/" % r.pk)
            if r.concluido_em:
                fim = ("preventiva" if r.tipo == Reparo.Tipo.PREVENTIVA
                       else "chamado_fim")
                add(id="repf%s" % r.pk, tipo=fim, data=_dia(r.concluido_em),
                    _tags=["chamado" if fim == "chamado_fim" else "preventiva",
                           "concluido", r.get_tipo_display()],
                    _d=r.concluido_em,
                    titulo=("Preventiva concluída" if fim == "preventiva"
                            else "Chamado concluído: " + (r.titulo or "")),
                    fala=(r.descricao or "").strip(), onde=onde, autor=tec,
                    maquina=maq, status="Concluído",
                    trilha=[_passo(tec, "concluiu o serviço", r.concluido_em)],
                    url="/parque/chamado-detalhe/%s/" % r.pk)

    # ----------------------------------------------- transferência de loja
    if "transferencia" in liberado:
        for t in Transferencia.objects.select_related(
                "computador", "registrado_por", "baia_origem__setor__unidade",
                "baia_destino__setor__unidade").prefetch_related("documentos"):
            o = _loja(t.baia_origem) if t.baia_origem_id else "sem loja"
            d = _loja(t.baia_destino) if t.baia_destino_id else "sem loja"
            tem = any(x.tipo == DOC.PROTOCOLO for x in t.documentos.all())
            quem = _nome(t.registrado_por)
            dt = t.data_entrada or t.data_saida
            add(id="tr%s" % t.pk, tipo="transferencia", data=_dia(dt), _d=dt,
                _tags=["transferencia", "entre-lojas", "externa"],
                titulo="Transferência de loja: %s → %s" % (o, d),
                onde=d, autor=quem,
                maquina=(t.computador.patrimonio if t.computador_id else ""),
                precisa="" if tem else "papel",
                trilha=[_passo(quem, "registrou a transferência", dt)],
                url="/parque/protocolo-transferencia/%s/" % t.pk,
                papel={"nome": "Protocolo de transferência", "tem": tem,
                       "alvo": "tr%s" % t.pk, "doc": DOC.PROTOCOLO})

        for t in TransferenciaNotebook.objects.select_related(
                "notebook", "unidade_destino", "registrado_por",
                "decidido_por").prefetch_related("documentos"):
            tem = any(x.tipo == DOC.PROTOCOLO for x in t.documentos.all())
            quem = _nome(t.registrado_por)
            dec = _nome(t.decidido_por)
            add(id="tn%s" % t.pk, tipo="transferencia", data=_dia(t.data), _d=t.data,
                _tags=["transferencia", "notebook", "entre-lojas", "externa"],
                titulo="Transferência de notebook para %s" % (
                    t.unidade_destino.name if t.unidade_destino_id else "sem loja"),
                fala=(t.specs or "").strip(),
                onde=(t.unidade_destino.name if t.unidade_destino_id else ""),
                autor=quem or (t.usuario or ""),
                maquina=(t.notebook.patrimonio if t.notebook_id else ""),
                status=t.get_status_display(),
                precisa="" if tem else "papel",
                trilha=[_passo(quem, "registrou o pedido", t.data),
                        _passo(dec, "decidiu", t.data)],
                url="/parque/protocolo-notebook/%s/" % t.pk,
                papel={"nome": "Protocolo de transferência", "tem": tem,
                       "alvo": "tn%s" % t.pk, "doc": DOC.PROTOCOLO})

    # ----------------------------------------------- movimentação de baia
    if "movimentacao" in liberado:
        for m in MovimentacaoBaia.objects.select_related(
                "baia__setor__unidade", "setor_origem", "setor_destino",
                "solicitante", "decidido_por"):
            ped = _nome(m.solicitante) or (m.colaborador_nome or "")
            dec = _nome(m.decidido_por)
            negada = m.status == MovimentacaoBaia.Status.NEGADA
            add(id="mb%s" % m.pk, tipo="movimentacao", data=_dia(m.criado_em),
                _tags=["movimentacao-de-baia", m.get_tipo_display(),
                       "negada" if negada else "autorizada"],
                hora=_hora(m.criado_em), _d=m.criado_em,
                titulo=m.get_tipo_display(), fala=(m.observacao or "").strip(),
                onde=_loja(m.baia) if m.baia_id else "",
                autor=ped, maquina=(m.patrimonio or ""),
                status=m.get_status_display(),
                precisa="revisao" if negada else "",
                trilha=[_passo(ped, "pediu a movimentação", m.criado_em),
                        _passo(dec, ("negou — %s" % (m.motivo or "sem motivo registrado"))
                               if negada else "autorizou", m.decidido_em)],
                url="/parque/mapa-completo/")

    # ------------------------------------------------ movimentação de peça
    if "peca" in liberado:
        for p in MovimentacaoPeca.objects.select_related(
                "unidade_origem", "unidade_destino", "por_usuario"):
            quem = _nome(p.por_usuario)
            add(id="mp%s" % p.pk, tipo="peca", data=_dia(p.em), hora=_hora(p.em),
                _tags=["peca", p.get_tipo_display()],
                _d=p.em, titulo="Peça movimentada: %s" % p.get_tipo_display(),
                fala="%s × %s" % (p.quantidade, (p.descricao or "").strip()),
                onde=(p.unidade_destino.name if p.unidade_destino_id else
                      (p.unidade_origem.name if p.unidade_origem_id else "")),
                autor=quem,
                trilha=[_passo(quem, "registrou a movimentação", p.em)],
                url="/parque/tabela-pecas/")

    # ---------------------------------------------------- envio à autorizada
    if "autorizada" in liberado:
        for e in EnvioAutorizada.objects.select_related(
                "autorizada", "computador", "notebook",
                "registrado_por").prefetch_related("documentos"):
            tem = any(x.tipo == DOC.LAUDO for x in e.documentos.all())
            quem = _nome(e.registrado_por)
            add(id="ea%s" % e.pk, tipo="autorizada", data=_dia(e.criado_em),
                _tags=["autorizada", "externa", "reparo",
                       "sem-conserto" if e.sem_conserto else ""],
                hora=_hora(e.criado_em), _d=e.criado_em,
                titulo="Envio à autorizada: %s" % (
                    e.autorizada.nome if e.autorizada_id else ""),
                fala=(e.problema or "").strip(),
                onde=(e.autorizada.cidade if e.autorizada_id else ""),
                autor=quem, maquina=(e.patrimonio or ""),
                status=e.get_status_display(),
                precisa="" if tem else "papel",
                trilha=[_passo(quem, "enviou o equipamento", e.criado_em)],
                url="/parque/autorizadas/envio/%s/" % e.pk,
                papel={"nome": "Laudo técnico", "tem": tem,
                       "alvo": "ea%s" % e.pk, "doc": DOC.LAUDO})

    # -------------------------------------------------------------- termos
    if "termo" in liberado:
        for t in TermoResponsabilidade.objects.select_related(
                "notebook", "colaborador", "criado_por"):
            assinado = t.status == TermoResponsabilidade.Status.ASSINADO
            emissor = _nome(t.criado_por)
            pessoa = (t.colaborador_nome or _nome(t.colaborador))
            add(id="tm%s" % t.pk, tipo="termo", data=_dia(t.criado_em),
                _tags=["termo", t.get_tipo_display(),
                       "assinado" if assinado else "sem-assinatura"],
                hora=_hora(t.criado_em), _d=t.criado_em,
                titulo="Termo de %s emitido" % t.get_tipo_display().lower(),
                fala=(t.equipamento_desc or "").strip(),
                autor=emissor or pessoa, para=pessoa,
                maquina=(t.notebook.patrimonio if t.notebook_id else ""),
                status=t.get_status_display(),
                precisa="" if assinado else "assinatura",
                trilha=[_passo(emissor, "emitiu o termo", t.criado_em),
                        _passo(pessoa, "assinou", t.assinado_em)],
                url="/parque/termo/%s/" % t.pk,
                papel={"nome": "Termo assinado", "tem": assinado,
                       "alvo": "tm%s" % t.pk, "doc": DOC.TERMO})

    # ---------------------------------------------------------- documentos
    if "documento" in liberado:
        for d in DocumentoEquipamento.objects.select_related(
                "computador", "notebook", "enviado_por"):
            eq = d.computador or d.notebook
            quem = _nome(d.enviado_por)
            add(id="doc%s" % d.pk, tipo="documento", data=_dia(d.enviado_em),
                _tags=["documento", d.get_tipo_display()],
                hora=_hora(d.enviado_em), _d=d.enviado_em,
                titulo="Documento anexado: %s" % d.get_tipo_display(),
                fala=(d.descricao or "").strip(), autor=quem,
                maquina=(getattr(eq, "patrimonio", "") or ""),
                trilha=[_passo(quem, "anexou no Arquivo", d.enviado_em)],
                url="/parque/arquivo/")

    # ------------------------------------------------------------- tarefas
    # Concluída: um post cada. ABERTAS: 125 linhas iguais não são 125 posts —
    # agrupo por (tipo, loja) e o post diz de quem é e quantas máquinas tem.
    if "tarefa" in liberado:
        for t in Tarefa.objects.exclude(fechada_em=None).select_related(
                "baia", "notebook", "unidade", "responsavel", "fechada_por"):
            quem = _nome(t.fechada_por) or _nome(t.responsavel)
            add(id="tk%s" % t.pk, tipo="tarefa", data=_dia(t.fechada_em),
                _tags=["preventiva", "tarefa", t.get_tipo_display(), "concluido"],
                hora=_hora(t.fechada_em), _d=t.fechada_em,
                titulo="Tarefa concluída: %s" % (t.titulo or ""),
                fala=(t.detalhe or "").strip(),
                onde=(t.unidade.name if t.unidade_id else ""), autor=quem,
                maquina=(t.baia.patrimonio if t.baia_id and
                         getattr(t.baia, "patrimonio", "")
                         else (t.notebook.patrimonio if t.notebook_id else "")),
                status="Concluída",
                trilha=[_passo(_nome(t.responsavel), "recebeu a tarefa", t.criada_em),
                        _passo(quem, "concluiu", t.fechada_em)],
                url="/parque/preventiva/")

    if "tarefa_aberta" in liberado:
        grupos = {}
        for t in Tarefa.objects.filter(fechada_em=None).select_related(
                "baia", "notebook", "unidade", "responsavel"):
            # A chave usa o ID da unidade, não o nome: renomear a loja não pode
            # jogar os comentários daquele card no lixo.
            ch = (t.tipo, t.unidade_id or 0)
            g = grupos.setdefault(ch, {
                "titulo": t.titulo or "", "detalhe": (t.detalhe or "").strip(),
                "loja": (t.unidade.name if t.unidade_id else "sem loja"),
                "rotulo_tipo": t.get_tipo_display(),
                "maquinas": [], "resp": Counter(), "desde": None, "n": 0})
            maq = (t.baia.patrimonio if t.baia_id and getattr(t.baia, "patrimonio", "")
                   else (t.notebook.patrimonio if t.notebook_id else ""))
            if maq and maq not in g["maquinas"]:
                g["maquinas"].append(maq)
            r = _nome(t.responsavel)
            if r:
                g["resp"][r] += 1
            dt = t.criada_em.date() if hasattr(t.criada_em, "date") else t.criada_em
            if g["desde"] is None or dt < g["desde"]:
                g["desde"] = dt
            g["n"] += 1

        for (tp, uni), g in grupos.items():
            donos = [n for n, _ in g["resp"].most_common()]
            add(id="tka-%s-%s" % (tp, uni), tipo="tarefa_aberta",
                _tags=["preventiva", "tarefa", g["rotulo_tipo"], "em-aberto"],
                data=_dia(g["desde"]), _d=g["desde"],
                titulo="%s — %d máquina%s em %s" % (
                    g["titulo"], g["n"], "s" if g["n"] > 1 else "", g["loja"]),
                fala=g["detalhe"], onde=g["loja"],
                autor=(donos[0] if donos else ""), donos=donos,
                maquinas=g["maquinas"][:40],
                maquina=(g["maquinas"][0] if g["maquinas"] else ""),
                status="Aberta", precisa="conclusao", lote=g["n"],
                trilha=[_passo(donos[0] if donos else "", "é o responsável",
                               g["desde"])],
                url="/parque/preventiva/")

    # ----------------------------------------------------------- orçamentos
    if Orcamento and "orcamento" in liberado:
        for o in Orcamento.objects.select_related("aprovado_por"):
            dt = o.data_solicitacao or o.criado_em
            pend = str(o.status) == "pendente"
            add(id="orc%s" % o.pk, tipo="orcamento", data=_dia(dt), _d=dt,
                _tags=["orcamento", o.get_status_display(), (o.fornecedor or "")],
                titulo="Orçamento: %s" % (o.titulo or "sem título"),
                fala=(o.descricao or "").strip(),
                autor=str(o.solicitante or ""), onde=str(o.fornecedor or ""),
                status=o.get_status_display(),
                precisa="decisao" if pend else "",
                valor=("%s" % o.valor) if o.valor is not None else "",
                trilha=[_passo(str(o.solicitante or ""), "pediu o orçamento", dt),
                        _passo(_nome(o.aprovado_por), "aprovou", o.data_aprovacao)],
                url="/orcamentos/")

    # ------------------------------------------------------- publicações
    # Escritas por gente, sem evento por trás. Entram na mesma ordem que o
    # resto — e, quando têm patrimônio, entram também na ficha corrida
    # daquela máquina, porque `maquina` é o mesmo campo que o filtro usa.
    if "aviso" in liberado:
        for pub in PublicacaoMural.objects.select_related(
                "autor", "unidade").prefetch_related("mencionados"):
            texto = (pub.texto or "").strip()
            titulo = texto.split("\n")[0][:120]
            resto = texto[len(titulo):].strip()
            add(id="pub%s" % pub.pk, tipo="aviso",
                _tags=["publicacao"] + (pub.tags or "").split(),
                alvo=pub.alvo, alvo_titulo=pub.alvo_titulo,
                arquivo=(pub.arquivo.url if pub.arquivo else ""),
                arquivo_nome=pub.nome_do_arquivo,
                e_imagem=pub.e_imagem,
                data=_dia(timezone.localtime(pub.criado_em)),
                hora=_hora(timezone.localtime(pub.criado_em)), _d=pub.criado_em,
                titulo=titulo or "(sem texto)", fala=resto,
                onde=(pub.unidade.name if pub.unidade_id else ""),
                autor=_nome(pub.autor) or pub.autor.get_username(),
                maquina=(pub.patrimonio or ""),
                status=("editada" if pub.editado_em else ""),
                mencionados=[_nome(u) or u.get_username()
                             for u in pub.mencionados.all()],
                meu=(pub.autor_id == user.pk),
                editavel=(pub.autor_id == user.pk or user.is_superuser),
                pub=pub.pk,
                url="/parque/mural/")

    eventos.sort(key=lambda e: (e["data"], e.get("hora") or ""), reverse=True)
    return eventos


def _gente(eventos):
    """As pessoas que aparecem no feed, com inicial, cor e volume."""
    achadas = {}
    for e in eventos:
        nomes = [e.get("autor", "")] + [p["quem"] for p in e["trilha"]] + \
                list(e.get("donos") or [])
        for nome in nomes:
            nome = (nome or "").strip()
            if len(nome) < 2 or nome == "equipe de TI":
                continue
            k = _chave_nome(nome)
            g = achadas.setdefault(k, {"nome": nome, "n": 0, "k": k})
            if len(nome) > len(g["nome"]):
                g["nome"] = nome
            g["n"] += 1
    pessoas = sorted(achadas.values(), key=lambda g: (-g["n"], g["nome"]))
    for i, p in enumerate(pessoas):
        p["ini"] = _iniciais(p["nome"])
        p["cor"] = i % 8
    return pessoas


def montar_conversa(eventos, user):
    """Comentários, fotos e marcas dos cards que estão no feed.

    Uma consulta para tudo, filtrada pelas chaves que o usuário pode ver — o
    que também é a segunda tranca: comentário de card que ele não vê não sai
    do banco nem por acidente.
    """
    chaves = {e["id"] for e in eventos}
    comentarios = {}
    fotos = {}
    for c in ComentarioEvento.objects.filter(chave__in=chaves).select_related("autor"):
        quem = _nome(c.autor) or c.autor.get_username()
        if (c.texto or "").strip():
            comentarios.setdefault(c.chave, []).append({
                "id": c.pk, "quem": quem, "texto": c.texto,
                "quando": timezone.localtime(c.criado_em).strftime("%d/%m %H:%M"),
                "meu": c.autor_id == user.pk,
            })
        if c.foto:
            fotos.setdefault(c.chave, []).append({
                # `meu` decide quem vê o botão de apagar. Sem isto a tela não
                # tinha como distinguir a minha foto da dos outros — e o botão
                # não podia existir. O comentário já trazia o dele.
                "id": c.pk, "url": c.foto.url, "quem": quem,
                "meu": c.autor_id == user.pk,
                "leg": c.legenda or "Foto do serviço",
                "quando": timezone.localtime(c.criado_em).strftime("%d/%m %H:%M"),
            })

    assumido, seguindo = {}, {}
    for m in MarcaEvento.objects.filter(chave__in=chaves).select_related("usuario"):
        alvo = assumido if m.marca == MarcaEvento.Marca.ASSUMIDO else seguindo
        alvo.setdefault(m.chave, []).append({
            "quem": _nome(m.usuario) or m.usuario.get_username(),
            "eu": m.usuario_id == user.pk,
        })
    return {"comentarios": comentarios, "fotos": fotos,
            "assumido": assumido, "seguindo": seguindo}


def montar_presenca(user):
    """Substitui o painel "Usuários online". Online = visto nos últimos 5 min.

    Um pontinho verde/cinza não diz nada quando ninguém está dentro da janela,
    então sai a FAIXA: agora / hoje / esta semana / sumido / nunca entrou.
    """
    if not pode_ver_tela(user, "online"):
        return []
    agora = timezone.now()
    fora = []
    vistos = set()
    for a in AtividadeUsuario.objects.select_related("usuario").order_by("-visto_em"):
        if not a.usuario_id:
            continue
        vistos.add(a.usuario_id)
        mins = int((agora - a.visto_em).total_seconds() // 60)
        if mins <= 5:
            faixa = "agora"
        elif mins <= 60 * 24:
            faixa = "hoje"
        elif mins <= 60 * 24 * 7:
            faixa = "semana"
        else:
            faixa = "sumido"
        fora.append({"nome": _nome(a.usuario) or a.usuario.get_username(),
                     "mins": mins, "faixa": faixa, "ip": a.ip or "",
                     "su": bool(a.usuario.is_superuser),
                     "staff": bool(a.usuario.is_staff),
                     "eu": a.usuario_id == user.pk})
    for u in U.objects.exclude(pk__in=vistos):
        fora.append({"nome": _nome(u) or u.get_username(), "mins": None,
                     "faixa": "nunca", "ip": "", "su": bool(u.is_superuser),
                     "staff": bool(u.is_staff), "eu": u.pk == user.pk})
    return fora


def montar_logs(user, quantos=220):
    """Substitui o item "Logs": acessos (LogAcesso) e ações (admin.LogEntry).

    O volume não é a notícia. O que merece olho é erro de senha, exclusão e
    mexida em usuário/grupo — sai marcado com `sens` para a tela destacar.
    """
    if not pode_ver_tela(user, "logs"):
        return {"logs": [], "resumo": {}, "dias": {}}

    EV = {"login": ("entrou", "ok"), "logout": ("saiu", "neutro"),
          "falha": ("errou a senha", "alerta"),
          "recuperacao": ("pediu senha temporária", "aviso"),
          "troca_senha": ("trocou a senha", "aviso")}
    ACAO = {ADDITION: ("criou", "ok"), CHANGE: ("alterou", "neutro"),
            DELETION: ("apagou", "alerta")}

    logs = []
    for l in LogAcesso.objects.select_related("usuario").order_by("-em")[:quantos]:
        rot, tom = EV.get(l.evento, (l.evento, "neutro"))
        logs.append({
            "id": "la%s" % l.pk, "lane": "acesso",
            "quem": _nome(l.usuario) or l.username_tentado or "desconhecido",
            "oque": rot,
            "alvo": ('usuário “%s”' % l.username_tentado) if l.evento == "falha" else "",
            "quando": _dia(timezone.localtime(l.em)),
            "hora": _hora(timezone.localtime(l.em)),
            "ip": l.ip or "", "tom": tom,
            "sens": l.evento in ("falha", "troca_senha", "recuperacao"),
        })
    for e in LogEntry.objects.select_related(
            "user", "content_type").order_by("-action_time")[:quantos]:
        rot, tom = ACAO.get(e.action_flag, ("mexeu em", "neutro"))
        modelo = e.content_type.model if e.content_type_id else ""
        sens = modelo in SENSIVEL
        logs.append({
            "id": "le%s" % e.pk, "lane": "acao", "quem": _nome(e.user) or "?",
            "oque": rot,
            "alvo": "%s: %s" % (
                (e.content_type.name if e.content_type_id else "registro"),
                (e.object_repr or "")[:52]),
            "quando": _dia(timezone.localtime(e.action_time)),
            "hora": _hora(timezone.localtime(e.action_time)),
            "ip": "", "sens": sens,
            "tom": ("alerta" if e.action_flag == DELETION
                    else ("aviso" if sens else tom)),
        })
    logs.sort(key=lambda x: (x["quando"], x["hora"]), reverse=True)

    dias = Counter(x["quando"] for x in logs)
    resumo = {
        "acessos": LogAcesso.objects.count(),
        "acoes": LogEntry.objects.count(),
        "falhas": LogAcesso.objects.filter(evento="falha").count(),
        "exclusoes": LogEntry.objects.filter(action_flag=DELETION).count(),
        "permissao": LogEntry.objects.filter(
            content_type__model__in=SENSIVEL).count(),
    }
    return {"logs": logs, "resumo": resumo, "dias": dict(dias)}


def _msg_json(m, eu):
    return {
        "id": m.pk,
        "meu": m.de_id == eu.pk,
        "quem": _nome(m.de) or m.de.get_username(),
        "texto": m.texto,
        "arquivo": (m.arquivo.url if m.arquivo else ""),
        "arquivo_nome": m.nome_do_arquivo,
        "e_imagem": m.e_imagem,
        "alvo": m.alvo, "alvo_titulo": m.alvo_titulo,
        "quando": timezone.localtime(m.criado_em).strftime("%d/%m %H:%M"),
        "lida": bool(m.lida_em),
    }


def montar_conversas(user):
    """Uma linha por pessoa: a última mensagem e quantas eu não li.

    A lista traz TODO MUNDO que tem acesso ao sistema, não só quem já falou —
    a tela é ao mesmo tempo a lista de usuários e a porta da conversa, e um
    chat que só mostra quem já te escreveu não serve para começar conversa.
    """
    agora = timezone.now()
    minhas = (MensagemDireta.objects
              .filter(Q(de=user) | Q(para=user))
              .select_related("de", "para").order_by("-criado_em"))

    ultima, nao_lidas = {}, {}
    for m in minhas:
        outro = m.para_id if m.de_id == user.pk else m.de_id
        if outro not in ultima:
            ultima[outro] = m
        if m.para_id == user.pk and not m.lida_em:
            nao_lidas[outro] = nao_lidas.get(outro, 0) + 1

    visto = {}
    if pode_ver_tela(user, "online"):
        for a in AtividadeUsuario.objects.select_related("usuario"):
            if a.usuario_id:
                visto[a.usuario_id] = a.visto_em

    fora = []
    for u in U.objects.filter(is_active=True).exclude(pk=user.pk):
        m = ultima.get(u.pk)
        mins = None
        if u.pk in visto:
            mins = int((agora - visto[u.pk]).total_seconds() // 60)
        fora.append({
            "id": u.pk,
            "nome": _nome(u) or u.get_username(),
            "su": bool(u.is_superuser),
            "mins": mins,
            "faixa": ("agora" if mins is not None and mins <= 5 else
                      "hoje" if mins is not None and mins <= 60 * 24 else
                      "semana" if mins is not None and mins <= 60 * 24 * 7 else
                      "sumido" if mins is not None else "nunca"),
            "ultima": ((m.texto or ("arquivo: " + m.nome_do_arquivo))[:80]
                       if m else ""),
            "ultima_minha": (m.de_id == user.pk) if m else False,
            "quando": (timezone.localtime(m.criado_em).strftime("%d/%m %H:%M")
                       if m else ""),
            "ordem": (m.criado_em.isoformat() if m else ""),
            "nao_lidas": nao_lidas.get(u.pk, 0),
        })

    # Quem tem conversa vem primeiro, do mais recente; depois o resto por nome.
    fora.sort(key=lambda x: (0 if x["ordem"] else 1,
                             x["ordem"] and (1, x["ordem"]) or (1, ""),
                             x["nome"]), reverse=False)
    fora.sort(key=lambda x: (x["ordem"] == "", x["ordem"] and "" or x["nome"]))
    com = [x for x in fora if x["ordem"]]
    sem = [x for x in fora if not x["ordem"]]
    com.sort(key=lambda x: x["ordem"], reverse=True)
    sem.sort(key=lambda x: x["nome"])
    return com + sem


def montar(user):
    """Tudo que a tela precisa, num dicionário só — é o que vai virar JSON."""
    eventos = montar_eventos(user)
    conversa = montar_conversa(eventos, user)
    logs = montar_logs(user)
    pessoas = _gente(eventos)

    demandas = []
    for pid, rot in PRECISA:
        n = sum(e.get("lote", 1) for e in eventos if e.get("precisa") == pid)
        if n:
            demandas.append({"id": pid, "rotulo": rot, "n": n})

    # Os temas em uso, com quantos posts cada um — é o que enche a lista de
    # temas do seletor. Sem contagem ninguém sabe se vale clicar.
    temas = Counter()
    for e in eventos:
        for t in e.get("tags") or []:
            temas[t] += 1

    meses = Counter(e["data"][:7] for e in eventos if e["data"])
    return {
        "hoje": _dia(timezone.localdate()),
        "eu": _nome(user) or user.get_username(),
        "pessoas": pessoas,
        "eventos": eventos,
        "tipos": [{"id": t, "nome": n, "ic": i,
                   "n": sum(1 for e in eventos if e["tipo"] == t)}
                  for t, n, i in TIPOS],
        "demandas": demandas,
        "meses": dict(meses),
        "lojas": sorted({e["onde"] for e in eventos if e["onde"]}),
        # As lojas com a tag pronta: o `#` do composer sugere loja e tema na
        # mesma lista, e a loja da publicação sai daí.
        "lojas_tag": [{"nome": l.name, "t": tag(l.name)}
                      for l in Location.objects.order_by("name")],
        "temas": [{"t": t, "n": n} for t, n in temas.most_common(40)],
        "comentarios": conversa["comentarios"],
        "fotos": conversa["fotos"],
        "assumido": conversa["assumido"],
        "seguindo": conversa["seguindo"],
        "presenca": montar_presenca(user),
        "conversas": montar_conversas(user),
        "nao_lidas": MensagemDireta.objects.filter(para=user,
                                                   lida_em=None).count(),
        "logs": logs["logs"],
        "log_resumo": logs["resumo"],
        "log_dias": logs["dias"],
        "pode_comentar": user.has_perm("parque.add_comentarioevento"),
        "pode_publicar": user.has_perm("parque.add_publicacaomural"),
        "lojas_id": [{"id": l.pk, "nome": l.name}
                     for l in Location.objects.order_by("name")],
        "patrimonios": _patrimonios(),
        "pode_anexar": user.has_perm("parque.add_documentoequipamento"),
        "resumo": {
            "posts": len(eventos),
            "acontecimentos": sum(e.get("lote", 1) for e in eventos),
            "precisa": sum(d["n"] for d in demandas),
        },
    }


# ------------------------------------------- a régua do topo (o antigo Início)
# Para quem abre o Mural, ESTA é a tela inicial — `inicio()` manda para cá. A
# régua responde numa linha o que o painel do admin respondia numa tela: o que
# exige ação agora e o tamanho do parque. O painel inteiro continua a um clique.
#
# Os dois cuidados são os MESMOS do feed:
#   · nenhum número novo — cada um já aparecia na tela que o link abre;
#   · cada item só existe para quem PODE ABRIR aquela tela (`pode_ver_tela`),
#     o mesmo contrato do TELA_DO_TIPO. A régua não abre porta nova: para quem
#     só tem "chamados", ela tem um item só.
#
# E um terceiro, de desempenho, que decidiu o conteúdo: aqui só entra contagem
# que o BANCO resolve — todos os campos de status usados são `db_index=True`.
# Os números bonitos do painel (máquinas críticas, preventiva vencida) saem de
# `dashboard_callback`, que varre TODAS as baias e calcula índice de desempenho
# em Python; é o gargalo de docs/AUDITORIA-BACKEND.md §3.1, e trazê-lo para cá
# colocaria essa varredura na tela que mais gente abre por dia.
ATRASO_DIAS = 2   # o que "passou do prazo" quer dizer nesta casa


def _aprovacoes_paradas():
    return (Transferencia.objects.filter(status=Transferencia.Status.PENDENTE).count()
            + MovimentacaoBaia.objects.filter(status=MovimentacaoBaia.Status.PENDENTE).count())


def estado_dia(user):
    """O ÚNICO fato da faixa: o primeiro da escada que tiver número.

    A faixa mostra UM fato, nunca uma lista — se tudo virasse item, nada seria
    prioridade. A ordem é por quanto DÓI, não por quanto é fácil de contar:

        1. chamado que estourou o prazo   — alguém está parado esperando
        2. solicitação esperando decisão  — alguém está bloqueado por mim
        3. máquina parada com defeito     — custo dormindo
        4. nada disso                     — e a tela diz isso, em uma linha

    QUANTIDADE NÃO PROMOVE, ATRASO PROMOVE: sete chamados abertos pode ser um
    dia normal; três parados há três dias não é. Os que estão dentro do prazo
    descem para a linha de apoio e continuam alcançáveis pelo filtro do feed.

    Cada degrau só é considerado para quem PODE ABRIR a tela correspondente —
    quem não abre Chamados começa a escada na aprovação.
    """
    hoje = timezone.localdate()
    ve_aprov = pode_ver_tela(user, "aprovacoes")
    paradas = _aprovacoes_paradas() if ve_aprov else 0

    if pode_ver_tela(user, "chamados"):
        abertos = Reparo.objects.filter(concluido_em__isnull=True)
        atrasados = abertos.filter(
            data__lt=hoje - timedelta(days=ATRASO_DIAS)).count()
        if atrasados:
            no_prazo = abertos.count() - atrasados
            apoio = ("Outro %d aberto dentro do prazo" % no_prazo if no_prazo == 1
                     else "Outros %d abertos dentro do prazo" % no_prazo) if no_prazo \
                else "Nenhum outro chamado aberto"
            if ve_aprov:
                apoio += (" · nenhuma aprovação parada" if not paradas
                          else " · %d aguardando aprovação" % paradas)
            return {"nivel": "age", "n": atrasados,
                    "titulo": ("chamado passou de %d horas" % (ATRASO_DIAS * 24))
                              if atrasados == 1 else
                              ("chamados passaram de %d horas" % (ATRASO_DIAS * 24)),
                    "sub": apoio, "acao": "Ver no feed", "tema": "atrasado", "url": "",
                    "curto": "%d atrasado%s" % (atrasados, "" if atrasados == 1 else "s")}

    if paradas:
        return {"nivel": "aten", "n": paradas,
                "titulo": "solicitação espera sua decisão" if paradas == 1
                          else "solicitações esperam sua decisão",
                "sub": "Nenhum chamado atrasado",
                "acao": "Abrir aprovações", "tema": "", "url": "/parque/aprovacoes/",
                "curto": "%d esperando decisão" % paradas}

    if pode_ver_tela(user, "mapa"):
        defeito = Computador.objects.filter(
            status=Computador.Status.DEFEITO).count()
        if defeito:
            return {"nivel": "aten", "n": defeito,
                    "titulo": "máquina parada com defeito" if defeito == 1
                              else "máquinas paradas com defeito",
                    "sub": "Nenhum chamado atrasado e nenhuma aprovação esperando decisão",
                    "acao": "Ver no mapa", "tema": "",
                    "url": "/parque/mapa-completo/",
                    "curto": "%d com defeito" % defeito}

    return {"nivel": "ok", "n": None, "titulo": "Tudo em dia",
            "sub": "Nenhum chamado atrasado e nenhuma aprovação esperando decisão",
            "acao": "", "tema": "", "url": "", "curto": "tudo em dia"}


def inventario(user):
    """O tamanho do parque, em uma linha discreta — e em conjuntos que NÃO se
    sobrepõem. A primeira versão desta régua dizia "129 máquinas" e "27 em
    estoque", e as 27 estavam DENTRO das 129: lado a lado, com o mesmo peso,
    convidavam a somar.

    Só contagem que o banco resolve (`status` é `db_index=True`). Máquina
    crítica e preventiva vencida continuam fora: vêm do `dashboard_callback`,
    que varre todas as baias — ver AUDITORIA-BACKEND §3.1.
    """
    itens = []

    def add(tela, rotulo, valor, url):
        if pode_ver_tela(user, tela):
            itens.append({"rotulo": rotulo, "valor": valor, "url": url})

    S = Computador.Status
    add("mapa", "em uso", Computador.objects.filter(status=S.EM_USO).count(),
        "/parque/mapa-completo/")
    add("estoque", "em estoque",
        Computador.objects.filter(status=S.EM_ESTOQUE).count(), "/parque/estoque/")
    add("mapa", "com defeito",
        Computador.objects.filter(status=S.DEFEITO).count(), "/parque/mapa-completo/")
    return itens


# ------------------------------------------------------------------- a tela
@staff_member_required
def mural(request):
    exigir(request.user, TELA)
    # `each_context` NÃO é enfeite: é ele que leva ao template as variáveis de
    # que a casca do admin precisa para montar cabeçalho, gaveta e — o que só
    # apareceu medindo — as FOLHAS DE ESTILO de UNFOLD["STYLES"], onde vive o
    # make-m3.css com todos os tokens --md-*.
    #
    # Sem esta linha a página abria com QUATRO folhas em vez de oito: os
    # tokens do sistema ficavam vazios, `border-radius: var(--md-shape-full)`
    # não resolvia e os avatares saíam QUADRADOS. Nada quebrava e nada dava
    # erro de JS — a tela só ficava sem o desenho do sistema. Foi
    # `getComputedStyle` no render que mostrou; ler o código não mostrava.
    dados = montar(request.user)
    return render(request, "parque/mural.html", {
        **dj_admin.site.each_context(request),
        "title": "Início",
        "dados_js": dados,
        # A faixa e a linha de inventário do topo. Nome diferente do `resumo`
        # que vai DENTRO do dados_js (posts, acontecimentos, precisa): aquele
        # é do feed, estes são do cabeçalho.
        "estado_dia": estado_dia(request.user),
        "inventario": inventario(request.user),
        # Quantas demandas esperam por ESTA pessoa. Já está calculado para o
        # feed — reaproveitar não custa consulta nenhuma.
        "precisa_de_mim": dados["resumo"]["precisa"],
    })


@staff_member_required
def inicio(request):
    """Para onde o login manda. O Mural, para quem o abre.

    NÃO é um `redirect` fixo de propósito: 8 dos 13 usuários não têm a tela
    "registros" (nunca tiveram — é a mesma porta do antigo "Registros"), e
    mandá-los direto ao Mural seria um "acesso negado" logo depois do login.
    Quem não abre continua caindo no painel de sempre.

    Abrir o Mural para todos é decisão de uma linha na tela de acessos: o feed
    já filtra por pessoa (TELA_DO_TIPO), então ninguém passaria a ver o que
    não vê hoje.
    """
    if pode_ver_tela(request.user, TELA):
        return redirect("parque_mural")
    return redirect("admin:index")


# ----------------------------------------------------- escrever no mural
def _card_visivel(user, chave):
    """A chave existe E este usuário pode vê-la? Sem isto, alguém escreveria
    num card que não abre para ele — e leria a resposta de quem pode."""
    for e in montar_eventos(user):
        if e["id"] == chave:
            return e
    return None


@staff_member_required
@require_POST
def mural_comentar(request):
    """Comenta num acontecimento. A foto do serviço vem no mesmo POST."""
    exigir(request.user, TELA)
    if not request.user.has_perm("parque.add_comentarioevento"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para comentar."},
                            status=403)

    chave = (request.POST.get("chave") or "").strip()[:64]
    texto = (request.POST.get("texto") or "").strip()
    legenda = (request.POST.get("legenda") or "").strip()[:160]
    foto = request.FILES.get("foto")

    if not texto and not foto:
        return JsonResponse({"ok": False, "erro": "Escreva algo ou anexe uma foto."},
                            status=400)
    if len(texto) > 4000:
        return JsonResponse({"ok": False, "erro": "Comentário muito longo (4.000)."},
                            status=400)

    evento = _card_visivel(request.user, chave)
    if not evento:
        return JsonResponse({"ok": False, "erro": "Acontecimento não encontrado."},
                            status=404)

    if foto:
        ext = foto.name.rsplit(".", 1)[-1].lower() if "." in foto.name else ""
        if ext not in ComentarioEvento.FORMATOS_FOTO:
            return JsonResponse(
                {"ok": False, "erro": "Foto tem que ser PNG, JPG ou WEBP."}, status=400)
        if foto.size > 12 * 1024 * 1024:
            return JsonResponse({"ok": False, "erro": "Foto acima de 12 MB."},
                                status=400)

    c = ComentarioEvento.objects.create(
        chave=chave, tipo=evento["tipo"], autor=request.user, texto=texto,
        foto=foto, legenda=(legenda or ("Foto do serviço" if foto else "")))
    # Quem comenta passa a acompanhar: é o que ele espera ao entrar na conversa.
    MarcaEvento.objects.get_or_create(
        chave=chave, usuario=request.user, marca=MarcaEvento.Marca.SEGUINDO,
        defaults={"tipo": evento["tipo"]})

    return JsonResponse({
        "ok": True,
        "comentario": {
            "id": c.pk, "quem": _nome(request.user) or request.user.get_username(),
            "texto": c.texto, "meu": True,
            "quando": timezone.localtime(c.criado_em).strftime("%d/%m %H:%M"),
        },
        "foto": ({"id": c.pk, "url": c.foto.url, "leg": c.legenda,
                  "quem": _nome(request.user) or request.user.get_username(),
                  "quando": timezone.localtime(c.criado_em).strftime("%d/%m %H:%M")}
                 if c.foto else None),
    })


@staff_member_required
@require_POST
def mural_marcar(request):
    """Assume a demanda ou passa a acompanhar. Clicar de novo desfaz."""
    exigir(request.user, TELA)

    chave = (request.POST.get("chave") or "").strip()[:64]
    marca = (request.POST.get("marca") or "").strip()
    if marca not in MarcaEvento.Marca.values:
        return JsonResponse({"ok": False, "erro": "Marca inválida."}, status=400)

    evento = _card_visivel(request.user, chave)
    if not evento:
        return JsonResponse({"ok": False, "erro": "Acontecimento não encontrado."},
                            status=404)

    achada = MarcaEvento.objects.filter(chave=chave, usuario=request.user,
                                        marca=marca).first()
    if achada:
        achada.delete()
        # Deixar de cuidar não faz deixar de acompanhar: são decisões diferentes.
        return JsonResponse({"ok": True, "ligado": False, "marca": marca})

    try:
        MarcaEvento.objects.create(chave=chave, tipo=evento["tipo"],
                                   usuario=request.user, marca=marca)
    except IntegrityError:  # clique duplo
        pass
    if marca == MarcaEvento.Marca.ASSUMIDO:
        MarcaEvento.objects.get_or_create(
            chave=chave, usuario=request.user, marca=MarcaEvento.Marca.SEGUINDO,
            defaults={"tipo": evento["tipo"]})
    return JsonResponse({"ok": True, "ligado": True, "marca": marca,
                         "quem": _nome(request.user) or request.user.get_username()})


def _pub_do_usuario(request, pk):
    """A publicação existe e ESTE usuário pode mexer nela? Autor sempre;
    superusuário para moderar. Mais ninguém — nem quem abre a tela."""
    pub = PublicacaoMural.objects.filter(pk=id_ou_nada(pk)).first()
    if not pub:
        return None, JsonResponse({"ok": False, "erro": "Publicação não encontrada."},
                                  status=404)
    if pub.autor_id != request.user.pk and not request.user.is_superuser:
        return None, JsonResponse(
            {"ok": False, "erro": "Só quem escreveu pode mexer nesta publicação."},
            status=403)
    return pub, None


def _loja_da_tag(tags):
    """A loja sai de uma #tag: `#bonsucesso` resolve para a Location.

    Era um <select> a mais no composer. O `#` já existe para tema; loja é só
    outro tipo de tema, e a tela sugere as duas listas no mesmo popover.
    """
    for l in Location.objects.all():
        if tag(l.name) in tags:
            return l
    return None


def _valida_publicacao(request, user):
    texto = (request.POST.get("texto") or "").strip()
    if not texto:
        return None, JsonResponse({"ok": False, "erro": "Escreva o texto."},
                                  status=400)
    if len(texto) > 6000:
        return None, JsonResponse({"ok": False, "erro": "Texto acima de 6.000 letras."},
                                  status=400)

    # ARQUIVO, não foto: nota em PDF, planilha e print também são anexo de
    # aviso. O limite é o mesmo do resto do sistema.
    arq = request.FILES.get("arquivo")
    if arq:
        ext = arq.name.rsplit(".", 1)[-1].lower() if "." in arq.name else ""
        if ext not in PublicacaoMural.FORMATOS:
            return None, JsonResponse(
                {"ok": False,
                 "erro": "Formato não aceito. Use imagem, PDF, DOCX, XLSX, CSV ou TXT."},
                status=400)
        if arq.size > 16 * 1024 * 1024:
            return None, JsonResponse({"ok": False, "erro": "Arquivo acima de 16 MB."},
                                      status=400)

    # O REGISTRO CITADO. Ninguém digita patrimônio: escolhe-se um registro que
    # a pessoa PODE VER, e dele saem o patrimônio e a loja. A checagem de
    # visibilidade é a mesma do comentário — sem ela, dava para citar (e
    # descobrir o título de) um registro de tela que não abre.
    chave = (request.POST.get("alvo") or "").strip()[:64]
    evento = None
    if chave:
        evento = _card_visivel(user, chave)
        if not evento:
            return None, JsonResponse(
                {"ok": False, "erro": "Registro citado não encontrado."}, status=404)

    tags = _tags_do_texto(texto)
    uni = _loja_da_tag(tags)
    pat = ""
    if evento:
        pat = (evento.get("maquina") or "")[:40]
        if not uni and evento.get("onde"):
            uni = Location.objects.filter(name=evento["onde"]).first()

    return {"texto": texto, "arquivo": arq, "patrimonio": pat, "unidade": uni,
            "tags": tags,
            "alvo": (evento["id"] if evento else ""),
            "alvo_titulo": ((evento["titulo"] or "")[:160] if evento else "")}, None


def _pub_json(pub, request):
    return {
        "id": pub.pk, "texto": pub.texto,
        "autor": _nome(pub.autor) or pub.autor.get_username(),
        "arquivo": (pub.arquivo.url if pub.arquivo else ""),
        "arquivo_nome": pub.nome_do_arquivo,
        "e_imagem": pub.e_imagem,
        "patrimonio": pub.patrimonio,
        "alvo": pub.alvo, "alvo_titulo": pub.alvo_titulo,
        "tags": (pub.tags or "").split(),
        "loja": (pub.unidade.name if pub.unidade_id else ""),
        "quando": timezone.localtime(pub.criado_em).strftime("%d/%m %H:%M"),
        "editada": bool(pub.editado_em),
        "mencionados": [_nome(u) or u.get_username() for u in pub.mencionados.all()],
    }


@staff_member_required
@require_POST
def mural_publicar(request):
    """Publica no mural. Pode ficar presa a uma máquina e a uma loja."""
    exigir(request.user, TELA)
    if not request.user.has_perm("parque.add_publicacaomural"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para publicar."},
                            status=403)
    dados, erro = _valida_publicacao(request, request.user)
    if erro:
        return erro

    pub = PublicacaoMural.objects.create(
        autor=request.user, texto=dados["texto"], arquivo=dados["arquivo"],
        patrimonio=dados["patrimonio"], unidade=dados["unidade"],
        alvo=dados["alvo"], alvo_titulo=dados["alvo_titulo"],
        tags=" ".join(dados["tags"]))
    pub.mencionados.set(_mencoes(dados["texto"]))
    return JsonResponse({"ok": True, "publicacao": _pub_json(pub, request)})


@staff_member_required
@require_POST
def mural_editar_publicacao(request):
    """Edita a própria publicação. Fica marcada como editada — não some o
    rastro de que o texto mudou depois que gente já tinha lido."""
    exigir(request.user, TELA)
    pub, erro = _pub_do_usuario(request, request.POST.get("id"))
    if erro:
        return erro
    dados, erro = _valida_publicacao(request, request.user)
    if erro:
        return erro

    pub.texto = dados["texto"]
    pub.patrimonio = dados["patrimonio"]
    pub.unidade = dados["unidade"]
    pub.alvo = dados["alvo"]
    pub.alvo_titulo = dados["alvo_titulo"]
    pub.tags = " ".join(dados["tags"])
    if dados["arquivo"]:
        pub.arquivo = dados["arquivo"]
    elif request.POST.get("tirar_arquivo") == "1":
        pub.arquivo = None
    pub.editado_em = timezone.now()
    pub.save()
    pub.mencionados.set(_mencoes(dados["texto"]))
    return JsonResponse({"ok": True, "publicacao": _pub_json(pub, request)})


@staff_member_required
@require_POST
def mural_apagar_publicacao(request):
    """Apaga a própria publicação, e com ela os comentários dela."""
    exigir(request.user, TELA)
    pub, erro = _pub_do_usuario(request, request.POST.get("id"))
    if erro:
        return erro
    chave = "pub%s" % pub.pk
    ComentarioEvento.objects.filter(chave=chave).delete()
    MarcaEvento.objects.filter(chave=chave).delete()
    pub.delete()
    return JsonResponse({"ok": True})


def _o_outro(request):
    """A pessoa do outro lado da conversa. Tem que ser usuário ativo do
    sistema — conversa com quem saiu da empresa não começa."""
    pk = id_ou_nada(request.POST.get("com"))
    if not pk:
        return None, JsonResponse({"ok": False, "erro": "Com quem?"}, status=400)
    if pk == request.user.pk:
        return None, JsonResponse(
            {"ok": False, "erro": "Não dá para conversar consigo mesmo."}, status=400)
    outro = U.objects.filter(pk=pk, is_active=True).first()
    if not outro:
        return None, JsonResponse({"ok": False, "erro": "Pessoa não encontrada."},
                                  status=404)
    return outro, None


@staff_member_required
def mural_lista(request):
    """A lista de conversas, para o widget que roda FORA do mural.

    O widget do chat vive em toda tela do sistema (igual ao assistente), e
    fora do mural ele não tem os dados da página. Aqui ele pergunta — uma vez
    por carregamento — quem existe e quantas mensagens não foram lidas.

    Quem não abre o mural recebe `pode: false` e o widget NÃO APARECE. É a
    mesma porta da tela: o chat não cria acesso novo.
    """
    if not pode_ver_tela(request.user, TELA):
        return JsonResponse({"ok": True, "pode": False})
    return JsonResponse({
        "ok": True, "pode": True,
        "eu": _nome(request.user) or request.user.get_username(),
        "conversas": montar_conversas(request.user),
        "nao_lidas": MensagemDireta.objects.filter(para=request.user,
                                                   lida_em=None).count(),
    })


@staff_member_required
@require_POST
def mural_conversa(request):
    """A conversa com uma pessoa. Marca como lida o que ela me mandou.

    SÓ AS DUAS PESSOAS. O filtro é por par, não por "eu sou admin": não há
    parâmetro que faça esta view devolver a conversa de outros dois.
    """
    exigir(request.user, TELA)
    outro, erro = _o_outro(request)
    if erro:
        return erro

    fila = (MensagemDireta.objects
            .filter(Q(de=request.user, para=outro) | Q(de=outro, para=request.user))
            .select_related("de", "para").order_by("criado_em"))
    mensagens = [_msg_json(m, request.user) for m in fila[:400]]

    # Abrir a conversa é ler: marca as dela como lidas.
    MensagemDireta.objects.filter(de=outro, para=request.user,
                                  lida_em=None).update(lida_em=timezone.now())

    return JsonResponse({
        "ok": True,
        "com": {"id": outro.pk, "nome": _nome(outro) or outro.get_username()},
        "mensagens": mensagens,
        "nao_lidas": MensagemDireta.objects.filter(para=request.user,
                                                   lida_em=None).count(),
    })


@staff_member_required
@require_POST
def mural_mandar(request):
    """Manda uma mensagem. Pode citar um registro do sistema."""
    exigir(request.user, TELA)
    outro, erro = _o_outro(request)
    if erro:
        return erro

    texto = (request.POST.get("texto") or "").strip()
    arq = request.FILES.get("arquivo")
    if not texto and not arq:
        return JsonResponse({"ok": False, "erro": "Escreva algo ou anexe um arquivo."},
                            status=400)
    if len(texto) > 4000:
        return JsonResponse({"ok": False, "erro": "Mensagem acima de 4.000 letras."},
                            status=400)
    if arq:
        ext = arq.name.rsplit(".", 1)[-1].lower() if "." in arq.name else ""
        if ext not in MensagemDireta.FORMATOS:
            return JsonResponse(
                {"ok": False, "erro": "Formato não aceito."}, status=400)
        if arq.size > 16 * 1024 * 1024:
            return JsonResponse({"ok": False, "erro": "Arquivo acima de 16 MB."},
                                status=400)

    # O registro citado tem que ser visível PARA QUEM MANDA. Sem isso, dava
    # para descobrir o título de um registro de tela que não abre.
    chave = (request.POST.get("alvo") or "").strip()[:64]
    titulo = ""
    if chave:
        evento = _card_visivel(request.user, chave)
        if not evento:
            return JsonResponse({"ok": False, "erro": "Registro citado não encontrado."},
                                status=404)
        titulo = (evento["titulo"] or "")[:160]

    m = MensagemDireta.objects.create(
        de=request.user, para=outro, texto=texto, arquivo=arq,
        alvo=chave, alvo_titulo=titulo)
    return JsonResponse({"ok": True, "mensagem": _msg_json(m, request.user)})


@staff_member_required
@require_POST
def mural_apagar_comentario(request):
    """Apaga o próprio comentário. Comentário de outro só superusuário apaga."""
    exigir(request.user, TELA)
    c = ComentarioEvento.objects.filter(pk=id_ou_nada(request.POST.get("id"))).first()
    if not c:
        return JsonResponse({"ok": False, "erro": "Comentário não encontrado."},
                            status=404)
    if c.autor_id != request.user.pk and not request.user.is_superuser:
        return JsonResponse({"ok": False, "erro": "Só o autor apaga o comentário."},
                            status=403)
    c.delete()
    return JsonResponse({"ok": True})


def mural_orfaos():
    """Comentários cujo card não existe mais (o registro foi apagado).

    Não aparece em tela: é para conferência pelo shell, e para justificar a
    escolha de `chave` de texto no lugar de ForeignKey — ver models.py.
    """
    from django.contrib.auth.models import AnonymousUser  # noqa: F401
    vivos = set()
    for u in U.objects.filter(is_superuser=True)[:1]:
        vivos = {e["id"] for e in montar_eventos(u)}
    if not vivos:
        return ComentarioEvento.objects.none()
    return ComentarioEvento.objects.exclude(chave__in=vivos)
