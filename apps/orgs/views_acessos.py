# -*- coding: utf-8 -*-
"""USUÁRIOS E ACESSOS — uma tela no lugar de três.

Era: a lista de usuários do admin, a lista de grupos do admin, e o mapa
"qual grupo abre qual tela" que não existia em tela nenhuma — vivia espalhado
nas condições do menu e dentro de cada view.

Aqui: a pessoa é o CHIP no meio da placa, cada grupo é um COMPONENTE em volta
carregando os balões das telas que destrava, e ligar o acesso fecha o
circuito. O desenho não é enfeite: ele mostra de uma vez o que três telas
juntas não mostravam — que o grupo Diretor não abria tela nenhuma, que Gerente
e Supervisor eram idênticos, e quem estava sem grupo.

DUAS COISAS SE SALVAM AQUI, COM PERMISSÕES DIFERENTES
-----------------------------------------------------
· pessoa ↔ grupo — quem abre a tela pode mexer, com uma trava: ninguém entrega
  um acesso que ele mesmo não tem (só superusuário escapa dela);
· grupo → tela — reservado a SUPERUSUÁRIO. Isto reescreve o acesso de todo
  mundo de uma vez; não é operação de rotina.

Nada aqui inventa regra: o que a tela lê e escreve é o registro de
apps/orgs/acessos.py, o mesmo que o menu consulta e as views obedecem.
"""
from django.contrib import admin as dj_admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.orgs.acessos import (
    ABERTAS, POR_ID, RESTRITAS, TELAS, exigir, mapa_completo, pode_ver_tela,
    telas_do_usuario,
)
from apps.orgs.models import TelaGrupo

TELA = "acessos"
U = get_user_model()

# Maior inteiro que o banco guarda. Acima disso a consulta nem chega lá.
LIMITE_ID = 9223372036854775807


def _id(valor):
    """id que veio do formulário, em int — ou None.

    `filter(pk="abc")` estoura ValueError, e a varredura do usuário leigo
    achou isto em três rotas desta tela: mandar letra no lugar do id dava 500
    em vez de "não encontrado".
    """
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return n if 0 < n <= LIMITE_ID else None


def _inicial(nome):
    partes = [p for p in (nome or "?").split() if p]
    if len(partes) >= 2:
        return (partes[0][0] + partes[-1][0]).upper()
    return (partes[0][:2] if partes else "?").upper()


def _dados(user_atual):
    mapa = mapa_completo()
    grupos = []
    for g in Group.objects.prefetch_related("user_set").order_by("name"):
        ids = sorted([t.id for t in TELAS if g.name in mapa.get(t.id, set())],
                     key=lambda i: [x.id for x in TELAS].index(i))
        grupos.append({
            "id": g.pk, "nome": g.name, "membros": g.user_set.count(),
            "telas": ids, "vazio": not ids,
        })

    usuarios = []
    for u in U.objects.prefetch_related("groups").order_by("-is_superuser", "username"):
        nome = u.get_full_name() or u.get_username()
        usuarios.append({
            "id": u.pk, "user": u.get_username(), "nome": nome,
            "inicial": _inicial(nome), "su": bool(u.is_superuser),
            "staff": bool(u.is_staff), "ativo": bool(u.is_active),
            "grupos": [g.name for g in u.groups.all()],
            "email": u.email or "",
            "telas": len(telas_do_usuario(u, mapa)),
        })

    return {
        "telas": [{"id": t.id, "nome": t.nome, "url": t.url, "ic": t.icone,
                   "grupos": sorted(mapa.get(t.id, set())), "aberta": not t.grupos}
                  for t in TELAS],
        "pode_grupo": bool(user_atual.is_superuser),
        "grupos": grupos,
        "usuarios": usuarios,
        "restritas": [t.id for t in RESTRITAS],
        "abertas": [t.id for t in ABERTAS],
        "eu": user_atual.get_username(),
        "pode_pessoa": True,
        "pode_mapa": bool(user_atual.is_superuser),
    }


@staff_member_required
def acessos(request):
    exigir(request.user, TELA)
    dados = _dados(request.user)
    return render(request, "orgs/acessos.html", {
        **dj_admin.site.each_context(request),
        "title": "Usuários e acessos",
        "dados_js": dados,
        "n_pessoas": len(dados["usuarios"]),
        "n_grupos": len(dados["grupos"]),
        "n_telas": len(dados["telas"]),
        "n_restritas": len(dados["restritas"]),
    })


# ---------------------------------------------------------------- pessoa ↔ grupo
@staff_member_required
@require_POST
def acessos_salvar_pessoa(request):
    """Grava os grupos de uma pessoa.

    A TRAVA: quem não é superusuário não pode conceder grupo que destrave tela
    que ele mesmo não vê. Sem isso, quem tem esta tela consegue se promover
    (ou promover um colega) a qualquer coisa — inclusive ao que decide custo.
    """
    exigir(request.user, TELA)

    alvo = U.objects.filter(pk=_id(request.POST.get("usuario"))).first()
    if not alvo:
        return JsonResponse({"ok": False, "erro": "Usuário não encontrado."}, status=404)

    # A GUARDA DE ALVO VEM ANTES DE OLHAR O DELTA. Estava depois, e por isso um
    # POST de não-superusuário para um superusuário SEM mudança nenhuma passava
    # com 200 ("nada mudou") em vez de 403 — o teste pegou. Guarda que só vale
    # quando há mudança não é guarda: é sorte.
    if not request.user.is_superuser and alvo.is_superuser:
        return JsonResponse(
            {"ok": False, "erro": "Só superusuário mexe nos grupos de um superusuário."},
            status=403)

    pedidos = set(filter(None, request.POST.getlist("grupos")))
    existentes = {g.name: g for g in Group.objects.filter(name__in=pedidos)}
    if len(existentes) != len(pedidos):
        faltam = sorted(pedidos - set(existentes))
        return JsonResponse({"ok": False, "erro": "Grupo inexistente: " + ", ".join(faltam)},
                            status=400)

    tinha = set(alvo.groups.values_list("name", flat=True))
    entrando, saindo = pedidos - tinha, tinha - pedidos
    if not entrando and not saindo:
        return JsonResponse({"ok": True, "msg": "Nada mudou."})

    if not request.user.is_superuser:
        mapa = mapa_completo()
        minhas = telas_do_usuario(request.user, mapa)
        for nome in sorted(entrando):
            dando = {tid for tid, gs in mapa.items() if nome in gs}
            fora = sorted(dando - minhas)
            if fora:
                return JsonResponse({
                    "ok": False,
                    "erro": ("Você não pode conceder o grupo %s: ele destrava %s, "
                             "que você não vê." % (
                                 nome,
                                 ", ".join(POR_ID[t].nome for t in fora if t in POR_ID))),
                }, status=403)

    with transaction.atomic():
        alvo.groups.set(existentes.values())

    partes = []
    if entrando:
        partes.append("+ " + ", ".join(sorted(entrando)))
    if saindo:
        partes.append("− " + ", ".join(sorted(saindo)))
    return JsonResponse({
        "ok": True,
        "msg": "%s: %s" % (alvo.get_full_name() or alvo.get_username(), " · ".join(partes)),
        "telas": len(telas_do_usuario(alvo)),
    })


# ------------------------------------------------------------- criar e excluir
# Esta tela substituiu /admin/auth/group/ no menu. Sem criar e excluir, ela
# substituiu pela metade: para abrir um grupo novo a pessoa tinha de voltar ao
# admin — e aí a tela nova era um enfeite no caminho.
@staff_member_required
@require_POST
def acessos_criar_grupo(request):
    """Cria um grupo. Só superusuário: grupo novo é peça de acesso."""
    exigir(request.user, TELA)
    if not request.user.is_superuser:
        return JsonResponse({"ok": False, "erro": "Criar grupo é restrito a superusuário."},
                            status=403)

    nome = (request.POST.get("nome") or "").strip()
    if len(nome) < 2:
        return JsonResponse({"ok": False, "erro": "O nome precisa de pelo menos 2 letras."},
                            status=400)
    if len(nome) > 150:
        return JsonResponse({"ok": False, "erro": "Nome muito longo (máximo 150)."},
                            status=400)
    if Group.objects.filter(name__iexact=nome).exists():
        return JsonResponse({"ok": False, "erro": "Já existe um grupo com esse nome."},
                            status=400)

    grupo = Group.objects.create(name=nome)

    # Pode nascer já destravando telas — é o caso comum: cria "Diretoria" e
    # marca as três telas na mesma ida.
    pedidas = set(request.POST.getlist("telas")) & {t.id for t in RESTRITAS}
    if pedidas:
        TelaGrupo.objects.bulk_create(
            [TelaGrupo(grupo=grupo, tela=t, criado_por=request.user) for t in pedidas],
            ignore_conflicts=True)

    return JsonResponse({"ok": True, "msg": "Grupo %s criado." % nome, "recarregar": True})


@staff_member_required
@require_POST
def acessos_excluir_grupo(request):
    """Apaga um grupo VAZIO.

    Com gente dentro, apagar tira acesso de todo mundo de uma vez e sem
    rastro — então aqui não apaga: diz quantas pessoas tirar primeiro. É o tipo
    de operação que não deve ser possível por engano.
    """
    exigir(request.user, TELA)
    if not request.user.is_superuser:
        return JsonResponse({"ok": False, "erro": "Excluir grupo é restrito a superusuário."},
                            status=403)

    grupo = Group.objects.filter(pk=_id(request.POST.get("grupo"))).first()
    if not grupo:
        return JsonResponse({"ok": False, "erro": "Grupo não encontrado."}, status=404)

    n = grupo.user_set.count()
    if n:
        return JsonResponse({
            "ok": False,
            "erro": ("%s ainda tem %d pessoa(s) dentro. Tire as pessoas do grupo "
                     "antes de excluir — assim você vê quem perde acesso." % (grupo.name, n)),
        }, status=400)

    nome = grupo.name
    with transaction.atomic():
        TelaGrupo.objects.filter(grupo=grupo).delete()
        grupo.delete()
    return JsonResponse({"ok": True, "msg": "Grupo %s excluído." % nome, "recarregar": True})


# ----------------------------------------------------------------- grupo → tela
@staff_member_required
@require_POST
def acessos_salvar_grupo(request):
    """Grava quais telas um grupo destrava. Só superusuário.

    Isto reescreve o acesso de todos os membros do grupo de uma vez — e o menu
    e as views passam a obedecer no próximo clique. Não é operação de rotina.
    """
    exigir(request.user, TELA)
    if not request.user.is_superuser:
        return JsonResponse(
            {"ok": False, "erro": "Mudar o que um grupo destrava é restrito a superusuário."},
            status=403)

    grupo = Group.objects.filter(pk=_id(request.POST.get("grupo"))).first()
    if not grupo:
        return JsonResponse({"ok": False, "erro": "Grupo não encontrado."}, status=404)

    pedidas = set(request.POST.getlist("telas"))
    validas = {t.id for t in RESTRITAS}
    invalidas = pedidas - validas
    if invalidas:
        return JsonResponse(
            {"ok": False,
             "erro": ("Tela fora da lista, ou aberta a toda a equipe: "
                      + ", ".join(sorted(invalidas)))},
            status=400)

    tinha = set(TelaGrupo.objects.filter(grupo=grupo).values_list("tela", flat=True))
    entrando, saindo = pedidas - tinha, tinha - pedidas

    with transaction.atomic():
        if saindo:
            TelaGrupo.objects.filter(grupo=grupo, tela__in=saindo).delete()
        if entrando:
            TelaGrupo.objects.bulk_create(
                [TelaGrupo(grupo=grupo, tela=t, criado_por=request.user) for t in entrando],
                ignore_conflicts=True)
        # Tela restrita que ficou sem NENHUM grupo passa a ser de superusuário
        # só — não volta ao padrão do código (ver grupos_da_tela). Quem tira
        # todos os grupos está trancando a tela, e é isso que acontece.

    partes = []
    if entrando:
        partes.append("+ " + ", ".join(sorted(POR_ID[t].nome for t in entrando)))
    if saindo:
        partes.append("− " + ", ".join(sorted(POR_ID[t].nome for t in saindo)))
    return JsonResponse({"ok": True, "msg": "%s: %s" % (grupo.name, " · ".join(partes) or "nada"),
                         "recarregar": True})
