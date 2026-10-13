"""
Liga o TEXTO `Notebook.usuario` ao VÍNCULO `Notebook.colaborador`.

POR QUE ISTO EXISTE
-------------------
O Notebook guarda quem usa em dois lugares:

    usuario      CharField   — texto livre, como veio da planilha do Bitrix
    colaborador  FK(Person)  — o vínculo de verdade

Quem faz a ligação é o sinal `conectar_notebook_ao_colaborador`
(apps/parque/signals.py), em `pre_save`. Só que ele tinha um defeito: o
fallback por primeiro nome comparava "Arthur" com o `full_name` INTEIRO, então
só casava com quem estivesse cadastrado literalmente como "Arthur" — nunca com
"Arthur Souza". Na prática o fallback nunca pegava.

Resultado nos dados: a tabela de notebooks mostrava "Alberto" e o formulário de
edição mostrava "Selecione…" — a mesma máquina, duas respostas. E tudo que
depende do vínculo (filtro por pessoa, "notebooks deste colaborador", a ficha
de Cadastros) enxergava vazio.

O sinal foi corrigido, mas sinal só roda em `save()`: as linhas que já estavam
no banco continuam descasadas. Este comando reprocessa essas linhas.

COMO SE USA (no servidor, onde os dados estão)
----------------------------------------------
    python manage.py casar_notebooks                  # só relata
    python manage.py casar_notebooks --detalhe        # linha a linha
    python manage.py casar_notebooks --aplicar        # grava o que é seguro
    python manage.py casar_notebooks --aplicar --criar-pessoas

Sem `--aplicar` nada é gravado.

O QUE ELE NUNCA FAZ
-------------------
  · não sobrescreve `colaborador` já preenchido;
  · não resolve ambiguidade sozinho (dois "Carlos" ficam de fora, listados);
  · não altera o texto de `usuario` — é o que permite rodar de novo e conferir.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.orgs.models import Person
from apps.parque.models import Notebook

# A regra de casar nome mora no sinal, e é importada — não copiada. Duas cópias
# divergem na primeira vez que alguém ajustar uma delas, e foi assim que os
# dados ficaram descasados.
from apps.parque.signals import _eh_placeholder, _person_por_nome


def _candidatos(nome):
    """Quantas pessoas disputam esse nome — só para o relatório saber dizer
    'ambíguo' em vez de um 'não encontrei' que esconde a causa."""
    nome = (nome or "").strip()
    if not nome:
        return []
    exatos = list(Person.objects.filter(full_name__iexact=nome)[:3])
    if exatos:
        return exatos
    primeiro = nome.split(" ")[0]
    return list(Person.objects.filter(
        Q(full_name__istartswith=primeiro + " ") | Q(full_name__iexact=primeiro)
    )[:3])


class Command(BaseCommand):
    help = ("Liga Notebook.usuario (texto) a Notebook.colaborador (vínculo). "
            "Por padrão só relata; grava com --aplicar.")

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true",
                            help="Grava. Sem isto, o comando apenas relata.")
        parser.add_argument("--criar-pessoas", action="store_true",
                            help="Cria Person para os nomes que não existem no cadastro.")
        parser.add_argument("--detalhe", action="store_true",
                            help="Lista linha a linha, não só os totais.")

    def handle(self, *args, **opts):
        aplicar, criar, detalhe = opts["aplicar"], opts["criar_pessoas"], opts["detalhe"]

        alvos = list(Notebook.objects.filter(colaborador__isnull=True).exclude(usuario=""))

        liga, ambiguos, sem_pessoa, rotulos = [], [], [], []
        for nb in alvos:
            if _eh_placeholder(nb.usuario):
                rotulos.append(nb)
                continue
            pessoa = _person_por_nome(nb.usuario)
            if pessoa is not None:
                liga.append((nb, pessoa))
            elif len(_candidatos(nb.usuario)) > 1:
                ambiguos.append((nb, _candidatos(nb.usuario)))
            else:
                sem_pessoa.append(nb)

        total = Notebook.objects.count()
        com_vinculo = Notebook.objects.filter(colaborador__isnull=False).count()
        sem_nada = Notebook.objects.filter(usuario="", colaborador__isnull=True).count()

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Notebooks — quem usa"))
        self.stdout.write(f"  total no banco ..................... {total:5d}")
        self.stdout.write(f"  já com vínculo ..................... {com_vinculo:5d}")
        self.stdout.write(f"  sem texto e sem vínculo ............ {sem_nada:5d}")
        self.stdout.write(f"  COM texto e SEM vínculo ............ {len(alvos):5d}  <- o problema")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Do que está sem vínculo"))
        self.stdout.write(f"  casa com uma pessoa ................ {len(liga):5d}  seguro")
        self.stdout.write(f"  ambíguo (2+ pessoas) ............... {len(ambiguos):5d}  precisa de você")
        self.stdout.write(f"  sem pessoa no cadastro ............. {len(sem_pessoa):5d}"
                          f"  {'será criada' if criar else 'use --criar-pessoas'}")
        self.stdout.write(f"  rótulo, não pessoa ................. {len(rotulos):5d}  ignorado")
        self.stdout.write("")

        if detalhe:
            self._listar("Vai ligar", [(n, p.full_name) for n, p in liga])
            self._listar("Ambíguos (NÃO serão tocados)",
                         [(n, " | ".join(c.full_name for c in cs)) for n, cs in ambiguos])
            self._listar("Sem pessoa no cadastro", [(n, "—") for n in sem_pessoa])
            self._listar("Rótulos (não são pessoas)", [(n, "—") for n in rotulos])
        elif ambiguos:
            self.stdout.write(self.style.WARNING(
                "  Há ambíguos. Rode com --detalhe para ver quais."))
            self.stdout.write("")

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "MODO RELATÓRIO — nada foi gravado. Para aplicar: --aplicar"))
            self.stdout.write("")
            return

        ligados = criados = 0
        with transaction.atomic():
            for nb, pessoa in liga:
                nb.colaborador = pessoa
                nb.save()          # o sinal ainda ajusta unidade/setor
                ligados += 1

            if criar:
                for nb in sem_pessoa:
                    nome = " ".join(w.capitalize() for w in nb.usuario.split())
                    pessoa, novo = Person.objects.get_or_create(
                        full_name=nome, defaults={"job_title": "", "active": True})
                    criados += 1 if novo else 0
                    nb.colaborador = pessoa
                    nb.save()
                    ligados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Aplicado: {ligados} notebook(s) ligado(s), {criados} pessoa(s) criada(s)."))
        if ambiguos:
            self.stdout.write(self.style.WARNING(
                f"{len(ambiguos)} ambíguo(s) continuam sem vínculo, de propósito."))
        self.stdout.write("")

    def _listar(self, titulo, itens):
        if not itens:
            return
        self.stdout.write(self.style.MIGRATE_LABEL(f"  {titulo} ({len(itens)})"))
        for nb, alvo in itens[:200]:
            self.stdout.write(f"    {(nb.patrimonio or '—'):<10} "
                              f"{nb.usuario[:28]:<28} -> {alvo}")
        if len(itens) > 200:
            self.stdout.write(f"    … e mais {len(itens) - 200}")
        self.stdout.write("")
