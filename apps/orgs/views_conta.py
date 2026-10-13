# -*- coding: utf-8 -*-
"""A CONTA DE ACESSO, pela ficha do colaborador.

Era preciso ir a `/admin/auth/user/` para desativar alguém — uma tela que saiu
do menu quando a de Acessos nasceu, e à qual ninguém mais chega. O resultado
estava no banco: contas de gente que não trabalha mais na empresa, ativas,
porque o caminho para fechá-las não existia na prática.

Aqui a conta é tratada de onde o assunto aparece: a ficha da pessoa.

POR QUE DESATIVAR, E NÃO EXCLUIR
--------------------------------
Excluir leva junto o rastro: quem fez o quê, quando entrou, o que assinou.
Desativar é imediato, reversível e auditável — e, medido em 13/10/2026, é
completo: mata a sessão já aberta (o próximo clique cai no login), recusa novo
login, e não encosta em baia, computador nem notebook. O patrimônio continua
rastreado; o que acaba é o acesso.

Por isso não existe aqui uma rota de excluir conta. Quem precisar mesmo
apagar usa o admin, que mostra o que vai junto antes de confirmar.

A OUTRA PONTA
-------------
Desligar a PESSOA desativa a conta sozinho — `desligar_pessoa_desliga_a_conta`
(apps/orgs/signals.py). Estas rotas são para o caso inverso: a pessoa continua
na empresa e o acesso é que precisa parar (afastamento, troca de função,
suspeita de senha vazada).
"""
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import LogAcesso, PerfilUsuario, Person
from .views import gerar_senha_temporaria

U = get_user_model()


def _sem_poder(request, perm="auth.change_user", alvo=None):
    """Devolve a recusa, ou None quando pode. JSON, não exceção.

    `PermissionDenied` aqui seria errado: o projeto tem
    `handler403 = config.urls.acesso_negado`, que REDIRECIONA para uma tela de
    aviso. Isso é bom para quem clicou num link e ótimo de ler — e inútil para
    um `fetch`, que seguiria o desvio em silêncio e receberia HTML onde espera
    JSON. A ficha ficaria "pensando" sem dizer nada.

    `auth.change_user` é o portão. O segundo degrau impede quem tem essa
    permissão de desativar um superusuário e, com isso, assumir o sistema:
    superusuário só é mexido por superusuário.
    """
    if not request.user.is_authenticated or not request.user.has_perm(perm):
        return _erro("Você não tem permissão para mexer em contas de acesso.", 403)
    if alvo is not None and alvo.is_superuser and not request.user.is_superuser:
        return _erro("Só um superusuário mexe na conta de outro superusuário.", 403)
    return None


def _erro(texto, status=400):
    return JsonResponse({"ok": False, "erro": texto}, status=status)


@require_POST
def conta_desativar(request, pk):
    """Fecha o acesso da conta ligada a este colaborador."""
    pessoa = get_object_or_404(Person.objects.select_related("user"), pk=pk)
    conta = pessoa.user
    if conta is None:
        return _erro("Este colaborador não tem conta de acesso.")
    recusa = _sem_poder(request, alvo=conta)
    if recusa:
        return recusa

    # Trancar a si mesmo para fora é irreversível pela própria tela: depois do
    # clique não há sessão para desfazer o clique.
    if conta.pk == request.user.pk:
        return _erro("Você não pode desativar a sua própria conta.")
    if not conta.is_active:
        return _erro("A conta já está desativada.")

    conta.is_active = False
    conta.save(update_fields=["is_active"])
    LogAcesso.objects.create(
        usuario=conta, evento=LogAcesso.Evento.LOGOUT,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=("conta desativada por " + request.user.get_username())[:300],
    )
    return JsonResponse({
        "ok": True, "ativa": False, "usuario": conta.get_username(),
        "nome": pessoa.full_name,
        "aviso": "Acesso encerrado agora. A sessão aberta, se houver, cai no "
                 "próximo clique. O cadastro e o histórico ficam.",
    })


@require_POST
def conta_ativar(request, pk):
    """Devolve o acesso. Decisão explícita — nenhum signal faz isto sozinho."""
    pessoa = get_object_or_404(Person.objects.select_related("user"), pk=pk)
    conta = pessoa.user
    if conta is None:
        return _erro("Este colaborador não tem conta de acesso.")
    recusa = _sem_poder(request, alvo=conta)
    if recusa:
        return recusa
    if conta.is_active:
        return _erro("A conta já está ativa.")

    # Reativar o acesso de quem está marcado como DESLIGADO devolveria, no
    # próximo save do cadastro, exatamente o que o signal acabou de tirar — e a
    # pessoa ficaria com acesso oscilando sem ninguém entender por quê.
    if (not pessoa.active) or pessoa.data_desligamento:
        return _erro(
            "Este colaborador está marcado como desligado. Reative o cadastro "
            "dele primeiro — senão o acesso é fechado de novo no próximo save."
        )

    conta.is_active = True
    conta.save(update_fields=["is_active"])
    return JsonResponse({
        "ok": True, "ativa": True, "usuario": conta.get_username(),
        "nome": pessoa.full_name,
        "aviso": "Acesso devolvido. A senha continua sendo a mesma de antes — "
                 "se ninguém a conhece, use “Redefinir senha”.",
    })


@require_POST
def conta_criar(request, pk):
    """Cria a conta de acesso de um colaborador que ainda não tem.

    Existir no cadastro e entrar no sistema são coisas separadas de propósito
    (`Person.user` é nulo): quem só recebe equipamento não precisa de login.
    Esta rota é o caminho de quem passou a precisar.

    O usuário nasce SEM GRUPO: acesso se concede na ficha, um a um, depois de
    alguém decidir. Conta nova que já nasce podendo tudo é como se perde a
    conta do que cada um abre.
    """
    recusa = _sem_poder(request, "auth.add_user")
    if recusa:
        return recusa

    pessoa = get_object_or_404(Person.objects.select_related("user"), pk=pk)
    if pessoa.user_id:
        return _erro("Este colaborador já tem conta de acesso.")
    if (not pessoa.active) or pessoa.data_desligamento:
        return _erro("Este colaborador está desligado. Reative o cadastro antes "
                     "de criar uma conta de acesso.")

    usuario = _username_livre(pessoa.full_name)
    if usuario is None:
        return _erro("Não consegui montar um nome de usuário a partir deste "
                     "nome. Crie a conta pelo admin.")

    senha = gerar_senha_temporaria()

    # A ORDEM AQUI NÃO É ESTILO, É O ÚNICO JEITO QUE FUNCIONA.
    #
    # `garantir_colaborador_do_usuario` (signals.py) cria um Person para todo
    # usuário STAFF, e ele roda DENTRO do create_user. Criando já com
    # is_staff=True, o signal não acha vínculo, cria uma segunda ficha, e o
    # `pessoa.user = conta` seguinte estoura:
    #     UNIQUE constraint failed: orgs_person.user_id
    #
    # Então: nasce sem staff (o signal passa direto), liga-se a pessoa que JÁ
    # existe, e só aí vira staff — quando o signal roda de novo, acha o
    # vínculo e não faz nada.
    conta = U.objects.create_user(
        username=usuario, email=(pessoa.email or ""), password=senha,
    )
    pessoa.user = conta
    pessoa.save(update_fields=["user"])
    conta.is_staff = True
    conta.save(update_fields=["is_staff"])

    PerfilUsuario.objects.update_or_create(
        usuario=conta,
        defaults={"senha_temporaria": True, "senha_temporaria_em": timezone.now()},
    )
    return JsonResponse({
        "ok": True, "usuario": conta.get_username(), "senha": senha,
        "nome": pessoa.full_name,
        "aviso": "A senha aparece uma vez só e tem de ser trocada no primeiro "
                 "acesso. A conta nasce sem grupo nenhum — libere as telas "
                 "abaixo.",
    })


def _username_livre(nome_completo):
    """Monta um nome de usuário a partir do nome, sem colidir.

    "João Bernardes" -> joao.bernardes; se existir, joao.bernardes2, 3...
    Devolve None quando não sobra letra nenhuma (nome só com símbolos).
    """
    import re
    import unicodedata

    sem_acento = unicodedata.normalize("NFKD", nome_completo or "")
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    partes = [p for p in re.split(r"[^A-Za-z0-9]+", sem_acento) if p]
    if not partes:
        return None
    base = (partes[0] + ("." + partes[-1] if len(partes) > 1 else "")).lower()[:140]

    if not U.objects.filter(username__iexact=base).exists():
        return base
    for n in range(2, 100):
        tentativa = f"{base}{n}"
        if not U.objects.filter(username__iexact=tentativa).exists():
            return tentativa
    return None
