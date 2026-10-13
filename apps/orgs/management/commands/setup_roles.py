"""
Cria/atualiza os papéis (grupos de permissão) do sistema.

Uso:
    python manage.py setup_roles

Idempotente — pode rodar quantas vezes quiser. Para aplicar um papel a alguém:
Admin → Usuários → (editar usuário) → marcar "Membro da equipe" e escolher o Grupo.
"""

from django.apps import apps as django_apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

OUR_APPS = ["parque", "inventory", "maintenance", "catalog", "orgs"]
CRUD = ["add", "change", "delete", "view"]


def model_perms(app_label, model_name, actions):
    model = django_apps.get_model(app_label, model_name)
    ct = ContentType.objects.get_for_model(model)
    out = []
    for a in actions:
        p = Permission.objects.filter(
            content_type=ct, codename=f"{a}_{model_name}"
        ).first()
        if p:
            out.append(p)
    return out


def app_perms(app_label, actions):
    out = []
    for model in django_apps.get_app_config(app_label).get_models():
        out += model_perms(app_label, model._meta.model_name, actions)
    return out


def apps_perms(app_labels, actions):
    out = []
    for app_label in app_labels:
        out += app_perms(app_label, actions)
    return out


class Command(BaseCommand):
    help = "Cria/atualiza os grupos de papéis e suas permissões."

    def handle(self, *args, **opts):
        papeis = {}

        # Gerente — todas as permissões do sistema (poder total).
        papeis["Gerente"] = list(Permission.objects.all())

        # Supervisor — CRUD completo em todos os apps do sistema.
        papeis["Supervisor"] = apps_perms(OUR_APPS, CRUD)

        # Técnico de Pós Venda — CRUD completo no Parque; ver o resto; e gerenciar
        # contas de acesso (ver/editar/excluir usuários) — desligamento de colaborador.
        papeis["Técnico de Pós Venda"] = (
            app_perms("parque", CRUD)
            + apps_perms(["inventory", "maintenance", "catalog", "orgs"], ["view"])
            + model_perms("auth", "user", ["view", "change", "delete"])
        )

        # Estagiário — transferências (criar) + alterar info do computador
        # (sem excluir); ver o resto.
        papeis["Estagiário"] = (
            app_perms("parque", ["view"])
            + model_perms("parque", "transferencia", ["add", "change"])
            + model_perms("parque", "baia", ["change"])
            + apps_perms(["inventory", "maintenance", "catalog", "orgs"], ["view"])
        )

        # Diretor — somente visualização.
        papeis["Diretor"] = apps_perms(OUR_APPS, ["view"])

        # Controle de Notebooks — foco em notebooks: ver/cadastrar/editar notebooks
        # (sem excluir), gerar/gerir termos de responsabilidade, alocar em baias,
        # ver estoque e colaboradores. Acesso restrito (sem superusuário).
        papeis["Controle de Notebooks"] = (
            model_perms("parque", "notebook", ["view", "add", "change"])
            + model_perms("parque", "termoresponsabilidade", ["view", "add", "change"])
            + model_perms("parque", "transferencianotebook", ["view", "add", "change"])
            + model_perms("parque", "baia", ["view", "change"])
            + model_perms("parque", "computador", ["view"])
            + model_perms("orgs", "person", ["view"])
        )

        for nome, perms in papeis.items():
            grupo, _ = Group.objects.get_or_create(name=nome)
            grupo.permissions.set(perms)
            self.stdout.write(self.style.SUCCESS(
                f"  {nome}: {grupo.permissions.count()} permissoes"
            ))
        self.stdout.write(self.style.SUCCESS("Papeis configurados."))
