"""
Consolida coletas de telemetria DUPLICADAS da mesma máquina física.

Quando uma máquina roda agentes diferentes (com/sem MAC) ou muda de esquema de
serial, pode aparecer mais de uma linha para o MESMO computador (ex.: HOST-LAB12
e MAC-00E04...). Este comando junta essas linhas por hostname, mantendo a de
melhor identidade (MAC- > tem MAC > mais completa > vinculada > mais recente),
preservando o vínculo/MAC no patrimônio.

Uso:  python manage.py telemetria_dedup [--dry-run]
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.parque.models import TelemetriaMaquina

ENRIQUECIDOS = ("ram_tipo", "particao", "gpu", "gpu_tipo", "uptime_seg", "ip_publico",
                "geo_cidade", "geo_regiao", "geo_pais", "geo_lat", "geo_lon")


def _riqueza(r):
    return sum(1 for f in ("ram_tipo", "particao", "gpu", "uptime_seg", "geo_cidade")
               if getattr(r, f))


class Command(BaseCommand):
    help = "Junta coletas duplicadas da mesma máquina (por hostname), mantendo a melhor."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        grupos = defaultdict(list)
        for t in TelemetriaMaquina.objects.all():
            if t.hostname and (t.serial.startswith(("HOST-", "MAC-")) or "@" in t.serial):
                grupos[t.hostname].append(t)

        removidas = 0
        for host, rows in grupos.items():
            if len(rows) < 2:
                continue
            rows.sort(key=lambda r: (r.serial.startswith("MAC-"), bool(r.mac), _riqueza(r),
                                     bool(r.computador_id or r.notebook_id), r.visto_em),
                      reverse=True)
            keep, resto = rows[0], rows[1:]
            for r in resto:
                if not keep.mac and r.mac:
                    keep.mac = r.mac
                if not (keep.computador_id or keep.notebook_id) and (r.computador_id or r.notebook_id):
                    keep.computador_id, keep.notebook_id = r.computador_id, r.notebook_id
                for f in ENRIQUECIDOS:
                    if not getattr(keep, f) and getattr(r, f):
                        setattr(keep, f, getattr(r, f))
            self.stdout.write(f"{host}: mantém {keep.serial}, remove "
                              f"{', '.join(r.serial for r in resto)}")
            if not dry:
                for r in resto:
                    r.delete()
                keep.save()
                maq = keep.computador or keep.notebook
                if maq:
                    campos = []
                    if (maq.serial or "") != keep.serial:
                        maq.serial = keep.serial
                        campos.append("serial")
                    if keep.mac and getattr(maq, "mac", "") != keep.mac:
                        maq.mac = keep.mac
                        campos.append("mac")
                    if campos:
                        maq.save(update_fields=campos)
            removidas += len(resto)

        prefixo = "[dry-run] " if dry else ""
        self.stdout.write(self.style.SUCCESS(f"{prefixo}{removidas} duplicata(s) consolidada(s)."))
