# -*- coding: utf-8 -*-
"""Semeia a tabela de acessos com EXATAMENTE o que o sistema já fazia.

Esta migração é a razão de a mudança poder ir de uma vez. Ela copia, para a
tabela, o padrão que está escrito em `apps/orgs/acessos.py:TELAS` — que por sua
vez é a transcrição literal das condições que existiam no menu e dentro das
views. No dia em que rodar, ninguém ganha nem perde acesso; o que muda é onde a
resposta mora.

Grupo que a semente cita e não existe no banco é ignorado (não cria grupo: se
"Visão total" não existe nesta instalação, é porque não deve existir).

O `atras` limpa o que foi semeado. Voltar a migração devolve o sistema ao
padrão do código, que é o mesmo — de novo, ninguém perde acesso.
"""
from django.db import migrations

# Copiado de apps/orgs/acessos.py. Repetido aqui de propósito: migração tem de
# continuar valendo daqui a um ano, mesmo que o registro do código mude.
SEMENTE = {
    "dashboard": ("Gerente", "Supervisor", "Visão total", "RH"),
    "arquivo": ("RH", "Supervisor", "Gerente", "Visão total"),
    "registros": ("RH", "Gerente", "Supervisor"),
    "aprovacoes": ("Técnico de Pós Venda", "Supervisor", "Gerente"),
    "acessos": ("Gerente", "Supervisor", "Desenvolvimento", "Técnico de Pós Venda"),
    "online": ("Gerente", "Supervisor"),
    "logs": ("Gerente", "Supervisor"),
    # "grupos" era item de menu próprio (Gerente, Supervisor, Desenvolvimento);
    # virou parte da tela de acessos, então o acesso dele é o de "acessos".
}


def frente(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    TelaGrupo = apps.get_model("orgs", "TelaGrupo")
    por_nome = {g.name: g for g in Group.objects.all()}
    novos = []
    for tela, grupos in SEMENTE.items():
        for nome in grupos:
            g = por_nome.get(nome)
            if g is None:
                continue
            novos.append(TelaGrupo(tela=tela, grupo=g))
    # ignore_conflicts: rodar duas vezes não pode duplicar nem estourar
    TelaGrupo.objects.bulk_create(novos, ignore_conflicts=True)


def atras(apps, schema_editor):
    TelaGrupo = apps.get_model("orgs", "TelaGrupo")
    TelaGrupo.objects.filter(tela__in=list(SEMENTE)).delete()


class Migration(migrations.Migration):

    dependencies = [("orgs", "0015_telagrupo")]

    operations = [migrations.RunPython(frente, atras)]
