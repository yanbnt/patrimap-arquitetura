"""
Importa a planilha de Notebooks (exportada do Bitrix) para o modelo Notebook.

Uso:
    python manage.py import_notebooks "C:\\caminho\\Notebooks_Grupo_1610.xlsx"
    python manage.py import_notebooks "<arquivo.xlsx>" --reset   # apaga antes

Faz upsert idempotente pelo ID da tarefa do Bitrix (ou pelo nº de série).
Cada coluna da planilha vira um campo do Notebook.
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from apps.parque.models import Notebook

# Cabeçalho da planilha -> campo do modelo.
COLUNAS = {
    "ID Tarefa": "bitrix_task_id",
    "Titulo (Bitrix)": "titulo",
    "Marca": "marca",
    "Modelo": "modelo",
    "Usuario": "usuario",
    "Unidade/Setor": "unidade_setor",
    "Numero de Serie": "serial",
    "Conta": "conta",
    "Senha": "senha",
    "AnyDesk": "anydesk",
    "Senha AnyDesk": "anydesk_senha",
    "Processador": "processador",
    "RAM": "memoria_ram",
    "Armazenamento": "armazenamento",
    "Observacoes": "observacoes",
    "Criada em": "criada_em_origem",
    "Atualizada em": "atualizada_em_origem",
}
CAMPOS_DATA = {"criada_em_origem", "atualizada_em_origem"}


def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _data(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _status(titulo, observacoes):
    txt = f"{titulo} {observacoes}".upper()
    if "DEFEITO" in txt:
        return Notebook.Status.DEFEITO
    if "OBSOLET" in txt:
        return Notebook.Status.OBSOLETO
    return Notebook.Status.ATIVO


class Command(BaseCommand):
    help = "Importa a planilha de Notebooks (Bitrix) para o modelo Notebook."

    def add_arguments(self, parser):
        parser.add_argument("arquivo", help="Caminho do .xlsx de notebooks.")
        parser.add_argument("--reset", action="store_true",
                            help="Apaga todos os notebooks antes de importar.")

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl nao instalado. Rode: pip install openpyxl")

        caminho = opts["arquivo"]
        try:
            wb = openpyxl.load_workbook(caminho, data_only=True)
        except FileNotFoundError:
            raise CommandError(f"Arquivo nao encontrado: {caminho}")
        ws = wb.active

        linhas = list(ws.iter_rows(values_only=True))
        if not linhas:
            raise CommandError("Planilha vazia.")

        cabecalho = [(_texto(c)) for c in linhas[0]]
        # indice de cada coluna conhecida
        idx = {}
        for i, nome in enumerate(cabecalho):
            if nome in COLUNAS:
                idx[COLUNAS[nome]] = i
        faltando = set(COLUNAS.values()) - set(idx)
        if faltando:
            self.stdout.write(self.style.WARNING(
                "Colunas nao encontradas (serao ignoradas): " + ", ".join(sorted(faltando))
            ))

        if opts["reset"]:
            n = Notebook.objects.count()
            Notebook.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Reset: {n} notebook(s) apagado(s)."))

        criados = atualizados = ignorados = vinculados = 0
        for row in linhas[1:]:
            if not any(c not in (None, "") for c in row):
                continue
            dados = {}
            for campo, i in idx.items():
                val = row[i] if i < len(row) else None
                dados[campo] = _data(val) if campo in CAMPOS_DATA else _texto(val)

            dados["status"] = _status(dados.get("titulo", ""), dados.get("observacoes", ""))

            bitrix = dados.get("bitrix_task_id", "")
            serial = dados.get("serial", "")

            if bitrix:
                obj, novo = Notebook.objects.update_or_create(
                    bitrix_task_id=bitrix, defaults=dados)
            elif serial:
                obj, novo = Notebook.objects.update_or_create(
                    serial=serial, defaults=dados)
            else:
                # sem chave: cria sempre (evita duplicar so se titulo coincidir)
                if dados.get("titulo") and Notebook.objects.filter(titulo=dados["titulo"]).exists():
                    ignorados += 1
                    continue
                obj = Notebook.objects.create(**dados)
                novo = True

            criados += 1 if novo else 0
            atualizados += 0 if novo else 1

            if obj.colaborador_id is not None:
                vinculados += 1

        self.stdout.write(self.style.SUCCESS(
            f"OK: {criados} criado(s), {atualizados} atualizado(s), "
            f"{ignorados} ignorado(s). Total no banco: {Notebook.objects.count()}."
        ))
        # O vínculo com o colaborador é feito pelo sinal `pre_save`
        # (apps/parque/signals.py) — aqui só se reporta o resultado. Duplicar a
        # regra de casar nome em cada importador foi o que deixou os dados
        # descasados antes.
        sem_vinculo = Notebook.objects.filter(
            colaborador__isnull=True).exclude(usuario="").count()
        self.stdout.write(self.style.SUCCESS(
            f"Com colaborador vinculado: {vinculados}."
        ))
        if sem_vinculo:
            self.stdout.write(self.style.WARNING(
                f"{sem_vinculo} notebook(s) com nome no texto e SEM vínculo "
                "(nome ambíguo ou pessoa não cadastrada)."
            ))
            self.stdout.write(
                "Para ver quais: python manage.py casar_notebooks --detalhe"
            )
