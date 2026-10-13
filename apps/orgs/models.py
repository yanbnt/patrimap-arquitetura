"""
Organização: onde os ativos ficam e quem os utiliza.

Local/Unidade é hierárquico (empresa → prédio → sala) e suporta multi-unidade.
Pessoa é o colaborador que recebe o ativo — propositalmente separado do User de
login do Django (quem segura um equipamento não precisa acessar o sistema).
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from apps.orgs.validators import (
    UFS, so_digitos, valida_cep, valida_cnpj, valida_cpf, valida_telefone,
)

# Janela (minutos) em que um usuário é considerado "online" desde a última atividade.
MINUTOS_ONLINE = 5


class TelaGrupo(models.Model):
    """Qual GRUPO abre qual TELA.

    Antes desta tabela, a resposta vivia em dois lugares que não conversavam: a
    condição do item no menu e o `if` dentro de cada view. Duas listas para a
    mesma pergunta divergem — e divergiram (ver apps/orgs/acessos.py).

    A tabela nasce semeada com exatamente o que o sistema já fazia, e é ela que
    a tela /parque/acessos/ edita. Tela sem nenhuma linha aqui cai no padrão do
    registro `TELAS`, então nunca fica sem resposta.

    `tela` é o id do registro (texto), não uma FK: a lista de telas é do
    código, não do banco — tela que não existe mais no código simplesmente
    deixa de ser consultada, sem migração para limpar.
    """

    tela = models.CharField("tela", max_length=40, db_index=True)
    grupo = models.ForeignKey(
        "auth.Group", verbose_name="grupo", on_delete=models.CASCADE,
        related_name="telas_liberadas",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="liberado por",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="acessos_concedidos",
    )

    class Meta:
        verbose_name = "acesso de grupo a tela"
        verbose_name_plural = "acessos de grupo a telas"
        constraints = [
            models.UniqueConstraint(fields=["tela", "grupo"],
                                    name="acesso_unico_por_tela_e_grupo"),
        ]
        ordering = ["tela", "grupo__name"]

    def __str__(self):
        from apps.orgs.acessos import POR_ID
        t = POR_ID.get(self.tela)
        return "%s → %s" % (self.grupo.name, t.nome if t else self.tela)


class AtividadeUsuario(models.Model):
    """Última atividade de cada usuário, alimentada pelo middleware.

    Usada para o painel "Usuários online": online = atividade nos últimos
    MINUTOS_ONLINE minutos.
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="usuário", on_delete=models.CASCADE,
        related_name="atividade",
    )
    visto_em = models.DateTimeField("última atividade", default=timezone.now)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "atividade de usuário"
        verbose_name_plural = "atividades de usuário"
        ordering = ["-visto_em"]

    def __str__(self):
        return f"{self.usuario} — {self.visto_em:%d/%m/%Y %H:%M}"

    @property
    def online(self):
        limite = timezone.now() - timezone.timedelta(minutes=MINUTOS_ONLINE)
        return self.visto_em >= limite


class PerfilUsuario(models.Model):
    """Dados extras do usuário de login. Liga manualmente o usuário a uma baia
    (a máquina onde ele trabalha) para exibir o patrimônio em "Usuários online"."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="usuário", on_delete=models.CASCADE,
        related_name="perfil",
    )
    baia = models.ForeignKey(
        "parque.Baia", verbose_name="baia / máquina", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="usuarios",
        help_text="Baia (máquina) onde este usuário trabalha. Define o patrimônio "
                  "mostrado em Usuários online.",
    )
    unidade = models.ForeignKey(
        "orgs.Location", verbose_name="loja / unidade", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="usuarios_perfil",
        help_text="Loja onde o usuário trabalha. O colaborador vinculado passa a "
                  "aparecer no mapa dessa loja (mesmo sem computador/notebook).",
    )
    senha_temporaria = models.BooleanField(
        "senha temporária", default=False,
        help_text="Ligado quando o usuário recebe uma senha temporária por e-mail. "
                  "Enquanto estiver ligado, ele é obrigado a definir uma nova senha "
                  "no próximo acesso.",
    )
    senha_temporaria_em = models.DateTimeField(
        "senha temporária gerada em", null=True, blank=True,
        help_text="Momento em que a senha temporária foi gerada. Usado para expirá-la.",
    )

    class Meta:
        verbose_name = "perfil de usuário"
        verbose_name_plural = "perfis de usuário"

    @property
    def senha_temp_expirada(self):
        """True se há senha temporária ativa porém fora da janela de validade."""
        if not self.senha_temporaria or not self.senha_temporaria_em:
            return False
        from django.conf import settings as cfg
        validade = timezone.timedelta(hours=getattr(cfg, "SENHA_TEMP_VALIDADE_HORAS", 24))
        return timezone.now() > self.senha_temporaria_em + validade

    def __str__(self):
        return f"Perfil de {self.usuario}"

    @property
    def patrimonio(self):
        b = self.baia
        if b and b.computador_id:
            return b.computador.patrimonio or ""
        return ""


class UsuarioOnline(User):
    """Proxy de User para o painel só-leitura "Usuários online"."""

    class Meta:
        proxy = True
        verbose_name = "usuário online"
        verbose_name_plural = "usuários online"


class LogAcesso(models.Model):
    """Log de acessos: login, logout e tentativas de login com falha."""

    class Evento(models.TextChoices):
        LOGIN = "login", "Entrou"
        LOGOUT = "logout", "Saiu"
        FALHA = "falha", "Falha de login"
        RECUPERACAO = "recuperacao", "Pediu senha temporária"
        TROCA_SENHA = "troca_senha", "Trocou a senha"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuário", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="acessos",
    )
    username_tentado = models.CharField("usuário tentado", max_length=150, blank=True)
    evento = models.CharField("evento", max_length=20, choices=Evento.choices)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("navegador", max_length=300, blank=True)
    em = models.DateTimeField("data/hora", auto_now_add=True)

    class Meta:
        verbose_name = "log de acesso"
        verbose_name_plural = "log de acessos"
        ordering = ["-em"]

    def __str__(self):
        quem = self.usuario or self.username_tentado or "?"
        return f"{self.get_evento_display()} — {quem} ({self.em:%d/%m/%Y %H:%M})"


class Location(models.Model):
    """Local físico ou unidade. Auto-relacionável para formar hierarquia."""

    name = models.CharField(
        "nome", max_length=160,
        help_text="Nome do local/unidade. Ex.: Matriz, CD Cascavel, Sala da TI.",
    )
    parent = models.ForeignKey(
        "self",
        verbose_name="local pai",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        help_text="Local que contém este (hierarquia). Ex.: 'Matriz' é pai de "
                  "'Sala da TI'. Deixe vazio se for o nível mais alto.",
    )
    # ---- Identificação fiscal e operacional -----------------------------
    #
    # Estes campos existem porque o cadastro de 4 campos não sustentava o
    # trabalho real: o comprovante de transferência entre filiais saía só com
    # o NOME da loja (sem CNPJ não fecha com nota fiscal), a razão social
    # estava chumbada no template do termo, e a sigla do patrimônio vinha de
    # um dicionário em Python — loja nova exigia editar código-fonte.
    #
    # Todos aceitam vazio no banco: há linhas antigas e locais que não são
    # loja (Sala da TI). Quem cobra o preenchimento é o formulário, conforme
    # o `tipo`.
    class Tipo(models.TextChoices):
        LOJA = "loja", "Loja"
        CD = "cd", "Centro de distribuição"
        MATRIZ = "matriz", "Matriz"
        INTERNO = "interno", "Sala / setor interno"
        OUTRO = "outro", "Outro"

    tipo = models.CharField(
        "tipo", max_length=12, choices=Tipo.choices, default=Tipo.LOJA,
        db_index=True,
        help_text="O que este local é. Loja, CD e Matriz emitem documento e "
                  "por isso pedem CNPJ; sala interna não.",
    )
    razao_social = models.CharField(
        "razão social", max_length=160, blank=True,
        help_text="Nome jurídico, como sai na nota. O campo 'nome' é o nome "
                  "de uso (Centro, Boqueirão).",
    )
    cnpj = models.CharField(
        "CNPJ", max_length=14, blank=True, db_index=True,
        validators=[valida_cnpj],
        help_text="Só números. Necessário para transferência entre filiais e "
                  "para os documentos impressos.",
    )
    codigo = models.CharField(
        "código", max_length=4, blank=True,
        help_text="Sigla de 1 a 4 letras usada no patrimônio (B, CF, CTB). "
                  "Sem ela o patrimônio cai na 1ª letra do nome e colide.",
    )
    telefone = models.CharField(
        "telefone", max_length=11, blank=True,
        validators=[valida_telefone],
        help_text="Só números, com DDD. É para onde a TI e a transportadora "
                  "ligam quando a máquina chega ou atrasa.",
    )
    ativo = models.BooleanField(
        "ativa", default=True, db_index=True,
        help_text="Desmarque em vez de excluir: loja fechada não pode sair do "
                  "banco (há setores e peças apontando para ela), mas sai dos "
                  "seletores de transferência.",
    )

    address = models.CharField(
        "endereço", max_length=255, blank=True,
        help_text="Logradouro. Ex.: Av. Brasil, 1000.",
    )
    numero = models.CharField(
        "número", max_length=10, blank=True,
        help_text="Número do imóvel. Separado do logradouro porque etiqueta "
                  "de transportadora exige os dois em campos distintos.",
    )
    bairro = models.CharField(
        "bairro", max_length=80, blank=True,
        help_text="Bairro do local.",
    )
    cep = models.CharField(
        "CEP", max_length=8, blank=True,
        validators=[valida_cep],
        help_text="Só números. Sem CEP não se gera frete nem etiqueta.",
    )
    city = models.CharField(
        "cidade", max_length=120, blank=True,
        help_text="Cidade do local. Ex.: Cascavel.",
    )
    state = models.CharField(
        "UF", max_length=2, blank=True, choices=UFS,
        help_text="Estado do local. Antes era texto livre e nada validava as "
                  "2 letras que a ajuda prometia.",
    )
    notes = models.TextField(
        "observações", blank=True,
        help_text="Texto livre para anotações sobre o local.",
    )

    def save(self, *args, **kwargs):
        """Guarda documento e contato SÓ COM DÍGITOS, e o código em maiúscula.

        Máscara é assunto de formulário. Guardar "00.000.000/0000-00" impede
        comparar, indexar e cruzar com o Sankhya — e é o tipo de sujeira que
        depois exige limpeza em massa.
        """
        self.cnpj = so_digitos(self.cnpj)
        self.telefone = so_digitos(self.telefone)
        self.cep = so_digitos(self.cep)
        self.codigo = (self.codigo or "").strip().upper()
        self.state = (self.state or "").strip().upper()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "local / unidade"
        verbose_name_plural = "locais / unidades"
        ordering = ["name"]

    def __str__(self):
        if self.parent:
            return f"{self.parent} › {self.name}"
        return self.name


class Department(models.Model):
    """Setor da empresa (TI, Comercial, Logística...)."""

    name = models.CharField(
        "nome", max_length=120,
        help_text="Nome do setor. Ex.: TI, Comercial, Logística, Financeiro.",
    )
    location = models.ForeignKey(
        Location,
        verbose_name="local / unidade",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="departments",
        help_text="Local/unidade onde o setor fica. Selecione um local cadastrado.",
    )
    manager = models.ForeignKey(
        "orgs.Person",
        verbose_name="responsável",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_departments",
        help_text="Pessoa responsável pelo setor. Selecione uma pessoa cadastrada.",
    )

    class Meta:
        verbose_name = "departamento"
        verbose_name_plural = "departamentos"
        ordering = ["location__name", "name"]

    def __str__(self):
        # Mostra a loja junto: o mesmo setor (ex.: "Comercial") existe em várias lojas,
        # então sem a unidade a lista de seleção parece repetida.
        return f"{self.name} — {self.location.name}" if self.location_id else self.name


class Person(models.Model):
    """
    Colaborador que pode receber/segurar ativos. Independente do User de login.
    """

    full_name = models.CharField(
        "nome completo", max_length=160,
        help_text="Nome completo do colaborador. Ex.: Maria da Silva.",
    )
    email = models.EmailField(
        "e-mail", blank=True,
        help_text="E-mail corporativo. Ex.: pessoa@exemplo.com.br",
    )
    cpf = models.CharField(
        "CPF", max_length=11, blank=True, db_index=True,
        validators=[valida_cpf],
        help_text="Só números. O Termo de Responsabilidade imprime o CPF — sem "
                  "ele o documento sai com linha em branco para preencher à mão.",
    )
    telefone = models.CharField(
        "telefone", max_length=11, blank=True,
        validators=[valida_telefone],
        help_text="Só números, com DDD. Contato de quem usa a máquina quando o "
                  "chamado precisa de resposta rápida.",
    )
    data_desligamento = models.DateField(
        "desligado em", null=True, blank=True,
        help_text="Preencha ao desligar. É o que permite cobrar devolução de "
                  "notebook e encerrar o termo de responsabilidade.",
    )
    employee_no = models.CharField(
        "matrícula", max_length=40, blank=True,
        help_text="Matrícula/registro do colaborador. Ex.: 1042.",
    )
    job_title = models.CharField(
        "cargo", max_length=120, blank=True,
        help_text="Cargo/função. Ex.: Analista de Infraestrutura.",
    )
    foto = models.ImageField(
        "foto",
        upload_to="colaboradores/avatar/",
        blank=True,
        null=True,
        help_text=(
            "Foto do colaborador, usada como avatar na gaveta de navegação e nas "
            "telas onde ele aparece. Quadrada fica melhor (é exibida em círculo). "
            "Sem foto, mostra a inicial do nome."
        ),
    )

    class Sexo(models.TextChoices):
        MASCULINO = "M", "Masculino"
        FEMININO = "F", "Feminino"

    sexo = models.CharField(
        "sexo", max_length=1, choices=Sexo.choices, blank=True,
        help_text="Define o avatar (masculino/feminino) no mapa de notebooks.",
    )
    department = models.ForeignKey(
        Department,
        verbose_name="departamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="people",
        help_text="Setor do colaborador. Selecione um departamento cadastrado.",
    )
    location = models.ForeignKey(
        Location,
        verbose_name="local / unidade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="people",
        help_text="Local/unidade onde o colaborador trabalha.",
    )
    active = models.BooleanField(
        "ativo", default=True,
        help_text="Desmarque para colaboradores desligados (mantém o histórico).",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="conta de acesso",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="colaborador",
        help_text="Conta de login vinculada (admins/equipe também são colaboradores).",
    )

    def save(self, *args, **kwargs):
        """CPF e telefone só com dígitos — mesma regra da Location."""
        self.cpf = so_digitos(self.cpf)
        self.telefone = so_digitos(self.telefone)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "pessoa"
        verbose_name_plural = "pessoas"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name
