"""
Liga o nome escrito na BAIA ao colaborador cadastrado.

A baia se chama "9 - Juliana": o número identifica a posição e o resto é quem
senta ali. Quem faz a ligação é o signal `numerar_e_conectar_baia`
(apps/parque/signals.py), em `pre_save` — mas signal só roda quando alguém
salva. As baias importadas antes de o casamento por primeiro nome funcionar
ficaram com o nome no texto e sem vínculo.

Este comando reprocessa essas baias. É irmão do `casar_notebooks` e usa
exatamente a mesma regra de nome, a mesma lista de rótulos e o mesmo padrão de
"só relata, a não ser que mande aplicar".

O QUE NÃO É PESSOA
------------------
"Direita", "Esquerda", "Vazio", "Caixa", "Câmeras", "Recepção" são POSIÇÃO, não
gente. A lista está em `_PLACEHOLDERS` (signals.py) e vale aqui também — numa
medição real, 38 das 42 baias "sem vínculo" eram disso.

USO
---
    python manage.py casar_baias               # só relata
    python manage.py casar_baias --detalhe     # linha a linha
    python manage.py casar_baias --aplicar     # grava
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.orgs.models import Person
from apps.parque.models import Baia
from apps.parque.signals import (
    _eh_placeholder, _person_por_nome, partes_do_nome_da_baia,
)


def _candidatos(nome):
    """Quem disputa esse nome — para o relatório poder dizer 'ambíguo' em vez
    de um 'não encontrei' que esconde a causa."""
    nome = (nome or "").strip()
    if not nome:
        return []
    exatos = list(Person.objects.filter(full_name__iexact=nome)[:5])
    if exatos:
        return exatos
    primeiro = nome.split(" ")[0]
    return list(Person.objects.filter(
        Q(full_name__istartswith=primeiro + " ") | Q(full_name__iexact=primeiro)
    )[:5])


def eh_ambiguo(nome):
    """Ambíguo é quando o texto DISPUTA entre pessoas — não quando ele nomeia
    alguém que o cadastro não tem.

    Medido no servidor em 05/10/2026: "2 - Paula Andrade" saía como ambíguo
    oferecendo "Paula Moreira | Paula Pinto | Paula Castro". Não
    disputam coisa nenhuma: nenhuma delas é a Gustavo. O relatório dizia
    "precisa de você" e servia três respostas erradas de bandeja — convidando
    ao chute que `pessoa_para_baia` tinha acabado de impedir.

    Só é disputa de verdade em dois casos: duas fichas com o nome EXATO, ou um
    primeiro nome solto que serve a mais de uma pessoa.
    """
    nome = (nome or "").strip()
    if Person.objects.filter(full_name__iexact=nome).count() > 1:
        return True
    return len(nome.split()) == 1 and len(_candidatos(nome)) > 1


def pessoa_para_baia(baia, nome):
    """Acha a pessoa, usando a LOJA da baia para desempatar.

    Por que a loja entra aqui e não no signal: a baia sabe de qual unidade ela é
    (setor → unidade), e o signal genérico de nome não tem esse contexto.

    O caso que motivou: existem três Paulas — Gustavo em Vilar, Lima na
    Taquara e Moreno. Pelo nome, "Paula" é sempre ambíguo e nada casa. Mas
    uma baia DE VILAR com "Paula" só pode ser a de Vilar.

    Só desempata quando sobra exatamente UMA candidata naquela loja. Duas
    Paulas na mesma unidade continuam sendo decisão humana.
    """
    direta = _person_por_nome(nome)
    if direta is not None:
        return direta, "nome"

    # O desempate por loja SÓ vale quando o texto não afirma sobrenome.
    #
    # Isto já falhou feio: "2 - Paula Andrade" (Vilar) foi parar em "Paula
    # Moreno" porque a Moreno é de Vilar e sobrou só ela naquela loja. A loja
    # desempatou um nome que NÃO era ambíguo — era simplesmente outro. O texto
    # dizia "Gustavo" e o sistema entregou a mesa para a Moreno.
    #
    # A loja serve para escolher entre homônimas ("Paula" e "Paula"), não
    # para atropelar um sobrenome que não bate. Com sobrenome no texto e nenhum
    # cadastro correspondente, a resposta certa é "essa pessoa não tem ficha".
    if len(nome.split()) > 1:
        return None, ""

    unidade_id = (baia.setor.unidade_id
                  if baia.setor_id and baia.setor.unidade_id else None)
    if unidade_id is None:
        return None, ""

    mesmos = [p for p in _candidatos(nome) if p.location_id == unidade_id]
    if len(mesmos) == 1:
        return mesmos[0], "nome + loja"
    return None, ""


class Command(BaseCommand):
    help = ("Liga o nome escrito na baia ao colaborador cadastrado. "
            "Por padrão só relata; grava com --aplicar.")

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true",
                            help="Grava. Sem isto, o comando apenas relata.")
        parser.add_argument("--detalhe", action="store_true",
                            help="Lista linha a linha, não só os totais.")

    def handle(self, *args, **opts):
        aplicar, detalhe = opts["aplicar"], opts["detalhe"]

        alvos = list(
            Baia.objects.filter(colaborador__isnull=True)
            .select_related("setor", "setor__unidade")
            .order_by("nome")
        )

        liga, ambiguos, sem_pessoa, rotulos, sem_nome = [], [], [], [], []
        for b in alvos:
            _, parte = partes_do_nome_da_baia(b.nome)
            if not parte:
                sem_nome.append(b)
            elif _eh_placeholder(parte):
                rotulos.append((b, parte))
            else:
                pessoa, como = pessoa_para_baia(b, parte)
                if pessoa is not None:
                    liga.append((b, parte, pessoa, como))
                elif eh_ambiguo(parte):
                    ambiguos.append((b, parte, _candidatos(parte)))
                else:
                    sem_pessoa.append((b, parte))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Baias — quem senta"))
        self.stdout.write(f"  total no banco ..................... {Baia.objects.count():5d}")
        self.stdout.write(f"  já com colaborador ................. "
                          f"{Baia.objects.filter(colaborador__isnull=False).count():5d}")
        self.stdout.write(f"  sem colaborador .................... {len(alvos):5d}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Das que estão sem colaborador"))
        self.stdout.write(f"  só o número (sem nome) ............. {len(sem_nome):5d}  normal")
        self.stdout.write(f"  rótulo de posição, não pessoa ...... {len(rotulos):5d}  normal")
        self.stdout.write(f"  NOME DE PESSOA que casa ............ {len(liga):5d}  seguro")
        self.stdout.write(f"  ambíguo (2+ pessoas) ............... {len(ambiguos):5d}  precisa de você")
        self.stdout.write(f"  nome sem ficha no cadastro ......... {len(sem_pessoa):5d}  cadastre a pessoa")
        self.stdout.write("")

        if detalhe:
            self._listar("Vai ligar",
                         [(b, f"{parte}  ->  {p.full_name}   [{como}]")
                          for b, parte, p, como in liga])
            self._listar("Ambíguos (NÃO serão tocados)",
                         [(b, f"{parte}  ->  " + " | ".join(c.full_name for c in cs))
                          for b, parte, cs in ambiguos])
            # Mostrar os quase-iguais é o que diferencia "não procurei" de
            # "procurei e nenhuma é ela". Vem com o aviso colado, para ninguém
            # ler a lista como se fosse um menu de escolha.
            self._listar("Sem ficha no cadastro", [
                (b, parte if not _candidatos(parte) else
                 parte + "   (no cadastro só há "
                 + " | ".join(c.full_name for c in _candidatos(parte))
                 + " — sobrenome diferente, nenhuma é esta)")
                for b, parte in sem_pessoa
            ])
            self._listar("Rótulos de posição (ignorados)", [(b, parte) for b, parte in rotulos])
        elif ambiguos or sem_pessoa:
            self.stdout.write(self.style.WARNING(
                "  Rode com --detalhe para ver os casos que precisam de decisão."))
            self.stdout.write("")

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "MODO RELATÓRIO — nada foi gravado. Para aplicar: --aplicar"))
            self.stdout.write("")
            return

        ligados = 0
        with transaction.atomic():
            for b, _parte, pessoa, _como in liga:
                b.colaborador = pessoa
                b.save()       # os demais signals da baia continuam valendo
                ligados += 1

        self.stdout.write(self.style.SUCCESS(f"Aplicado: {ligados} baia(s) ligada(s)."))
        if ambiguos or sem_pessoa:
            self.stdout.write(self.style.WARNING(
                f"{len(ambiguos) + len(sem_pessoa)} continuam sem vínculo, "
                "aguardando decisão sua."))
        self.stdout.write("")

    def _listar(self, titulo, itens):
        if not itens:
            return
        self.stdout.write(self.style.MIGRATE_LABEL(f"  {titulo} ({len(itens)})"))
        for baia, texto in itens[:200]:
            unidade = (baia.setor.unidade.name
                       if baia.setor_id and baia.setor.unidade_id else "—")
            self.stdout.write(f"    {unidade[:14]:<14} {baia.nome[:26]:<26} {texto}")
        if len(itens) > 200:
            self.stdout.write(f"    … e mais {len(itens) - 200}")
        self.stdout.write("")
