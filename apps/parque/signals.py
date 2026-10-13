"""
Sinais do app parque.

Mantém o Departamento (e a unidade) da Pessoa em sincronia com o SETOR da baia
que ela ocupa — assim o departamento aparece automaticamente em Pessoas, sem
digitação. O setor da planilha vira um orgs.Department (por unidade).

O COLABORADOR é a chave: ele se liga à baia e ao notebook. A baia é identificada
por um NÚMERO; quando o nome traz o ocupante ("1 - Valéria"), o colaborador é
vinculado automaticamente (e herda o setor/unidade da baia).
"""

import logging
import re

from django.db.models import F, Max, Q
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from apps.orgs.models import Department, Person

logger = logging.getLogger(__name__)

from .models import Baia, Computador, MovimentacaoPeca, Notebook, Peca, Reparo, Setor, SOChoices

# Nome da baia: "<número> - <ocupante>", com "Baia" opcional na frente.
#
# O prefixo entrou porque existem "Baia 3 - Direita" e "Baia 5" no banco: sem
# ele, o nome inteiro virava "ocupante" e o sistema procurava uma pessoa
# chamada "Baia 3 - Direita".
_BAIA_RE = re.compile(r"^\s*(?:baia\s+)?(\d+)\s*[-–—]\s*(.*)$", re.IGNORECASE)
_BAIA_SO_NUM_RE = re.compile(r"^\s*(?:baia\s+)?(\d+)\s*$", re.IGNORECASE)

# Rótulos que NÃO são pessoas (não viram colaborador).
#
# A segunda leva veio do servidor em 05/10/2026: de 11 baias acusadas como
# "pessoa sem cadastro", 8 eram rótulo. "direta" está aqui de propósito — é
# como "direita" aparece digitado no banco, e corrigir o dado não é tarefa
# desta lista.
_PLACEHOLDERS = (
    "vazio", "vaga", "vago", "livre", "disponivel", "disponível", "sem ocupante",
    "caixa", "conferente", "camera", "câmera", "cameras", "câmeras", "estacionamento",
    "direita", "direta", "esquerda", "centro", "fundo", "frente", "balcao", "balcão",
    "recepcao", "recepção", "fulano",
    # Função ou local, não pessoa.
    "direcao", "direção", "treinamento", "monitoramento", "teste", "reuniao",
    "reunião", "almoxarifado", "deposito", "depósito", "pc ", "notebook",
)


def _eh_placeholder(nome_parte):
    base = (nome_parte or "").strip().lower()
    if not base:
        return True
    return any(base == p or base.startswith(p) for p in _PLACEHOLDERS)


def _person_por_nome(nome):
    """Acha UMA Person pelo nome (nome cheio; senão primeiro nome único).

    O segundo passo já esteve quebrado: comparava o primeiro nome do texto com
    o `full_name` INTEIRO (`full_name__iexact=primeiro`). Isso só casaria com
    alguém cadastrado literalmente como "Arthur" — nunca com "Arthur Souza",
    que é o caso normal. Na prática o fallback nunca pegou, e os notebooks
    importados da planilha ficaram com texto e sem vínculo: a tabela mostrava
    o nome e o formulário mostrava "Selecione…".

    Hoje ele compara primeiro nome COM primeiro nome, e continua devolvendo
    None quando há mais de uma candidata — adivinhar aqui colocaria a máquina
    na mão da pessoa errada sem ninguém perceber.
    """
    nome = (nome or "").strip()
    if not nome or _eh_placeholder(nome):
        return None

    qs = Person.objects.filter(full_name__iexact=nome)
    if qs.count() == 1:
        return qs.first()
    if qs.count() > 1:
        return None

    partes = nome.split()
    # O fallback por primeiro nome SÓ vale quando o texto não afirma sobrenome.
    #
    # "Jonas" não diz qual Jonas é — achar um único "João Bernardes" resolve.
    # Já "Paula Andrade" afirma um sobrenome; se o cadastro só tem "Paula
    # Lima", são provavelmente pessoas diferentes (ou uma mesa de dois). Cair no
    # primeiro nome aí entrega o equipamento à pessoa errada, e ninguém percebe
    # porque o sistema fica coerente consigo mesmo.
    if len(partes) > 1:
        return None

    primeiro = partes[0]
    # `istartswith` com o espaço evita que "Ana" case com "Anatólio"; o
    # `iexact` cobre quem está cadastrado só com o primeiro nome.
    candidatos = list(
        Person.objects.filter(
            Q(full_name__istartswith=primeiro + " ") | Q(full_name__iexact=primeiro)
        )[:3]
    )
    return candidatos[0] if len(candidatos) == 1 else None


@receiver(pre_save, sender=Notebook)
def conectar_notebook_ao_colaborador(sender, instance, **kwargs):
    """Tudo conectado: o notebook segue o colaborador, que pertence a um setor.

    1) Se não há colaborador vinculado mas o nome (usuario) bate com UM colaborador
       cadastrado, faz o vínculo automaticamente.
    2) Com colaborador, a unidade/setor do notebook passa a ser a do colaborador
       (unidade = local, setor = departamento) — assim ele aparece no setor certo.
    """
    if instance.colaborador_id is None and instance.usuario:
        pessoa = _person_por_nome(instance.usuario)
        if pessoa is not None:
            instance.colaborador = pessoa

    c = instance.colaborador
    if c is not None and c.location_id:
        setor = c.department.name if c.department_id else ""
        instance.unidade_setor = f"{c.location.name}{' / ' + setor if setor else ''}"


@receiver(pre_delete, sender=MovimentacaoPeca)
def estornar_movimentacao_peca(sender, instance, **kwargs):
    """Excluir a transferência ESTORNA o estoque: devolve à origem e tira do destino."""
    qtd = instance.quantidade or 0
    if not qtd:
        return
    if instance.unidade_origem_id:
        origem, _ = Peca.objects.get_or_create(
            unidade_id=instance.unidade_origem_id, tipo=instance.tipo,
            descricao=instance.descricao, defaults={"quantidade": 0},
        )
        origem.quantidade = (origem.quantidade or 0) + qtd
        origem.save(update_fields=["quantidade"])
    if instance.unidade_destino_id:
        destino = Peca.objects.filter(
            unidade_id=instance.unidade_destino_id, tipo=instance.tipo,
            descricao=instance.descricao,
        ).first()
        if destino:
            destino.quantidade = max(0, (destino.quantidade or 0) - qtd)
            destino.save(update_fields=["quantidade"])


def partes_do_nome_da_baia(nome):
    """Separa "1 - Simone (Marketing)" em (numero, nome_do_ocupante).

    Extraído do signal para o comando `casar_baias` e a auditoria usarem a
    MESMA leitura. Enquanto isso morava só aqui dentro, a auditoria inventava a
    própria regra e acusava 42 baias com problema onde havia 4 — as outras 38
    eram "Direita", "Esquerda", "Vazio", que são posição e não gente.

    O parêntese final é descartado: "Simone (Marketing)" é a Simone, e o setor
    entre parênteses impedia o casamento por nome.
    """
    bruto = (nome or "").strip()
    numero = None

    m = _BAIA_RE.match(bruto)
    if m:
        numero = int(m.group(1))
        parte = m.group(2).strip()
    else:
        so_num = _BAIA_SO_NUM_RE.match(bruto)
        if so_num:
            numero = int(so_num.group(1))
            parte = ""
        else:
            parte = bruto

    parte = re.sub(r"\s*\([^)]*\)\s*$", "", parte).strip()
    return numero, parte


@receiver(pre_save, sender=Baia)
def numerar_e_conectar_baia(sender, instance, **kwargs):
    """A baia é identificada por um NÚMERO; o ocupante do nome vira colaborador.

    "1 - Valéria" → numero=1 e colaborador=Valéria (se ela já estiver cadastrada).
    Placeholders ("Vazio", "Caixa", "Conferente"...) não viram colaborador.
    """
    numero, nome_parte = partes_do_nome_da_baia(instance.nome)
    if numero is not None:
        instance.numero = numero
    # Vincula o colaborador a partir do nome, se ainda não houver um.
    if instance.colaborador_id is None and not _eh_placeholder(nome_parte):
        pessoa = _person_por_nome(nome_parte)
        if pessoa is not None:
            instance.colaborador = pessoa


@receiver(pre_save, sender=Baia)
def gerar_computador_da_baia(sender, instance, **kwargs):
    """Toda baia COM PC e sem computador vinculado vira um Computador do estoque,
    com PATRIMÔNIO GERADO AUTOMATICAMENTE pela loja da baia.

    Assim, ao cadastrar uma máquina que existia fisicamente mas não estava no
    sistema (ex.: criar a baia "Pós Venda" em Bonsucesso com um PC), o patrimônio
    sai sozinho. Notebooks e baias Sem PC não geram. O patrimônio em si é gerado
    no Computador.save() a partir de `ultima_unidade`.
    """
    # SÓ para baias NOVAS (importação/cadastro). Em baias existentes, DESVINCULAR um
    # dispositivo (desativar/remover/transferir) NÃO pode recriar um computador fantasma
    # a partir de specs legadas que sobraram nas colunas da própria baia.
    if instance.pk:
        return
    if instance.computador_id or instance.notebook_id:
        return
    # Só gera um Computador quando há SPECS PRÓPRIAS digitadas (importação/edição manual);
    # mesa vazia (sem specs e sem dispositivo) permanece vazia.
    if not any([instance.sistema_operacional, instance.processador, instance.placa_mae,
                instance.memoria_ram, instance.armazenamento]):
        return
    if not instance.setor_id:
        return
    unidade_nome = instance.setor.unidade.name
    comp = Computador.objects.create(
        sistema_operacional=instance.sistema_operacional,
        processador=instance.processador,
        placa_mae=instance.placa_mae,
        memoria_ram=instance.memoria_ram,
        armazenamento=instance.armazenamento,
        status=(Computador.Status.DEFEITO if instance.pc_status == SOChoices.DEFEITO
                else Computador.Status.EM_USO),
        ultima_unidade=unidade_nome,
    )
    instance.computador = comp


@receiver(pre_save, sender=Baia)
def _guardar_computador_anterior(sender, instance, **kwargs):
    """Guarda com QUAL computador a baia estava, para o post_save saber qual
    liberar. É um SELECT por pk (barato) que substitui uma varredura de tabela
    inteira a cada save — ver `sincronizar_status_computador`."""
    if not instance.pk:
        instance._computador_anterior_id = None
        return
    instance._computador_anterior_id = (
        Baia.objects.filter(pk=instance.pk)
        .values_list("computador_id", flat=True).first()
    )


@receiver(post_save, sender=Baia)
def sincronizar_status_computador(sender, instance, **kwargs):
    """
    Mantém o status do computador em sincronia com o vínculo:
      • vinculado a uma baia  → "Em uso"
      • saiu desta baia       → volta para "Em estoque" (se não foi para outra)
    Não mexe em computadores marcados como Defeito/Desativado (status manual).

    ANTES: liberava com `filter(status=EM_USO, baia__isnull=True).update(...)`,
    isto é, uma VARREDURA DA TABELA INTEIRA de computadores a **cada save de
    baia** — no SQLite isso é um lock global de escrita, e era uma das causas
    do "database is locked" com o servidor 24/7 + agentes de telemetria.
    AGORA: libera só o computador que realmente saiu desta baia.
    Para reconciliar o parque inteiro (casos em que o vínculo mudou por
    `queryset.update()`, que não dispara signal), use:
        manage.py sincronizar_status_computadores
    """
    if instance.computador_id:
        Computador.objects.filter(
            pk=instance.computador_id
        ).exclude(
            status__in=[Computador.Status.DEFEITO, Computador.Status.DESATIVADO]
        ).exclude(
            status=Computador.Status.EM_USO
        ).update(status=Computador.Status.EM_USO)

    anterior = getattr(instance, "_computador_anterior_id", None)
    if anterior and anterior != instance.computador_id:
        Computador.objects.filter(
            pk=anterior, status=Computador.Status.EM_USO, baia__isnull=True
        ).update(status=Computador.Status.EM_ESTOQUE)


@receiver(pre_save, sender=Baia)
def guardar_pc_anterior_da_baia(sender, instance, **kwargs):
    """Anota qual PC estava na mesa antes de salvar.

    Sem isto, tirar o computador da baia deixaria o usuário grudado nele: o
    `post_save` só enxerga o vínculo NOVO, e a máquina que saiu continuaria
    dizendo que é da pessoa daquela mesa — justamente o rastro falso que este
    campo veio eliminar.
    """
    instance._pc_anterior_id = None
    if instance.pk:
        antes = Baia.objects.filter(pk=instance.pk).values_list(
            "computador_id", flat=True).first()
        instance._pc_anterior_id = antes


@receiver(post_save, sender=Baia)
def sincronizar_usuario_do_pc(sender, instance, **kwargs):
    """Quem senta na baia é quem usa o computador que está nela.

    A REGRA, dita pelo dono em 05/10/2026: a baia é referência física — serve
    para achar a máquina na empresa. O computador fica nela com ou sem alguém.
    Pôr um colaborador na baia passa a máquina para ele; TIRAR o colaborador
    deixa o PC onde está, sem usuário.

    Por que gravar no computador em vez de só olhar a baia: sem este campo, "de
    quem é esta máquina" só se responde passando pela mesa, e máquina fora de
    mesa (estoque, conserto) não responde de jeito nenhum. Agora o dado está no
    bem, que é o que o sistema existe para rastrear.

    `update()` em vez de `save()` de propósito: não re-dispara signal e não
    mexe em `atualizado_em` — isto é espelhamento, não edição do computador.
    """
    # O PC que SAIU da mesa perde o usuário: ele não está mais com ninguém.
    anterior = getattr(instance, "_pc_anterior_id", None)
    if anterior and anterior != instance.computador_id:
        Computador.objects.filter(pk=anterior).exclude(
            colaborador__isnull=True).update(colaborador=None)

    if not instance.computador_id:
        return
    Computador.objects.filter(pk=instance.computador_id).exclude(
        colaborador_id=instance.colaborador_id
    ).update(colaborador_id=instance.colaborador_id)


@receiver(post_delete, sender=Baia)
def liberar_dispositivo_da_baia_apagada(sender, instance, **kwargs):
    """Apagar a MESA não apaga a MÁQUINA — ela volta para o estoque.

    Pedido do dono em 13/10/2026, ao apagar baias de teste: "caso exclua, o pc
    saia da baia, mas sem ser apagado". O banco já garantia metade disso: o
    vínculo mora na baia (`Baia.computador`), então apagar a linha da baia leva
    só o vínculo, nunca o computador.

    A outra metade faltava e era um fantasma: o PC ficava marcado "Em uso",
    com colaborador, sem mesa nenhuma. Sumia do mapa (que desenha por baia) e
    não aparecia no estoque (que lista por status) — some da tela sem sair do
    banco, que é o pior jeito de um patrimônio desaparecer.

    Aqui, e não na view que apaga, porque existe mais de um caminho para apagar
    uma baia (mapa, tabela, admin, shell) e todos têm de soltar a máquina.
    Defeito/Desativado são status decididos por gente e não se mexe neles.

    O NOTEBOOK fica como está, de propósito: ele acompanha a pessoa, não a
    mesa (ver `sincronizar_notebook_da_baia`). Perde a mesa e segue com o dono.
    """
    if not instance.computador_id:
        return
    Computador.objects.filter(pk=instance.computador_id).exclude(
        status__in=[Computador.Status.DEFEITO, Computador.Status.DESATIVADO]
    ).update(status=Computador.Status.EM_ESTOQUE)
    # Sem mesa não há quem use: mesma regra de quando o PC sai da baia.
    Computador.objects.filter(pk=instance.computador_id).exclude(
        colaborador__isnull=True).update(colaborador=None)


@receiver(post_save, sender=Baia)
def sincronizar_notebook_da_baia(sender, instance, **kwargs):
    """REGRA: o notebook é a "camada" do COLABORADOR — acompanha ele na mesa.

    (1) Mesa com um colaborador que POSSUI notebook e SEM computador de mesa → o
        notebook dele fica automaticamente na mesa (tirando de outra mesa, se preciso).
        Quando a mesa NÃO tem colaborador, não força nada (um notebook alocado
        manualmente numa mesa vazia é preservado).
    (2) O notebook que está na mesa segue o colaborador/unidade e fica Ativo.
    """
    # (1) O notebook do colaborador acompanha ele.
    alvo = instance.notebook_id
    if instance.colaborador_id and not instance.computador_id:
        nb0 = instance.colaborador.notebooks.first()
        if nb0:
            alvo = nb0.pk
    if alvo != instance.notebook_id:
        # update() em vez de save() → não re-dispara este signal (evita recursão).
        if alvo:
            Baia.objects.filter(notebook_id=alvo).exclude(pk=instance.pk).update(notebook=None)
        Baia.objects.filter(pk=instance.pk).update(notebook=alvo)
        instance.notebook_id = alvo

    # (2) Sincroniza os dados do notebook que ficou na mesa.
    if not instance.notebook_id:
        return
    nb = Notebook.objects.filter(pk=instance.notebook_id).first()
    if nb is None:
        # O notebook sumiu (apagado por fora / dado inconsistente). Antes isso
        # era `.get()` e estourava 500 em QUALQUER save da baia.
        logger.warning(
            "Baia %s aponta para notebook %s que não existe; limpando o vínculo.",
            instance.pk, instance.notebook_id,
        )
        Baia.objects.filter(pk=instance.pk).update(notebook=None)
        instance.notebook_id = None
        return
    campos = []
    if instance.colaborador_id and nb.colaborador_id != instance.colaborador_id:
        nb.colaborador_id = instance.colaborador_id
        nb.usuario = instance.colaborador.full_name
        campos += ["colaborador", "usuario"]
    elif not instance.colaborador_id and instance.setor_id:
        uni = instance.setor.unidade.name
        if nb.unidade_setor != uni:
            nb.unidade_setor = uni
            campos.append("unidade_setor")
    if nb.status == Notebook.Status.OBSOLETO:
        nb.status = Notebook.Status.ATIVO
        campos.append("status")
    if campos:
        nb.save(update_fields=list(dict.fromkeys(campos)) + ["atualizado_em"])


@receiver(post_save, sender=Reparo)
def incrementar_reparos_do_computador(sender, instance, created, **kwargs):
    """A cada novo reparo, soma 1 no contador da máquina (Computador) da baia."""
    if not created:
        return
    comp_id = getattr(instance.baia, "computador_id", None)
    if comp_id:
        Computador.objects.filter(pk=comp_id).update(qtd_reparos=F("qtd_reparos") + 1)


# Mapa: peça do reparo → campo de especificação na máquina (baia / computador).
_PECA_PARA_SPEC = {
    Reparo.Peca.PROCESSADOR: "processador",
    Reparo.Peca.MEMORIA_RAM: "memoria_ram",
    Reparo.Peca.ARMAZENAMENTO: "armazenamento",
}


@receiver(post_save, sender=Reparo)
def aplicar_upgrade_na_maquina(sender, instance, **kwargs):
    """UPGRADE de peça atualiza a spec da máquina → o score recalcula sozinho.

    Quando o reparo é tipo 'Upgrade', a peça é Processador/RAM/Armazenamento e há
    'nova_especificacao', grava o novo valor no computador vinculado (ou nos campos
    da própria baia, se não houver computador)."""
    campo = _PECA_PARA_SPEC.get(instance.peca)
    nova = (instance.nova_especificacao or "").strip()
    if instance.tipo != Reparo.Tipo.UPGRADE or not campo or not nova:
        return
    # Chamado de notebook solto: atualiza a spec no próprio notebook.
    if instance.notebook_id:
        Notebook.objects.filter(pk=instance.notebook_id).update(**{campo: nova})
        return
    baia = instance.baia
    if not baia:
        return
    if baia.computador_id:
        Computador.objects.filter(pk=baia.computador_id).update(**{campo: nova})
    else:
        # Atualiza direto na baia (evita re-disparar signals de Baia desnecessários).
        Baia.objects.filter(pk=baia.pk).update(**{campo: nova})


@receiver(post_delete, sender=Reparo)
def decrementar_reparos_do_computador(sender, instance, **kwargs):
    """Se um reparo for excluído, ajusta o contador para baixo (sem ficar negativo)."""
    comp_id = getattr(instance.baia, "computador_id", None)
    if comp_id:
        Computador.objects.filter(pk=comp_id, qtd_reparos__gt=0).update(
            qtd_reparos=F("qtd_reparos") - 1
        )


@receiver(post_save, sender=Baia)
def sincronizar_departamento_da_pessoa(sender, instance, **kwargs):
    if not instance.colaborador_id:
        return
    setor = instance.setor
    departamento, _ = Department.objects.get_or_create(
        name=setor.nome, location_id=setor.unidade_id
    )
    pessoa = instance.colaborador
    campos = []
    if pessoa.department_id != departamento.id:
        pessoa.department = departamento
        campos.append("department")
    if pessoa.location_id != setor.unidade_id:
        pessoa.location_id = setor.unidade_id
        campos.append("location")
    if campos:
        pessoa.save(update_fields=campos)


# --- Visão unificada: todo colaborador ativo de uma loja aparece no mapa ------
def garantir_baia_do_colaborador(person):
    """Garante que um colaborador ATIVO com loja tenha uma baia no mapa.

    Cria uma baia VAZIA (sem dispositivo) no setor do departamento do colaborador
    (ou "A alocar" se não tiver departamento), criando o setor na loja se faltar.
    Assim toda pessoa da loja aparece nos mapas mesmo sem computador/notebook.
    Idempotente: se o colaborador já tem baia, não faz nada.
    """
    if not person or not person.active or not person.location_id:
        return None
    if Baia.objects.filter(colaborador=person).exists():
        return None
    nome_setor = (person.department.name if person.department_id else "").strip() or "A alocar"
    setor, _ = Setor.objects.get_or_create(unidade_id=person.location_id, nome=nome_setor)
    ultimo = Baia.objects.filter(setor=setor).aggregate(m=Max("numero"))["m"] or 0
    return Baia.objects.create(
        setor=setor, colaborador=person, nome=f"{ultimo + 1} - {person.full_name}",
    )


@receiver(post_save, sender=Person)
def garantir_baia_ao_salvar_pessoa(sender, instance, **kwargs):
    """Ao salvar um colaborador com loja, garante a baia dele no mapa."""
    garantir_baia_do_colaborador(instance)
