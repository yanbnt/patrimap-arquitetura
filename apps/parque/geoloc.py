"""
Verificação de localização por IP público + sub-rede local (telemetria).

Aprendemos qual unidade é "dona" de cada ponto de rede pela MAIORIA das máquinas
que reportam dali (quórum + maioria estrita), sem configuração manual.

Duas lojas podem sair para a internet pelo MESMO IP público (mesmo ISP/CGNAT/
link central). Nesse caso o IP público sozinho não distingue as lojas. Por isso
a chave de agrupamento é o par **(IP público, sub-rede /24 do IP local)**: cada
loja quase sempre tem uma sub-rede LAN distinta (ex.: 192.168.0.x vs 192.168.1.x),
então o mesmo IP público pode ter várias unidades donas — uma por segmento.

Uma máquina só está com a localização divergente quando o segmento de rede DELA
(IP público + sub-rede) é dominado por uma unidade DIFERENTE da cadastrada.
Empate/sem quórum/sem sinal fino ⇒ sem dono ⇒ não acusa (evita falso positivo).

Só coletas recentes votam — coletas antigas de máquinas que já mudaram de lugar
não "envenenam" a decisão.
"""

from collections import Counter, defaultdict
from datetime import timedelta

from django.utils import timezone

# Mínimo de máquinas concordando para um segmento "pertencer" a uma unidade.
QUORUM_MIN = 2
# Só coletas vistas nos últimos N dias participam da votação.
JANELA_DIAS = 45


def unidade_cadastrada_de(tel):
    """Unidade onde a máquina da coleta está cadastrada (via baia → setor → unidade)."""
    return tel.unidade_cadastrada


def _seg_local(ip_local):
    """Sub-rede /24 (3 primeiros octetos) do IP local — distingue lojas atrás do
    mesmo IP público. Vazio quando não há IP local utilizável."""
    ip = (ip_local or "").strip()
    partes = ip.split(".")
    return ".".join(partes[:3]) if len(partes) >= 3 and all(partes[:3]) else ""


def donos_por_segmento(tels, min_maquinas=QUORUM_MIN):
    """Mapa {(ip_publico, seg_local): Location} — a unidade dona de cada segmento de
    rede, por maioria estrita (quórum + topo único). Um IP público pode aparecer em
    vários segmentos (várias donas) quando lojas dividem o link."""
    por_seg = defaultdict(list)
    for t in tels:
        ip = (t.ip_publico or "").strip()
        if ip:
            por_seg[(ip, _seg_local(t.ip_local))].append(t)

    donos = {}
    for chave, grupo in por_seg.items():
        votos = Counter()
        unidades = {}
        for t in grupo:
            u = unidade_cadastrada_de(t)
            if u:
                votos[u.id] += 1
                unidades[u.id] = u
        if not votos:
            continue
        top_id, top_n = votos.most_common(1)[0]
        # Precisa de quórum e ser estritamente dominante (sem empate no topo).
        if top_n >= min_maquinas and list(votos.values()).count(top_n) == 1:
            donos[chave] = unidades[top_id]
    return donos


def recalcular(min_maquinas=QUORUM_MIN, janela_dias=JANELA_DIAS):
    """Recalcula `unidade_detectada` de todas as coletas e devolve as divergências.

    O "dono" de cada segmento (IP público + sub-rede /24 local) é aprendido só com
    coletas recentes. Retorna a lista de TelemetriaMaquina com localização divergente
    (cadastrada ≠ detectada, não ignorada)."""
    from .models import TelemetriaMaquina

    tels = list(
        TelemetriaMaquina.objects.select_related(
            "computador__baia__setor__unidade",
            "notebook__baia__setor__unidade",
            "unidade_detectada",
        )
    )

    # Só coletas vistas recentemente votam (coletas antigas não envenenam a decisão).
    corte = timezone.now() - timedelta(days=janela_dias)
    votantes = [t for t in tels if t.visto_em and t.visto_em >= corte]
    donos = donos_por_segmento(votantes, min_maquinas)

    divergencias = []
    for t in tels:
        ip = (t.ip_publico or "").strip()
        dono = donos.get((ip, _seg_local(t.ip_local))) if ip else None
        novo_id = dono.id if dono else None
        if t.unidade_detectada_id != novo_id:
            t.unidade_detectada_id = novo_id
            t.save(update_fields=["unidade_detectada"])
        if t.local_divergente:
            divergencias.append(t)
    return divergencias
