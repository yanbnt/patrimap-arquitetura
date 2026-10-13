# -*- coding: utf-8 -*-
"""ARQUIVO DO PATRIMÔNIO — todo documento do parque em um só lugar.

POR QUE EXISTE
--------------
O sistema já EMITE papel o dia inteiro: protocolo de transferência, termo de
responsabilidade, etiqueta, orçamento, nota de compra do envio à autorizada.
Tudo isso saía impresso e morria na gaveta. Quando o RH precisa provar que o
notebook foi entregue — ou devolvido — não há onde olhar.

Esta tela é o lugar. E ela não é uma lista de anexos: é uma lista do que
DEVERIA existir. O que falta aparece como item faltando, e é isso que
transforma a pasta em fila de trabalho.

O DOSSIÊ NÃO É LISTA FIXA
-------------------------
O que cada pasta deve conter sai do que ACONTECEU com aquele equipamento:

    comprado                  → nota fiscal de compra
    está com um colaborador   → termo de entrega assinado
    tinha dono e não tem mais → termo de devolução assinado
    cada transferência        → um protocolo
    cada envio à autorizada   → laudo + orçamento + nota de serviço

É isso que faz "2 de 4" significar algo em vez de ser enfeite. E é isso que
mantém a tela verdadeira amanhã: quem transfere uma máquina hoje aumenta o
denominador dela sozinho.

QUATRO MANEIRAS DE CHEGAR NO MESMO DOCUMENTO
--------------------------------------------
· por EQUIPAMENTO — a pasta da máquina;
· por PESSOA      — o que o RH assina e cobra;
· por EVENTO      — porque o protocolo de uma transferência pertence à
                    transferência (que envolve DUAS lojas), e o laudo pertence
                    ao envio, não à máquina;
· por TIPO        — a visão de auditoria: "0 de 163 notas fiscais".

O mesmo documento aparece em mais de uma pasta de propósito. Ele tem um dono
só no banco; a tela é que oferece vários caminhos até ele.

DESENHO
-------
O servidor monta a árvore inteira uma vez e manda como JSON; a navegação
acontece no navegador. Com 162 equipamentos isso é da ordem de 100 KB e
troca 20 idas ao servidor por zero — um explorador que pisca a cada clique
não parece um explorador.
"""
import os

from django.contrib import admin as dj_admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.orgs.models import Person
from apps.parque.models import (
    Computador, DocumentoEquipamento, EnvioAutorizada, Notebook,
    TermoResponsabilidade, Transferencia, TransferenciaNotebook,
)


# Quem entra: o registro único de telas (apps/orgs/acessos.py) — o mesmo que o
# menu consulta e que a tela /parque/acessos/ edita.
TELA = "arquivo"

# Mantidos só por compatibilidade com quem importava daqui.
GRUPOS_ARQUIVO = ("Gerente", "Supervisor", "Visão total", "RH")


def pode_ler(user):
    from apps.orgs.acessos import pode_ver_tela
    return pode_ver_tela(user, TELA)


DOC = DocumentoEquipamento.Tipo
TERMO = TermoResponsabilidade

# Extensao -> rotulo curto do icone. So o que o FileField aceita.
ROTULO = {"pdf": "PDF", "png": "IMG", "jpg": "IMG", "jpeg": "IMG", "docx": "DOC"}

# Tipos agrupados para a visao por TIPO. Nota de compra e nota de servico sao
# papeis diferentes, mas na estante sao a mesma prateleira.
FAMILIAS = [
    ("nota", "Notas fiscais", (DOC.NOTA_COMPRA, DOC.NOTA_SERVICO)),
    ("termo", "Termos assinados", (DOC.TERMO,)),
    ("laudo", "Laudos tecnicos", (DOC.LAUDO,)),
    ("protocolo", "Protocolos e ordens", (DOC.PROTOCOLO, DOC.ORCAMENTO)),
    ("outro", "Outros arquivos", (DOC.OUTRO,)),
]
FAMILIA_DE = {t: fid for fid, _nome, tipos in FAMILIAS for t in tipos}


# ---------------------------------------------------------------- utilitários
def _id(valor):
    """id que veio do formulário, em int — ou None. `filter(pk="abc")` estoura
    ValueError, e a varredura do usuário leigo pegou exatamente isso no
    validar: letra no lugar do id dava 500 em vez de "não encontrado"."""
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return n if 0 < n <= 9223372036854775807 else None


def _dia(d):
    return d.strftime("%d/%m/%Y") if d else ""


def _rotulo(nome):
    ext = nome.rsplit(".", 1)[-1].lower() if "." in (nome or "") else ""
    return ROTULO.get(ext, "ARQ")


def _doc_json(d):
    """Um documento anexado, do jeito que a tela lê."""
    nome = os.path.basename(d.arquivo.name) if d.arquivo else ""
    return {
        "id": d.pk,
        "nome": d.descricao or d.get_tipo_display(),
        "arq": nome,
        "url": d.arquivo.url if d.arquivo else "",
        "kind": _rotulo(nome),
        "data": _dia(d.enviado_em),
        "estado": "validado" if d.validado_em else "arquivado",
        "tipo": FAMILIA_DE.get(d.tipo, "outro"),
        "por": (d.validado_por.get_full_name() or d.validado_por.get_username())
               if d.validado_por_id else "",
    }


def _emitir_url(alvo):
    """Onde o PRÓPRIO sistema imprime este papel.

    É o atalho que fecha o ciclo: emite, colhe a assinatura, escaneia e sobe o
    arquivo na mesma tela. Sem ele o usuário sabe que falta um protocolo e não
    sabe que o sistema o imprime desde sempre.
    """
    if len(alvo) < 3 or not alvo[2:].isdigit():
        return ""
    nome = {"tr": "parque_protocolo_transferencia",
            "tn": "parque_protocolo_notebook",
            "ea": "parque_protocolo_autorizada",
            "tm": "parque_termo_imprimir"}.get(alvo[:2])
    if not nome:
        return ""
    try:
        return reverse(nome, args=[int(alvo[2:])])
    except Exception:
        return ""


def _exigido(nome, tipo, porque, ok, alvo, doc_tipo):
    """Um item do dossiê. `alvo` diz onde o arquivo será pendurado se alguém
    anexar; `doc_tipo` diz com que tipo ele nasce — os dois juntos fazem o
    botão "Anexar" funcionar sem o navegador adivinhar nada."""
    return {"nome": nome, "tipo": tipo, "porque": porque, "ok": bool(ok),
            "alvo": alvo, "doc_tipo": doc_tipo, "emitir": _emitir_url(alvo)}


def _tem(docs, *tipos):
    return any(d.tipo in tipos for d in docs)


# ------------------------------------------------------------ por equipamento
def _pasta_equipamento(eq, ehNb, termos_de):
    docs = list(eq.documentos.all())
    alvo = ("nb%s" if ehNb else "pc%s") % eq.pk
    arquivos = [_doc_json(d) for d in docs]

    transf = list(eq.transferencias.all() if ehNb else eq.transferencias_loja.all())
    envios = list(eq.envios_autorizada.all())
    termos = termos_de.get(eq.pk, []) if ehNb else []
    # Computador não tem colaborador (quem "tem" um PC é a baia, não a pessoa);
    # Notebook tem. O mesmo montador serve os dois, então o dono é lido com
    # getattr — não com o campo, que só existe em um deles.
    pid = getattr(eq, "colaborador_id", None)
    dono = (eq.colaborador.full_name if pid else (getattr(eq, "usuario", "") or "")).strip()
    tem_dono = bool(dono)

    # Os termos entram na pasta como documentos, mesmo sem arquivo: um termo
    # aguardando assinatura É a informação.
    for t in termos:
        assinado = t.status == TERMO.Status.ASSINADO
        nome_t = os.path.basename(t.arquivo_assinado.name) if t.arquivo_assinado else ""
        arquivos.append({
            "id": "t%s" % t.pk,
            "nome": "Termo de %s — %s" % (t.get_tipo_display().lower(),
                                          t.colaborador_nome or "colaborador"),
            "arq": nome_t,
            "url": t.arquivo_assinado.url if t.arquivo_assinado else "",
            "kind": _rotulo(nome_t) if nome_t else "—",
            "data": _dia(t.criado_em),
            "estado": "assinado" if assinado else "aguardando assinatura",
            "tipo": "termo", "por": "",
        })

    exig = [_exigido("Nota fiscal de compra", "nota",
                     "todo equipamento comprado tem uma",
                     _tem(docs, DOC.NOTA_COMPRA), alvo, DOC.NOTA_COMPRA)]

    if ehNb and tem_dono:
        pend = [t for t in termos
                if t.tipo == TERMO.Tipo.ENTREGA and t.status != TERMO.Status.ASSINADO]
        assinado = any(t.tipo == TERMO.Tipo.ENTREGA and t.status == TERMO.Status.ASSINADO
                       for t in termos)
        exig.append(_exigido(
            "Termo de entrega assinado", "termo", "está com %s" % dono,
            assinado, ("tm%s" % pend[0].pk) if pend else alvo, DOC.TERMO))

    if ehNb and termos and not tem_dono:
        pend = [t for t in termos
                if t.tipo == TERMO.Tipo.DEVOLUCAO and t.status != TERMO.Status.ASSINADO]
        assinado = any(t.tipo == TERMO.Tipo.DEVOLUCAO and t.status == TERMO.Status.ASSINADO
                       for t in termos)
        exig.append(_exigido(
            "Termo de devolução assinado", "termo",
            "já foi entregue a alguém e voltou",
            assinado, ("tm%s" % pend[0].pk) if pend else alvo, DOC.TERMO))

    # UM protocolo POR transferência, cobrado na própria transferência. Somar
    # tudo num item só ("protocolos (3)") esconde qual das três está devendo.
    for t in transf:
        ev = ("tn%s" if ehNb else "tr%s") % t.pk
        data = _dia(getattr(t, "data_entrada", None) or getattr(t, "criado_em", None))
        exig.append(_exigido(
            "Protocolo de transferência%s" % ((" — " + data) if data else ""),
            "protocolo", "transferência registrada no sistema",
            _tem(list(t.documentos.all()), DOC.PROTOCOLO), ev, DOC.PROTOCOLO))

    for e in envios:
        docs_e = list(e.documentos.all())
        ev = "ea%s" % e.pk
        exig.append(_exigido("Laudo da autorizada", "laudo",
                             "foi para assistência externa",
                             _tem(docs_e, DOC.LAUDO), ev, DOC.LAUDO))
        exig.append(_exigido("Nota fiscal de serviço", "nota",
                             "serviço pago a terceiro",
                             _tem(docs_e, DOC.NOTA_SERVICO), ev, DOC.NOTA_SERVICO))

    marca = getattr(eq, "marca", "") or ""
    mod = getattr(eq, "modelo", "") or getattr(eq, "processador", "") or ""
    return {
        "id": alvo,
        "tipo": "Notebook" if ehNb else "Computador",
        "cod": eq.patrimonio or alvo.upper(),
        "modelo": (" ".join(x for x in [marca, mod] if x)).strip() or "sem modelo",
        "pessoa": dono,
        "serial": getattr(eq, "serial", "") or "",
        "alvo": alvo,
        "arquivos": arquivos,
        "exigidos": exig,
        "ok": sum(1 for e in exig if e["ok"]),
        "de": len(exig),
    }


def _pastas_equipamento():
    termos_de = {}
    for t in TERMO.objects.select_related("notebook").exclude(notebook=None):
        termos_de.setdefault(t.notebook_id, []).append(t)

    pastas = []
    nbs = (Notebook.objects.select_related("colaborador")
           .prefetch_related("documentos", "transferencias__documentos",
                             "envios_autorizada__documentos")
           .order_by("patrimonio"))
    for nb in nbs:
        pastas.append(_pasta_equipamento(nb, True, termos_de))

    pcs = (Computador.objects
           .prefetch_related("documentos", "transferencias_loja__documentos",
                             "envios_autorizada__documentos")
           .order_by("patrimonio"))
    for pc in pcs:
        pastas.append(_pasta_equipamento(pc, False, termos_de))
    return pastas


# ------------------------------------------------------------------ por pessoa
def _pastas_pessoa(pastas):
    """Uma pasta por NOME, não por cadastro.

    O cadastro tem homônimos e duplicatas (duas "Adriana" apontando para o
    mesmo notebook). Duas pastas idênticas lado a lado leem como bug; somadas,
    o duplicado vira um dado.
    """
    por_nome = {}
    ordem = []
    for p in Person.objects.prefetch_related("termos_responsabilidade").order_by("full_name"):
        termos = list(p.termos_responsabilidade.all())
        equip = [x for x in pastas if x["pessoa"] == p.full_name]
        if not termos and not equip:
            continue
        reg = por_nome.get(p.full_name)
        if reg is None:
            reg = {"id": "pe%s" % p.pk, "nome": p.full_name, "equip": [],
                   "cadastros": 0, "itens": [], "ok": 0, "de": 0}
            por_nome[p.full_name] = reg
            ordem.append(reg)
        reg["cadastros"] += 1
        for x in equip:
            if x["cod"] not in reg["equip"]:
                reg["equip"].append(x["cod"])
        for t in termos:
            assinado = t.status == TERMO.Status.ASSINADO
            nome_t = os.path.basename(t.arquivo_assinado.name) if t.arquivo_assinado else ""
            reg["itens"].append({
                "id": "t%s" % t.pk,
                "nome": "Termo de %s — %s" % (t.get_tipo_display().lower(),
                                              t.equipamento_desc or "equipamento"),
                "arq": nome_t,
                "url": t.arquivo_assinado.url if t.arquivo_assinado else "",
                "kind": _rotulo(nome_t) if nome_t else "—",
                "data": _dia(t.criado_em),
                "estado": "assinado" if assinado else "aguardando assinatura",
                "porque": "termo emitido pelo sistema",
                "alvo": "tm%s" % t.pk, "doc_tipo": DOC.TERMO,
            })

    # O dossiê da pessoa é o dos equipamentos que estão com ela: se ela tem
    # notebook e nenhum termo, falta um — e é isso que precisa aparecer.
    for reg in ordem:
        faltas = []
        for x in pastas:
            if x["pessoa"] != reg["nome"]:
                continue
            for e in x["exigidos"]:
                if e["tipo"] == "termo" and not e["ok"]:
                    faltas.append(dict(e, nome=e["nome"] + " — " + x["cod"],
                                       kind="falta", estado="não anexado", arq="",
                                       url="", data=""))
        reg["itens"] += faltas
        reg["ok"] = sum(1 for i in reg["itens"] if i.get("estado") == "assinado")
        reg["de"] = len(reg["itens"])
    return ordem


# ------------------------------------------------------------------ por evento
def _pastas_evento():
    eventos = []

    for t in (Transferencia.objects.select_related("computador")
              .prefetch_related("documentos")
              .select_related("baia_origem__setor__unidade",
                              "baia_destino__setor__unidade")
              .order_by("-id")[:120]):
        o = (t.baia_origem.setor.unidade.name
             if (t.baia_origem_id and t.baia_origem.setor_id
                 and t.baia_origem.setor.unidade_id) else "sem loja")
        d = (t.baia_destino.setor.unidade.name
             if (t.baia_destino_id and t.baia_destino.setor_id
                 and t.baia_destino.setor.unidade_id) else "sem loja")
        docs = list(t.documentos.all())
        eventos.append({
            "id": "tr%s" % t.pk, "alvo": "tr%s" % t.pk,
            # O título é o EQUIPAMENTO: "sem loja → sem loja" não identifica
            # nada, e quem procura procura pelo patrimônio.
            "titulo": (t.computador.patrimonio if t.computador_id else "") or "sem equipamento",
            "sub": "Transferência · %s → %s" % (o, d),
            "data": _dia(getattr(t, "data_entrada", None)),
            "arquivos": [_doc_json(x) for x in docs],
            "exigidos": [_exigido("Protocolo de transferência", "protocolo",
                                  "toda transferência emite um",
                                  _tem(docs, DOC.PROTOCOLO), "tr%s" % t.pk,
                                  DOC.PROTOCOLO)],
        })

    for t in (TransferenciaNotebook.objects.select_related("notebook")
              .prefetch_related("documentos").order_by("-id")[:120]):
        docs = list(t.documentos.all())
        eventos.append({
            "id": "tn%s" % t.pk, "alvo": "tn%s" % t.pk,
            "titulo": (t.notebook.patrimonio if t.notebook_id else "") or "notebook",
            "sub": "Transferência de notebook",
            "data": _dia(getattr(t, "criado_em", None) or getattr(t, "data", None)),
            "arquivos": [_doc_json(x) for x in docs],
            "exigidos": [_exigido("Protocolo de transferência", "protocolo",
                                  "toda transferência emite um",
                                  _tem(docs, DOC.PROTOCOLO), "tn%s" % t.pk,
                                  DOC.PROTOCOLO)],
        })

    for e in (EnvioAutorizada.objects
              .select_related("computador", "notebook", "autorizada")
              .prefetch_related("documentos").order_by("-id")[:120]):
        alvo_eq = e.computador or e.notebook
        docs = list(e.documentos.all())
        eventos.append({
            "id": "ea%s" % e.pk, "alvo": "ea%s" % e.pk,
            "titulo": (getattr(alvo_eq, "patrimonio", "") or "equipamento"),
            "sub": "Envio à autorizada · %s" % (e.autorizada.nome if e.autorizada_id
                                                else "sem autorizada"),
            "data": _dia(getattr(e, "data_envio", None) or getattr(e, "criado_em", None)),
            "arquivos": [_doc_json(x) for x in docs],
            "exigidos": [
                _exigido("Laudo técnico", "laudo", "diagnóstico do terceiro",
                         _tem(docs, DOC.LAUDO), "ea%s" % e.pk, DOC.LAUDO),
                _exigido("Orçamento aprovado", "protocolo", "custo autorizado",
                         _tem(docs, DOC.ORCAMENTO), "ea%s" % e.pk, DOC.ORCAMENTO),
                _exigido("Nota fiscal de serviço", "nota", "serviço pago",
                         _tem(docs, DOC.NOTA_SERVICO), "ea%s" % e.pk, DOC.NOTA_SERVICO),
            ],
        })

    for ev in eventos:
        ev["ok"] = sum(1 for x in ev["exigidos"] if x["ok"])
        ev["de"] = len(ev["exigidos"])
    return eventos


# -------------------------------------------------------------------- por tipo
def _pastas_tipo(pastas, eventos):
    tipos = []
    for fid, nome, _ts in FAMILIAS:
        tem = falta = 0
        itens = []
        # `onde` é o que muda de linha para linha nesta visão: o documento é
        # sempre o mesmo ("Nota fiscal de compra"), o equipamento é que varia.
        # Por isso a tela põe `onde` no título e o documento embaixo — 163
        # linhas com o mesmo título não são leitura.
        for p in pastas:
            for a in p["arquivos"]:
                if a["tipo"] == fid:
                    tem += 1
                    itens.append(dict(a, onde=p["cod"]))
            for e in p["exigidos"]:
                if e["tipo"] == fid and not e["ok"]:
                    falta += 1
                    itens.append(dict(e, onde=p["cod"], kind="falta",
                                      estado="não anexado", arq="", url="", data=""))
        for ev in eventos:
            for a in ev["arquivos"]:
                if a["tipo"] == fid:
                    tem += 1
                    itens.append(dict(a, onde=ev["titulo"] + " · " + ev["sub"]))
            for e in ev["exigidos"]:
                if e["tipo"] == fid and not e["ok"]:
                    falta += 1
                    itens.append(dict(e, onde=ev["titulo"] + " · " + ev["sub"],
                                      kind="falta", estado="não anexado",
                                      arq="", url="", data=""))
        tipos.append({"id": fid, "nome": nome, "tem": tem, "falta": falta,
                      "ok": tem, "de": tem + falta,
                      # A estante inteira não cabe na tela nem faz sentido:
                      # 163 linhas iguais não são leitura, são scroll.
                      "itens": itens[:80], "cortou": max(0, len(itens) - 80)})
    return tipos


# --------------------------------------------------------------------- a tela
@staff_member_required
def arquivo_central(request):
    from apps.orgs.acessos import exigir
    exigir(request.user, TELA)

    pastas = _pastas_equipamento()
    pessoas = _pastas_pessoa(pastas)
    eventos = _pastas_evento()
    tipos = _pastas_tipo(pastas, eventos)

    exigidos = sum(p["de"] for p in pastas) + sum(e["de"] for e in eventos)
    cumpridos = sum(p["ok"] for p in pastas) + sum(e["ok"] for e in eventos)

    dados = {
        "pastas": pastas, "pessoas": pessoas, "eventos": eventos, "tipos": tipos,
        "resumo": {
            "equipamentos": len(pastas),
            "exigidos": exigidos,
            "cumpridos": cumpridos,
            "arquivos": DocumentoEquipamento.objects.count(),
            "aguardando": TERMO.objects.filter(status=TERMO.Status.PENDENTE).count(),
            "notebooks": sum(1 for p in pastas if p["tipo"] == "Notebook"),
            "computadores": sum(1 for p in pastas if p["tipo"] == "Computador"),
        },
        "pode_anexar": request.user.has_perm("parque.add_documentoequipamento"),
        "pode_validar": request.user.has_perm("parque.change_documentoequipamento"),
    }

    ctx = {
        **dj_admin.site.each_context(request),
        "title": "Arquivo do patrimônio",
        "dados_js": dados,
        "resumo": dados["resumo"],
        "faltam": exigidos - cumpridos,
        "pc_montado": round(cumpridos / exigidos * 100) if exigidos else 0,
    }
    return render(request, "parque/arquivo.html", ctx)


# ------------------------------------------------------------------- anexar
def _pendurar(alvo, doc):
    """Liga o documento ao dono que o `alvo` nomeia. Devolve False se o alvo
    não existe — o que é erro de programação, não do usuário, mas vira 400 em
    vez de 500."""
    if len(alvo) < 3 or not alvo[2:].isdigit():
        return False
    campo = {"nb": "notebook_id", "pc": "computador_id", "tr": "transferencia_id",
             "tn": "transferencia_notebook_id", "ea": "envio_id"}.get(alvo[:2])
    if not campo:
        return False
    setattr(doc, campo, int(alvo[2:]))
    return True


@staff_member_required
@require_POST
def arquivo_anexar(request):
    """Sobe um arquivo para uma pasta do arquivo.

    Dois destinos possíveis: um TERMO já emitido (alvo `tm<id>` — o arquivo é a
    assinatura dele, e subir marca o termo como assinado) ou um documento novo
    pendurado no equipamento/evento que o `alvo` nomeia.
    """
    if not request.user.has_perm("parque.add_documentoequipamento"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para anexar documentos."},
                            status=403)

    arquivo = request.FILES.get("arquivo")
    if not arquivo:
        return JsonResponse({"ok": False, "erro": "Nenhum arquivo enviado."}, status=400)

    ext = arquivo.name.rsplit(".", 1)[-1].lower() if "." in arquivo.name else ""
    if ext not in DocumentoEquipamento.FORMATOS:
        return JsonResponse(
            {"ok": False, "erro": "Formato não aceito. Use PDF, PNG, JPEG ou DOCX."},
            status=400)

    alvo = (request.POST.get("alvo") or "").strip()
    tipo = (request.POST.get("tipo") or DOC.OUTRO).strip()
    if tipo not in DOC.values:
        tipo = DOC.OUTRO
    descricao = (request.POST.get("descricao") or "").strip()[:160]

    # Termo: o arquivo É a assinatura.
    if alvo.startswith("tm") and alvo[2:].isdigit():
        if not request.user.has_perm("parque.change_termoresponsabilidade"):
            return JsonResponse({"ok": False, "erro": "Sem permissão para alterar termos."},
                                status=403)
        termo = TERMO.objects.filter(pk=_id(alvo[2:])).first()
        if not termo:
            return JsonResponse({"ok": False, "erro": "Termo não encontrado."}, status=404)
        termo.arquivo_assinado = arquivo
        termo.save(update_fields=["arquivo_assinado"])
        termo.marcar_assinado()
        return JsonResponse({"ok": True, "msg": "Termo assinado arquivado.",
                             "recarregar": True})

    doc = DocumentoEquipamento(arquivo=arquivo, tipo=tipo, descricao=descricao,
                               enviado_por=request.user)
    if not _pendurar(alvo, doc):
        return JsonResponse({"ok": False, "erro": "Destino inválido."}, status=400)
    doc.save()
    return JsonResponse({"ok": True, "msg": "Documento arquivado.", "recarregar": True,
                         "doc": _doc_json(doc)})


@staff_member_required
@require_POST
def arquivo_validar(request):
    """Marca que uma pessoa conferiu o documento (é ato de gente, não do sistema)."""
    if not request.user.has_perm("parque.change_documentoequipamento"):
        return JsonResponse({"ok": False, "erro": "Sem permissão para validar documentos."},
                            status=403)

    doc = DocumentoEquipamento.objects.filter(pk=_id(request.POST.get("doc"))).first()
    if not doc:
        return JsonResponse({"ok": False, "erro": "Documento não encontrado."}, status=404)
    doc.marcar_validado(request.user)
    return JsonResponse({"ok": True, "msg": "Documento validado.",
                         "em": _dia(doc.validado_em) or _dia(timezone.now()),
                         "recarregar": True})
