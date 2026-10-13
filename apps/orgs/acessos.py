# -*- coding: utf-8 -*-
"""QUEM VÊ O QUÊ — o registro único das telas do sistema.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
A resposta para "quem entra na tela X?" estava escrita em DOIS lugares, e
nenhum deles falava com o outro:

  · a condição do item no menu (config/settings/base.py), uma lambda com a
    lista de grupos digitada à mão;
  · a checagem dentro da view (`GRUPOS_EXECUTIVO`, `pode_ler`,
    `_pode_ver_registros`, cada uma com a sua lista).

Duas listas para a mesma pergunta divergem — e divergiram: o Arquivo aparecia
no menu para Estagiário (a lambda aceitava a permissão de modelo) enquanto a
tela recusava por grupo; e o grupo **Diretor** não abria tela restrita nenhuma
sem que ninguém percebesse, porque não havia lugar onde essa lista pudesse ser
LIDA de uma vez.

Agora existe: `TELAS` abaixo. O menu lê daqui, a view lê daqui e a tela de
acessos (/parque/acessos/) lê e ESCREVE daqui.

O PADRÃO E O BANCO
------------------
Cada tela nasce com `grupos` — o padrão de fábrica, que é a transcrição literal
do que o sistema fazia antes desta mudança (tem teste provando:
`AcessoEquivalenteTests`). Depois de semeada a tabela `TelaGrupo`, é ela que
manda, e é ela que a tela de acessos edita.

`grupos` vazio no registro = tela ABERTA a toda a equipe (qualquer staff), e
isso não é editável por clique: Início e Mapa não deveriam poder ser trancados
sem alguém mexer em código. Onze das dezenove são assim, e é bom que sejam — a
decisão de acesso só existe sobre as oito restantes.

Tela restrita que fica sem NENHUM grupo no banco passa a ser de superusuário
só. Cair no padrão do código nesse caso devolveria o acesso que a pessoa
acabou de tirar na tela — o oposto do que ela pediu. Ver `grupos_da_tela`.
"""
from collections import namedtuple

Tela = namedtuple("Tela", "id nome url icone grupos")

# ---------------------------------------------------------------------------
# O REGISTRO. A ordem é a do menu, porque é a ordem em que as pessoas pensam.
# ---------------------------------------------------------------------------
TELAS = [
    # Aberta como sempre foi. A URL agora e' o desvio que escolhe entre o
    # Mural e o painel, conforme a pessoa abra ou nao a tela "registros".
    Tela("inicio", "Início", "/inicio/", "home", ()),
    Tela("mapa", "Mapa do parque", "/parque/mapa-completo/", "map", ()),
    Tela("dashboard", "Dashboard", "/parque/leitura-executiva/", "insights",
         ("Gerente", "Supervisor", "Visão total", "RH")),
    Tela("arquivo", "Arquivo", "/parque/arquivo/", "topic",
         ("RH", "Supervisor", "Gerente", "Visão total")),
    Tela("preventiva", "Preventiva", "/parque/preventiva/", "event_repeat", ()),
    # Mesmo id "registros": o grupo que abria o calendario abre o mural, e
    # nada no banco de acessos precisa mudar. Mudou o nome, a rota e o icone.
    #
    # ABERTA A TODA A EQUIPE desde 13/10/2026, a pedido do dono. Antes pedia
    # ("RH", "Gerente", "Supervisor") — herança de quando a tela se chamava
    # "Registros" e era um calendário. O efeito colateral era o Início: quem
    # não abria o Mural caía no painel, e a pessoa via DUAS telas iniciais
    # diferentes conforme a conta com que entrasse. Foi assim que apareceu.
    #
    # Abrir não vaza nada: o feed monta por pessoa pelo `TELA_DO_TIPO`
    # (apps/parque/mural.py) — um post só entra para quem já podia abrir a
    # tela que mostrava aquele acontecimento. Quem não abre Chamados continua
    # sem ver post de chamado.
    #
    # E não dá acesso de ESCRITA: publicar e comentar dependem de
    # `add_publicacaomural` / `add_comentarioevento`, que a migração 0066 deu
    # só a RH, Gerente e Supervisor. Toda a equipe LÊ; esses três escrevem.
    #
    # Preço de ser "aberta por desenho": sai da tela de Acessos e não dá mais
    # para trancar por clique (ver `grupos_da_tela`). Para restringir de novo,
    # devolva os grupos a esta tupla.
    Tela("registros", "Mural", "/parque/mural/", "forum", ()),
    Tela("chamados", "Chamados", "/parque/reparos/", "handyman", ()),
    Tela("autorizadas", "Assistência externa", "/parque/autorizadas/",
         "home_repair_service", ()),
    Tela("orcamentos", "Orçamentos", "/orcamentos/", "request_quote", ()),
    Tela("aprovacoes", "Aprovações", "/parque/aprovacoes/", "how_to_reg",
         ("Técnico de Pós Venda", "Supervisor", "Gerente")),
    Tela("estoque", "Estoque", "/parque/estoque/", "inventory_2", ()),
    Tela("transferencias", "Transferências", "/parque/transferencias/",
         "swap_horiz", ()),
    Tela("cadastros", "Cadastros", "/cadastros/", "folder_managed", ()),
    Tela("agente", "Agente e telemetria", "/parque/agente/", "sensors", ()),
    Tela("acessos", "Usuários e acessos", "/parque/acessos/", "manage_accounts",
         ("Gerente", "Supervisor", "Desenvolvimento", "Técnico de Pós Venda")),
    Tela("online", "Usuários online", "/admin/orgs/usuarioonline/", "wifi",
         ("Gerente", "Supervisor")),
    Tela("logs", "Logs", "/logs/", "history", ("Gerente", "Supervisor")),
]

POR_ID = {t.id: t for t in TELAS}

# Telas restritas: as únicas em que a decisão de acesso existe.
RESTRITAS = [t for t in TELAS if t.grupos]
ABERTAS = [t for t in TELAS if not t.grupos]


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _do_banco():
    """{tela_id: set(nomes de grupo)} — só as telas com linha na tabela.

    Se a tabela ainda não existe (durante a primeira migração, por exemplo),
    devolve vazio em vez de estourar: acesso não pode depender de o banco
    estar num estado específico para o sistema subir.
    """
    try:
        from apps.orgs.models import TelaGrupo
        mapa = {}
        for tela, grupo in TelaGrupo.objects.values_list("tela", "grupo__name"):
            mapa.setdefault(tela, set()).add(grupo)
        return mapa
    except Exception:
        return {}


def grupos_da_tela(tela_id, banco=None):
    """Quais grupos abrem esta tela.

    TRÊS ESTADOS, e a diferença entre eles importa muito:

      · tela ABERTA por desenho (`grupos` vazio no registro) — devolve vazio, e
        `pode_ver_tela` lê isso como "toda a equipe". Não é editável por
        clique: Início e Mapa não deveriam poder ser trancados sem alguém
        mexer em código.

      · tela RESTRITA com linha no banco — vale o banco, ponto.

      · tela RESTRITA sem linha, mas com a tabela POVOADA — significa
        NINGUÉM (só superusuário). É o caso de alguém ter removido todos os
        grupos na tela de acessos, e cair no padrão do código aqui seria
        devolver o acesso que a pessoa acabou de tirar.

    Só quando a tabela está inteiramente vazia — instalação nova, ou antes da
    migração de semeadura — é que vale o padrão do registro.
    """
    t = POR_ID.get(tela_id)
    if t is None:
        return set()
    if not t.grupos:
        return set()
    if banco is None:
        banco = _do_banco()
    if not banco:
        return set(t.grupos)
    return set(banco.get(tela_id, ()))


def mapa_completo():
    """{tela_id: set(grupos)} para TODAS as telas — uma consulta só.

    É o que a tela de acessos e o cálculo do menu usam: pedir tela por tela
    daria dezenove consultas por página.
    """
    banco = _do_banco()
    return {t.id: grupos_da_tela(t.id, banco) for t in TELAS}


def telas_do_usuario(user, mapa=None):
    """Os ids das telas que este usuário abre."""
    if not getattr(user, "is_authenticated", False):
        return set()
    if user.is_superuser:
        return set(POR_ID)
    if mapa is None:
        mapa = mapa_completo()
    meus = set(user.groups.values_list("name", flat=True))
    return {tid for tid, grupos in mapa.items()
            if (tid in POR_ID and not POR_ID[tid].grupos) or (grupos & meus)}


def pode_ver_tela(user, tela_id, request=None):
    """A pergunta que o menu e a view fazem.

    `request` é só cache: o menu chama isto dezenove vezes na mesma requisição
    e sem ele seriam dezenove idas ao banco.
    """
    if not getattr(user, "is_authenticated", False) or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    grupos = None
    if request is not None:
        mapa = getattr(request, "_acessos_mapa", None)
        if mapa is None:
            mapa = mapa_completo()
            try:
                request._acessos_mapa = mapa
            except Exception:
                pass
        grupos = mapa.get(tela_id)
    if grupos is None:
        grupos = grupos_da_tela(tela_id)
    t = POR_ID.get(tela_id)
    if t is not None and not t.grupos:
        return True          # aberta por desenho
    if not grupos:
        return False         # restrita e sem ninguém: só superusuário (acima)
    if request is not None:
        meus = getattr(request, "_acessos_grupos", None)
        if meus is None:
            meus = set(user.groups.values_list("name", flat=True))
            try:
                request._acessos_grupos = meus
            except Exception:
                pass
    else:
        meus = set(user.groups.values_list("name", flat=True))
    return bool(grupos & meus)


def porta(tela_id):
    """Condição pronta para o menu (config/settings/base.py).

    Devolve função, e o import do app acontece DENTRO dela: settings é
    carregado antes do registro de apps, e importar modelo ali estoura
    AppRegistryNotReady.
    """
    def condicao(request):
        from apps.orgs.acessos import pode_ver_tela  # noqa: F811 (lazy de propósito)
        return pode_ver_tela(request.user, tela_id, request=request)
    return condicao


def exigir(user, tela_id):
    """Barra na view. Mensagem que diz QUAL é a regra, não só 'proibido'."""
    from django.core.exceptions import PermissionDenied
    if pode_ver_tela(user, tela_id):
        return
    t = POR_ID.get(tela_id)
    grupos = sorted(grupos_da_tela(tela_id))
    raise PermissionDenied(
        "A tela %s é restrita a %s."
        % (t.nome if t else tela_id, ", ".join(grupos) or "superusuário")
    )
