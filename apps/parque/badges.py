"""Contadores (badges) para os itens do menu lateral do Unfold.

Estes contadores rodam em TODA página do admin (o Unfold monta a sidebar em
cada request), então cada query aqui é custo fixo por requisição — ver auditoria
3.7. Por isso `transferencias_novas` faz uma query só, e não quatro.

Regra de erro (auditoria 2.4/1.9): o badge some quando a query falha — isso é
proposital (é enfeite de menu, não pode derrubar o admin inteiro), mas antes
sumia em SILÊNCIO, com `except Exception: return None`. Agora o motivo real
sempre vai para o log; a falha continua não quebrando a tela.
"""

import logging

from django.db import DatabaseError

logger = logging.getLogger(__name__)


def solicitacoes_pendentes(request):
    """Nº de solicitações de movimentação pendentes (None oculta o badge)."""
    from .models import MovimentacaoBaia

    try:
        n = MovimentacaoBaia.objects.filter(status="pendente").count()
    except DatabaseError:  # banco ainda não migrado, lock, coluna faltando...
        logger.exception("Badge 'solicitações pendentes' falhou; badge oculto.")
        return None
    return n or None


def transferencias_pendentes(request):
    """Nº de transferências pendentes de autorização (None oculta o badge)."""
    from .models import Transferencia

    try:
        n = Transferencia.objects.filter(status="pendente").count()
    except DatabaseError:
        logger.exception("Badge 'transferências pendentes' falhou; badge oculto.")
        return None
    return n or None


def aprovacoes_pendentes(request):
    """Total de aprovações pendentes (transferências + movimentações de baia)."""
    from .models import MovimentacaoBaia, Transferencia

    try:
        n = (Transferencia.objects.filter(status="pendente").count()
             + MovimentacaoBaia.objects.filter(status="pendente").count())
    except DatabaseError:
        logger.exception("Badge 'aprovações pendentes' falhou; badge oculto.")
        return None
    return n or None


def transferencias_novas(request):
    """Nº de transferências NOVAS (PC + notebook + peças) desde a última visita.

    Zera quando o usuário abre a lista de Transferências. None oculta o badge.

    Auditoria 3.7: eram 4 COUNTs separados (um por modelo) em TODA página do
    admin. Como o número exibido é a SOMA deles, `UNION ALL` das 4 listas de pk
    dá exatamente o mesmo total numa ÚNICA ida ao banco — `all=True` é
    obrigatório: sem ele o UNION deduplica e pks iguais em modelos diferentes
    (id 7 de Remessa e id 7 de Transferencia) seriam contados uma vez só.
    O `.order_by()` limpa o ordering do Meta de cada modelo, que o banco não
    aceita dentro de subconsulta de UNION.
    """
    from django.db.models import Q
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from .models import MovimentacaoPeca, Remessa, Transferencia, TransferenciaNotebook

    try:
        desde = None
        visto = request.session.get("transferencias_visto_em")
        if visto:
            try:
                desde = parse_datetime(visto)
            except (ValueError, TypeError):
                # Sessão com valor corrompido/antigo: cai no default de 24h em
                # vez de derrubar a página — mas o valor fica registrado.
                logger.warning(
                    "transferencias_visto_em inválido na sessão: %r; usando 24h.", visto,
                )
        if desde is None:
            desde = timezone.now() - timezone.timedelta(days=1)  # 1ª vez: últimas 24h
        n = (
            Transferencia.objects.filter(
                Q(entre_lojas=True) | Q(setor_destino__isnull=False), created_at__gt=desde
            ).values("pk").order_by()
            .union(
                TransferenciaNotebook.objects.filter(
                    created_at__gt=desde).values("pk").order_by(),
                Remessa.objects.filter(em__gt=desde).values("pk").order_by(),
                MovimentacaoPeca.objects.filter(
                    remessa__isnull=True, em__gt=desde).values("pk").order_by(),
                all=True,
            )
            .count()
        )
    except DatabaseError:
        logger.exception("Badge 'transferências novas' falhou; badge oculto.")
        return None
    return n or None
