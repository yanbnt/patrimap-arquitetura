"""
Importador da planilha "Levantamento das Máquinas".

Cada aba de unidade (Bonsucesso, Campo Grande...) tem vários blocos de setor
empilhados: uma linha com o nome do setor, depois um cabeçalho que começa em
"Baia", depois as linhas de baia (que sempre começam com um dígito). A aba
"Transferencias" tem um log com cabeçalho "Local (Origem)"...
"""

import csv
import io
from datetime import datetime

from django.db import transaction

from apps.orgs.models import Location, Person

from .models import Baia, Setor, Transferencia

# Mapa de cabeçalho -> campo da Baia
_HEADER_FIELD = {
    "s.o": "sistema_operacional",
    "so": "sistema_operacional",
    "processador": "processador",
    "placa mãe": "placa_mae",
    "placa mae": "placa_mae",
    "memória ram": "memoria_ram",
    "memoria ram": "memoria_ram",
    "armazenamento": "armazenamento",
    "mouse": "mouse",
    "teclado": "teclado",
    "webcam": "webcam",
    "headset": "headset",
    "monitor": "monitor",
    "leitor cod. barras": "leitor_cod_barras",
    "leitor cód. barras": "leitor_cod_barras",
}
_PERIF_FIELDS = {"mouse", "teclado", "webcam", "headset", "monitor", "leitor_cod_barras"}
_GENERICO = {
    "vazio", "direita", "esquerda", "caixa", "conferente", "supervisão", "supervisao",
    "transporte", "marketing", "rma", "estacionamento", "treinamento", "direção",
    "direcao", "monitiranento", "monitoramento",
}


def _norm(s):
    return (s or "").strip().lower()


def parse_rows(text):
    return list(csv.reader(io.StringIO(text)))


def _linha_vazia(so):
    """A linha representa uma mesa SEM computador desktop (vazia ou notebook).

    Nesses casos não gravamos specs — assim o signal não cria um Computador
    fantasma. Notebooks reais são geridos no próprio cadastro de Notebook.
    """
    low = _norm(so)
    return "sem pc" in low or "notebook" in low


def _perif(v):
    low = _norm(v)
    if not low:
        return ""
    if "defeito" in low:
        return "defeito"
    if low == "sim":
        return "sim"
    if low in ("não", "nao"):
        return "nao"
    return ""


def _colaborador(nome):
    if " - " in nome:
        suf = nome.split(" - ", 1)[1].strip()
        if _norm(suf) not in _GENERICO:
            return suf
    return ""


def _pessoa(nome_baia, unidade):
    """Resolve (criando se preciso) a Pessoa do colaborador da baia."""
    nome = _colaborador(nome_baia)
    if not nome:
        return None
    pessoa, _ = Person.objects.get_or_create(
        full_name=nome, defaults={"location": unidade, "active": True}
    )
    return pessoa


def _parse_date(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@transaction.atomic
def import_unidade(nome_unidade, rows):
    """Importa uma aba de unidade (lista de linhas): cria Location, Setores, Baias."""
    unidade, _ = Location.objects.get_or_create(name=nome_unidade.strip())
    setor = None
    colmap = None
    baia_col = None
    stats = {"setores": 0, "baias": 0}

    for row in rows:
        if not row:
            continue
        first = (row[0] or "").strip()
        low = _norm(first)

        # Linha de cabeçalho de tabela?
        if low == "baia":
            colmap = {}
            baia_col = 0
            for i, h in enumerate(row):
                hn = _norm(h)
                if hn == "baia":
                    baia_col = i
                elif hn in _HEADER_FIELD:
                    colmap[i] = _HEADER_FIELD[hn]
            continue

        # Linha de dados (baia começa com dígito)?
        if colmap is not None and first[:1].isdigit():
            if setor is None:
                continue
            so_val = row[baia_col + 1] if len(row) > baia_col + 1 else ""
            # localiza S.O pela coluna mapeada, se houver
            so_idx = next((i for i, f in colmap.items() if f == "sistema_operacional"), None)
            if so_idx is not None and len(row) > so_idx:
                so_val = row[so_idx]
            vazia = _linha_vazia(so_val)
            _SPEC_FIELDS = ("sistema_operacional", "processador", "placa_mae",
                            "memoria_ram", "armazenamento")
            dados = {"nome": first, "colaborador": _pessoa(first, unidade)}
            for i, field in colmap.items():
                val = row[i].strip() if len(row) > i else ""
                if field in _PERIF_FIELDS:
                    dados[field] = _perif(val)
                elif field in _SPEC_FIELDS:
                    # Mesa vazia/notebook: sem specs (não gera Computador fantasma).
                    dados[field] = "" if vazia else val
                else:
                    dados[field] = val
            Baia.objects.update_or_create(setor=setor, nome=first, defaults=dados)
            stats["baias"] += 1
            continue

        # Caso contrário, se tem nome e não começa com dígito: é nome de setor.
        if first and not first[:1].isdigit() and _norm(first) != "periféricos":
            # ignora rótulos isolados de "Periféricos"
            if _norm(first) in ("baia",):
                continue
            setor, created = Setor.objects.get_or_create(unidade=unidade, nome=first)
            if created:
                stats["setores"] += 1
            colmap = None  # aguarda o próximo cabeçalho

    return stats


def _find_baia(local, nome_baia):
    nome_baia = (nome_baia or "").strip()
    local = (local or "").strip()
    if not nome_baia or not local:
        return None
    return Baia.objects.filter(
        setor__unidade__name__iexact=local, nome__iexact=nome_baia
    ).first()


@transaction.atomic
def import_transferencias(rows):
    """Importa o log da aba Transferencias (lista de linhas)."""
    header_idx = None
    cols = {}
    for idx, row in enumerate(rows):
        norm_row = [_norm(c) for c in row]
        if "local (origem)" in norm_row and "local (destino)" in norm_row:
            header_idx = idx
            for i, c in enumerate(norm_row):
                cols[c] = i
            break
    if header_idx is None:
        return {"transferencias": 0}

    def g(row, key):
        i = cols.get(key)
        return row[i].strip() if (i is not None and len(row) > i) else ""

    count = 0
    for row in rows[header_idx + 1:]:
        local_o = g(row, "local (origem)")
        local_d = g(row, "local (destino)")
        if not local_o and not local_d:
            continue
        t = Transferencia(
            baia_origem=_find_baia(local_o, g(row, "baia (saída)")),
            data_saida=_parse_date(g(row, "data (saída)")),
            colaborador_saida=g(row, "colaborador (saída)"),
            so_antigo=g(row, "s.o (antigo)"),
            processador_antigo=g(row, "processador (antigo)"),
            placa_mae_antigo=g(row, "placa mãe (antigo)"),
            ram_antigo=g(row, "memória ram (antigo)"),
            armazenamento_antigo=g(row, "armazenamento (antigo)"),
            baia_destino=_find_baia(local_d, g(row, "baia (destino)")),
            data_entrada=_parse_date(g(row, "data (entrada)")),
            colaborador_destino=g(row, "colaborador (destino)"),
            so_novo=g(row, "s.o (novo)"),
            processador_novo=g(row, "processador (novo)"),
            placa_mae_novo=g(row, "placa mãe (novo)"),
            ram_novo=g(row, "memória ram (novo)"),
            armazenamento_novo=g(row, "armazenamento (novo)"),
            observacao=f"Origem: {local_o or '?'} → Destino: {local_d or '?'}",
        )
        t.save()
        count += 1
    return {"transferencias": count}
