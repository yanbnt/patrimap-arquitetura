# -*- coding: utf-8 -*-
"""Dá aos grupos que ABREM o mural a permissão de escrever nele.

SEM ISTO O RECURSO SUBIA MORTO. Conferido no banco antes de escrever:

    Gerente          160 permissões — do mural, só add_documentoequipamento
    Supervisor       160 permissões — idem
    RH                 5 permissões — nenhuma do mural
    Visão total        0 permissões — nenhuma do mural

Ou seja: `add_comentarioevento` e `add_publicacaomural` não existiam em grupo
nenhum, e a tela abriria com o campo de comentário e o composer barrados para
todo mundo que não fosse superusuário. O dono testaria (ele é superusuário) e
acharia que estava funcionando.

QUEM GANHA O QUÊ
----------------
Os três grupos que já abrem a tela "registros" (RH, Gerente, Supervisor) —
os mesmos de sempre, nada de acesso novo — ganham comentar e publicar.
Apagar publicação NÃO vira permissão de grupo: quem apaga é o autor, e a view
decide isso pelo autor, não por permissão (apps/parque/mural.py). A permissão
de modelo `delete_publicacaomural` fica só com superusuário, para moderação
pelo admin.

Reversível: a migração de volta retira exatamente o que ela deu.
"""
from django.db import migrations

GRUPOS = ["RH", "Gerente", "Supervisor"]
PERMISSOES = [
    ("comentarioevento", "add"),      # escrever comentário
    ("comentarioevento", "view"),     # ler pelo admin, se precisar conferir
    ("publicacaomural", "add"),       # publicar
    ("publicacaomural", "change"),    # editar a própria (a view trava o autor)
    ("publicacaomural", "view"),
]


def _permissoes(apps):
    Permission = apps.get_model("auth", "Permission")
    fora = []
    for modelo, acao in PERMISSOES:
        p = Permission.objects.filter(
            codename="%s_%s" % (acao, modelo),
            content_type__app_label="parque").first()
        if p:
            fora.append(p)
    return fora


def dar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    perms = _permissoes(apps)
    if not perms:
        return
    for nome in GRUPOS:
        g = Group.objects.filter(name=nome).first()
        if g:
            g.permissions.add(*perms)


def tirar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    perms = _permissoes(apps)
    if not perms:
        return
    for nome in GRUPOS:
        g = Group.objects.filter(name=nome).first()
        if g:
            g.permissions.remove(*perms)


class Migration(migrations.Migration):

    dependencies = [
        ("parque", "0065_mural_publicacao"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(dar, tirar),
    ]
