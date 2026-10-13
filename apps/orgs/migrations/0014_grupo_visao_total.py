"""Cria o grupo "Visão total" — quem vê a agenda de TODAS as lojas.

Por que um grupo, e não `is_superuser`: a lista de quem deve ver tudo não
coincide com a de superusuários. Hoje os superusuários são Diego, Jonas e Yan,
e o dono quer Jonas, Raniele e Yan — a Raniele não é superusuária. Como grupo,
a lista fica no admin e ele muda sozinho ("vai entrar outro usuário que também
vai ver").

A migração cria o GRUPO, não os MEMBROS: quem está dentro é dado de operação,
que ele administra. Numa instalação nova o grupo nasce vazio, e o efeito é o
mais seguro possível — cada pessoa vê só a agenda da própria loja.
"""

from django.db import migrations

NOME = "Visão total"


def criar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=NOME)


def remover(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=NOME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("orgs", "0013_campos_de_cadastro"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(criar, remover),
    ]
