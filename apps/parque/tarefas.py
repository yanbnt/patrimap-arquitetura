"""
Painel de tarefas de saúde do parque (tela de preventivas).

Gera/atualiza `Tarefa` a partir de 3 condições calculadas por máquina:
  - SEM_TELEMETRIA: máquina em uso sem coleta recente (o agente não está rodando);
  - UPTIME_ALTO:    ligada direto há >= UPTIME_ALTO_DIAS dias;
  - SCORE_BAIXO:    índice de desempenho <= SCORE_TAREFA_MAX (Crítico/Baixo).

Idempotente (dedup por `Tarefa.chave`, uma linha por máquina+tipo):
  - condição verdadeira  → garante uma tarefa ABERTA (reabre RESOLVIDA_AUTO/CONCLUIDA;
                           respeita DISPENSADA, que o usuário mandou ignorar);
  - condição falsa       → uma tarefa ABERTA vira RESOLVIDA_AUTO.

Também expõe os helpers de ESCOPO por usuário usados pela view do painel.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    SCORE_TAREFA_MAX, UPTIME_ALTO_DIAS, Baia, Notebook, Tarefa,
)

RESPONSAVEIS = ["Técnico de Pós Venda", "Estagiário"]
GESTAO = ["Gerente", "Supervisor"]

# Rótulo/detalhe padrão por tipo de tarefa.
_TEXTOS = {
    Tarefa.Tipo.SEM_TELEMETRIA: (
        "Agente de coleta não está reportando",
        "A máquina não envia telemetria há mais de 2h (ou nunca enviou). "
        "Instale/relance o agente para o sistema acompanhar o hardware real.",
    ),
    Tarefa.Tipo.UPTIME_ALTO: (
        "Máquina ligada há muito tempo",
        "Está ligada direto há dias. Programe um reinício para manter o "
        "desempenho e aplicar atualizações pendentes.",
    ),
    Tarefa.Tipo.SCORE_BAIXO: (
        "Score de desempenho baixo",
        "O índice está em faixa Crítica/Baixa. Avalie limpeza, upgrade "
        "(RAM/SSD) ou troca da máquina.",
    ),
}


# --- Escopo por usuário -----------------------------------------------------
def unidade_do_usuario(user):
    """Unidade (loja) do usuário: perfil.unidade → colaborador.location → None."""
    perfil = getattr(user, "perfil", None)
    if perfil is not None and perfil.unidade_id:
        return perfil.unidade
    pessoa = getattr(user, "colaborador", None)
    if pessoa is not None and pessoa.location_id:
        return pessoa.location
    return None


def ve_tudo(user):
    """Gestão (superuser/Gerente/Supervisor) enxerga o parque inteiro."""
    return bool(
        user and user.is_authenticated and (
            user.is_superuser
            or user.groups.filter(name__in=GESTAO).exists()
        )
    )


def tecnicos_da_unidade(unidade_id):
    """Técnicos/estagiários ativos lotados na unidade (via colaborador.location)."""
    if not unidade_id:
        return []
    return list(
        User.objects.filter(
            is_active=True, groups__name__in=RESPONSAVEIS,
            colaborador__location_id=unidade_id,
        ).distinct()
    )


# --- Avaliação das condições por máquina ------------------------------------
def _condicoes(disp, score):
    """Conjunto de tipos de tarefa VERDADEIROS agora para um dispositivo.

    `disp` é o Computador ou Notebook; `score` é o indice_desempenho (0-100/None).
    """
    tipos = set()
    # Só máquinas que NUNCA reportaram (agente não instalado). Máquinas que já
    # reportaram e ficaram "inativo" (coleta velha) NÃO entram aqui — o agente
    # está instalado; costuma ser a URL do túnel que mudou, não falta de agente.
    if getattr(disp, "telemetria_status", "sem") == "sem":
        tipos.add(Tarefa.Tipo.SEM_TELEMETRIA)
    up = getattr(disp, "tel_uptime_seg", None)
    if up and up >= UPTIME_ALTO_DIAS * 86400:
        tipos.add(Tarefa.Tipo.UPTIME_ALTO)
    if score is not None and score <= SCORE_TAREFA_MAX:
        tipos.add(Tarefa.Tipo.SCORE_BAIXO)
    return tipos


def _alvos():
    """Itera as máquinas EM USO do parque como tuplas prontas para avaliar.

    Devolve: (chave_base, kwargs_alvo, unidade, dispositivo, score)
      - chave_base: 'c<pk>' (computador de baia) ou 'n<pk>' (notebook)
      - kwargs_alvo: {'baia': b} ou {'notebook': n}
    """
    baias = (
        Baia.objects.select_related("setor__unidade", "computador")
        .prefetch_related("reparos")
    )
    for b in baias:
        if not b.computador_id:
            continue
        yield (f"c{b.computador_id}", {"baia": b}, b.setor.unidade,
               b.computador, b.indice_desempenho)

    notebooks = (
        Notebook.objects.select_related(
            "colaborador__location", "baia__setor__unidade")
        .prefetch_related("reparos")
    )
    for n in notebooks:
        # "em uso" = tem colaborador OU está numa baia (baia é OneToOne reverso).
        try:
            baia = n.baia
        except ObjectDoesNotExist:
            baia = None
        unidade = None
        if n.colaborador_id and n.colaborador.location_id:
            unidade = n.colaborador.location
        elif baia is not None and baia.setor_id:
            unidade = baia.setor.unidade
        else:
            continue
        yield (f"n{n.pk}", {"notebook": n}, unidade, n, n.indice_desempenho)


def sincronizar_tarefas(dry_run=False):
    """Cria/atualiza/resolve tarefas do parque inteiro. Idempotente.

    Retorna um resumo: {'por_unidade': {uid: {'unidade', 'abertas'}},
                        'criadas', 'reabertas', 'resolvidas'}.
    """
    agora = timezone.now()
    criadas = reabertas = resolvidas = 0
    por_unidade = {}

    # Cache de tarefas existentes por chave (uma query).
    existentes = {t.chave: t for t in Tarefa.objects.all()}

    for chave_base, kwargs_alvo, unidade, disp, score in _alvos():
        ativos = _condicoes(disp, score)
        resp_cache = None  # técnico da unidade, resolvido só quando precisar

        for tipo in Tarefa.Tipo.values:
            chave = f"{tipo}:{chave_base}"
            t = existentes.get(chave)
            deve = tipo in ativos

            if deve:
                # Registra na contagem por unidade (para a notificação).
                if unidade is not None:
                    d = por_unidade.setdefault(
                        unidade.id, {"unidade": unidade, "abertas": 0})
                    d["abertas"] += 1

                if t is None:
                    if resp_cache is None and unidade is not None:
                        tecs = tecnicos_da_unidade(unidade.id)
                        resp_cache = tecs[0] if tecs else False
                    titulo, detalhe = _TEXTOS[tipo]
                    if not dry_run:
                        Tarefa.objects.create(
                            tipo=tipo, chave=chave, status=Tarefa.Status.ABERTA,
                            unidade=unidade,
                            responsavel=(resp_cache or None),
                            titulo=titulo, detalhe=detalhe, **kwargs_alvo,
                        )
                    criadas += 1
                elif t.status in (Tarefa.Status.RESOLVIDA_AUTO,
                                  Tarefa.Status.CONCLUIDA):
                    # A condição voltou — reabre e atualiza o alvo/unidade atuais.
                    if not dry_run:
                        t.status = Tarefa.Status.ABERTA
                        t.fechada_em = None
                        t.fechada_por = None
                        t.unidade = unidade
                        t.baia = kwargs_alvo.get("baia")
                        t.notebook = kwargs_alvo.get("notebook")
                        t.save(update_fields=[
                            "status", "fechada_em", "fechada_por",
                            "unidade", "baia", "notebook", "atualizada_em"])
                    reabertas += 1
                # DISPENSADA → não mexe. ABERTA → já está no estado certo.
            else:
                if t is not None and t.status == Tarefa.Status.ABERTA:
                    if not dry_run:
                        t.status = Tarefa.Status.RESOLVIDA_AUTO
                        t.fechada_em = agora
                        t.save(update_fields=[
                            "status", "fechada_em", "atualizada_em"])
                    resolvidas += 1

    return {
        "por_unidade": por_unidade,
        "criadas": criadas,
        "reabertas": reabertas,
        "resolvidas": resolvidas,
    }
