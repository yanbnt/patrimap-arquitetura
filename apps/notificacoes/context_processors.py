"""Injeta as notificações do usuário no contexto (sino do cabeçalho).

Roda em TODA página do admin (é context processor), então o custo daqui é fixo
por requisição — ver auditoria 3.7. Daí os dois limites abaixo.
"""

from .models import Notificacao

# Quantas notificações mostrar no dropdown do sino.
LIMITE_DROPDOWN = 8
# Teto das FIXAS (aprovar/negar). Auditoria 3.7: `fixas` era a única lista SEM
# limite — como a fixa só some quando alguém decide, um gerente que deixou 300
# transferências pendentes carregava as 300 (e renderizava 300 formulários no
# sino) em toda página. O teto é maior que o do dropdown porque fixa é ação
# pendente: some ao ser resolvida e não deve ser escondida à toa.
LIMITE_FIXAS = 20


def notificacoes(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    qs = Notificacao.objects.filter(destinatario=user)
    # Fixas (aprovar/negar) sempre no topo; depois as recentes normais.
    fixas = list(qs.filter(fixa=True)[:LIMITE_FIXAS])
    recentes = list(qs.filter(fixa=False)[:LIMITE_DROPDOWN])
    nao_lidas = qs.filter(lida=False).count()
    return {
        "notif_lista": fixas + recentes,
        "notif_nao_lidas": nao_lidas,
    }
