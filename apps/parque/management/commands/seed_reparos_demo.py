"""
Gera reparos de EXEMPLO ao longo dos últimos 12 meses, só para visualizar o
gráfico "Reparos por mês (quantidade)" — preventiva cai, corretiva sobe, total
em U. Cria a QUANTIDADE de reparos de cada mês. Todos marcados com "[EXEMPLO]".

    python manage.py seed_reparos_demo            # cria os exemplos
    python manage.py seed_reparos_demo --remove   # apaga os exemplos

Não afeta o índice de desempenho (afeta_desempenho=False) — não mexe no KPI de
máquinas críticas.
"""

from datetime import date

from django.core.management.base import BaseCommand

from apps.parque.models import Baia, Reparo

MARCA = "[EXEMPLO]"
# Quantidade de reparos por mês (12 meses, do mais antigo ao atual) — curva clássica.
PREVENTIVA = [10, 9, 8, 7, 6, 5, 4, 4, 3, 2, 2, 1]   # preventiva diminui
CORRETIVA = [1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 11, 13]   # corretiva aumenta


def _ultimos_12_meses():
    from django.utils import timezone
    hoje = timezone.localdate()
    yy, mm = hoje.year, hoje.month
    seq = []
    for _ in range(12):
        seq.append((yy, mm))
        mm -= 1
        if mm == 0:
            mm, yy = 12, yy - 1
    seq.reverse()
    return seq


class Command(BaseCommand):
    help = "Cria/remove reparos de EXEMPLO para o gráfico de Custos de Manutenção."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true",
                            help="Remove os reparos de exemplo.")

    def handle(self, *args, **opts):
        if opts["remove"]:
            n, _ = Reparo.objects.filter(titulo__startswith=MARCA).delete()
            self.stdout.write(self.style.SUCCESS(f"Removidos {n} registro(s) de exemplo."))
            return

        baias = list(Baia.objects.all()[:6])
        if not baias:
            self.stdout.write(self.style.ERROR("Nenhuma baia cadastrada."))
            return

        # Evita duplicar se rodar de novo.
        Reparo.objects.filter(titulo__startswith=MARCA).delete()

        meses = _ultimos_12_meses()
        novos = []
        k = 0
        for i, (yy, mm) in enumerate(meses):
            d = date(yy, mm, 15)
            for _ in range(PREVENTIVA[i]):
                novos.append(Reparo(
                    baia=baias[k % len(baias)], tipo=Reparo.Tipo.PREVENTIVA,
                    titulo=f"{MARCA} Manutenção preventiva", data=d, afeta_desempenho=False,
                ))
                k += 1
            for _ in range(CORRETIVA[i]):
                novos.append(Reparo(
                    baia=baias[k % len(baias)], tipo=Reparo.Tipo.REPARO,
                    titulo=f"{MARCA} Manutenção corretiva", data=d, afeta_desempenho=False,
                ))
                k += 1
        Reparo.objects.bulk_create(novos)

        self.stdout.write(self.style.SUCCESS(
            f"Criados {len(novos)} reparos de exemplo "
            f"({sum(PREVENTIVA)} preventivos + {sum(CORRETIVA)} corretivos). "
            f"Remova com: python manage.py seed_reparos_demo --remove"
        ))
