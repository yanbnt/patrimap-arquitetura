from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parque", "0003_reparo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reparo",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("reparo", "Reparo"),
                    ("upgrade", "Upgrade / melhoria"),
                    ("preventiva", "Manutenção preventiva"),
                    ("periferico", "Troca de periférico"),
                    ("desativacao", "Desativação para troca"),
                    ("outro", "Outro"),
                ],
                default="reparo",
                help_text=(
                    "Só o tipo 'Reparo' penaliza o desempenho. "
                    "'Troca de periférico' (ex.: headset) não conta."
                ),
                max_length=12,
                verbose_name="tipo",
            ),
        ),
    ]
