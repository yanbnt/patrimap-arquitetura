"""Notificações internas exibidas no sino do cabeçalho.

Cada notificação pertence a um usuário (destinatario). Os eventos do sistema
(reparo aberto, atribuição/devolução, garantia vencendo) criam notificações via
o helper `notificar()`, normalmente para os usuários dos grupos responsáveis.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class Notificacao(models.Model):
    class Nivel(models.TextChoices):
        INFO = "info", "Informação"
        SUCESSO = "sucesso", "Sucesso"
        ALERTA = "alerta", "Alerta"

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="destinatário",
        on_delete=models.CASCADE, related_name="notificacoes",
    )
    titulo = models.CharField("título", max_length=160)
    mensagem = models.CharField("mensagem", max_length=300, blank=True)
    url = models.CharField(
        "link", max_length=300, blank=True,
        help_text="Para onde levar ao clicar (ex.: a tela do reparo).",
    )
    icone = models.CharField(
        "ícone", max_length=40, default="notifications",
        help_text="Nome do ícone Material Symbols.",
    )
    nivel = models.CharField(
        "nível", max_length=10, choices=Nivel.choices, default=Nivel.INFO,
    )
    lida = models.BooleanField("lida", default=False)
    fixa = models.BooleanField(
        "fixa", default=False,
        help_text="Fica presa no topo do sino até ser resolvida (ex.: aprovar/negar). "
                  "Não some ao marcar tudo como lido.",
    )
    chave = models.CharField(
        "chave", max_length=60, blank=True, db_index=True,
        help_text="Identifica o item de origem (ex.: 'transf:123') para desduplicar e resolver.",
    )
    acao_ok_url = models.CharField("URL aprovar", max_length=300, blank=True)
    acao_no_url = models.CharField("URL negar", max_length=300, blank=True)
    criada_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "notificação"
        verbose_name_plural = "notificações"
        ordering = ["-criada_em"]
        indexes = [models.Index(fields=["destinatario", "lida", "-criada_em"])]

    def __str__(self):
        return f"{self.titulo} → {self.destinatario}"


def usuarios_dos_grupos(*nomes):
    """Usuários ativos que pertencem a algum dos grupos informados."""
    return User.objects.filter(
        is_active=True, groups__name__in=nomes,
    ).distinct()


def notificar(usuarios, titulo, mensagem="", url="", icone="notifications",
              nivel=Notificacao.Nivel.INFO, excluir=None,
              fixa=False, chave="", acao_ok_url="", acao_no_url=""):
    """Cria uma notificação para cada usuário.

    `usuarios` pode ser um QuerySet, lista de User ou um único User.
    `excluir` (User) tira alguém da lista — ex.: não notificar quem fez a ação.
    `fixa`/`chave`/`acao_ok_url`/`acao_no_url`: notificação de ação (aprovar/negar)
    que fica presa no topo até ser resolvida.
    """
    if usuarios is None:
        return
    if isinstance(usuarios, User):
        usuarios = [usuarios]
    objs = [
        Notificacao(
            destinatario=u, titulo=titulo, mensagem=mensagem,
            url=url, icone=icone, nivel=nivel,
            fixa=fixa, chave=chave, acao_ok_url=acao_ok_url, acao_no_url=acao_no_url,
        )
        for u in usuarios
        if u and (excluir is None or u.pk != excluir.pk)
    ]
    if objs:
        Notificacao.objects.bulk_create(objs)
