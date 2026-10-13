"""
Auditoria dos cadastros: pessoas, contas de acesso e o que está ligado a elas.

SÓ LEITURA. Não grava, não apaga, não corrige. Serve para decidir o que fazer.

POR QUE
-------
O sistema guarda "quem é a pessoa" em dois modelos de propósito:

    orgs.Person   o COLABORADOR — quem recebe equipamento
    auth.User     a CONTA DE ACESSO — quem entra no sistema

Nem todo colaborador tem conta (quem só recebe máquina não precisa entrar), e
é assim que foi desenhado. O problema aparece quando os dois DIVERGEM: conta
sem pessoa, pessoa duplicada, conta desativada ainda oferecida numa lista,
equipamento apontando para quem saiu da empresa.

Este comando põe tudo isso numa tela só.

USO
---
    python manage.py auditar_cadastros              # resumo
    python manage.py auditar_cadastros --detalhe    # lista cada caso
    python manage.py auditar_cadastros --csv saida.csv
"""

import csv
import unicodedata
from collections import defaultdict

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from apps.orgs.models import Person


def _norm(texto):
    limpo = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    return " ".join(limpo.split())


class Command(BaseCommand):
    help = "Audita pessoas, contas de acesso e vínculos. Só leitura."

    def add_arguments(self, parser):
        parser.add_argument("--detalhe", action="store_true",
                            help="Lista cada caso, não só os totais.")
        parser.add_argument("--csv", dest="csv_path", default="",
                            help="Grava os achados num CSV para tratar fora.")

    def handle(self, *args, **opts):
        self.detalhe = opts["detalhe"]
        self.achados = []          # (gravidade, categoria, quem, detalhe)

        self._cabecalho()
        self._contas_sem_pessoa()
        self._pessoas_duplicadas()
        self._cadastro_incompleto()
        self._contas_inativas_em_uso()
        self._desligados_com_equipamento()
        self._equipamento_sem_dono()
        self._resumo()

        if opts["csv_path"]:
            with open(opts["csv_path"], "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["gravidade", "categoria", "quem", "detalhe"])
                w.writerows(self.achados)
            self.stdout.write(self.style.SUCCESS(f"CSV: {opts['csv_path']}"))

    # ------------------------------------------------------------- utilidades
    def _titulo(self, t):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(t))

    def _achar(self, gravidade, categoria, quem, detalhe=""):
        self.achados.append((gravidade, categoria, quem, detalhe))

    def _linha(self, rotulo, n, gravidade="ok"):
        estilo = {"alto": self.style.ERROR, "medio": self.style.WARNING,
                  "ok": self.style.SUCCESS}[gravidade if n else "ok"]
        self.stdout.write("  %-46s %s" % (rotulo, estilo("%5d" % n)))

    def _listar(self, itens, limite=40):
        if not self.detalhe:
            return
        for texto in itens[:limite]:
            self.stdout.write("      · " + texto)
        if len(itens) > limite:
            self.stdout.write("      … e mais %d" % (len(itens) - limite))

    # --------------------------------------------------------------- panorama
    def _cabecalho(self):
        self._titulo("Panorama")
        self.stdout.write("  %-46s %5d" % ("pessoas (colaboradores)", Person.objects.count()))
        self.stdout.write("  %-46s %5d" % ("contas de acesso (usuários)", User.objects.count()))
        self.stdout.write("  %-46s %5d" % (
            "pessoas COM conta", Person.objects.filter(user__isnull=False).count()))
        self.stdout.write("  %-46s %5d" % (
            "pessoas SEM conta (normal)", Person.objects.filter(user__isnull=True).count()))

    # ------------------------------------------------------- conta sem pessoa
    def _contas_sem_pessoa(self):
        """Conta de acesso que não aparece em nenhum cadastro.

        É a que explica "fulano já foi excluído e continua na lista": a Pessoa
        sumiu, a conta ficou — e as listas de seleção mostram a CONTA.
        """
        self._titulo("Contas de acesso sem cadastro de pessoa")
        orfas = list(User.objects.filter(colaborador__isnull=True).order_by("username"))
        ativas = [u for u in orfas if u.is_active]
        self._linha("contas sem pessoa (total)", len(orfas), "medio")
        self._linha("  dessas, ATIVAS (aparecem nas listas)", len(ativas), "alto")
        for u in orfas:
            self._achar("alto" if u.is_active else "medio", "conta sem pessoa",
                        u.get_username(),
                        "ativa" if u.is_active else "inativa")
        self._listar(["%s%s" % (u.get_username(), "" if u.is_active else "  (inativa)")
                      for u in orfas])

    # ------------------------------------------------------ pessoa duplicada
    def _pessoas_duplicadas(self):
        self._titulo("Pessoas repetidas")

        por_nome = defaultdict(list)
        for p in Person.objects.all().only("id", "full_name", "cpf"):
            por_nome[_norm(p.full_name)].append(p)
        dup_nome = {k: v for k, v in por_nome.items() if len(v) > 1}

        dup_cpf = (Person.objects.exclude(cpf="").values("cpf")
                   .annotate(n=Count("id")).filter(n__gt=1))

        self._linha("mesmo NOME em 2+ cadastros", len(dup_nome), "medio")
        self._linha("mesmo CPF em 2+ cadastros", dup_cpf.count(), "alto")

        for chave, ps in dup_nome.items():
            self._achar("medio", "nome repetido", ps[0].full_name,
                        "ids: " + ", ".join(str(p.pk) for p in ps))
        self._listar(["%s  (ids %s)" % (ps[0].full_name, ", ".join(str(p.pk) for p in ps))
                      for ps in dup_nome.values()])

        for d in dup_cpf:
            nomes = list(Person.objects.filter(cpf=d["cpf"]).values_list("full_name", flat=True))
            self._achar("alto", "CPF repetido", d["cpf"], " | ".join(nomes))

    # ----------------------------------------------------- cadastro incompleto
    def _cadastro_incompleto(self):
        """Campos vazios que a operação usa.

        Não é frescura de formulário: sem CPF o Termo de Responsabilidade sai
        com linha em branco para preencher à mão, e sem unidade a pessoa não
        aparece no mapa da loja.
        """
        self._titulo("Cadastro incompleto (entre os ATIVOS)")
        ativos = Person.objects.filter(active=True)
        total = ativos.count()
        faltas = (
            ("CPF", ativos.filter(Q(cpf="") | Q(cpf__isnull=True)), "medio"),
            ("cargo", ativos.filter(Q(job_title="") | Q(job_title__isnull=True)), "medio"),
            ("unidade/loja", ativos.filter(location__isnull=True), "alto"),
            ("departamento", ativos.filter(department__isnull=True), "medio"),
            ("e-mail", ativos.filter(Q(email="") | Q(email__isnull=True)), "medio"),
        )
        for rotulo, qs, grav in faltas:
            n = qs.count()
            # Campo vazio em TODO MUNDO não é cadastro incompleto — é campo que
            # a operação nunca usou (o import não trouxe a coluna). Contar 91
            # "problemas" aí afoga os poucos achados que importam de verdade.
            if total and n == total:
                self.stdout.write("  %-46s %s" % (
                    "sem " + rotulo,
                    self.style.HTTP_INFO("todos — campo não utilizado")))
                continue
            self._linha("sem " + rotulo, n, grav)
            for p in qs[:200]:
                self._achar(grav, "incompleto: sem " + rotulo, p.full_name, "")
            self._listar([p.full_name for p in qs[:40]])

    # ------------------------------------------------- conta inativa em uso
    def _contas_inativas_em_uso(self):
        self._titulo("Contas desativadas que ainda aparecem ligadas")
        qs = Person.objects.filter(user__isnull=False, user__is_active=False)
        self._linha("pessoa ativa com conta DESATIVADA",
                    qs.filter(active=True).count(), "medio")
        for p in qs.filter(active=True):
            self._achar("medio", "conta desativada", p.full_name,
                        "conta: " + p.user.get_username())
        self._listar(["%s  (conta %s)" % (p.full_name, p.user.get_username())
                      for p in qs.filter(active=True)[:40]])

    # --------------------------------------------- desligado com equipamento
    def _desligados_com_equipamento(self):
        """Quem saiu da empresa não pode continuar com máquina no nome."""
        self._titulo("Desligados ainda com equipamento")
        from apps.parque.models import Baia, Notebook

        desligados = Person.objects.filter(
            Q(active=False) | Q(data_desligamento__isnull=False))

        com_nb = Notebook.objects.filter(colaborador__in=desligados)
        com_baia = Baia.objects.filter(colaborador__in=desligados)

        self._linha("notebooks no nome de desligado", com_nb.count(), "alto")
        self._linha("baias no nome de desligado", com_baia.count(), "alto")

        for nb in com_nb[:200]:
            self._achar("alto", "notebook de desligado",
                        nb.colaborador.full_name, nb.patrimonio or nb.serial or "")
        for b in com_baia[:200]:
            self._achar("alto", "baia de desligado", b.colaborador.full_name, b.nome)

        self._listar(["%s  ->  %s" % (nb.colaborador.full_name, nb.patrimonio or nb.serial)
                      for nb in com_nb[:40]])

    # ------------------------------------------------- equipamento sem dono
    def _equipamento_sem_dono(self):
        """O descasamento texto x vínculo, agora nos dois modelos."""
        self._titulo("Equipamento com nome em texto e sem vínculo")
        from apps.parque.models import Baia, Notebook

        nb = Notebook.objects.filter(colaborador__isnull=True).exclude(usuario="")
        self._linha("notebooks: tem texto, falta vínculo", nb.count(), "alto")
        for n in nb[:200]:
            self._achar("alto", "notebook sem vínculo", n.usuario,
                        n.patrimonio or n.serial or "")
        self._listar(["%-24s %s" % (n.usuario, n.patrimonio or n.serial or "") for n in nb[:40]])

        # Baia usa a MESMA leitura do signal: "9 - Juliana" é pessoa, mas
        # "3 - Direita" e "8 - Vazio" são posição. Contar tudo que não é número
        # puro acusava 42 problemas onde havia 4 — e relatório que grita demais
        # acaba ignorado.
        from apps.parque.signals import _eh_placeholder, partes_do_nome_da_baia

        pendentes = []
        for b in Baia.objects.filter(colaborador__isnull=True).only("id", "nome"):
            _, parte = partes_do_nome_da_baia(b.nome)
            if parte and not _eh_placeholder(parte):
                pendentes.append((b, parte))

        self._linha("baias com NOME DE PESSOA e sem vínculo", len(pendentes), "medio")
        for b, parte in pendentes[:200]:
            self._achar("medio", "baia sem vínculo", parte, b.nome)
        self._listar(["%-26s  ->  %s" % (b.nome, parte) for b, parte in pendentes[:40]])

    # ----------------------------------------------------------------- resumo
    def _resumo(self):
        altos = sum(1 for a in self.achados if a[0] == "alto")
        medios = sum(1 for a in self.achados if a[0] == "medio")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Resumo"))
        self.stdout.write("  achados graves .............. %s" % self.style.ERROR(str(altos)))
        self.stdout.write("  achados a revisar ........... %s" % self.style.WARNING(str(medios)))
        self.stdout.write("")
        if not self.detalhe:
            self.stdout.write("  Para ver caso a caso:  --detalhe")
            self.stdout.write("  Para tratar em planilha:  --csv cadastros.csv")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "  SÓ LEITURA — nada foi alterado."))
        self.stdout.write("")
