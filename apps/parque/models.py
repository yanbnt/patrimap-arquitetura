"""
Parque de Máquinas — espelha a planilha "Levantamento das Máquinas".

Hierarquia: Unidade (orgs.Location) › Setor › Baia.
A Baia é a posição de trabalho e guarda o PC atual (specs) + periféricos +
colaborador ocupante. O computador é identificado PELA BAIA (decisão do projeto).
A Transferência registra a movimentação de um PC entre baias, com snapshot das
specs antigas e novas — replicando a aba "Transferências".
"""

import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .campos import CampoTextoCifrado

logger = logging.getLogger(__name__)

# Janela de tempo (em dias) considerada para o fator de reparos no desempenho.
JANELA_REPAROS_DIAS = 182  # ~6 meses

# Periodicidade da manutenção PREVENTIVA: toda máquina deve passar a cada 60 dias.
PREVENTIVA_DIAS = 60
# Antecedência (dias) para começar a alertar "preventiva chegando".
PREVENTIVA_ALERTA_DIAS = 14
# Telemetria: a máquina é considerada "ativa" se enviou coleta nas últimas N horas.
TELEMETRIA_ATIVA_HORAS = 2
# Tarefas de saúde: uptime alto (máquina ligada direto há N dias) vira tarefa.
UPTIME_ALTO_DIAS = 7
# Tarefas de saúde: score de desempenho <= este valor conta como "baixo".
SCORE_TAREFA_MAX = 55


def humanizar_uptime(seg):
    """Tempo ligada em formato legível (ex.: '3d 5h', '2h 10min', '5min')."""
    if not seg:
        return "—"
    d, r = divmod(int(seg), 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}min"
    return f"{m}min"
# Itens do mini-checklist da manutenção preventiva (chave, rótulo).
PREVENTIVA_CHECKLIST = [
    ("limpeza", "Limpeza física (gabinete/ventoinhas)"),
    ("cabos", "Cabos e conexões"),
    ("atualizacoes", "Atualizações do sistema"),
    ("antivirus", "Antivírus / segurança"),
    ("disco", "Espaço em disco / limpeza"),
    ("hardware", "Teste de hardware (memória/disco)"),
    ("backup", "Backup / integridade"),
]


def _score_cpu(texto):
    """Pontua o processador (0–100) por família + geração + clock."""
    t = (texto or "").lower()
    if not t:
        return 0
    if "i9" in t or "ryzen 9" in t or "ryzen 7" in t:
        base = 90
    elif "i7" in t:
        base = 75
    elif "i5" in t:
        base = 55
    elif "i3" in t:
        base = 40
    elif "celeron" in t or "pentium" in t or "atom" in t:
        base = 15
    else:
        base = 45
    m = re.search(r"i[357]\D*(\d{3,5})", t)
    if m:
        num = m.group(1)
        geracao = int(num[0]) if len(num) >= 4 else 1
        base += geracao * 4
    mc = re.search(r"(\d[.,]\d+)\s*ghz", t)
    if mc:
        base += (float(mc.group(1).replace(",", ".")) - 2.0) * 5
    return max(0, min(100, round(base)))


def _score_ram(texto):
    m = re.search(r"(\d+[.,]?\d*)\s*gb", (texto or "").lower())
    if not m:
        return 0
    gb = float(m.group(1).replace(",", "."))
    for limite, nota in ((2, 10), (4, 35), (6, 50), (8, 70), (12, 85)):
        if gb <= limite:
            return nota
    return 100


def _score_disco(texto):
    t = (texto or "").lower()
    if "nvme" in t or "m.2" in t:
        return 100
    tem_ssd, tem_hd = "ssd" in t, ("hd" in t or "hdd" in t)
    if tem_ssd and tem_hd:
        return 90
    if tem_ssd:
        return 85
    if tem_hd:
        return 30
    return 0


def _classe_desempenho(n):
    """Classe textual a partir da nota 0–100 (mesma régua p/ baia e notebook)."""
    if n is None:
        return "—"
    if n <= 35:
        return "Crítico"
    if n <= 55:
        return "Baixo"
    if n <= 75:
        return "Bom"
    return "Ótimo"


def diagnostico_desempenho(cpu_txt, ram_txt, disco_txt, em_defeito=False, reparos_recentes=0):
    """Explica o que derruba o score e sugere a solução. Lista de (causa, solução, nível)."""
    itens = []
    if em_defeito:
        itens.append(("Equipamento com defeito",
                      "Abrir um chamado de reparo para normalizar a máquina.", "alto"))
    cpu = _score_cpu(cpu_txt)
    if not cpu_txt:
        itens.append(("Processador não informado",
                      "Cadastrar o processador para avaliar o desempenho.", "medio"))
    elif cpu < 55:
        itens.append(("Processador de baixo desempenho",
                      "Avaliar troca por um Intel Core i5 / Ryzen 5 de geração recente.",
                      "alto" if cpu < 40 else "medio"))
    ram = _score_ram(ram_txt)
    if not ram_txt:
        itens.append(("Memória RAM não informada",
                      "Cadastrar a memória RAM da máquina.", "medio"))
    elif ram < 70:
        itens.append(("Pouca memória RAM",
                      "Expandir a memória para 8GB ou mais.",
                      "alto" if ram <= 35 else "medio"))
    disco = _score_disco(disco_txt)
    if not disco_txt:
        itens.append(("Armazenamento não informado",
                      "Cadastrar o disco (HD/SSD) da máquina.", "medio"))
    elif disco <= 30:
        itens.append(("Disco lento (HD mecânico)",
                      "Trocar o HD por um SSD — é o upgrade de maior impacto.", "alto"))
    if reparos_recentes:
        itens.append((f"{reparos_recentes} reparo(s) nos últimos 6 meses",
                      "Histórico recente penaliza o score; monitorar reincidência.", "baixo"))
    return [{"causa": c, "solucao": s, "nivel": n} for (c, s, n) in itens]


class SOChoices(models.TextChoices):
    """Situação do computador na baia."""
    TEM_PC = "tem_pc", "Com PC"
    SEM_PC = "sem_pc", "Sem PC"
    NOTEBOOK = "notebook", "Usa notebook"
    DEFEITO = "defeito", "Com defeito"


class PerifStatus(models.TextChoices):
    """Estado de um periférico."""
    SIM = "sim", "Sim"
    NAO = "nao", "Não"
    DEFEITO = "defeito", "Sim, porém com defeito"


class Computador(models.Model):
    """
    Computador cadastrado de forma INDEPENDENTE (estoque). Carrega as specs e pode
    ser **vinculado a uma Baia** (OneToOne em Baia.computador). Quando vinculado,
    a baia usa as specs deste computador e o status vira "Em uso"; ao desvincular,
    volta para "Em estoque". Identificado pelo nº de patrimônio/etiqueta.
    """

    class Status(models.TextChoices):
        EM_ESTOQUE = "em_estoque", "Em estoque"
        EM_USO = "em_uso", "Em uso"
        DEFEITO = "defeito", "Com defeito"
        DESATIVADO = "desativado", "Desativado"

    patrimonio = models.CharField(
        "patrimônio / etiqueta", max_length=40, unique=True,
        help_text="Código único do computador. Ex.: PC-0001.",
    )
    serial = models.CharField(
        "número de série", max_length=80, blank=True,
        help_text="Número de série do equipamento (opcional).",
    )
    mac = models.CharField(
        "MAC (identidade física)", max_length=12, blank=True, db_index=True,
        help_text="Endereço MAC (hex) que identifica esta máquina de forma única. "
                  "Preenchido pela telemetria; a coleta casa por MAC de forma permanente.",
    )
    marca = models.CharField(
        "marca / fabricante", max_length=80, blank=True,
        help_text="Ex.: Dell, Positivo, Lenovo.",
    )
    sistema_operacional = models.CharField(
        "S.O", max_length=80, blank=True, help_text="Ex.: Windows 11.",
    )
    processador = models.CharField(
        "processador", max_length=120, blank=True,
        help_text="Ex.: Intel Core i5 12400 2.50GHz.",
    )
    placa_mae = models.CharField("placa mãe", max_length=120, blank=True)
    memoria_ram = models.CharField("memória RAM", max_length=60, blank=True,
                                   help_text="Ex.: 16GB DDR4.")
    armazenamento = models.CharField("armazenamento", max_length=80, blank=True,
                                     help_text="Ex.: SSD NVMe 480GB.")
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices,
        default=Status.EM_ESTOQUE, db_index=True,
        help_text="Em estoque, Em uso, Com defeito ou Desativado. Fica 'Em uso' "
                  "automaticamente ao ser vinculado a uma baia.",
    )
    sankhya_id = models.CharField(
        "ID Sankhya", max_length=60, blank=True,
        help_text="ID deste computador no Sankhya (usado futuramente para puxar as informações).",
    )
    valor_compra = models.DecimalField(
        "valor de compra (R$)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Valor pago na compra do equipamento.",
    )
    data_compra = models.DateField(
        "data da compra", null=True, blank=True,
        help_text="Data em que o equipamento foi comprado.",
    )
    qtd_reparos = models.PositiveIntegerField(
        "reparos realizados", default=0,
        help_text="Quantidade de reparos já feitos nesta máquina. O sistema "
                  "incrementa automaticamente a cada novo reparo registrado.",
    )
    # QUEM ESTÁ USANDO — o ponto do sistema.
    #
    # Antes isto só existia na baia, e o computador não sabia de quem era: quem
    # sabia era a mesa. Na prática a pergunta "de quem é esta máquina" exigia
    # passar pela baia, e filtrar por pessoa no estoque era impossível.
    #
    # O valor VEM DA BAIA e é mantido pelo signal `sincronizar_usuario_do_pc`:
    # a baia é a referência física, e quem senta nela é quem usa a máquina.
    # Tirar a pessoa da baia LIMPA este campo — o PC continua na mesa, sem
    # usuário. É a regra do dono, dita em 05/10/2026.
    #
    # Não editar à mão: mexer aqui sem mexer na baia faz os dois discordarem, e
    # foi exatamente esse tipo de divergência (texto x vínculo no notebook) que
    # deixou a tabela e o formulário contando histórias diferentes.
    colaborador = models.ForeignKey(
        "orgs.Person", verbose_name="utilizado por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="computadores",
        help_text="Colaborador que usa esta máquina. Vem da baia onde ela está "
                  "— para trocar, mude o colaborador da baia.",
    )
    # Última localização conhecida (preenchida ao desativar/desvincular da baia).
    ultima_unidade = models.CharField("última unidade", max_length=120, blank=True)
    ultima_baia = models.CharField("última baia", max_length=160, blank=True)
    notes = models.TextField("observações", blank=True)
    # Telemetria REAL (coletada pelo agente): specs medidas na máquina. Quando
    # preenchidas, prevalecem sobre as digitadas no cálculo do score (*_efetivo).
    tel_cpu = models.CharField("CPU (telemetria)", max_length=120, blank=True)
    tel_ram = models.CharField("RAM (telemetria)", max_length=60, blank=True)
    tel_disco = models.CharField("disco (telemetria)", max_length=80, blank=True)
    tel_so = models.CharField("S.O (telemetria)", max_length=80, blank=True)
    tel_gpu = models.CharField("vídeo (telemetria)", max_length=80, blank=True)
    tel_uptime_seg = models.BigIntegerField("tempo ligada (telemetria)", null=True, blank=True)
    tel_local = models.CharField("localização (telemetria)", max_length=120, blank=True)
    tel_visto_em = models.DateTimeField("telemetria vista em", null=True, blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "computador (estoque)"
        verbose_name_plural = "estoque de computadores"
        ordering = ["status", "patrimonio"]

    def save(self, *args, **kwargs):
        # SEMPRE gera o patrimônio automaticamente quando não vier um (qualquer
        # caminho de criação: admin, +Baia no mapa, importação, programático).
        if (self.patrimonio or "").strip():
            return super().save(*args, **kwargs)

        # `proximo_patrimonio` lê o maior número existente e soma 1 — duas
        # criações simultâneas calculam o MESMO número. O campo é `unique`, então
        # a segunda estoura IntegrityError: recalcula e tenta de novo. Cada
        # tentativa vai em savepoint próprio, senão o erro aborta a transação
        # externa inteira e o retry falha na cara.
        ultima = 5
        for tentativa in range(1, ultima + 1):
            self.patrimonio = proximo_patrimonio(self.ultima_unidade or "")
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as erro:
                colidiu = "patrimonio" in str(erro).lower()
                if not colidiu or tentativa == ultima:
                    raise
                logger.warning(
                    "Patrimônio %s já existia (tentativa %d/%d); recalculando.",
                    self.patrimonio, tentativa, ultima,
                )
                self.patrimonio = ""

    # Specs EFETIVAS: o CADASTRO manda; a telemetria preenche o que está vazio.
    #
    # Era o contrário (`tel_cpu or processador`), e isso produzia a queixa mais
    # difícil de entender do sistema: a pessoa editava o cadastro da máquina,
    # salvava com sucesso, e o parque continuava mostrando o valor velho — sem
    # erro nenhum na tela. A edição não era perdida; era SOMBREADA pela leitura
    # do agente, que vinha primeiro no `or`. Somado a isso, `aplicar_na_maquina`
    # reescrevia o cadastro a cada coleta (a cada 30 min), então o valor
    # digitado também desaparecia do banco.
    #
    # Decisão do Jonas em 21/09/2026: manda o que a pessoa digita. O agente
    # passou a só completar campo vazio (ver `aplicar_na_maquina`) e a nunca
    # sobrescrever. Onde os dois discordam, `divergencias_telemetria` entrega o
    # par para a tela avisar — em vez de um dos dois sumir calado.
    @property
    def tem_telemetria(self):
        return self.tel_visto_em is not None

    @property
    def cpu_efetivo(self):
        return self.processador or self.tel_cpu

    @property
    def ram_efetivo(self):
        return self.memoria_ram or self.tel_ram

    @property
    def disco_efetivo(self):
        return self.armazenamento or self.tel_disco

    @property
    def so_efetivo(self):
        return self.sistema_operacional or self.tel_so

    @property
    def divergencias_telemetria(self):
        """Onde o cadastro digitado discorda do que o agente mediu.

        Devolve [(rótulo, valor_no_cadastro, valor_medido)]. Vazio quando não
        há agente, quando o campo do cadastro está em branco (aí não há
        conflito: a telemetria é o que aparece) ou quando os dois batem.

        Existe porque inverter a precedência tem um preço: um erro de digitação
        no cadastro passaria a esconder a leitura real da máquina. Em vez de
        escolher um dos dois em silêncio, a tela mostra os dois e quem decide é
        gente. A comparação ignora caixa e espaço de sobra — "8 GB" e "8gb" não
        são divergência, são a mesma coisa escrita de dois jeitos.
        """
        if not self.tel_visto_em:
            return []

        def _norm(v):
            return " ".join((v or "").split()).casefold()

        pares = [
            ("Processador", self.processador, self.tel_cpu),
            ("Memória", self.memoria_ram, self.tel_ram),
            ("Armazenamento", self.armazenamento, self.tel_disco),
            ("Sistema", self.sistema_operacional, self.tel_so),
        ]
        return [(rot, cad, med) for rot, cad, med in pares
                if cad and med and _norm(cad) != _norm(med)]

    @property
    def telemetria_status(self):
        """'ativo' (coleta recente) | 'inativo' (coletou mas faz tempo) | 'sem'."""
        if not self.tel_visto_em:
            return "sem"
        if self.tel_visto_em >= timezone.now() - timedelta(hours=TELEMETRIA_ATIVA_HORAS):
            return "ativo"
        return "inativo"

    @property
    def tel_uptime_humano(self):
        return humanizar_uptime(self.tel_uptime_seg)

    def __str__(self):
        partes = [self.marca, self.processador, self.armazenamento]
        resumo = " · ".join(p for p in partes if p)
        return f"{self.patrimonio}" + (f" — {resumo}" if resumo else "")

    @property
    def resumo_specs(self):
        partes = [self.sistema_operacional, self.processador, self.armazenamento]
        return " · ".join(p for p in partes if p) or "—"


# Sigla de cada unidade no patrimônio (ex.: PC-B0001 = Bonsucesso).
CODIGOS_UNIDADE = {
    "Bonsucesso": "B", "Cabo Frio": "CF", "Campo Grande": "CG",
    "Centro": "C", "Taquara": "T", "Vilar": "V",
}


def codigo_unidade(nome):
    """Sigla da unidade para o patrimônio (fallback: 1ª letra)."""
    return CODIGOS_UNIDADE.get(nome) or (nome[:1].upper() if nome else "")


def proximo_patrimonio(unidade_nome):
    """Gera o próximo patrimônio (PC-<sigla><NNNN>) continuando a sequência geral."""
    maior = 0
    for p in Computador.objects.values_list("patrimonio", flat=True):
        m = re.search(r"(\d+)$", p or "")
        if m:
            maior = max(maior, int(m.group(1)))
    return f"PC-{codigo_unidade(unidade_nome)}{maior + 1:04d}"


class Setor(models.Model):
    """Setor dentro de uma unidade (Comercial, Logística, Financeiro...)."""

    unidade = models.ForeignKey(
        "orgs.Location",
        verbose_name="unidade",
        on_delete=models.PROTECT,
        related_name="setores",
        help_text="Unidade/filial onde o setor fica. Ex.: Campo Grande, Bonsucesso.",
    )
    nome = models.CharField(
        "nome", max_length=120,
        help_text="Nome do setor. Ex.: Comercial, Logística, Inteligência Comercial.",
    )

    class Meta:
        verbose_name = "setor"
        verbose_name_plural = "setores"
        ordering = ["unidade__name", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["unidade", "nome"], name="unique_setor_por_unidade"
            )
        ]

    def __str__(self):
        return f"{self.unidade} › {self.nome}"


class Baia(models.Model):
    """
    Posição de trabalho. Guarda o computador atual (specs) e os periféricos.
    O nome normalmente identifica o ocupante. Ex.: "3 - Fernando", "1 - Vazio".
    """

    setor = models.ForeignKey(
        Setor,
        verbose_name="setor",
        on_delete=models.CASCADE,
        related_name="baias",
        help_text="Setor ao qual a baia pertence.",
    )
    nome = models.CharField(
        "baia", max_length=120,
        help_text='Identificação da baia, geralmente com o ocupante. '
                  'Ex.: "3 - Fernando", "1 - Vazio".',
    )
    numero = models.PositiveIntegerField(
        "número", null=True, blank=True, db_index=True,
        help_text="Número/posição da baia, extraído do nome automaticamente "
                  '(ex.: "3 - Fernando" → 3). É a identificação da baia.',
    )
    colaborador = models.ForeignKey(
        "orgs.Person",
        verbose_name="colaborador",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baias_ocupadas",
        help_text="Colaborador que ocupa a baia. Selecione uma pessoa já "
                  "cadastrada (não é possível digitar um nome novo aqui).",
    )

    # --- Computador atual na baia ---
    computador = models.OneToOneField(
        Computador,
        verbose_name="computador vinculado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baia",
        help_text="Vincule um computador do estoque. Ao vincular, a baia usa as "
                  "specs dele (os campos abaixo só são usados se NÃO houver "
                  "computador vinculado).",
    )
    notebook = models.OneToOneField(
        "Notebook",
        verbose_name="notebook vinculado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baia",
        help_text="Notebook do estoque alocado a esta mesa (alternativa ao computador). "
                  "Uma mesa tem no máximo UM dispositivo: computador OU notebook.",
    )
    # LEGADO: mantido durante a transição para não quebrar leitores antigos; o estado
    # real da baia agora é DERIVADO do dispositivo (ver esta_vazia/eh_notebook/situacao_label).
    pc_status = models.CharField(
        "situação do PC", max_length=12, choices=SOChoices.choices,
        default=SOChoices.TEM_PC,
        help_text="Com PC, Sem PC, Usa notebook ou Com defeito. "
                  "Se você vincular um computador acima, isto vira 'Com PC' automaticamente "
                  "(só precisa mexer aqui quando NÃO há computador vinculado).",
    )
    sistema_operacional = models.CharField(
        "S.O", max_length=80, blank=True,
        help_text="Sistema operacional. Ex.: Windows 10, Linux Mint 22.1.",
    )
    processador = models.CharField(
        "processador", max_length=120, blank=True,
        help_text="Ex.: Intel Core i5 3470 3.20GHz.",
    )
    placa_mae = models.CharField(
        "placa mãe", max_length=120, blank=True,
        help_text="Ex.: Intel H61, Gigabyte H81M-S1.",
    )
    memoria_ram = models.CharField(
        "memória RAM", max_length=60, blank=True,
        help_text="Ex.: 8.0GB DDR3.",
    )
    armazenamento = models.CharField(
        "armazenamento", max_length=80, blank=True,
        help_text="Ex.: SSD 240GB, HD 466GB.",
    )

    # --- Periféricos ---
    mouse = models.CharField("mouse", max_length=8, choices=PerifStatus.choices, blank=True)
    teclado = models.CharField("teclado", max_length=8, choices=PerifStatus.choices, blank=True)
    webcam = models.CharField("webcam", max_length=8, choices=PerifStatus.choices, blank=True)
    headset = models.CharField("headset", max_length=8, choices=PerifStatus.choices, blank=True)
    monitor = models.CharField("monitor", max_length=8, choices=PerifStatus.choices, blank=True)
    leitor_cod_barras = models.CharField(
        "leitor cód. barras", max_length=8, choices=PerifStatus.choices, blank=True
    )

    notes = models.TextField("observações", blank=True)
    criado_em = models.DateField(
        "em serviço desde", default=timezone.localdate,
        help_text="Data em que a máquina entrou em serviço. Base para contar os "
                  "dias sem manutenção preventiva quando ainda não houve nenhuma.",
    )
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "baia"
        verbose_name_plural = "baias"
        # Identificação é o número, em ordem DECRESCENTE dentro do setor.
        ordering = ["setor__unidade__name", "setor__nome", "-numero", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["setor", "nome"], name="unique_baia_por_setor"
            )
        ]

    def __str__(self):
        return f"{self.setor} › {self.nome}"

    def save(self, *args, **kwargs):
        # Uma mesa = no máximo UM dispositivo. Se vierem os dois, o computador tem
        # precedência (o notebook fica solto).
        if self.computador_id and self.notebook_id:
            self.notebook = None
        # Mantém o pc_status LEGADO coerente com o dispositivo (até ser removido),
        # para que leitores antigos ainda não migrados continuem sensatos.
        if self.notebook_id:
            self.pc_status = SOChoices.NOTEBOOK
        elif self.computador_id:
            self.pc_status = SOChoices.DEFEITO if self._em_defeito else SOChoices.TEM_PC
        else:
            self.pc_status = SOChoices.SEM_PC
        super().save(*args, **kwargs)

    # --- Dispositivo alocado à mesa (computador OU notebook) ---
    @property
    def dispositivo(self):
        """O equipamento alocado à mesa: o computador, senão o notebook, senão None."""
        if self.computador_id:
            return self.computador
        if self.notebook_id:
            return self.notebook
        return None

    @property
    def esta_vazia(self):
        return not self.computador_id and not self.notebook_id

    @property
    def eh_notebook(self):
        return bool(self.notebook_id)

    @property
    def situacao_label(self):
        """Rótulo do estado da mesa (repõe o antigo get_pc_status_display)."""
        if self.notebook_id:
            return "Notebook"
        if self.esta_vazia:
            return "Sem PC"
        if self._em_defeito:
            return "Com defeito"
        return "Com PC"

    @property
    def situacao_key(self):
        """Chave curta do estado (p/ classes CSS .baia--* e data-attrs), derivada do dispositivo."""
        if self.notebook_id:
            return "notebook"
        if self.esta_vazia:
            return "sem_pc"
        if self._em_defeito:
            return "defeito"
        return "tem_pc"

    # --- Specs EFETIVAS: do dispositivo (computador → notebook) senão dos campos da baia ---
    @property
    def eff_so(self):
        if self.computador_id:
            return self.computador.so_efetivo
        if self.notebook_id:
            return self.notebook.so_efetivo  # "" ou telemetria
        return self.sistema_operacional

    @property
    def eff_cpu(self):
        if self.computador_id:
            return self.computador.cpu_efetivo
        if self.notebook_id:
            return self.notebook.cpu_efetivo
        return self.processador

    @property
    def eff_placa(self):
        if self.computador_id:
            return self.computador.placa_mae
        if self.notebook_id:
            return ""  # notebook não guarda placa-mãe
        return self.placa_mae

    @property
    def eff_ram(self):
        if self.computador_id:
            return self.computador.ram_efetivo
        if self.notebook_id:
            return self.notebook.ram_efetivo
        return self.memoria_ram

    @property
    def eff_disco(self):
        if self.computador_id:
            return self.computador.disco_efetivo
        if self.notebook_id:
            return self.notebook.disco_efetivo
        return self.armazenamento

    # Extras SÓ de telemetria (vazios quando não há coleta) — para o card de detalhe.
    @property
    def _disp(self):
        return self.computador or self.notebook

    @property
    def eff_gpu(self):
        d = self._disp
        return getattr(d, "tel_gpu", "") if d else ""

    @property
    def eff_uptime(self):
        d = self._disp
        return d.tel_uptime_humano if (d and getattr(d, "tel_uptime_seg", None)) else ""

    @property
    def eff_local(self):
        d = self._disp
        return getattr(d, "tel_local", "") if d else ""

    @property
    def _em_defeito(self):
        """Defeito = status do DISPOSITIVO alocado (computador ou notebook)."""
        if self.computador_id:
            return self.computador.status == Computador.Status.DEFEITO
        if self.notebook_id:
            return self.notebook.status == Notebook.Status.DEFEITO
        return False

    # Alias público (templates Django não acessam nomes iniciados por "_").
    @property
    def em_defeito(self):
        return self._em_defeito

    @property
    def resumo_pc(self):
        """Resumo curto do dispositivo da mesa para listagens."""
        if self.esta_vazia:
            return self.situacao_label  # "Sem PC"
        partes = [self.eff_so, self.eff_cpu, self.eff_disco]
        return " · ".join(p for p in partes if p) or "—"

    @property
    def manutencao_previsao(self):
        """Maior previsão de conclusão entre reparos EM ANDAMENTO (>= hoje, não concluídos)."""
        hoje = timezone.localdate()
        datas = [
            r.previsao_conclusao for r in self.reparos.all()
            if r.previsao_conclusao and r.previsao_conclusao >= hoje and not r.concluido_em
        ]
        return max(datas) if datas else None

    @property
    def reparos_em_andamento(self):
        """Reparos desta baia ainda não concluídos (previsão definida)."""
        return [
            r for r in self.reparos.all()
            if r.previsao_conclusao and not r.concluido_em
        ]

    @property
    def reparos_abertos(self):
        """TODOS os chamados desta baia ainda não concluídos (com ou sem previsão).

        Base p/ o "Finalizar" do monitor fechar qualquer chamado aberto — não só os
        que estão 'em manutenção' (com previsão)."""
        return [r for r in self.reparos.all() if not r.concluido_em]

    @property
    def em_manutencao(self):
        return bool(self.manutencao_previsao)

    @property
    def manutencao_dias_restantes(self):
        prev = self.manutencao_previsao
        return (prev - timezone.localdate()).days if prev else None

    @property
    def reparos_recentes(self):
        """Nº de REPAROS (que afetam desempenho) nos últimos 6 meses."""
        limite = timezone.localdate() - timedelta(days=JANELA_REPAROS_DIAS)
        # Usa o cache de prefetch quando disponível (evita N+1 em listas/mapas).
        return sum(
            1 for r in self.reparos.all()
            if r.tipo == "reparo" and r.afeta_desempenho and r.data and r.data >= limite
        )

    @property
    def indice_desempenho(self):
        """Nota 0–100: specs (CPU/RAM/disco/saúde) menos penalidade por reparos."""
        if self.esta_vazia:
            return None
        if self.notebook_id:
            return self.notebook.indice_desempenho  # usa a régua do próprio notebook
        cpu = _score_cpu(self.eff_cpu)
        ram = _score_ram(self.eff_ram)
        disco = _score_disco(self.eff_disco)
        saude = 0 if self._em_defeito else 100
        base = 0.45 * cpu + 0.25 * ram + 0.25 * disco + 0.05 * saude
        penalidade = min(30, self.reparos_recentes * 8)
        return max(0, round(base - penalidade))

    @property
    def classe_desempenho(self):
        return _classe_desempenho(self.indice_desempenho)

    @property
    def telemetria_status(self):
        """Status da coleta (agente) do dispositivo da baia — p/ mostrar no mapa."""
        if self.computador_id:
            return self.computador.telemetria_status
        if self.notebook_id:
            return self.notebook.telemetria_status
        return "sem"

    # --- Manutenção PREVENTIVA (a cada PREVENTIVA_DIAS por máquina) ---
    preventiva_adiada_ate = models.DateField(
        "preventiva adiada até", null=True, blank=True,
        help_text="Novo prazo aprovado de adiamento da preventiva. Empurra o "
                  "vencimento; é limpo quando a preventiva é concluída.",
    )

    @property
    def ultima_preventiva(self):
        """Data da última preventiva CONCLUÍDA (tarefa pendente não zera o ciclo)."""
        datas = [
            r.concluido_em for r in self.reparos.all()
            if r.tipo == Reparo.Tipo.PREVENTIVA and r.concluido_em
        ]
        return max(datas) if datas else None

    @property
    def tem_tarefa_preventiva_aberta(self):
        """True se já existe uma tarefa de preventiva pendente (não concluída)."""
        return any(
            r.tipo == Reparo.Tipo.PREVENTIVA and r.concluido_em is None
            for r in self.reparos.all()
        )

    @property
    def diagnostico(self):
        """Causas do score baixo + soluções (vazio para baia sem máquina)."""
        if self.esta_vazia:
            return []
        if self.notebook_id:
            return self.notebook.diagnostico
        return diagnostico_desempenho(
            self.eff_cpu, self.eff_ram, self.eff_disco,
            self._em_defeito, self.reparos_recentes,
        )

    @property
    def diagnostico_json(self):
        return json.dumps(self.diagnostico, ensure_ascii=False)

    @property
    def _preventiva_referencia(self):
        """Marco do ciclo: última preventiva ou, se nunca houve, 'em serviço desde'."""
        return self.ultima_preventiva or self.criado_em

    @property
    def preventiva_vencimento(self):
        """Data-limite da próxima preventiva (marco + 60 dias), respeitando o
        adiamento aprovado (se empurrar para depois)."""
        base = self._preventiva_referencia + timedelta(days=PREVENTIVA_DIAS)
        if self.preventiva_adiada_ate and self.preventiva_adiada_ate > base:
            return self.preventiva_adiada_ate
        return base

    @property
    def preventiva_dias_restantes(self):
        """Dias até a próxima preventiva (negativo = atrasada)."""
        return (self.preventiva_vencimento - timezone.localdate()).days

    @property
    def dias_sem_preventiva(self):
        """Dias decorridos desde a última preventiva (ou desde que entrou em serviço)."""
        return max(0, (timezone.localdate() - self._preventiva_referencia).days)

    @property
    def preventiva_status(self):
        """'em_dia' | 'proxima' | 'vencida' (já fez, mas passou) | 'pendente' (nunca fez e passou).

        None quando a baia não tem máquina física (não precisa de preventiva)."""
        if self.esta_vazia:
            return None
        d = self.preventiva_dias_restantes
        if d < 0:
            return "vencida" if self.ultima_preventiva else "pendente"
        if d <= PREVENTIVA_ALERTA_DIAS:
            return "proxima"
        return "em_dia"


class Transferencia(models.Model):
    """
    Movimentação de um computador entre baias (replica a aba Transferências).
    Guarda o snapshot das specs antigas (origem) e novas (destino).
    """

    # --- Origem ---
    baia_origem = models.ForeignKey(
        Baia,
        verbose_name="baia de origem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transferencias_saida",
        help_text="De qual baia o computador saiu.",
    )
    data_saida = models.DateField(
        "data de saída", null=True, blank=True,
        help_text="Data da saída. Ex.: 16/04/2026.",
    )
    colaborador_saida = models.CharField(
        "colaborador (saída)", max_length=120, blank=True,
        help_text="Responsável/colaborador na origem.",
    )
    so_antigo = models.CharField("S.O", max_length=80, blank=True)
    processador_antigo = models.CharField("processador", max_length=120, blank=True)
    placa_mae_antigo = models.CharField("placa mãe", max_length=120, blank=True)
    ram_antigo = models.CharField("RAM", max_length=60, blank=True)
    armazenamento_antigo = models.CharField("armazenamento", max_length=80, blank=True)

    # --- Destino ---
    baia_destino = models.ForeignKey(
        Baia,
        verbose_name="baia de destino",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transferencias_entrada",
        help_text="Para qual baia o computador foi.",
    )
    data_entrada = models.DateField(
        "data de entrada", null=True, blank=True,
        help_text="Data da entrada no destino.",
    )
    colaborador_destino = models.CharField(
        "colaborador (destino)", max_length=120, blank=True,
        help_text="Responsável/colaborador no destino.",
    )
    so_novo = models.CharField("S.O", max_length=80, blank=True)
    processador_novo = models.CharField("processador", max_length=120, blank=True)
    placa_mae_novo = models.CharField("placa mãe", max_length=120, blank=True)
    ram_novo = models.CharField("RAM", max_length=60, blank=True)
    armazenamento_novo = models.CharField("armazenamento", max_length=80, blank=True)

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transferencias_registradas",
        help_text="Usuário que registrou a transferência (preenchido automaticamente).",
    )
    observacao = models.TextField("observação", blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    # --- Transferência ENTRE LOJAS (fluxo do caminhão) ---
    entre_lojas = models.BooleanField(
        "transferência entre lojas", default=False, db_index=True,
        help_text="Marcada quando a transferência leva o computador para OUTRA "
                  "unidade (fluxo do caminhão). Move o computador de fato e gera "
                  "comprovante de transferência.",
    )
    setor_destino = models.ForeignKey(
        Setor, verbose_name="setor de destino", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transferencias_loja",
        help_text="Setor da unidade de destino que vai receber a máquina.",
    )
    nome_baia_destino = models.CharField(
        "nome da baia de destino", max_length=120, blank=True,
        help_text="Quando uma baia nova é criada no destino, é o nome dela. "
                  "Se a máquina vai para uma baia já existente, fica vazio.",
    )
    computador = models.ForeignKey(
        Computador, verbose_name="computador transferido", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transferencias_loja",
        help_text="Computador que está sendo transferido (snapshot do vínculo).",
    )
    bitrix_task_id = models.CharField(
        "ID da tarefa (Bitrix)", max_length=40, blank=True,
        help_text="ID da tarefa de transferência entre lojas no Bitrix24.",
    )

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente de autorização"
        AUTORIZADA = "autorizada", "Autorizada"
        NEGADA = "negada", "Negada"

    status = models.CharField(
        "situação", max_length=12, choices=Status.choices,
        default=Status.AUTORIZADA, db_index=True,
        help_text="Transferências criadas por quem não pode autorizar ficam pendentes.",
    )
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="decidido por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transferencias_decididas",
    )
    decidido_em = models.DateTimeField("decidido em", null=True, blank=True)
    motivo = models.CharField("motivo (negação)", max_length=200, blank=True)

    class Meta:
        verbose_name = "transferência"
        verbose_name_plural = "transferências"
        ordering = ["-data_entrada", "-created_at"]

    def __str__(self):
        o = self.baia_origem or "?"
        d = self.baia_destino or "?"
        return f"{o} → {d}"

    @transaction.atomic
    def autorizar(self, user):
        """Marca como autorizada e aplica a transferência.

        Entre lojas: move o computador de fato (origem → destino) e abre a tarefa
        no Bitrix. Caso contrário, mantém o comportamento antigo (copia as specs
        'novas' na baia de destino).

        TRANSACIONAL: são 4 escritas (a própria transferência, a baia de origem,
        o computador e a baia de destino). Sem `atomic`, uma falha no meio deixava
        a transferência "autorizada" com o computador nem na origem nem no destino.
        """
        self.status = self.Status.AUTORIZADA
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.save()
        if self.entre_lojas:
            self.aplicar_transferencia_loja()
            # Chamada externa (HTTP) NÃO roda dentro da transação: se o Bitrix
            # demorar ou cair, o banco não fica com lock aberto — e só abrimos a
            # tarefa se a transferência realmente foi gravada.
            transaction.on_commit(self.abrir_tarefa_transferencia_bitrix)
        else:
            self.aplicar_no_destino()

    def negar(self, user, motivo=""):
        self.status = self.Status.NEGADA
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.motivo = (motivo or "")[:200]
        self.save()

    @transaction.atomic
    def aplicar_no_destino(self):
        """Aplica as specs 'novas' na baia de destino (estado atual = destino)."""
        b = self.baia_destino
        if not b:
            return
        if self.so_novo:
            b.sistema_operacional = self.so_novo
            b.pc_status = SOChoices.TEM_PC
        if self.processador_novo:
            b.processador = self.processador_novo
        if self.placa_mae_novo:
            b.placa_mae = self.placa_mae_novo
        if self.ram_novo:
            b.memoria_ram = self.ram_novo
        if self.armazenamento_novo:
            b.armazenamento = self.armazenamento_novo
        if self.colaborador_destino:
            from apps.orgs.models import Person
            pessoa, _ = Person.objects.get_or_create(
                full_name=self.colaborador_destino.strip()
            )
            b.colaborador = pessoa
        b.save()

    @transaction.atomic
    def aplicar_transferencia_loja(self):
        """
        Aplica a transferência ENTRE LOJAS: move o Computador da baia de origem
        para o destino, deixando a origem 'Sem PC' e o destino 'Com PC'.

        Resolve a baia de destino: usa `baia_destino` (vaga existente) ou cria
        uma baia nova no `setor_destino` com `nome_baia_destino`. A baia nova só
        é criada AQUI (na aplicação), nunca numa solicitação pendente.

        TRANSACIONAL: tem `atomic` próprio porque também é chamada direto pela
        view de transferência entre lojas, fora do `autorizar()`.
        """
        origem = self.baia_origem
        comp = self.computador or (origem.computador if origem and origem.computador_id else None)

        # 1) Resolve / cria a baia de destino.
        destino = self.baia_destino
        if destino is None and self.setor_destino_id:
            nome = (self.nome_baia_destino or "").strip() or "Nova baia"
            destino, _ = Baia.objects.get_or_create(
                setor=self.setor_destino, nome=nome,
                defaults={"pc_status": SOChoices.SEM_PC},
            )
            self.baia_destino = destino
            self.save(update_fields=["baia_destino"])
        if destino is None:
            return

        # 2) Move o computador (OneToOne) da origem para o destino.
        if comp is not None:
            if origem is not None and origem.computador_id == comp.pk:
                origem.computador = None
                origem.pc_status = SOChoices.SEM_PC
                origem.save(update_fields=["computador", "pc_status"])
            comp.status = Computador.Status.EM_USO
            comp.ultima_unidade = destino.setor.unidade.name
            comp.ultima_baia = f"{destino.setor.nome} › {destino.nome}"
            comp.save(update_fields=["status", "ultima_unidade", "ultima_baia"])
            destino.computador = comp
            destino.pc_status = SOChoices.TEM_PC
        elif self.so_novo:
            # Sem computador vinculado: replica as specs (snapshot) no destino.
            destino.pc_status = SOChoices.TEM_PC
            destino.sistema_operacional = self.so_novo
            destino.processador = self.processador_novo
            destino.placa_mae = self.placa_mae_novo
            destino.memoria_ram = self.ram_novo
            destino.armazenamento = self.armazenamento_novo

        # 3) Colaborador de destino (opcional).
        if self.colaborador_destino:
            from apps.orgs.models import Person
            pessoa, _ = Person.objects.get_or_create(
                full_name=self.colaborador_destino.strip()
            )
            destino.colaborador = pessoa
        destino.save()  # dispara signals (departamento da pessoa segue o setor)

    def abrir_tarefa_transferencia_bitrix(self):
        """
        Abre a tarefa de transferência entre lojas no Bitrix24 e devolve o ID.

        FUTURO (integração Bitrix24): quando a transferência entre lojas é
        autorizada, este método cria uma tarefa no Bitrix com o modelo de
        "transferência entre lojas" (origem, destino, máquina, colaboradores) e
        guarda o ID em `bitrix_task_id`. Enquanto a API não está conectada, é um
        no-op (retorna "").
        """
        # TODO(Bitrix): criar a tarefa de transferência via API e gravar o ID.
        return ""


class Reparo(models.Model):
    """
    Reparo / manutenção registrado para uma baia (histórico da infra por máquina).
    Reparos do tipo 'reparo' que afetam o desempenho penalizam o índice da baia.
    Trocas de periférico (ex.: headset) NÃO entram no cálculo do desempenho.
    """

    class Tipo(models.TextChoices):
        REPARO = "reparo", "Reparo"
        UPGRADE = "upgrade", "Upgrade / melhoria"
        PREVENTIVA = "preventiva", "Manutenção preventiva"
        PERIFERICO = "periferico", "Troca de periférico"
        DESATIVACAO = "desativacao", "Desativação para troca"
        OUTRO = "outro", "Outro"

    class Peca(models.TextChoices):
        """Peça a trocar — espelha os atributos/componentes de uma Baia."""
        NENHUMA = "nenhuma", "Nenhuma (sem troca de peça)"
        PROCESSADOR = "processador", "Processador"
        PLACA_MAE = "placa_mae", "Placa-mãe"
        MEMORIA_RAM = "memoria_ram", "Memória RAM"
        ARMAZENAMENTO = "armazenamento", "Armazenamento (HD / SSD)"
        FONTE = "fonte", "Fonte"
        MOUSE = "mouse", "Mouse"
        TECLADO = "teclado", "Teclado"
        WEBCAM = "webcam", "Webcam"
        HEADSET = "headset", "Headset"
        MONITOR = "monitor", "Monitor"
        LEITOR = "leitor_cod_barras", "Leitor de código de barras"
        MAQUINA = "maquina", "Máquina inteira (troca)"
        OUTRO = "outro", "Outra peça"

    # O chamado é de uma MÁQUINA: ou uma baia (computador/notebook de mesa) OU um
    # notebook solto (sem baia). Exatamente um dos dois é preenchido (ver clean()).
    baia = models.ForeignKey(
        Baia,
        verbose_name="baia",
        on_delete=models.CASCADE,
        related_name="reparos",
        null=True, blank=True,
        help_text="Mesa (baia) que recebeu o reparo — quando a máquina está numa mesa.",
    )
    notebook = models.ForeignKey(
        "Notebook",
        verbose_name="notebook",
        on_delete=models.CASCADE,
        related_name="reparos",
        null=True, blank=True,
        help_text="Notebook (sem mesa) que recebeu o reparo — alternativa à baia.",
    )
    tipo = models.CharField(
        "tipo", max_length=12, choices=Tipo.choices, default=Tipo.REPARO,
        help_text="Só o tipo 'Reparo' penaliza o desempenho. "
                  "'Troca de periférico' (ex.: headset) não conta.",
    )
    titulo = models.CharField(
        "título", max_length=160,
        help_text="Resumo. Ex.: 'Troca de fonte', 'Formatação', 'Troca de SSD'.",
    )
    descricao = models.TextField("descrição", blank=True)
    data = models.DateField(
        "data", default=timezone.localdate,
        help_text="Data do reparo. Usada na janela de 6 meses do desempenho.",
    )
    previsao_conclusao = models.DateField(
        "previsão de conclusão", null=True, blank=True,
        help_text="Data prevista para a máquina ficar pronta. Enquanto não chega, "
                  "a estação aparece em manutenção no mapa (faixas + relógio).",
    )
    concluido_em = models.DateField(
        "concluído em", null=True, blank=True,
        help_text="Preenchido ao finalizar o reparo (encerra a manutenção).",
    )
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="técnico responsável",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reparos_baia",
        help_text="Técnico responsável pelo reparo/troca. Lista apenas usuários "
                  "dos grupos Estagiário e Técnico de Pós Venda.",
    )
    baia_realocacao = models.ForeignKey(
        Baia, verbose_name="mesa temporária do colaborador", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reparos_realocados",
        help_text="Mesa livre (com PC) para onde o colaborador foi movido durante o "
                  "reparo. Ao finalizar, ele volta para a mesa original.",
    )
    custo = models.DecimalField(
        "custo (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
    )
    afeta_desempenho = models.BooleanField(
        "afeta o desempenho?", default=True,
        help_text="Desmarque para trocas que não impactam o PC, como troca de "
                  "headset. (Trocas de periférico já são ignoradas no cálculo.)",
    )

    # --- Peça / cotação / Bitrix ---
    peca = models.CharField(
        "peça a trocar", max_length=20, choices=Peca.choices, blank=True,
        help_text="Qual peça/componente da máquina precisa ser trocado.",
    )
    peca_outro = models.CharField(
        "qual peça (outra)", max_length=120, blank=True,
        help_text="Descreva a peça quando 'Peça a trocar' for 'Outra peça'. "
                  "Habilitado apenas nessa opção.",
    )
    pecas = models.CharField(
        "peças a trocar", max_length=255, blank=True,
        help_text="Uma ou mais peças/componentes a trocar (chaves separadas por "
                  "vírgula). Permite trocar mais de uma peça no mesmo chamado.",
    )
    nova_especificacao = models.CharField(
        "nova especificação (upgrade)", max_length=120, blank=True,
        help_text="Em um UPGRADE de Processador / Memória RAM / Armazenamento, "
                  "informe a nova spec (ex.: 'SSD NVMe 480GB'). Ao salvar, a máquina "
                  "é atualizada e o score recalcula automaticamente.",
    )
    preventiva_checklist = models.CharField(
        "checklist da preventiva", max_length=255, blank=True,
        help_text="Itens verificados na manutenção preventiva (chaves separadas por vírgula).",
    )
    pontos = models.PositiveSmallIntegerField(
        "pontos", default=0,
        help_text="Pontos ganhos por quem concluiu a preventiva (bônus se antecipada). "
                  "Base do ranking de usuários.",
    )
    realizar_cotacao = models.BooleanField(
        "precisa comprar a peça (realizar cotação)?", default=False,
        help_text="Marque se a peça precisa ser comprada. Ao salvar, é aberto um "
                  "orçamento pendente de aprovação na seção Orçamentos.",
    )
    bitrix_task_id = models.CharField(
        "ID da tarefa (Bitrix)", max_length=40, blank=True,
        help_text="ID da tarefa no Bitrix24 desta cotação. Informe um ID já "
                  "existente para vincular, OU deixe vazio: ao marcar a cotação o "
                  "sistema abre a(s) tarefa(s) no Bitrix e puxa o ID automaticamente.",
    )
    orcamento = models.ForeignKey(
        "orcamentos.Orcamento",
        verbose_name="orçamento gerado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reparos",
        help_text="Orçamento aberto a partir desta cotação (preenchido "
                  "automaticamente).",
    )

    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "reparo / manutenção"
        verbose_name_plural = "reparos / manutenções"
        ordering = ["-data", "-created_at"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.titulo}"

    @property
    def equipamento(self):
        """A máquina do chamado: o dispositivo da baia OU o notebook solto."""
        if self.baia_id:
            return self.baia.dispositivo
        return self.notebook

    @property
    def alvo(self):
        """Rótulo do alvo do chamado (baia ou notebook) para títulos/telas."""
        if self.baia_id:
            return self.baia
        return self.notebook

    # --- Rótulos unificados para os cards (Kanban) — funcionam p/ baia e notebook ---
    @property
    def maquina_eh_notebook(self):
        return self.baia.eh_notebook if self.baia_id else True

    @property
    def maquina_titulo(self):
        if self.baia_id:
            return self.baia.colaborador.full_name if self.baia.colaborador_id else self.baia.nome
        nb = self.notebook
        if not nb:
            return "—"
        nome = (nb.colaborador.full_name if nb.colaborador_id else nb.usuario) or ""
        return nome or " ".join(p for p in [nb.marca, nb.modelo] if p) or "Notebook"

    @property
    def maquina_patrimonio(self):
        if self.baia_id:
            return self.baia.computador.patrimonio if self.baia.computador_id else ""
        return self.notebook.patrimonio if self.notebook_id else ""

    @property
    def maquina_local(self):
        if self.baia_id:
            return f"{self.baia.setor.unidade.name} › {self.baia.setor.nome}"
        return (self.notebook.unidade_setor if self.notebook_id else "") or "Notebook (sem mesa)"

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.baia_id) == bool(self.notebook_id):
            raise ValidationError(
                "Informe exatamente um alvo do chamado: uma baia OU um notebook."
            )

    def abrir_tarefas_bitrix(self):
        """
        Abre as tarefas da cotação no Bitrix24 e devolve o ID gerado.

        FUTURO (integração Bitrix24): quando 'realizar_cotacao' está marcado e o
        'bitrix_task_id' está vazio, este método chama a API do Bitrix para abrir
        **2 tarefas**:
          1. **Cotação / compra** — corresponde ao Orçamento (Orçamentos →
             Pendentes de aprovação). O ID dela é o que liga o `Orcamento`.
          2. **Manutenção** — corresponde a ESTE Reparo (fica em Reparos /
             Manutenção), atribuída ao `tecnico` responsável pela troca/reparo.

        Retorna o ID da tarefa de **cotação/compra** (gravado em `bitrix_task_id`,
        usado para vincular o `Orcamento`). O ID da tarefa de manutenção poderá ser
        guardado em campo próprio quando a API for conectada.

        Enquanto a API não está configurada, é um no-op (retorna ""): o orçamento é
        aberto sem ID e o ID pode ser preenchido depois pelo sync.
        """
        # TODO(Bitrix): criar as 2 tarefas (cotação/compra + manutenção do técnico)
        # via API e retornar o task_id da cotação/compra.
        return ""

    def fechar_tarefa_bitrix(self):
        """
        Fecha (conclui) a tarefa de manutenção deste reparo no Bitrix24.

        FUTURO: ao finalizar o reparo, chama a API do Bitrix para marcar a tarefa
        (`bitrix_task_id`) como concluída. Sem API configurada → no-op.
        """
        # TODO(Bitrix): fechar a tarefa via API usando self.bitrix_task_id.
        return None

    @transaction.atomic
    def finalizar(self):
        """Encerra a manutenção: marca a conclusão e fecha a tarefa no Bitrix.
        Se o colaborador tinha sido realocado para uma mesa temporária, devolve-o
        para a mesa original agora que a máquina voltou.

        TRANSACIONAL: são até 4 escritas (o reparo, a baia original, a temporária
        e o reparo de novo). Importa especialmente na finalização em LOTE pelo
        mapa, que chama isto num laço — sem `atomic`, uma falha no meio deixava
        parte dos chamados fechada e colaboradores em mesa temporária."""
        if self.concluido_em:
            return
        self.concluido_em = timezone.localdate()
        self.save(update_fields=["concluido_em"])
        transaction.on_commit(self.fechar_tarefa_bitrix)  # HTTP fora da transação
        self._devolver_colaborador()

    @transaction.atomic
    def _devolver_colaborador(self):
        """Volta o colaborador da mesa temporária (baia_realocacao) para a original."""
        temp = self.baia_realocacao
        if not (temp and temp.colaborador_id and self.baia_id):
            return
        pessoa = temp.colaborador
        orig = self.baia
        orig.colaborador = pessoa
        orig.nome = f"{orig.numero} - {pessoa.full_name}" if orig.numero else pessoa.full_name
        orig.save(update_fields=["colaborador", "nome"])
        temp.colaborador = None
        temp.nome = str(temp.numero) if temp.numero else ""
        temp.save(update_fields=["colaborador", "nome"])
        self.baia_realocacao = None
        self.save(update_fields=["baia_realocacao"])

    @property
    def pecas_lista(self):
        """Rótulos das peças do chamado (usa `pecas`; cai no `peca` legado)."""
        rotulos = dict(self.Peca.choices)
        chaves = [k for k in (self.pecas or "").split(",") if k and k != self.Peca.NENHUMA]
        if not chaves and self.peca and self.peca != self.Peca.NENHUMA:
            chaves = [self.peca]
        itens = []
        for k in chaves:
            if k == self.Peca.OUTRO:
                itens.append(self.peca_outro or rotulos.get(k, "Outra peça"))
            else:
                itens.append(rotulos.get(k, k))
        return itens

    @property
    def pecas_display(self):
        return ", ".join(self.pecas_lista)

    @property
    def pecas_keys(self):
        """Chaves das peças selecionadas (para marcar os chips no formulário)."""
        chaves = [k for k in (self.pecas or "").split(",") if k]
        if not chaves and self.peca:
            chaves = [self.peca]
        return chaves

    def garantir_orcamento(self, user=None):
        """
        Quando 'realizar_cotacao' está marcado, garante um Orçamento pendente
        ligado a este reparo. Se o 'bitrix_task_id' estiver vazio, tenta abrir a(s)
        tarefa(s) no Bitrix e puxar o ID automaticamente; se já houver um ID,
        vincula à tarefa existente (sem duplicar).
        """
        if not self.realizar_cotacao or self.orcamento_id:
            return
        from apps.orcamentos.models import Orcamento

        # Sem ID informado → o sistema abre a(s) tarefa(s) no Bitrix e puxa o ID.
        if not self.bitrix_task_id:
            task_id = self.abrir_tarefas_bitrix()
            if task_id:
                self.bitrix_task_id = task_id
                self.save(update_fields=["bitrix_task_id"])

        peca_txt = self.pecas_display or "peça"
        titulo = f"Cotação: {peca_txt} — {self.alvo}"[:200]
        solicitante = ""
        if user is not None:
            solicitante = user.get_full_name() or user.get_username()
        defaults = {
            "titulo": titulo,
            "descricao": self.descricao or self.titulo,
            "solicitante": solicitante,
            "status": Orcamento.Status.PENDENTE,
            "data_solicitacao": self.data,
        }
        if self.bitrix_task_id:
            orc, _ = Orcamento.objects.get_or_create(
                bitrix_task_id=self.bitrix_task_id, defaults=defaults
            )
        else:
            orc = Orcamento.objects.create(**defaults)
        self.orcamento = orc
        self.save(update_fields=["orcamento"])

    def aplicar_desativacao(self):
        """
        Para reparos do tipo 'Desativação para troca': se a baia tem um computador
        vinculado, marca-o como **Desativado** (vai para o Estoque de Desativados) e
        o tira da baia, deixando a posição livre (Sem PC) para a máquina nova.
        """
        if self.tipo != self.Tipo.DESATIVACAO or not self.baia_id:
            return
        baia = self.baia
        if not baia.computador_id:
            return
        # Guarda de onde o computador saiu, para o estoque de desativados.
        Computador.objects.filter(pk=baia.computador_id).update(
            status=Computador.Status.DESATIVADO,
            ultima_unidade=baia.setor.unidade.name,
            ultima_baia=f"{baia.setor.nome} › {baia.nome}",
        )
        baia.computador = None
        baia.pc_status = SOChoices.SEM_PC
        # Limpa specs legadas da baia (senão a mesa vazia mostraria specs-zumbi da máquina antiga).
        baia.sistema_operacional = ""
        baia.processador = ""
        baia.placa_mae = ""
        baia.memoria_ram = ""
        baia.armazenamento = ""
        baia.save(update_fields=["computador", "pc_status", "sistema_operacional",
                                 "processador", "placa_mae", "memoria_ram", "armazenamento"])


# Papéis que podem AUTORIZAR/realizar movimentações de baia diretamente.
GRUPOS_MOVIMENTACAO = ["Técnico de Pós Venda", "Supervisor", "Gerente"]


def pode_mover_baia(user):
    """True se o usuário pode mover baia direto / autorizar solicitações."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.groups.filter(name__in=GRUPOS_MOVIMENTACAO).exists())
    )


class RegistroReparo(models.Model):
    """Registro/relatório do que foi feito num chamado (log com carimbo de data e autor).

    Cada entrada é uma anotação da manutenção em andamento — permite acompanhar o
    histórico do atendimento sem depender do admin.
    """
    reparo = models.ForeignKey(
        Reparo, verbose_name="chamado", on_delete=models.CASCADE, related_name="registros",
    )
    texto = models.TextField("registro")
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="autor", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="registros_reparo",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "registro do chamado"
        verbose_name_plural = "registros do chamado"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Registro de {self.criado_em:%d/%m/%Y %H:%M}"


class MovimentacaoBaia(models.Model):
    """
    Movimentação/relocação de uma BAIA entre setores (mesma unidade), levando o
    PC e o ocupante junto. Serve como SOLICITAÇÃO e REGISTRO: usuários autorizados
    (GRUPOS_MOVIMENTACAO) aplicam direto; os demais criam uma pendente que esses
    papéis decidem (autorizar/negar). É diferente de Transferencia (PC entre baias).
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente de autorização"
        AUTORIZADA = "autorizada", "Autorizada"
        NEGADA = "negada", "Negada"

    class Tipo(models.TextChoices):
        MOVER = "mover", "Mover baia (entre setores)"
        TROCAR = "trocar", "Trocar computadores (entre baias)"

    tipo = models.CharField(
        "tipo", max_length=10, choices=Tipo.choices, default=Tipo.MOVER, db_index=True,
    )
    baia = models.ForeignKey(
        Baia, verbose_name="baia", on_delete=models.CASCADE, related_name="movimentacoes",
    )
    baia_parceira = models.ForeignKey(
        Baia, verbose_name="baia parceira (troca)", on_delete=models.CASCADE,
        null=True, blank=True, related_name="movimentacoes_parceira",
        help_text="A outra baia, quando o tipo é troca de computadores.",
    )
    setor_origem = models.ForeignKey(
        Setor, verbose_name="setor de origem", on_delete=models.SET_NULL,
        null=True, related_name="movimentacoes_saida",
    )
    setor_destino = models.ForeignKey(
        Setor, verbose_name="setor de destino", on_delete=models.SET_NULL,
        null=True, related_name="movimentacoes_entrada",
    )
    info_pc = models.CharField("PC (snapshot)", max_length=200, blank=True)
    colaborador_nome = models.CharField("colaborador (snapshot)", max_length=160, blank=True)
    patrimonio = models.CharField("patrimônio (snapshot)", max_length=40, blank=True)
    # Snapshot da baia parceira (apenas para troca).
    info_pc_parceira = models.CharField("PC parceira (snapshot)", max_length=200, blank=True)
    colaborador_parceira = models.CharField("colaborador parceira (snapshot)", max_length=160, blank=True)
    patrimonio_parceira = models.CharField("patrimônio parceira (snapshot)", max_length=40, blank=True)
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
    )
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="solicitante", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movimentacoes_solicitadas",
    )
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="decidido por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movimentacoes_decididas",
    )
    observacao = models.TextField("observação", blank=True)
    motivo = models.CharField("motivo (negação)", max_length=200, blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    decidido_em = models.DateTimeField("decidido em", null=True, blank=True)

    class Meta:
        verbose_name = "movimentação interna"
        verbose_name_plural = "movimentações internas"
        ordering = ["-criado_em"]

    def __str__(self):
        if self.tipo == self.Tipo.TROCAR:
            return f"Troca: {self.baia} ↔ {self.baia_parceira}"
        return f"{self.baia} : {self.setor_origem} → {self.setor_destino}"

    def capturar_snapshot(self):
        """Guarda o estado do PC/ocupante no momento da movimentação (para o log)."""
        self.info_pc = (self.baia.resumo_pc or "")[:200]
        self.colaborador_nome = str(self.baia.colaborador) if self.baia.colaborador_id else ""
        self.patrimonio = self.baia.computador.patrimonio if self.baia.computador_id else ""
        if self.tipo == self.Tipo.TROCAR and self.baia_parceira_id:
            p = self.baia_parceira
            self.info_pc_parceira = (p.resumo_pc or "")[:200]
            self.colaborador_parceira = str(p.colaborador) if p.colaborador_id else ""
            self.patrimonio_parceira = p.computador.patrimonio if p.computador_id else ""

    @transaction.atomic
    def aplicar(self, user):
        """Aplica a movimentação (mover ou trocar) e marca como autorizada.

        TRANSACIONAL: move/troca a baia E marca a autorização — se a segunda
        parte falhasse, a baia já tinha se movido sem registro da decisão."""
        if self.tipo == self.Tipo.TROCAR:
            self._aplicar_troca()
        else:
            b = self.baia
            if self.setor_destino_id and b.setor_id != self.setor_destino_id:
                b.setor = self.setor_destino
                b.save()  # dispara signals (departamento da pessoa segue o setor)
        self.status = self.Status.AUTORIZADA
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.save()

    @transaction.atomic
    def _aplicar_troca(self):
        """Troca o computador (e specs) entre self.baia e self.baia_parceira.

        TRANSACIONAL — este era o PIOR caso do sistema: os dois computadores são
        desvinculados primeiro (para não bater no OneToOne) e só depois religados
        cruzados. Uma falha entre as duas metades deixava **as duas baias sem
        computador**, com as máquinas órfãs. Agora ou troca inteira, ou nada.
        """
        a, b = self.baia, self.baia_parceira
        if not b:
            return
        ca, cb = a.computador, b.computador
        # Desvincula os dois primeiro (evita conflito do OneToOne) e troca as specs.
        a.computador = None
        b.computador = None
        a.save(update_fields=["computador"])
        b.save(update_fields=["computador"])
        # A máquina leva junto os PERIFÉRICOS (monitor, teclado, etc.) — senão eles
        # ficam presos na baia de origem e o PC movido aparece "sem monitor".
        campos = ["pc_status", "sistema_operacional", "processador", "placa_mae",
                  "memoria_ram", "armazenamento",
                  "monitor", "teclado", "mouse", "headset", "webcam", "leitor_cod_barras"]
        va = {f: getattr(a, f) for f in campos}
        for f in campos:
            setattr(a, f, getattr(b, f))
            setattr(b, f, va[f])
        a.computador = cb
        b.computador = ca
        a.save()
        b.save()

    def negar(self, user, motivo=""):
        self.status = self.Status.NEGADA
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.motivo = (motivo or "")[:200]
        self.save()


class Notebook(models.Model):
    """
    Notebook (laptop) cadastrado a partir da planilha "Notebooks" do Bitrix.
    Equipamento MÓVEL, atribuído a um usuário — um campo para cada coluna da
    planilha (marca, modelo, usuário, credenciais de acesso, AnyDesk, specs).
    Diferente de Computador (estoque de desktops vinculados a baias).
    """

    class Status(models.TextChoices):
        ATIVO = "ativo", "Ativo"
        DEFEITO = "defeito", "Com defeito"
        OBSOLETO = "obsoleto", "Obsoleto / sem uso"

    # --- Identificação ---
    marca = models.CharField("marca", max_length=60, blank=True,
                             help_text="Ex.: ASUS, Dell, Acer, HP, Lenovo, Samsung.")
    modelo = models.CharField("modelo", max_length=120, blank=True,
                              help_text="Ex.: X515J, Inspiron 3501, Nitro 5.")
    serial = models.CharField("número de série", max_length=80, blank=True,
                              help_text="Número de série do equipamento.")
    mac = models.CharField(
        "MAC (identidade física)", max_length=12, blank=True, db_index=True,
        help_text="Endereço MAC (hex) que identifica este notebook de forma única. "
                  "Preenchido pela telemetria; a coleta casa por MAC de forma permanente.")
    patrimonio = models.CharField(
        "patrimônio / etiqueta", max_length=40, unique=True, null=True, blank=True,
        help_text="Código único do notebook (ex.: NB-0001). Gerado automaticamente; "
                  "usado na etiqueta e no escaneamento para abrir chamado.",
    )
    status = models.CharField("situação", max_length=10, choices=Status.choices,
                              default=Status.ATIVO, db_index=True)
    sankhya_id = models.CharField(
        "ID Sankhya", max_length=60, blank=True,
        help_text="ID deste notebook no Sankhya (usado futuramente para puxar as informações).",
    )
    valor_compra = models.DecimalField(
        "valor de compra (R$)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Valor pago na compra do equipamento.",
    )
    data_compra = models.DateField(
        "data da compra", null=True, blank=True,
        help_text="Data em que o equipamento foi comprado.",
    )

    # --- Uso ---
    usuario = models.CharField("usuário", max_length=120, blank=True,
                               help_text="Colaborador que usa o notebook (texto livre, como na planilha).")
    colaborador = models.ForeignKey(
        "orgs.Person", verbose_name="colaborador", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="notebooks",
        help_text="Colaborador a quem o notebook está alocado (vínculo confiável).",
    )
    unidade_setor = models.CharField("unidade / setor", max_length=120, blank=True,
                                     help_text="Unidade ou setor de lotação (texto livre).")

    # --- Acesso ---
    conta = models.CharField("conta", max_length=160, blank=True,
                             help_text="Conta/e-mail de acesso do equipamento.")
    # CIFRADAS no banco (auditoria 1.12): antes ficavam em texto claro, legíveis
    # por qualquer membro da equipe e presentes em todo backup. Continuam
    # legíveis na tela para quem tem permissão — é cifragem reversível, não
    # hash, porque a TI precisa USAR a senha para acessar a máquina.
    # Ver apps/parque/campos.py (chave em CAMPO_CRIPTO_KEY).
    senha = CampoTextoCifrado("senha", max_length=120, blank=True)
    anydesk = models.CharField("AnyDesk (ID)", max_length=60, blank=True)
    anydesk_senha = CampoTextoCifrado("senha AnyDesk", max_length=120, blank=True)

    # --- Configuração ---
    sistema_operacional = models.CharField("S.O", max_length=80, blank=True,
                                           help_text="Ex.: Windows 11.")
    processador = models.CharField("processador", max_length=120, blank=True)
    placa_mae = models.CharField("placa mãe", max_length=120, blank=True)
    memoria_ram = models.CharField("memória RAM", max_length=60, blank=True)
    armazenamento = models.CharField("armazenamento", max_length=120, blank=True)

    observacoes = models.TextField("observações", blank=True)

    # --- Telemetria REAL (coletada pelo agente) ---
    tel_cpu = models.CharField("CPU (telemetria)", max_length=120, blank=True)
    tel_ram = models.CharField("RAM (telemetria)", max_length=60, blank=True)
    tel_disco = models.CharField("disco (telemetria)", max_length=80, blank=True)
    tel_so = models.CharField("S.O (telemetria)", max_length=80, blank=True)
    tel_gpu = models.CharField("vídeo (telemetria)", max_length=80, blank=True)
    tel_uptime_seg = models.BigIntegerField("tempo ligada (telemetria)", null=True, blank=True)
    tel_local = models.CharField("localização (telemetria)", max_length=120, blank=True)
    tel_visto_em = models.DateTimeField("telemetria vista em", null=True, blank=True)

    # --- Origem (Bitrix) ---
    bitrix_task_id = models.CharField("ID da tarefa (Bitrix)", max_length=40, blank=True, db_index=True,
                                      help_text="ID da tarefa do Bitrix de onde o notebook foi importado.")
    titulo = models.CharField("título (Bitrix)", max_length=200, blank=True)
    criada_em_origem = models.DateField("criada em (origem)", null=True, blank=True)
    atualizada_em_origem = models.DateField("atualizada em (origem)", null=True, blank=True)

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "notebook"
        verbose_name_plural = "notebooks"
        ordering = ["marca", "modelo", "usuario"]
        constraints = [
            models.UniqueConstraint(
                fields=["bitrix_task_id"], name="unique_notebook_bitrix",
                condition=models.Q(bitrix_task_id__gt=""),
            )
        ]

    def save(self, *args, **kwargs):
        # Gera o patrimônio (NB-<NNNN>) automaticamente quando não vier um.
        if not (self.patrimonio or "").strip():
            self.patrimonio = proximo_patrimonio_notebook()
        super().save(*args, **kwargs)

    def __str__(self):
        partes = [p for p in [self.marca, self.modelo] if p]
        base = " ".join(partes) or "Notebook"
        return f"{base} — {self.usuario}" if self.usuario else base

    # Specs EFETIVAS: o CADASTRO manda; a telemetria preenche o que está vazio.
    # Mesma regra e mesmo motivo do `Computador` — a explicação longa está lá.
    @property
    def tem_telemetria(self):
        return self.tel_visto_em is not None

    @property
    def cpu_efetivo(self):
        return self.processador or self.tel_cpu

    @property
    def ram_efetivo(self):
        return self.memoria_ram or self.tel_ram

    @property
    def disco_efetivo(self):
        return self.armazenamento or self.tel_disco

    @property
    def so_efetivo(self):
        return self.sistema_operacional or self.tel_so

    @property
    def divergencias_telemetria(self):
        """Onde o cadastro digitado discorda do que o agente mediu.
        [(rótulo, valor_no_cadastro, valor_medido)] — ver `Computador`."""
        if not self.tel_visto_em:
            return []

        def _norm(v):
            return " ".join((v or "").split()).casefold()

        pares = [
            ("Processador", self.processador, self.tel_cpu),
            ("Memória", self.memoria_ram, self.tel_ram),
            ("Armazenamento", self.armazenamento, self.tel_disco),
            ("Sistema", self.sistema_operacional, self.tel_so),
        ]
        return [(rot, cad, med) for rot, cad, med in pares
                if cad and med and _norm(cad) != _norm(med)]

    @property
    def telemetria_status(self):
        """'ativo' (coleta recente) | 'inativo' (coletou mas faz tempo) | 'sem'."""
        if not self.tel_visto_em:
            return "sem"
        if self.tel_visto_em >= timezone.now() - timedelta(hours=TELEMETRIA_ATIVA_HORAS):
            return "ativo"
        return "inativo"

    @property
    def tel_uptime_humano(self):
        return humanizar_uptime(self.tel_uptime_seg)

    @property
    def resumo_specs(self):
        partes = [self.cpu_efetivo, self.ram_efetivo, self.disco_efetivo]
        return " · ".join(p for p in partes if p) or "—"

    @property
    def indice_desempenho(self):
        """Nota 0–100 do notebook (mesma fórmula da baia, sem penalidade de reparos).
        Usa as specs EFETIVAS (telemetria real quando houver)."""
        if not (self.cpu_efetivo or self.ram_efetivo or self.disco_efetivo):
            return None  # sem specs cadastradas nem telemetria
        cpu = _score_cpu(self.cpu_efetivo)
        ram = _score_ram(self.ram_efetivo)
        disco = _score_disco(self.disco_efetivo)
        saude = 0 if self.status == self.Status.DEFEITO else 100
        return max(0, round(0.45 * cpu + 0.25 * ram + 0.25 * disco + 0.05 * saude))

    @property
    def classe_desempenho(self):
        return _classe_desempenho(self.indice_desempenho)

    @property
    def diagnostico(self):
        return diagnostico_desempenho(
            self.cpu_efetivo, self.ram_efetivo, self.disco_efetivo,
            self.status == self.Status.DEFEITO, 0,
        )

    @property
    def diagnostico_json(self):
        return json.dumps(self.diagnostico, ensure_ascii=False)

    # --- Manutenção PREVENTIVA (mesmo ciclo da baia; notebook não tem "em serviço
    # desde" próprio, então usamos a data de origem/cadastro como marco inicial) ---
    preventiva_adiada_ate = models.DateField(
        "preventiva adiada até", null=True, blank=True,
        help_text="Novo prazo aprovado de adiamento da preventiva. Empurra o "
                  "vencimento; é limpo quando a preventiva é concluída.",
    )

    @property
    def ultima_preventiva(self):
        """Data da última preventiva CONCLUÍDA (tarefa pendente não zera o ciclo)."""
        datas = [
            r.concluido_em for r in self.reparos.all()
            if r.tipo == Reparo.Tipo.PREVENTIVA and r.concluido_em
        ]
        return max(datas) if datas else None

    @property
    def tem_tarefa_preventiva_aberta(self):
        return any(
            r.tipo == Reparo.Tipo.PREVENTIVA and r.concluido_em is None
            for r in self.reparos.all()
        )

    @property
    def _preventiva_referencia(self):
        marco = self.ultima_preventiva or self.criada_em_origem
        if marco:
            return marco
        return self.criado_em.date() if self.criado_em else timezone.localdate()

    @property
    def preventiva_vencimento(self):
        base = self._preventiva_referencia + timedelta(days=PREVENTIVA_DIAS)
        if self.preventiva_adiada_ate and self.preventiva_adiada_ate > base:
            return self.preventiva_adiada_ate
        return base

    @property
    def preventiva_dias_restantes(self):
        return (self.preventiva_vencimento - timezone.localdate()).days

    @property
    def dias_sem_preventiva(self):
        return max(0, (timezone.localdate() - self._preventiva_referencia).days)

    @property
    def preventiva_status(self):
        """'em_dia' | 'proxima' | 'vencida' | 'pendente' (notebook sempre precisa)."""
        d = self.preventiva_dias_restantes
        if d < 0:
            return "vencida" if self.ultima_preventiva else "pendente"
        if d <= PREVENTIVA_ALERTA_DIAS:
            return "proxima"
        return "em_dia"


def proximo_patrimonio_notebook():
    """Próximo patrimônio de notebook (NB-<NNNN>), em sequência própria e global."""
    maior = 0
    for p in Notebook.objects.exclude(patrimonio__isnull=True).values_list("patrimonio", flat=True):
        m = re.search(r"(\d+)$", p or "")
        if m:
            maior = max(maior, int(m.group(1)))
    return f"NB-{maior + 1:04d}"


class TransferenciaNotebook(models.Model):
    """
    Transferência de um NOTEBOOK (equipamento móvel) entre lojas.

    Espelha a transferência entre lojas dos computadores, mas para notebooks:
    como o notebook não fica numa baia/setor (só tem `unidade_setor` em texto
    livre), o destino é apenas a LOJA (orgs.Location). Aplicar a transferência
    atualiza o `unidade_setor` do notebook e gera o comprovante (protocolo).
    Guarda um snapshot dos dados para o protocolo continuar válido depois.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente de autorização"
        AUTORIZADA = "autorizada", "Autorizada"
        NEGADA = "negada", "Negada"

    notebook = models.ForeignKey(
        Notebook, verbose_name="notebook", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transferencias",
        help_text="Notebook que está sendo transferido.",
    )
    # --- Origem (snapshot) ---
    unidade_origem = models.CharField(
        "unidade de origem", max_length=120, blank=True,
        help_text="Unidade/setor de onde o notebook saiu (texto, como no cadastro).",
    )
    usuario = models.CharField(
        "usuário", max_length=120, blank=True,
        help_text="Colaborador que usava o notebook na origem.",
    )
    # --- Snapshot do equipamento (p/ o protocolo) ---
    marca = models.CharField("marca", max_length=60, blank=True)
    modelo = models.CharField("modelo", max_length=120, blank=True)
    serial = models.CharField("número de série", max_length=80, blank=True)
    specs = models.CharField("configuração", max_length=200, blank=True)

    # --- Destino ---
    unidade_destino = models.ForeignKey(
        "orgs.Location", verbose_name="loja de destino", on_delete=models.PROTECT,
        related_name="notebooks_recebidos",
        help_text="Loja que vai receber o notebook.",
    )
    usuario_destino = models.CharField(
        "usuário (destino)", max_length=120, blank=True,
        help_text="Colaborador que vai receber o notebook no destino (opcional).",
    )

    data = models.DateField("data", null=True, blank=True)
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices,
        default=Status.AUTORIZADA, db_index=True,
        help_text="Transferências criadas por quem não pode autorizar ficam pendentes.",
    )
    bitrix_task_id = models.CharField(
        "ID da tarefa (Bitrix)", max_length=40, blank=True,
        help_text="ID da tarefa de transferência de notebook no Bitrix24.",
    )

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="registrado por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transf_notebooks_registradas",
    )
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="decidido por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="transf_notebooks_decididas",
    )
    decidido_em = models.DateTimeField("decidido em", null=True, blank=True)
    observacao = models.TextField("observação", blank=True)
    motivo = models.CharField("motivo (negação)", max_length=200, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "transferência de notebook"
        verbose_name_plural = "transferências de notebooks"
        ordering = ["-data", "-created_at"]

    def __str__(self):
        nb = self.marca or (str(self.notebook) if self.notebook_id else "Notebook")
        return f"{nb} → {self.unidade_destino}"

    @transaction.atomic
    def aplicar(self):
        """Aplica a transferência: muda a unidade/setor do notebook para a loja de destino."""
        nb = self.notebook
        if nb is None:
            return
        nb.unidade_setor = self.unidade_destino.name
        if self.usuario_destino:
            nb.usuario = self.usuario_destino
        nb.save(update_fields=["unidade_setor", "usuario", "atualizado_em"])

    def autorizar(self, user):
        self.status = self.Status.AUTORIZADA
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.save()
        self.aplicar()
        self.abrir_tarefa_transferencia_bitrix()

    def negar(self, user, motivo=""):
        self.status = self.Status.NEGADA
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.motivo = (motivo or "")[:200]
        self.save()

    def abrir_tarefa_transferencia_bitrix(self):
        """Stub da integração Bitrix24 (no-op enquanto a API não está conectada)."""
        # TODO(Bitrix): criar a tarefa de transferência de notebook e gravar o ID.
        return ""


class Peca(models.Model):
    """
    Estoque de PEÇAS / componentes por QUANTIDADE, por unidade.
    Ex.: "8GB DDR4" (Memória) — 12 unidades em Bonsucesso. Serve para gerir
    quantos componentes/periféricos de reposição cada loja tem.
    """

    class Tipo(models.TextChoices):
        MEMORIA_RAM = "memoria_ram", "Memória RAM"
        ARMAZENAMENTO = "armazenamento", "Armazenamento (HD / SSD)"
        PROCESSADOR = "processador", "Processador"
        PLACA_MAE = "placa_mae", "Placa-mãe"
        FONTE = "fonte", "Fonte"
        MOUSE = "mouse", "Mouse"
        TECLADO = "teclado", "Teclado"
        WEBCAM = "webcam", "Webcam"
        HEADSET = "headset", "Headset"
        MONITOR = "monitor", "Monitor"
        LEITOR = "leitor_cod_barras", "Leitor de código de barras"
        CABO = "cabo", "Cabo / adaptador"
        OUTRO = "outro", "Outro"

    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices, db_index=True)
    descricao = models.CharField(
        "descrição / especificação", max_length=120,
        help_text="Ex.: 8GB DDR4, SSD 240GB, Mouse USB, Headset USB.",
    )
    unidade = models.ForeignKey(
        "orgs.Location", verbose_name="unidade", on_delete=models.PROTECT,
        related_name="pecas", help_text="Loja onde a peça está em estoque.",
    )
    quantidade = models.PositiveIntegerField("quantidade", default=0)
    notes = models.TextField("observações", blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "peça (estoque)"
        verbose_name_plural = "peças em estoque"
        ordering = ["tipo", "descricao", "unidade__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["unidade", "tipo", "descricao"], name="unique_peca_por_unidade"
            )
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.descricao} ({self.unidade})"

    @property
    def em_falta(self):
        # Sem estoque = em falta.
        return self.quantidade <= 0


class Remessa(models.Model):
    """Caixa de envio: agrupa vários itens (peças) numa única transferência/protocolo."""

    unidade_origem = models.ForeignKey(
        "orgs.Location", verbose_name="origem", on_delete=models.SET_NULL,
        null=True, related_name="remessas_saida",
    )
    unidade_destino = models.ForeignKey(
        "orgs.Location", verbose_name="destino", on_delete=models.SET_NULL,
        null=True, related_name="remessas_entrada",
    )
    colaborador_destino = models.ForeignKey(
        "orgs.Person", verbose_name="recebido por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="remessas_recebidas",
    )
    data_chegada = models.DateField("data de chegada", null=True, blank=True)
    por_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="remessas",
    )
    em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "remessa (caixa)"
        verbose_name_plural = "remessas (caixas)"
        ordering = ["-em"]

    def __str__(self):
        return f"Caixa #{self.pk}: {self.unidade_origem} → {self.unidade_destino}"


class MovimentacaoPeca(models.Model):
    """Registro de transferência de uma quantidade de peças entre unidades."""

    remessa = models.ForeignKey(
        Remessa, verbose_name="remessa (caixa)", on_delete=models.CASCADE,
        null=True, blank=True, related_name="itens",
        help_text="Caixa de envio à qual este item pertence (quando enviado em lote).",
    )
    tipo = models.CharField("tipo", max_length=20, choices=Peca.Tipo.choices)
    descricao = models.CharField("descrição", max_length=120)
    unidade_origem = models.ForeignKey(
        "orgs.Location", verbose_name="origem", on_delete=models.SET_NULL,
        null=True, related_name="pecas_saida",
    )
    unidade_destino = models.ForeignKey(
        "orgs.Location", verbose_name="destino", on_delete=models.SET_NULL,
        null=True, related_name="pecas_entrada",
    )
    quantidade = models.PositiveIntegerField("quantidade")
    colaborador_destino = models.ForeignKey(
        "orgs.Person", verbose_name="recebido por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="pecas_recebidas",
        help_text="Colaborador que vai receber a peça no destino.",
    )
    data_chegada = models.DateField(
        "data de chegada", null=True, blank=True,
        help_text="Data prevista de chegada no destino.",
    )
    por_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movimentacoes_peca",
    )
    bitrix_task_id = models.CharField(
        "ID da tarefa (Bitrix)", max_length=40, blank=True, db_index=True,
        help_text="ID da tarefa de transferência de peça no Bitrix24.",
    )
    em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "movimentação de peça"
        verbose_name_plural = "movimentações de peças"
        ordering = ["-em"]

    def __str__(self):
        return f"{self.quantidade}× {self.descricao}: {self.unidade_origem} → {self.unidade_destino}"


class TermoResponsabilidade(models.Model):
    """
    Termo de responsabilidade que um colaborador assina ao receber um NOTEBOOK.

    O RH gera o documento (impresso), colhe a assinatura do colaborador e sobe o
    arquivo assinado de volta ao sistema. Os campos `colaborador_nome` e
    `equipamento_desc` são um SNAPSHOT do momento da emissão — o termo continua
    íntegro mesmo que o notebook seja re-alocado ou o colaborador mude depois.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Aguardando assinatura"
        ASSINADO = "assinado", "Assinado"

    class Tipo(models.TextChoices):
        ENTREGA = "entrega", "Entrega"
        DEVOLUCAO = "devolucao", "Devolução"

    # ENTREGA e DEVOLUÇÃO são o mesmo documento em sentidos opostos: um diz que
    # o colaborador RECEBEU, o outro que ENTREGOU de volta. Sem os dois, a
    # retirada de um notebook não deixa rastro assinado — era o buraco que o RH
    # tapava com papel na gaveta.
    tipo = models.CharField(
        "tipo", max_length=10, choices=Tipo.choices, default=Tipo.ENTREGA,
        db_index=True,
    )

    notebook = models.ForeignKey(
        Notebook, verbose_name="notebook", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="termos",
    )
    colaborador = models.ForeignKey(
        "orgs.Person", verbose_name="colaborador", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="termos_responsabilidade",
    )
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
    )

    # Snapshot no momento da emissão (documento imutável).
    colaborador_nome = models.CharField("colaborador (nome)", max_length=160, blank=True)
    equipamento_desc = models.CharField("equipamento", max_length=240, blank=True)

    arquivo_assinado = models.FileField(
        "documento assinado", upload_to="termos/", null=True, blank=True,
        help_text="PDF ou foto do termo assinado pelo colaborador.",
    )

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="gerado por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="termos_gerados",
    )
    criado_em = models.DateTimeField("gerado em", auto_now_add=True)
    assinado_em = models.DateTimeField("assinado em", null=True, blank=True)

    class Meta:
        verbose_name = "termo de responsabilidade"
        verbose_name_plural = "termos de responsabilidade"
        ordering = ["-criado_em"]

    def __str__(self):
        nome = self.colaborador_nome or (
            self.colaborador.full_name if self.colaborador_id else "—"
        )
        return f"Termo de {self.get_tipo_display().lower()} #{self.pk} — {nome}"

    def marcar_assinado(self):
        """Marca o termo como assinado agora (idempotente)."""
        self.status = self.Status.ASSINADO
        if not self.assinado_em:
            self.assinado_em = timezone.now()
        self.save(update_fields=["status", "assinado_em"])


class DocumentoEquipamento(models.Model):
    """
    Documento anexado a um equipamento — computador OU notebook (nota fiscal,
    laudo, termo, foto, etc.). Cada máquina pode ter VÁRIOS. Formatos aceitos:
    PDF, PNG, JPEG e DOCX. Um documento pertence a um único equipamento (o
    vínculo é preenchido automaticamente pelo inline do admin).
    """

    FORMATOS = ["pdf", "png", "jpg", "jpeg", "docx"]

    class Tipo(models.TextChoices):
        NOTA_COMPRA = "nota_compra", "Nota fiscal de compra"
        NOTA_SERVICO = "nota_servico", "Nota fiscal de serviço"
        TERMO = "termo", "Termo assinado"
        LAUDO = "laudo", "Laudo técnico"
        PROTOCOLO = "protocolo", "Protocolo / ordem de serviço"
        ORCAMENTO = "orcamento", "Orçamento aprovado"
        OUTRO = "outro", "Outro"

    # O TIPO é o que permite cobrar o que falta. Sem ele o arquivo só sabe
    # dizer "tem 3 anexos"; com ele sabe dizer "falta a nota fiscal" — que é a
    # pergunta que o RH e o contador realmente fazem.
    tipo = models.CharField(
        "tipo", max_length=14, choices=Tipo.choices, default=Tipo.OUTRO,
        db_index=True,
    )

    computador = models.ForeignKey(
        "Computador", verbose_name="computador", on_delete=models.CASCADE,
        null=True, blank=True, related_name="documentos",
    )
    notebook = models.ForeignKey(
        "Notebook", verbose_name="notebook", on_delete=models.CASCADE,
        null=True, blank=True, related_name="documentos",
    )

    # ALGUNS DOCUMENTOS NÃO SÃO DE UMA MÁQUINA, SÃO DE UM EVENTO. O protocolo de
    # uma transferência entre lojas pertence à transferência (que envolve duas
    # lojas); o laudo e a nota de serviço pertencem ao envio à autorizada. Por
    # isso o vínculo é opcional em quatro direções — e o arquivo mostra o mesmo
    # papel na pasta do equipamento E na pasta do evento.
    transferencia = models.ForeignKey(
        "Transferencia", verbose_name="transferência de loja", on_delete=models.CASCADE,
        null=True, blank=True, related_name="documentos",
    )
    transferencia_notebook = models.ForeignKey(
        "TransferenciaNotebook", verbose_name="transferência de notebook",
        on_delete=models.CASCADE, null=True, blank=True, related_name="documentos",
    )
    envio = models.ForeignKey(
        "EnvioAutorizada", verbose_name="envio à autorizada", on_delete=models.CASCADE,
        null=True, blank=True, related_name="documentos",
    )
    arquivo = models.FileField(
        "arquivo", upload_to="documentos_equipamento/",
        validators=[FileExtensionValidator(FORMATOS)],
        help_text="Formatos aceitos: PDF, PNG, JPEG, DOCX.",
    )
    descricao = models.CharField("descrição", max_length=160, blank=True,
                                 help_text="Ex.: Nota fiscal, laudo, foto do equipamento.")
    enviado_em = models.DateTimeField("enviado em", auto_now_add=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="anexado por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="documentos_enviados",
    )

    # VALIDAR é ato de gente, não do sistema: alguém do RH abriu o arquivo,
    # conferiu se é o papel certo, assinado, legível — e assumiu isso.
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="validado por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="documentos_validados",
    )
    validado_em = models.DateTimeField("validado em", null=True, blank=True)

    class Meta:
        verbose_name = "documento do equipamento"
        verbose_name_plural = "documentos do equipamento"
        ordering = ["-enviado_em"]

    def __str__(self):
        if self.descricao:
            return self.descricao
        if self.tipo != self.Tipo.OUTRO:
            return self.get_tipo_display()
        return self.arquivo.name.rsplit("/", 1)[-1] if self.arquivo else "documento"

    @property
    def nome_arquivo(self):
        return self.arquivo.name.rsplit("/", 1)[-1] if self.arquivo else ""

    def marcar_validado(self, usuario):
        """Registra quem conferiu o documento (idempotente)."""
        from django.utils import timezone as _tz
        self.validado_por = usuario
        self.validado_em = self.validado_em or _tz.now()
        self.save(update_fields=["validado_por", "validado_em"])


class Autorizada(models.Model):
    """Autorizada / assistência técnica externa para onde equipamentos são enviados
    para reparo. Cadastro mantido pela equipe (Parque → Assistência externa)."""

    nome = models.CharField("nome", max_length=160)
    cnpj = models.CharField("CNPJ", max_length=20, blank=True)
    contato = models.CharField("contato (pessoa)", max_length=120, blank=True)
    telefone = models.CharField("telefone", max_length=40, blank=True)
    email = models.EmailField("e-mail", blank=True)
    endereco = models.CharField("endereço", max_length=200, blank=True)
    cidade = models.CharField("cidade", max_length=80, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    observacoes = models.TextField("observações", blank=True)
    ativo = models.BooleanField("ativa", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "autorizada / assistência"
        verbose_name_plural = "autorizadas / assistências"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class EnvioAutorizada(models.Model):
    """Envio de um equipamento (computador OU notebook) a uma AUTORIZADA para reparo.
    Acompanhado por STATUS (quadro Kanban), com anexos exigidos em cada etapa e uma
    timeline de comentários (RegistroEnvioAutorizada). Não altera o status do
    equipamento no resto do sistema — é acompanhado só aqui."""

    FORMATOS = ["pdf", "jpg", "jpeg", "png"]

    class Status(models.TextChoices):
        ENVIADO = "enviado", "Enviado"
        EM_ANALISE = "em_analise", "Em análise"
        AGUARDANDO = "aguardando", "Aguardando aprovação"
        EM_REPARO = "em_reparo", "Em reparo"
        RETORNANDO = "retornando", "Retornando"
        FINALIZADO = "finalizado", "Finalizado"

    class Devolutiva(models.TextChoices):
        POSITIVA = "positiva", "Positiva (vai reparar)"
        NEGATIVA = "negativa", "Negativa (sem conserto)"

    autorizada = models.ForeignKey(
        Autorizada, verbose_name="autorizada", on_delete=models.PROTECT, related_name="envios",
    )
    # Exatamente um equipamento (ver clean()). SET_NULL para o histórico sobreviver.
    computador = models.ForeignKey(
        "Computador", verbose_name="computador", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="envios_autorizada",
    )
    notebook = models.ForeignKey(
        "Notebook", verbose_name="notebook", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="envios_autorizada",
    )
    equipamento_desc = models.CharField("equipamento", max_length=200, blank=True)
    quantidade = models.PositiveIntegerField("quantidade", default=1)
    patrimonio = models.CharField("patrimônio", max_length=40, blank=True)
    serial = models.TextField(
        "nº de série", blank=True,
        help_text="Um ou mais números de série (para itens avulsos, liste vários — um por linha).",
    )

    problema = models.TextField("problema relatado", blank=True)
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices,
        default=Status.ENVIADO, db_index=True,
    )
    sem_conserto = models.BooleanField("sem conserto / inviável", default=False)
    devolutiva = models.CharField(
        "devolutiva da análise", max_length=10, choices=Devolutiva.choices, blank=True,
    )
    bitrix_task_id = models.CharField("tarefa Bitrix", max_length=40, blank=True)
    valor_reparo = models.DecimalField(
        "valor do reparo (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
    )

    os_make = models.FileField(
        "OS (Ordem de Serviço da Make)", upload_to="autorizada/os_make/",
        validators=[FileExtensionValidator(FORMATOS)], null=True, blank=True,
        help_text="Nossa OS — anexada ao registrar o envio.",
    )
    os_arquivo = models.FileField(
        "OS da autorizada", upload_to="autorizada/os/",
        validators=[FileExtensionValidator(FORMATOS)], null=True, blank=True,
    )
    orcamento_arquivo = models.FileField(
        "nota / orçamento", upload_to="autorizada/orcamento/",
        validators=[FileExtensionValidator(FORMATOS)], null=True, blank=True,
    )
    comprovante_pagamento = models.FileField(
        "comprovante de pagamento", upload_to="autorizada/pagamento/",
        validators=[FileExtensionValidator(FORMATOS)], null=True, blank=True,
    )
    autorizacao_arquivo = models.FileField(
        "autorização de retirada (print)", upload_to="autorizada/autorizacao/",
        validators=[FileExtensionValidator(FORMATOS)], null=True, blank=True,
    )
    autorizacao_texto = models.TextField("autorização de retirada (texto)", blank=True)
    foto_recebido = models.FileField(
        "foto do material recebido", upload_to="autorizada/recebido/",
        validators=[FileExtensionValidator(FORMATOS)], null=True, blank=True,
    )

    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="registrado por", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="envios_autorizada_registrados",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    data_finalizado = models.DateTimeField("finalizado em", null=True, blank=True)

    class Meta:
        verbose_name = "envio p/ autorizada"
        verbose_name_plural = "envios p/ autorizadas"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.equipamento_display} → {self.autorizada}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.computador_id and self.notebook_id:
            raise ValidationError("Escolha só um equipamento do estoque: computador OU notebook.")
        # Sem dispositivo do estoque é permitido para ITEM AVULSO (fora do estoque),
        # desde que haja uma descrição.
        if not self.computador_id and not self.notebook_id and not (self.equipamento_desc or "").strip():
            raise ValidationError("Escolha um equipamento do estoque ou descreva um item avulso.")

    @property
    def eh_avulso(self):
        """Item que não está no estoque (sem computador/notebook vinculado)."""
        return not self.computador_id and not self.notebook_id

    @property
    def dispositivo(self):
        return self.computador or self.notebook

    @property
    def eh_notebook(self):
        return bool(self.notebook_id)

    @property
    def equipamento_display(self):
        if self.equipamento_desc:
            return self.equipamento_desc
        d = self.dispositivo
        return str(d) if d else "Equipamento"

    def preencher_snapshot(self):
        """Copia descrição/patrimônio/série do dispositivo vinculado (histórico)."""
        d = self.dispositivo
        if d is None:
            return
        if self.notebook_id:
            self.equipamento_desc = f"{d.marca} {d.modelo}".strip() or "Notebook"
        else:
            self.equipamento_desc = str(d)
        self.patrimonio = getattr(d, "patrimonio", "") or ""
        self.serial = getattr(d, "serial", "") or ""


class RegistroEnvioAutorizada(models.Model):
    """Comentário / andamento de um envio p/ autorizada (log com autor e carimbo)."""

    envio = models.ForeignKey(
        EnvioAutorizada, verbose_name="envio", on_delete=models.CASCADE, related_name="registros",
    )
    texto = models.TextField("registro")
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="autor", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="registros_envio_autorizada",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "registro do envio"
        verbose_name_plural = "registros do envio"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Registro de {self.criado_em:%d/%m/%Y %H:%M}"


class NotaCompraEnvio(models.Model):
    """NF de compra anexada a um envio (item fora do estoque) — pode ter várias."""

    envio = models.ForeignKey(
        EnvioAutorizada, verbose_name="envio", on_delete=models.CASCADE, related_name="notas_compra",
    )
    arquivo = models.FileField(
        "NF de compra", upload_to="autorizada/nf/",
        validators=[FileExtensionValidator(EnvioAutorizada.FORMATOS)],
    )
    enviado_em = models.DateTimeField("enviado em", auto_now_add=True)

    class Meta:
        verbose_name = "NF de compra"
        verbose_name_plural = "NFs de compra"
        ordering = ["enviado_em"]

    def __str__(self):
        return self.arquivo.name.rsplit("/", 1)[-1] if self.arquivo else "NF"

    @property
    def nome(self):
        return self.arquivo.name.rsplit("/", 1)[-1] if self.arquivo else "NF"


class TelemetriaMaquina(models.Model):
    """Última coleta de hardware enviada pelo AGENTE (PowerShell) de uma máquina.

    Casa com um Computador/Notebook pelo `serial`. Uma linha por serial (upsert a
    cada 30 min). Sem máquina casada = **pendente** (o admin vincula o serial ao
    patrimônio). As specs medidas são espelhadas em Computador/Notebook.tel_* para
    o score usar os dados reais sem consulta extra nos mapas.
    """
    computador = models.ForeignKey(
        "parque.Computador", verbose_name="computador", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="telemetrias",
    )
    notebook = models.ForeignKey(
        "parque.Notebook", verbose_name="notebook", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="telemetrias",
    )
    serial = models.CharField("nº de série", max_length=120, unique=True, db_index=True)
    mac = models.CharField("MAC (identidade física)", max_length=12, blank=True, db_index=True,
                           help_text="Endereço MAC normalizado (hex). Identifica a máquina "
                                     "física de forma única mesmo com specs idênticas.")
    hostname = models.CharField("nome da máquina", max_length=120, blank=True)
    # Inventário estruturado (sem benchmark).
    so = models.CharField("S.O", max_length=120, blank=True)
    cpu_modelo = models.CharField("CPU", max_length=160, blank=True)
    cpu_nucleos = models.PositiveIntegerField("núcleos", null=True, blank=True)
    cpu_ghz = models.DecimalField("clock (GHz)", max_digits=4, decimal_places=2, null=True, blank=True)
    ram_gb = models.DecimalField("RAM (GB)", max_digits=6, decimal_places=1, null=True, blank=True)
    ram_tipo = models.CharField("tipo de RAM", max_length=20, blank=True)  # DDR3/DDR3L/DDR4/DDR5
    disco_tipo = models.CharField("tipo de disco", max_length=20, blank=True)  # NVMe/SSD/HD
    disco_total_gb = models.DecimalField("disco total (GB)", max_digits=8, decimal_places=1, null=True, blank=True)
    disco_livre_gb = models.DecimalField("disco livre (GB)", max_digits=8, decimal_places=1, null=True, blank=True)
    particao = models.CharField("esquema de partição", max_length=10, blank=True)  # GPT/MBR
    gpu = models.CharField("placa de vídeo", max_length=160, blank=True)
    gpu_tipo = models.CharField("vídeo (tipo)", max_length=12, blank=True)  # integrada/dedicada
    uptime_seg = models.BigIntegerField("tempo ligada (s)", null=True, blank=True)
    ip_publico = models.CharField("IP público", max_length=45, blank=True)
    ip_local = models.CharField("IP local (LAN)", max_length=45, blank=True, db_index=True,
                                help_text="IP da máquina na rede interna. Usado p/ identificar "
                                          "automaticamente o computador quando acessado pela LAN.")
    geo_cidade = models.CharField("cidade", max_length=80, blank=True)
    geo_regiao = models.CharField("estado/região", max_length=80, blank=True)
    geo_pais = models.CharField("país", max_length=60, blank=True)
    geo_lat = models.CharField("latitude", max_length=20, blank=True)
    geo_lon = models.CharField("longitude", max_length=20, blank=True)
    # Localização deduzida pelo IP público (unidade "dona" do IP, por maioria).
    unidade_detectada = models.ForeignKey(
        "orgs.Location", verbose_name="unidade detectada (por IP)",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Unidade onde a maioria das máquinas deste IP público está cadastrada.",
    )
    local_ignorado = models.BooleanField(
        "ignorar divergência", default=False,
        help_text="Marque para exceções legítimas (ex.: notebook em home office) "
                  "e parar de acusar divergência de localização desta máquina.",
    )
    raw = models.TextField("JSON bruto", blank=True)
    visto_em = models.DateTimeField("visto em", db_index=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "telemetria de máquina"
        verbose_name_plural = "telemetria (coletas)"
        ordering = ["-visto_em"]

    def __str__(self):
        return f"{self.serial} · {self.hostname or '—'}"

    @property
    def alvo(self):
        if self.computador_id:
            return self.computador.patrimonio
        if self.notebook_id:
            return self.notebook.patrimonio or str(self.notebook)
        return "— pendente —"

    @property
    def pendente(self):
        return not (self.computador_id or self.notebook_id)

    @property
    def uptime_humano(self):
        """Tempo ligada em formato legível (ex.: '3d 5h', '2h 10min')."""
        return humanizar_uptime(self.uptime_seg)

    @property
    def gpu_label(self):
        """Vídeo com o tipo por extenso (ex.: 'NVIDIA GTX 1650 · dedicada').

        Este texto é GRAVADO em `tel_gpu` e exibido na tela — por isso diz o
        tipo por palavra em vez de emoji (DESIGN-PRO.md §0). Registros antigos
        guardam o emoji até o agente enviar telemetria de novo.
        """
        if not self.gpu:
            return ""
        tipo = "dedicada" if self.gpu_tipo == "dedicada" else "integrada"
        return f"{self.gpu} · {tipo}"

    def _disco_base(self):
        """Disco sem o esquema de partição (ex.: 'SSD 238GB') — para o cadastro."""
        return (f"{self.disco_tipo} {round(float(self.disco_total_gb))}GB".strip()
                if self.disco_total_gb else (self.disco_tipo or ""))

    def _txts(self):
        """Monta as strings enriquecidas (mesmo formato do endpoint) a partir dos
        campos já gravados nesta coleta."""
        cpu = (self.cpu_modelo or "").strip()
        if cpu and self.cpu_ghz and "ghz" not in cpu.lower():
            cpu = f"{cpu} {self.cpu_ghz}GHz"
        ram = (f"{self.ram_gb}GB {self.ram_tipo}".strip() if self.ram_gb
               else (self.ram_tipo or ""))
        disco_base = self._disco_base()
        disco = (f"{disco_base} · {self.particao}" if (disco_base and self.particao)
                 else (disco_base or self.particao or ""))
        return cpu, ram, disco, (self.so or "").strip()

    def aplicar_na_maquina(self, atualizar_cadastro=True):
        """Espelha esta coleta na máquina vinculada (Computador/Notebook).

        - `tel_*`: telemetria efetiva usada no score/status (sempre).
        - Cadastro (processador/RAM/armazenamento/S.O): **só preenche o que
          está em branco.** Nunca sobrescreve o que uma pessoa digitou.

        Retorna True se aplicou.

        ANTES isto reescrevia o cadastro inteiro a cada coleta, com a intenção
        de "manter coerente com o hardware real". O efeito prático era outro: o
        agente roda a cada 30 minutos, então qualquer correção feita à mão no
        cadastro era apagada em menos de meia hora, sem aviso e sem registro de
        quem apagou. Quem editava concluía que salvar não funcionava.

        A leitura do agente não se perde: ela continua inteira nos campos
        `tel_*`, alimenta o score e aparece na tela quando o cadastro está
        vazio. Quando os dois discordam, `divergencias_telemetria` (no
        Computador/Notebook) entrega o par para a tela mostrar os dois lados.
        Decisão do Jonas em 21/09/2026."""
        alvo = self.computador or self.notebook
        if alvo is None:
            return False
        cpu, ram, disco, so = self._txts()
        geo = self.geo_label if self.geo_label != "—" else ""
        alvo.tel_cpu = cpu[:120]
        alvo.tel_ram = ram[:60]
        alvo.tel_disco = disco[:80]
        alvo.tel_so = so[:80]
        alvo.tel_gpu = (self.gpu_label or "")[:80]
        alvo.tel_uptime_seg = self.uptime_seg
        alvo.tel_local = (geo or "")[:120]
        alvo.tel_visto_em = self.visto_em
        campos = ["tel_cpu", "tel_ram", "tel_disco", "tel_so", "tel_gpu",
                  "tel_uptime_seg", "tel_local", "tel_visto_em"]
        # Atrela o MAC ao patrimônio (identidade física permanente).
        if self.mac and getattr(alvo, "mac", "") != self.mac:
            alvo.mac = self.mac
            campos.append("mac")
        if atualizar_cadastro:
            # COMPLETA o cadastro, não o reescreve: cada campo só recebe a
            # medição quando está em branco. Assim o vínculo de uma máquina nova
            # já nasce com as specs certas (era o objetivo original), e a
            # correção feita à mão numa máquina antiga sobrevive às coletas.
            def _vazio(campo):
                return not (getattr(alvo, campo, "") or "").strip()

            if cpu and _vazio("processador"):
                alvo.processador = cpu[:120]
                campos.append("processador")
            if ram and _vazio("memoria_ram"):
                alvo.memoria_ram = ram[:60]
                campos.append("memoria_ram")
            base = self._disco_base()
            if base and _vazio("armazenamento"):
                alvo.armazenamento = base[:80]
                campos.append("armazenamento")
            if so and hasattr(alvo, "sistema_operacional") and _vazio("sistema_operacional"):
                alvo.sistema_operacional = so[:80]
                campos.append("sistema_operacional")
        alvo.save(update_fields=campos)
        return True

    @property
    def geo_label(self):
        partes = [p for p in [self.geo_cidade, self.geo_regiao, self.geo_pais] if p]
        return " · ".join(partes) if partes else "—"

    @property
    def mac_label(self):
        """MAC formatado com ':' (ex.: AA:BB:CC:DD:EE:FF)."""
        m = self.mac or ""
        return ":".join(m[i:i + 2] for i in range(0, len(m), 2)) if m else ""

    @property
    def ativa(self):
        """True se a última coleta chegou dentro da janela de atividade."""
        if not self.visto_em:
            return False
        return self.visto_em >= timezone.now() - timedelta(hours=TELEMETRIA_ATIVA_HORAS)

    @property
    def unidade_cadastrada(self):
        """Unidade onde a máquina está cadastrada (via baia → setor → unidade)."""
        alvo = self.computador or self.notebook
        baia = getattr(alvo, "baia", None) if alvo else None
        if baia and baia.setor_id:
            return baia.setor.unidade
        return None

    @property
    def local_divergente(self):
        """True quando a unidade cadastrada difere da detectada pelo IP público
        (e a divergência não foi ignorada). É o gatilho da correção/notificação."""
        if self.local_ignorado or not self.unidade_detectada_id:
            return False
        uc = self.unidade_cadastrada
        return bool(uc and uc.id != self.unidade_detectada_id)


class Tarefa(models.Model):
    """
    Tarefa de saúde do parque, dirigida por telemetria — o item que aparece no
    painel de tarefas da tela de preventivas para o responsável agir.

    Gerada automaticamente (management command `gerar_tarefas`) a partir de 3
    condições da máquina: sem telemetria ativa, tempo ligado alto e score baixo.
    Fecha sozinha (RESOLVIDA_AUTO) quando a condição some; o usuário pode
    CONCLUIR (agiu) ou DISPENSAR (ignorar de vez). Dedup por `chave` (uma linha
    por máquina + tipo, para sempre). Alvo é uma baia OU um notebook (ver clean).
    """

    class Tipo(models.TextChoices):
        SEM_TELEMETRIA = "sem_telemetria", "Sem telemetria ativa"
        UPTIME_ALTO = "uptime_alto", "Tempo ligado alto"
        SCORE_BAIXO = "score_baixo", "Score de desempenho baixo"

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        CONCLUIDA = "concluida", "Concluída"
        DISPENSADA = "dispensada", "Dispensada"
        RESOLVIDA_AUTO = "resolvida_auto", "Resolvida automaticamente"

    baia = models.ForeignKey(
        Baia, verbose_name="baia", on_delete=models.CASCADE,
        related_name="tarefas", null=True, blank=True,
        help_text="Mesa (baia) alvo — quando a máquina está numa mesa.",
    )
    notebook = models.ForeignKey(
        "Notebook", verbose_name="notebook", on_delete=models.CASCADE,
        related_name="tarefas", null=True, blank=True,
        help_text="Notebook alvo — alternativa à baia.",
    )
    tipo = models.CharField("tipo", max_length=16, choices=Tipo.choices, db_index=True)
    status = models.CharField(
        "status", max_length=16, choices=Status.choices,
        default=Status.ABERTA, db_index=True,
    )
    unidade = models.ForeignKey(
        "orgs.Location", verbose_name="unidade", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="tarefas",
        help_text="Unidade da máquina (desnormalizado para filtro por responsável).",
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="responsável",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tarefas_atribuidas",
    )
    chave = models.CharField(
        "chave (dedup)", max_length=60, unique=True, db_index=True,
        help_text="Identidade única da tarefa (tipo + máquina). Evita duplicar.",
    )
    titulo = models.CharField("título", max_length=160)
    detalhe = models.TextField("detalhe", blank=True)
    observacao = models.TextField(
        "observação", blank=True,
        help_text="Anotação do responsável ao concluir/dispensar.",
    )
    criada_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizada_em = models.DateTimeField("atualizada em", auto_now=True)
    fechada_em = models.DateTimeField("fechada em", null=True, blank=True)
    fechada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="fechada por",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tarefas_fechadas",
    )

    class Meta:
        verbose_name = "tarefa"
        verbose_name_plural = "tarefas"
        ordering = ["-criada_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.patrimonio or self.titulo}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.baia_id) == bool(self.notebook_id):
            raise ValidationError(
                "Informe exatamente um alvo da tarefa: uma baia OU um notebook."
            )

    # --- Alvo / exibição (espelham Reparo.maquina_patrimonio / maquina_local) ---
    @property
    def alvo(self):
        if self.baia_id:
            return self.baia.dispositivo if self.baia.dispositivo else self.baia
        return self.notebook

    @property
    def patrimonio(self):
        if self.baia_id:
            d = self.baia.dispositivo
            return getattr(d, "patrimonio", "") or "" if d else ""
        return (self.notebook.patrimonio if self.notebook_id else "") or ""

    @property
    def local(self):
        if self.baia_id and self.baia.setor_id:
            return f"{self.baia.setor.unidade.name} › {self.baia.setor.nome}"
        if self.notebook_id:
            return self.notebook.unidade_setor or "Notebook (sem mesa)"
        return "—"

    @property
    def eh_notebook(self):
        return bool(self.notebook_id)

    @property
    def acao_url(self):
        """Deep-link contextual da tarefa (o que fazer)."""
        if self.tipo == self.Tipo.SEM_TELEMETRIA:
            return "/parque/agente/"
        # score baixo / uptime alto → mapa da unidade (card/diagnóstico da máquina)
        if self.unidade_id:
            return f"/parque/mapa-completo/?unidade={self.unidade_id}"
        return "/parque/preventiva/?vista=tarefas"


class GrupoManutencao(models.Model):
    """
    Grupo de máquinas (computadores/notebooks) para ANTECIPAR a preventiva em
    lote, em vez de esperar cada uma vencer. Pertence a uma unidade: qualquer
    usuário da loja vê/edita (add/remove); a gestão vê todos. Concluir a
    preventiva do grupo zera o ciclo de cada máquina (via Reparo) e pontua.
    """

    nome = models.CharField("nome do grupo", max_length=120)
    unidade = models.ForeignKey(
        "orgs.Location", verbose_name="unidade", on_delete=models.CASCADE,
        related_name="grupos_manutencao",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="criado por",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="grupos_manutencao_criados",
    )
    baias = models.ManyToManyField(
        Baia, verbose_name="computadores (baias)", blank=True,
        related_name="grupos_manutencao",
    )
    notebooks = models.ManyToManyField(
        "Notebook", verbose_name="notebooks", blank=True,
        related_name="grupos_manutencao",
    )
    criada_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "grupo de manutenção"
        verbose_name_plural = "grupos de manutenção"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.unidade.name if self.unidade_id else '—'})"

    @property
    def total_membros(self):
        return self.baias.count() + self.notebooks.count()


class AdiamentoPreventiva(models.Model):
    """
    Pedido de ADIAMENTO de uma preventiva (com justificativa) que o Supervisor
    aprova ou nega. Espelha o fluxo de Transferencia (notificação fixa de
    aprovar/negar). Ao aprovar, empurra `preventiva_adiada_ate` da máquina.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente de aprovação"
        APROVADO = "aprovado", "Aprovado"
        NEGADO = "negado", "Negado"

    baia = models.ForeignKey(
        Baia, verbose_name="baia", on_delete=models.CASCADE,
        related_name="adiamentos", null=True, blank=True,
    )
    notebook = models.ForeignKey(
        "Notebook", verbose_name="notebook", on_delete=models.CASCADE,
        related_name="adiamentos", null=True, blank=True,
    )
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="solicitante",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="adiamentos_solicitados",
    )
    justificativa = models.TextField("justificativa")
    nova_data = models.DateField("nova data-limite")
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
    )
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="decidido por",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="adiamentos_decididos",
    )
    decidido_em = models.DateTimeField("decidido em", null=True, blank=True)
    motivo = models.CharField("motivo (negação)", max_length=200, blank=True)
    criada_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "adiamento de preventiva"
        verbose_name_plural = "adiamentos de preventiva"
        ordering = ["-criada_em"]

    def __str__(self):
        return f"Adiar {self.patrimonio or '—'} até {self.nova_data:%d/%m/%Y}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.baia_id) == bool(self.notebook_id):
            raise ValidationError(
                "Informe exatamente um alvo do adiamento: uma baia OU um notebook."
            )

    @property
    def alvo(self):
        return self.baia if self.baia_id else self.notebook

    @property
    def patrimonio(self):
        if self.baia_id:
            d = self.baia.dispositivo
            return getattr(d, "patrimonio", "") or "" if d else ""
        return (self.notebook.patrimonio if self.notebook_id else "") or ""

    @property
    def local(self):
        if self.baia_id and self.baia.setor_id:
            return f"{self.baia.setor.unidade.name} › {self.baia.setor.nome}"
        if self.notebook_id:
            return self.notebook.unidade_setor or "Notebook (sem mesa)"
        return "—"

    def aprovar(self, user):
        self.status = self.Status.APROVADO
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.save()
        alvo = self.alvo
        if alvo is not None:
            alvo.preventiva_adiada_ate = self.nova_data
            alvo.save(update_fields=["preventiva_adiada_ate"])

    def negar(self, user, motivo=""):
        self.status = self.Status.NEGADO
        self.decidido_por = user
        self.decidido_em = timezone.now()
        self.motivo = (motivo or "")[:200]
        self.save()


# ---------------------------------------------------------------------------
# MURAL — a conversa em cima do que aconteceu
# ---------------------------------------------------------------------------
# O mural NAO guarda os acontecimentos: eles ja existem em dez modelos (Reparo,
# Transferencia, MovimentacaoBaia, Tarefa, Termo, ...) e o feed e' montado a
# partir deles. O que nao existia era o que gente escreve DEPOIS: o comentario,
# a foto do servico, e quem assumiu a demanda.
#
# POR QUE `chave` DE TEXTO E NAO ForeignKey/GenericForeignKey
# ------------------------------------------------------------
# Um card do mural nem sempre e' uma linha de tabela. "Agente de coleta nao
# esta reportando — 31 maquinas em Bonsucesso" e' um card que resume 31 Tarefas;
# nao ha' UMA linha para apontar. A `chave` e' o id do card ("rep181",
# "tka-sem_telemetria-7"), montado sempre pelo mesmo lugar (mural.py), o que
# deixa comentario de card agrupado e de registro unico no mesmo lugar.
#
# O preco: apagar o registro nao apaga o comentario — ele fica orfao e para de
# aparecer (nenhum card o reivindica). E' visivel em `mural_orfaos()` e nao
# vaza para tela nenhuma.
class ComentarioEvento(models.Model):
    """Um comentario de gente num acontecimento do parque."""

    FORMATOS_FOTO = ["png", "jpg", "jpeg", "webp"]

    chave = models.CharField(
        "acontecimento", max_length=64, db_index=True,
        help_text="id do card no mural (ex.: rep181, mb22, tka-sem_telemetria-7)",
    )
    tipo = models.CharField(
        "tipo do acontecimento", max_length=24, blank=True, db_index=True,
        help_text="chamado, transferencia, tarefa_aberta... serve para filtrar",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="autor", on_delete=models.CASCADE,
        related_name="comentarios_mural",
    )
    texto = models.TextField("texto", blank=True)
    foto = models.ImageField(
        "foto", upload_to="mural/fotos/%Y/%m/", null=True, blank=True,
        validators=[FileExtensionValidator(FORMATOS_FOTO)],
        help_text="foto do servico: antes/depois, etiqueta, peca queimada",
    )
    legenda = models.CharField("legenda da foto", max_length=160, blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True, db_index=True)
    editado_em = models.DateTimeField("editado em", null=True, blank=True)

    class Meta:
        verbose_name = "comentário do mural"
        verbose_name_plural = "comentários do mural"
        ordering = ["criado_em"]
        indexes = [models.Index(fields=["chave", "criado_em"])]

    def __str__(self):
        corpo = (self.texto or "").strip() or ("foto" if self.foto else "vazio")
        return f"{self.autor} em {self.chave}: {corpo[:40]}"

    @property
    def tem_foto(self):
        return bool(self.foto)


class MarcaEvento(models.Model):
    """Quem assumiu e quem acompanha um acontecimento.

    Duas marcas na mesma tabela porque sao a mesma forma (pessoa + card + data)
    e sempre aparecem juntas: assumir tambem passa a acompanhar.
    """

    class Marca(models.TextChoices):
        ASSUMIDO = "assumido", "Está cuidando"
        SEGUINDO = "seguindo", "Acompanhando"

    chave = models.CharField("acontecimento", max_length=64, db_index=True)
    tipo = models.CharField("tipo do acontecimento", max_length=24, blank=True)
    marca = models.CharField("marca", max_length=10, choices=Marca.choices,
                             db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuário", on_delete=models.CASCADE,
        related_name="marcas_mural",
    )
    em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "marca do mural"
        verbose_name_plural = "marcas do mural"
        ordering = ["-em"]
        constraints = [
            models.UniqueConstraint(fields=["chave", "usuario", "marca"],
                                    name="marca_unica_por_pessoa_e_card"),
        ]

    def __str__(self):
        return f"{self.usuario} {self.get_marca_display().lower()} {self.chave}"


class PublicacaoMural(models.Model):
    """Um post escrito por gente, sem evento por tras.

    O que o mural mostrava era o que o SISTEMA registrou. Isto e' o que a
    PESSOA quer contar: "amanha a loja do Centro fica sem rede das 8 as 10",
    "chegaram 12 SSD, quem precisar fala comigo".

    O QUE ISTO TEM QUE O FEED CORPORATIVO NAO TEM
    ---------------------------------------------
    A publicacao pode ficar PRESA A UMA MAQUINA (`patrimonio`) e a uma loja.
    Presa a uma maquina, ela aparece na ficha corrida daquele equipamento —
    junto do chamado, da transferencia e do laudo. Seis meses depois, quem
    abrir o PC-CG0111 le "trocamos a fonte, a antiga estufou" no meio da
    historia dele. Post solto em feed de empresa se perde; este fica no lugar
    onde alguem vai procurar.
    """

    # ARQUIVO, nao foto. A foto do servico e' o caso mais comum, mas o que a
    # pessoa quer anexar num aviso e' tambem a nota fiscal em PDF, a planilha
    # de contagem, o print da tela. ImageField recusaria tudo isso.
    FORMATOS = ["png", "jpg", "jpeg", "webp", "gif", "pdf", "docx", "xlsx",
                "csv", "txt"]
    FORMATOS_IMAGEM = ["png", "jpg", "jpeg", "webp", "gif"]

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="autor", on_delete=models.CASCADE,
        related_name="publicacoes_mural",
    )
    texto = models.TextField("texto")
    arquivo = models.FileField(
        "arquivo", upload_to="mural/publicacoes/%Y/%m/", null=True, blank=True,
        validators=[FileExtensionValidator(FORMATOS)],
    )
    # O REGISTRO DE QUE A PUBLICACAO FALA. Nao se escolhe numa lista: a pessoa
    # escreve, e o sistema oferece o que tem relacao com o que ela escreveu
    # (uma movimentacao, um chamado, uma telemetria). Escolhido o registro, o
    # patrimonio e a loja vem DELE — ninguem digita patrimonio errado.
    #
    # `alvo` e' a chave do card no mural ("mb22", "rep181"), a mesma de
    # ComentarioEvento. `alvo_titulo` e' um retrato do texto na hora do
    # vinculo: se o registro mudar de nome depois, o card continua legivel, e
    # se o registro for apagado a publicacao ainda diz do que falava.
    alvo = models.CharField("registro citado", max_length=64, blank=True,
                            db_index=True)
    alvo_titulo = models.CharField("registro (retrato)", max_length=160, blank=True)

    # Amarras no parque. Ficam como TEXTO (o patrimonio) e FK (a loja) porque o
    # patrimonio pode ser de computador OU de notebook — duas tabelas. As duas
    # sao PREENCHIDAS a partir do `alvo`, nao digitadas.
    patrimonio = models.CharField(
        "patrimônio", max_length=40, blank=True, db_index=True,
        help_text="vem do registro citado; a publicação entra na ficha dele",
    )
    unidade = models.ForeignKey(
        "orgs.Location", verbose_name="loja", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="publicacoes_mural",
    )
    # As tags que a pessoa escreveu com # no texto, normalizadas e separadas
    # por espaco. Guardadas fora do texto porque o filtro por tema tem que
    # comparar valor exato — "#Transferência" e "#transferencia" sao a mesma
    # coisa, e isso se resolve na gravacao, nao na leitura.
    tags = models.CharField(
        "temas", max_length=240, blank=True, db_index=True,
        help_text="preenchido a partir das #tags do texto",
    )
    # Quem foi chamado no texto. Guardado separado do texto para o "me
    # mencionaram" nao depender de reler e reinterpretar o texto de todo post.
    mencionados = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name="mencionados", blank=True,
        related_name="mencoes_mural",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True, db_index=True)
    editado_em = models.DateTimeField("editado em", null=True, blank=True)

    class Meta:
        verbose_name = "publicação do mural"
        verbose_name_plural = "publicações do mural"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.autor}: {(self.texto or '')[:48]}"

    @property
    def foi_editada(self):
        return bool(self.editado_em)

    @property
    def e_imagem(self):
        """A tela mostra imagem em tile e o resto como ficha de arquivo."""
        nome = (self.arquivo.name or "") if self.arquivo else ""
        return nome.rsplit(".", 1)[-1].lower() in self.FORMATOS_IMAGEM

    @property
    def nome_do_arquivo(self):
        nome = (self.arquivo.name or "") if self.arquivo else ""
        return nome.rsplit("/", 1)[-1]


class MensagemDireta(models.Model):
    """Conversa de duas pessoas dentro do sistema.

    POR QUE ISTO MORA AQUI E NAO NUM WHATSAPP
    -----------------------------------------
    "A movimentacao da baia 12 pode?" hoje acontece no zap, e a resposta se
    perde. Aqui a mensagem pode CITAR UM REGISTRO (`alvo`, a mesma chave do
    mural): a conversa fica do lado da coisa conversada, e seis meses depois
    quem abrir a maquina acha o "pode" que autorizou.

    ACESSO — A PARTE QUE NAO PODE CEDER
    -----------------------------------
    So' as DUAS PESSOAS da conversa leem. Superusuario NAO le conversa alheia:
    o mural inteiro respeita o acesso de quem olha, e um canal privado que o
    admin le por padrao nao e' canal privado. Quem precisar auditar usa o
    banco, com a decisao consciente de fazer isso.
    """

    FORMATOS = ["png", "jpg", "jpeg", "webp", "gif", "pdf", "docx", "xlsx",
                "csv", "txt"]

    de = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="de", on_delete=models.CASCADE,
        related_name="mensagens_enviadas",
    )
    para = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="para", on_delete=models.CASCADE,
        related_name="mensagens_recebidas",
    )
    texto = models.TextField("texto", blank=True)
    arquivo = models.FileField(
        "arquivo", upload_to="mural/conversa/%Y/%m/", null=True, blank=True,
        validators=[FileExtensionValidator(FORMATOS)],
    )
    # O registro citado, quando a conversa e' sobre alguma coisa do sistema.
    alvo = models.CharField("registro citado", max_length=64, blank=True,
                            db_index=True)
    alvo_titulo = models.CharField("registro (retrato)", max_length=160, blank=True)

    criado_em = models.DateTimeField("enviada em", auto_now_add=True, db_index=True)
    lida_em = models.DateTimeField("lida em", null=True, blank=True)

    class Meta:
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        ordering = ["criado_em"]
        indexes = [
            # As duas consultas da tela: a conversa de um par, e o que ainda
            # nao foi lido por mim.
            models.Index(fields=["de", "para", "criado_em"]),
            models.Index(fields=["para", "lida_em"]),
        ]

    def __str__(self):
        return f"{self.de} → {self.para}: {(self.texto or '')[:40]}"

    @property
    def e_imagem(self):
        nome = (self.arquivo.name or "") if self.arquivo else ""
        return nome.rsplit(".", 1)[-1].lower() in ["png", "jpg", "jpeg", "webp", "gif"]

    @property
    def nome_do_arquivo(self):
        nome = (self.arquivo.name or "") if self.arquivo else ""
        return nome.rsplit("/", 1)[-1]
