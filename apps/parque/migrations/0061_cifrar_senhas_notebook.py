"""Cifra as senhas de notebook que ainda estão em texto claro no banco.

Auditoria 1.12. Roda depois da 0060 (que trocou o tipo dos campos).

REVERSÍVEL: a migração de volta decifra e grava em claro de novo — para o caso
de precisar desfazer. Ela depende da MESMA `CAMPO_CRIPTO_KEY`; sem a chave, os
valores não voltam (é o objetivo da cifragem).
"""

from django.db import migrations


def cifrar(apps, schema_editor):
    from apps.parque.campos import PREFIXO, cifrar as _cifrar

    Notebook = apps.get_model("parque", "Notebook")
    # `apps.get_model` devolve o modelo HISTÓRICO, cujos campos são CharField
    # comuns — por isso o valor vem cru do banco e a cifragem é feita à mão.
    n = 0
    for nb in Notebook.objects.exclude(senha="").only("id", "senha").iterator():
        if not str(nb.senha).startswith(PREFIXO):
            Notebook.objects.filter(pk=nb.pk).update(senha=_cifrar(nb.senha))
            n += 1
    for nb in Notebook.objects.exclude(anydesk_senha="").only("id", "anydesk_senha").iterator():
        if not str(nb.anydesk_senha).startswith(PREFIXO):
            Notebook.objects.filter(pk=nb.pk).update(
                anydesk_senha=_cifrar(nb.anydesk_senha))
            n += 1
    if n:
        print(f"  {n} senha(s) de notebook cifrada(s).")


def decifrar(apps, schema_editor):
    from apps.parque.campos import decifrar as _decifrar

    Notebook = apps.get_model("parque", "Notebook")
    for campo in ("senha", "anydesk_senha"):
        for nb in Notebook.objects.exclude(**{campo: ""}).only("id", campo).iterator():
            valor = getattr(nb, campo)
            Notebook.objects.filter(pk=nb.pk).update(**{campo: _decifrar(valor)})


class Migration(migrations.Migration):

    dependencies = [
        ("parque", "0060_alter_notebook_anydesk_senha_alter_notebook_senha"),
    ]

    operations = [
        migrations.RunPython(cifrar, decifrar),
    ]
