"""
Sinais do app orgs.

Ao atribuir um cargo (grupo) a um usuário, marca automaticamente "Membro da
equipe" (is_staff) — todos os cargos do sistema precisam acessar o painel.
Evita o erro de login "conta de equipe" por esquecer de marcar a opção.
"""

from django.contrib.auth.models import User
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from .models import LogAcesso, PerfilUsuario, Person


@receiver(m2m_changed, sender=User.groups.through)
def liberar_acesso_ao_receber_cargo(sender, instance, action, **kwargs):
    if action == "post_add" and isinstance(instance, User):
        if not instance.is_staff and instance.groups.exists():
            instance.is_staff = True
            instance.save(update_fields=["is_staff"])


@receiver(post_save, sender=Person)
def desligar_pessoa_desliga_a_conta(sender, instance, **kwargs):
    """Quem sai da empresa para de entrar no sistema. No mesmo instante.

    MEDIDO EM 13/10/2026, antes de existir esta regra: `Person.active = False`
    não encostava em `User.is_active`. Eram dois campos independentes, em duas
    telas diferentes, sem nada ligando um ao outro — então marcar alguém como
    desligado no cadastro não fechava porta nenhuma. O caso que achou isto foi
    o Alberto Pinheiro: fora da empresa, conta abrindo 11 telas.

    Desativar a conta é imediato e completo (também medido): mata a sessão já
    aberta — o próximo clique cai no login — e recusa novo login. E não encosta
    em baia, computador, notebook nem nos logs. O patrimônio dela continua
    rastreado; o que acaba é o acesso.

    SÓ VAI NUM SENTIDO, de propósito. Religar a pessoa NÃO religa a conta:
    devolver acesso é decisão de quem administra, com nome e hora, não efeito
    colateral de uma edição de cadastro. Fechar errado se conserta num clique;
    abrir errado ninguém fica sabendo.

    O superusuário é poupado: desligar o cadastro de quem administra o sistema
    e, com isso, trancar a própria porta de volta é um jeito de ficar sem
    ninguém com acesso. Essa decisão tem de ser explícita.
    """
    desligada = (not instance.active) or bool(instance.data_desligamento)
    if not desligada or not instance.user_id:
        return
    # `update()` em vez de `save()`: não re-dispara signal de User (que voltaria
    # aqui pelo `garantir_colaborador_do_usuario`) e não mexe em mais nada.
    User.objects.filter(
        pk=instance.user_id, is_active=True, is_superuser=False,
    ).update(is_active=False)


@receiver(post_save, sender=User)
def garantir_colaborador_do_usuario(sender, instance, **kwargs):
    """Todo usuário da equipe (admin/staff) também é um Colaborador (Person).

    Vincula a um Person existente (por e-mail ou nome) ou cria um novo, ligado
    pela OneToOne `Person.user`. Idempotente: se já houver vínculo, não faz nada.
    """
    if not instance.is_staff:
        return
    ja = Person.objects.filter(user=instance).first()
    if ja is not None:
        # Mantém o e-mail do colaborador em dia quando o usuário tiver um e ele
        # ainda estiver vazio.
        email_u = (instance.email or "").strip()
        if email_u and not ja.email:
            ja.email = email_u
            ja.save(update_fields=["email"])
        return
    nome = (instance.get_full_name() or instance.username).strip()
    email = (instance.email or "").strip()
    pessoa = None
    if email:
        pessoa = Person.objects.filter(email__iexact=email, user__isnull=True).first()
    if pessoa is None and nome:
        pessoa = Person.objects.filter(full_name__iexact=nome, user__isnull=True).first()
    if pessoa is None:
        pessoa = Person(full_name=nome or instance.username, active=True)
    pessoa.user = instance
    if email and not pessoa.email:
        pessoa.email = email
    pessoa.save()


@receiver(post_save, sender=PerfilUsuario)
def sincronizar_loja_do_colaborador(sender, instance, **kwargs):
    """A 'loja' definida no usuário vai para o colaborador vinculado (Person.location),
    que é a fonte da visão unificada de colaboradores nos mapas."""
    if not instance.unidade_id:
        return
    person = getattr(instance.usuario, "colaborador", None)
    if person is not None and person.location_id != instance.unidade_id:
        person.location_id = instance.unidade_id
        person.save(update_fields=["location"])  # dispara a garantia de baia (app parque)


# --- Log de acessos (login / logout / falha) ---------------------------------
def _ip(request):
    return request.META.get("REMOTE_ADDR") if request else None


def _ua(request):
    return (request.META.get("HTTP_USER_AGENT", "")[:300]) if request else ""


@receiver(user_logged_in)
def _log_login(sender, request, user, **kwargs):
    LogAcesso.objects.create(
        usuario=user, evento=LogAcesso.Evento.LOGIN, ip=_ip(request), user_agent=_ua(request),
    )


@receiver(user_logged_out)
def _log_logout(sender, request, user, **kwargs):
    LogAcesso.objects.create(
        usuario=user, evento=LogAcesso.Evento.LOGOUT, ip=_ip(request), user_agent=_ua(request),
    )


@receiver(user_login_failed)
def _log_falha(sender, credentials, request=None, **kwargs):
    LogAcesso.objects.create(
        username_tentado=(credentials or {}).get("username", "")[:150],
        evento=LogAcesso.Evento.FALHA, ip=_ip(request), user_agent=_ua(request),
    )
