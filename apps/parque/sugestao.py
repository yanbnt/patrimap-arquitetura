"""
Sugestão de patrimônio por PROXIMIDADE DE HARDWARE.

Quando uma coleta de telemetria está pendente (serial não casou com nenhuma
máquina), sugerimos os patrimônios mais prováveis comparando as specs medidas
(CPU/RAM/disco) com as cadastradas — para o técnico escolher a máquina certa.
"""

import re


def _cpu_token(s):
    """Extrai o modelo do processador (ex.: 'i5-3470' -> 'i53470'; 'Ryzen 5 3600')."""
    s = (s or "").lower()
    m = re.search(r"(i[3579]|ryzen|celeron|pentium|athlon|xeon|core\s*2)\s*[-]?\s*"
                  r"([a-z]?\d{3,5}[a-z]*)", s)
    if m:
        return (m.group(1) + m.group(2)).replace(" ", "").replace("-", "")
    return ""


def _num(s):
    m = re.search(r"(\d+)", str(s or ""))
    return int(m.group(1)) if m else None


def pontuar(tel, maq):
    """Pontua 0–100 a semelhança entre a coleta `tel` e a máquina `maq`."""
    score = 0
    tcpu, mcpu = _cpu_token(tel.cpu_modelo), _cpu_token(getattr(maq, "processador", ""))
    if tcpu and mcpu:
        if tcpu == mcpu:
            score += 60
        elif tcpu[:2] == mcpu[:2]:   # mesma família (i5, i3…)
            score += 12
    tram = int(tel.ram_gb) if tel.ram_gb else None
    mram = _num(getattr(maq, "memoria_ram", ""))
    if tram and mram and tram == mram:
        score += 20
    tdisk = int(tel.disco_total_gb) if tel.disco_total_gb else None
    mdisk = _num(getattr(maq, "armazenamento", ""))
    if tdisk and mdisk and abs(tdisk - mdisk) <= 25:
        score += 20
    return score


def sugerir(tel, limite=6):
    """Lista candidatos (tipo, máquina, score) ordenados por semelhança (score>0)."""
    from .models import Computador, Notebook

    cands = []
    comps = Computador.objects.exclude(status=Computador.Status.DESATIVADO)
    for m in comps:
        cands.append(("computador", m, pontuar(tel, m)))
    nbs = Notebook.objects.exclude(status=Notebook.Status.OBSOLETO)
    for m in nbs:
        cands.append(("notebook", m, pontuar(tel, m)))
    cands = [c for c in cands if c[2] > 0]
    cands.sort(key=lambda c: c[2], reverse=True)
    return cands[:limite]
