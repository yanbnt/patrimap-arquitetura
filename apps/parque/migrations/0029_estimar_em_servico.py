"""Estima 'em serviço desde' das máquinas já cadastradas.

Como o sistema não tinha esse dado histórico, distribui as datas ao longo do
último ano (de forma determinística por PK) para a contagem de manutenção
preventiva (ciclo de 60 dias) fazer sentido desde já. É uma estimativa — pode
ser corrigida por máquina no admin (campo 'em serviço desde')."""

from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def estimar(apps, schema_editor):
    Baia = apps.get_model("parque", "Baia")
    hoje = timezone.localdate()
    for b in Baia.objects.all():
        # 45 a ~365 dias atrás, espalhado pela PK (a maioria > 60 dias = pendente).
        dias = 45 + (b.pk * 37) % 320
        Baia.objects.filter(pk=b.pk).update(criado_em=hoje - timedelta(days=dias))


class Migration(migrations.Migration):

    dependencies = [
        ("parque", "0028_baia_criado_em"),
    ]

    operations = [
        migrations.RunPython(estimar, migrations.RunPython.noop),
    ]
