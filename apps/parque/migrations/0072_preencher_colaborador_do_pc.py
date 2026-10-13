"""Preenche `Computador.colaborador` a partir da baia onde a máquina está.

O campo nasceu vazio na 0071. O dado, porém, já existe: quem usa o computador é
quem ocupa a mesa onde ele está. Esta migração só muda o dado de lugar — da
baia para o bem — para que "de quem é esta máquina" tenha resposta mesmo quando
ela sai da mesa (estoque, conserto).

Daí em diante quem mantém sincronizado é o signal `sincronizar_usuario_do_pc`.

Reversível: desfazer limpa o campo e nada se perde, porque a baia continua
sendo a fonte.
"""

from django.db import migrations


def preencher(apps, schema_editor):
    Baia = apps.get_model("parque", "Baia")
    Computador = apps.get_model("parque", "Computador")

    # Uma consulta, uma escrita por baia ocupada. Baia sem colaborador não
    # escreve nada: o campo já nasce nulo, e o PC numa mesa vazia está mesmo
    # sem usuário.
    pares = (Baia.objects
             .filter(computador__isnull=False, colaborador__isnull=False)
             .values_list("computador_id", "colaborador_id"))

    for computador_id, colaborador_id in pares:
        Computador.objects.filter(pk=computador_id).update(colaborador_id=colaborador_id)


def limpar(apps, schema_editor):
    Computador = apps.get_model("parque", "Computador")
    Computador.objects.exclude(colaborador__isnull=True).update(colaborador=None)


class Migration(migrations.Migration):

    dependencies = [
        ("parque", "0071_computador_colaborador"),
    ]

    operations = [
        migrations.RunPython(preencher, limpar),
    ]
