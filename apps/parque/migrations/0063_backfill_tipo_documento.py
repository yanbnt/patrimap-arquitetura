# -*- coding: utf-8 -*-
"""Deduz o tipo dos documentos que já estavam anexados.

Até agora o tipo não existia: o que identificava um documento era a descrição
digitada à mão ("Nota fiscal 12345", "laudo da autorizada"). Esta migração lê
essa descrição — e o nome do arquivo, quando a descrição está vazia — e marca o
tipo. O que não der para reconhecer fica OUTRO, que é a verdade: ninguém sabe.
"""
from django.db import migrations

PALAVRAS = [
    ("nota_servico", ("nota de servi", "nota fiscal de servi", "nf servi", "nfs")),
    ("nota_compra", ("nota fiscal", "nota de compra", "nf compra", "danfe", "nfe")),
    ("termo", ("termo",)),
    ("laudo", ("laudo",)),
    ("orcamento", ("orçamento", "orcamento")),
    ("protocolo", ("protocolo", "ordem de servi", "os ")),
]


def deduzir(texto):
    t = (texto or "").lower()
    for tipo, chaves in PALAVRAS:
        if any(k in t for k in chaves):
            return tipo
    return "outro"


def frente(apps, schema_editor):
    Doc = apps.get_model("parque", "DocumentoEquipamento")
    for d in Doc.objects.all().only("id", "descricao", "arquivo", "tipo"):
        tipo = deduzir(d.descricao) 
        if tipo == "outro" and d.arquivo:
            tipo = deduzir(str(d.arquivo).rsplit("/", 1)[-1])
        if tipo != d.tipo:
            d.tipo = tipo
            d.save(update_fields=["tipo"])


def atras(apps, schema_editor):
    """Nada a desfazer: o campo inteiro sai na migração anterior."""


class Migration(migrations.Migration):

    dependencies = [("parque", "0062_documentoequipamento_enviado_por_and_more")]

    operations = [migrations.RunPython(frente, atras)]
