"""
Assistente de ajuda do Patrimap — responde perguntas de quem está aprendendo a usar
o sistema, com passo a passo e link direto para a tela.

Por que NÃO é um LLM (por enquanto)
-----------------------------------
Este assistente funciona **offline, sem chave de API e sem custo por pergunta**:
casa a pergunta do usuário com uma base de tópicos escrita à mão, aqui neste
arquivo. Para um sistema interno com um domínio fechado (parque, chamados,
preventiva, estoque), isso responde melhor e mais rápido que um modelo genérico
— e nunca inventa um passo que não existe.

Se um dia quiser um LLM de verdade, o gancho está pronto: veja `responder()` e
a setting `ASSISTENTE_LLM` no fim do arquivo.

Como acrescentar um tópico
--------------------------
Some um dicionário em `TOPICOS`:

    {
        "id": "abrir-chamado",
        "titulo": "Como abrir um chamado",
        "secao": "Chamados",
        "perguntas": ["como abro um chamado", "máquina quebrou", ...],
        "passos": ["Abra o mapa…", "Clique na máquina…"],
        "url": "/parque/reparos/",
        "ajuda": "reparos",       # id da seção em /ajuda/
    }

`perguntas` são as formas como as pessoas de verdade perguntam — inclua gírias
e o jeito errado também ("travou", "não liga", "sumiu do mapa").
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Palavras que não ajudam a distinguir um tópico do outro.
_VAZIAS = {
    "a", "as", "o", "os", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "por", "para", "pra", "pro", "com", "sem", "que",
    "e", "ou", "se", "eu", "meu", "minha", "como", "onde", "qual", "quais",
    "quando", "quem", "faz", "fazer", "faço", "posso", "consigo", "preciso",
    "quero", "tem", "ter", "é", "ser", "está", "esta", "isso", "isto", "ao",
    "aos", "à", "às", "the", "of",
}


def _normalizar(texto):
    """minúsculas, sem acento, só letras/números/espaço."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9\s]+", " ", texto.lower())


def _palavras(texto):
    return {p for p in _normalizar(texto).split() if len(p) > 2 and p not in _VAZIAS}


# =============================================================================
# BASE DE CONHECIMENTO
# =============================================================================

TOPICOS = [
    {
        "id": "primeiro-acesso",
        "titulo": "Entrar no sistema pela primeira vez",
        "secao": "Acesso",
        "perguntas": [
            "primeiro acesso", "como entro no sistema", "não consigo logar",
            "login", "usuario e senha", "como faço para entrar", "acessar o sistema",
        ],
        "passos": [
            "Abra o sistema e use seu **usuário OU e-mail corporativo** — os dois funcionam.",
            "Se for seu primeiro acesso, use a senha que a TI entregou.",
            "O sistema pede uma senha nova na hora. Escolha uma que só você saiba.",
            "Pronto: a partir daí é sempre usuário/e-mail + a sua senha.",
        ],
        "url": "/admin/login/",
        "ajuda": "acesso",
    },
    {
        "id": "esqueci-senha",
        "titulo": "Esqueci minha senha",
        "secao": "Acesso",
        "perguntas": [
            "esqueci a senha", "perdi a senha", "recuperar senha", "resetar senha",
            "trocar senha", "mudar minha senha", "senha nova", "senha temporaria",
            "senha expirou", "nao lembro a senha",
        ],
        "passos": [
            "Na tela de login, clique em **Esqueceu sua senha?**",
            "Digite seu usuário ou e-mail e envie.",
            "Chega no e-mail cadastrado uma **senha temporária**, válida por 24 horas.",
            "Entre com ela — o sistema pede a senha definitiva na sequência.",
            "Se não chegar: só conseguimos enviar para o e-mail cadastrado na conta. "
            "Sem e-mail cadastrado, a TI gera a senha e entrega para você.",
        ],
        "url": "/admin/password_reset/",
        "ajuda": "acesso",
    },
    {
        "id": "abrir-chamado",
        "titulo": "Abrir um chamado (máquina com problema)",
        "secao": "Chamados",
        "perguntas": [
            "abrir chamado", "maquina quebrou", "computador com defeito", "pc travando",
            "travou", "travando", "esta lenta", "muito lenta", "nao liga", "desliga sozinho",
            "tela azul", "notebook nao liga", "chamar a ti", "reportar problema",
            "abrir ticket", "manutencao corretiva", "pedir conserto", "com problema",
            "com defeito", "parou de funcionar", "deu pau",
        ],
        "passos": [
            "Vá em **Chamados** no menu (ou abra o mapa da loja e clique na máquina).",
            "Use **Escanear máquina** para ler a etiqueta de patrimônio — é o jeito mais rápido.",
            "Descreva o problema com o que você VÊ acontecendo (ex.: “desliga sozinha ao abrir o sistema”).",
            "Envie. O chamado entra na coluna **Abertos** do quadro e a TI é notificada.",
        ],
        "url": "/parque/reparos/",
        "ajuda": "reparos",
    },
    {
        "id": "acompanhar-chamado",
        "titulo": "Acompanhar e finalizar um chamado",
        "secao": "Chamados",
        "perguntas": [
            "acompanhar chamado", "status do chamado", "quando fica pronto",
            "finalizar chamado", "fechar chamado", "chamado parado", "aguardando peca",
        ],
        "passos": [
            "O quadro de **Chamados** tem quatro colunas: Abertos → Aguardando peça → "
            "Em manutenção → Finalizados.",
            "Clique no cartão para ver o detalhe: quem está executando, prazo e registros.",
            "Quem tem permissão finaliza pelo botão **Finalizar** no próprio cartão.",
            "Ao finalizar, se o colaborador tinha ido para uma mesa temporária, ele volta "
            "automaticamente para a mesa dele.",
        ],
        "url": "/parque/reparos/",
        "ajuda": "reparos",
    },
    {
        "id": "preventiva",
        "titulo": "Fazer a manutenção preventiva",
        "secao": "Preventiva",
        "perguntas": [
            "preventiva", "manutencao preventiva", "limpeza da maquina", "60 dias",
            "preventiva vencida", "adiar preventiva", "pontos preventiva", "ranking",
        ],
        "passos": [
            "Toda máquina deve passar por preventiva a cada **60 dias**.",
            "Abra **Preventiva** no menu: a aba *Tarefas* mostra o que precisa de ação hoje.",
            "Concluiu a limpeza/checagem? Registre pelo botão de concluir — isso zera o "
            "contador da máquina e soma pontos no seu ranking do mês.",
            "Não vai dar para fazer no prazo? Peça **adiamento** com data e justificativa — "
            "o supervisor aprova ou nega.",
        ],
        "url": "/parque/preventiva/",
        "ajuda": "preventiva",
    },
    {
        "id": "transferir-maquina",
        "titulo": "Transferir uma máquina entre lojas ou setores",
        "secao": "Transferências",
        "perguntas": [
            "transferir maquina", "mover computador", "trocar de loja", "mudar de setor",
            "transferencia entre lojas", "levar pc para outra loja", "movimentacao interna",
            "trocar pcs de lugar",
        ],
        "passos": [
            "Abra o **mapa** da loja de origem.",
            "**Arraste a máquina** para o destino (outro setor, outra mesa) ou use o "
            "caminhão para enviar a outra loja.",
            "Confirme o destino e a tarefa do Bitrix quando pedida.",
            "Quem tem permissão de gestão aplica na hora; quem não tem, envia para "
            "autorização — a solicitação aparece em **Aprovações**.",
            "Depois de aplicada, o sistema gera o **protocolo** para imprimir e assinar.",
        ],
        "url": "/parque/transferencias/",
        "ajuda": "transferencias",
    },
    {
        "id": "aprovacoes",
        "titulo": "Aprovar transferências e movimentações pendentes",
        "secao": "Transferências",
        "perguntas": [
            "aprovar transferencia", "autorizar movimentacao", "aprovacoes pendentes",
            "negar transferencia", "fila de aprovacao", "quem aprova",
        ],
        "passos": [
            "Abra **Aprovações** (ou clique no aviso do sino de notificações).",
            "Cada pedido mostra origem, destino, máquina e quem solicitou.",
            "**Autorizar** aplica a movimentação de verdade; **Negar** pede o motivo.",
            "Só Gerente e Supervisor decidem. A decisão fica registrada com data e autor.",
        ],
        "url": "/parque/aprovacoes/",
        "ajuda": "transferencias",
    },
    {
        "id": "estoque-pecas",
        "titulo": "Consultar e transferir peças do estoque",
        "secao": "Estoque",
        "perguntas": [
            "estoque de pecas", "quantas memorias tem", "transferir peca", "pedir peca",
            "montar caixa", "remessa de pecas", "perifericos",
        ],
        "passos": [
            "**Estoque › Periféricos** lista as peças por unidade, com a quantidade.",
            "Para enviar peça a outra loja, abra a peça e use **Transferir**: informe "
            "quantidade, destino e a tarefa do Bitrix.",
            "Vai enviar várias peças juntas? Use **Montar caixa** — sai um protocolo único "
            "com todos os itens.",
            "O sistema não deixa transferir mais do que existe em estoque.",
        ],
        "url": "/parque/tabela-pecas/",
        "ajuda": "estoque",
    },
    {
        "id": "etiquetas",
        "titulo": "Gerar etiqueta de patrimônio",
        "secao": "Estoque",
        "perguntas": [
            "etiqueta", "patrimonio", "imprimir etiqueta", "codigo da maquina",
            "qr code da maquina", "colar etiqueta",
        ],
        "passos": [
            "Todo computador e notebook recebe um patrimônio automático (ex.: PC-C0012).",
            "Abra **Etiquetas** no menu do parque, escolha as máquinas e gere a folha.",
            "Imprima em folha adesiva e cole na máquina — a etiqueta é o que o "
            "**Escanear máquina** lê para abrir chamado em segundos.",
        ],
        "url": "/parque/etiquetas/",
        "ajuda": "estoque",
    },
    {
        "id": "notebook-termo",
        "titulo": "Entregar um notebook e gerar o termo de responsabilidade",
        "secao": "Notebooks",
        "perguntas": [
            "termo de responsabilidade", "entregar notebook", "atribuir notebook",
            "notebook para colaborador", "assinatura do termo",
        ],
        "passos": [
            "Abra **Notebooks** e atribua o equipamento ao colaborador.",
            "Use **Gerar termo** — sai o documento com os dados do equipamento e do colaborador.",
            "Imprima, colha a assinatura e guarde o documento digitalizado no cadastro.",
        ],
        "url": "/parque/mapa-notebooks/",
        "ajuda": "notebooks",
    },
    {
        "id": "assistencia-externa",
        "titulo": "Enviar equipamento para a assistência (autorizada)",
        "secao": "Assistência",
        "perguntas": [
            "assistencia externa", "autorizada", "mandar para garantia", "enviar para conserto",
            "rma", "garantia do fabricante",
        ],
        "passos": [
            "Abra **Assistência externa** e clique em enviar.",
            "Escolha o equipamento, a autorizada e anexe a OS/nota quando houver.",
            "Acompanhe pelo quadro: Enviado → Em análise → Aguardando aprovação → "
            "Em reparo → Retornando → Finalizado.",
            "Cada envio gera protocolo para acompanhar a máquina fora da empresa.",
        ],
        "url": "/parque/autorizadas/",
        "ajuda": "assistencia",
    },
    {
        "id": "score",
        "titulo": "Entender o score / índice de desempenho da máquina",
        "secao": "Desempenho",
        "perguntas": [
            "score", "indice de desempenho", "maquina critica", "nota da maquina",
            "por que a maquina esta critica", "classificacao otimo bom baixo critico",
        ],
        "passos": [
            "O score de 0 a 100 combina processador, memória, disco e o histórico de reparos.",
            "As faixas são: **Crítico**, **Baixo**, **Bom** e **Ótimo**.",
            "Com o agente de telemetria instalado, o score usa a configuração REAL da "
            "máquina em vez do que foi digitado no cadastro.",
            "Máquina crítica aparece em destaque na Início e no mapa — é candidata a "
            "upgrade ou troca.",
        ],
        "url": "/parque/mapa-score/",
        "ajuda": "desempenho",
    },
    {
        "id": "telemetria",
        "titulo": "Instalar o agente de telemetria numa máquina",
        "secao": "Telemetria",
        "perguntas": [
            "agente", "telemetria", "instalar agente", "coleta automatica",
            "maquina sem telemetria", "score real", "monitoramento",
        ],
        "passos": [
            "Abra **Agente e telemetria** e baixe o instalador (Windows ou Linux).",
            "Rode na máquina do colaborador — ele coleta a configuração e envia sozinho.",
            "A máquina aparece na lista de coletas; se não casar automaticamente pelo "
            "patrimônio, use **Vincular** para ligar a coleta ao equipamento certo.",
            "Sem telemetria, o score usa só o que foi digitado no cadastro.",
        ],
        "url": "/parque/agente/",
        "ajuda": "telemetria",
    },
    {
        "id": "mapa",
        "titulo": "Usar o mapa da loja",
        "secao": "Parque",
        "perguntas": [
            "mapa da loja", "planta", "onde fica a maquina", "achar computador",
            "baia", "mesa", "setor", "quem senta onde",
        ],
        "passos": [
            "**Unidade › Setor › Baia**: a baia é a mesa, e cada baia tem um dispositivo "
            "(um computador OU um notebook) e um colaborador.",
            "Clique numa máquina para ver as specs, o histórico e abrir chamado.",
            "Use a busca do mapa para achar por nome, patrimônio ou número de série.",
            "Arraste para mover a máquina de mesa, de setor ou de loja.",
        ],
        "url": "/parque/mapa-completo/",
        "ajuda": "parque",
    },
    {
        "id": "permissoes",
        "titulo": "O que cada cargo pode fazer",
        "secao": "Permissões",
        "perguntas": [
            "permissao", "nao tenho acesso", "acesso negado", "cargo", "grupo",
            "por que nao consigo", "quem pode aprovar", "perfil de usuario",
        ],
        "passos": [
            "O que você pode fazer vem do **cargo** (grupo), não de permissões soltas.",
            "Gerente e Supervisor decidem transferências, movimentações e adiamentos.",
            "Técnico registra chamados e preventivas.",
            "Se uma tela disser *acesso negado*, é o cargo — peça à TI para revisar o seu.",
        ],
        "url": "/parque/acessos/",
        "ajuda": "papeis",
    },
    {
        "id": "notificacoes",
        "titulo": "Notificações e o sino",
        "secao": "Avisos",
        "perguntas": [
            "notificacao", "sino", "avisos", "nao recebi aviso", "limpar notificacoes",
        ],
        "passos": [
            "O sino no topo mostra o que precisa da sua atenção: aprovações, garantias "
            "vencendo, preventivas atrasadas.",
            "Alguns avisos trazem os botões **Aprovar/Negar** direto no sino.",
            "Marcar todas como lidas limpa a lista sem apagar o histórico.",
        ],
        "url": "/admin/",
        "ajuda": "avisos",
    },
    {
        "id": "orcamento",
        "titulo": "Orçamentos de reparo",
        "secao": "Orçamentos",
        "perguntas": [
            "orcamento", "aprovar orcamento", "custo do reparo", "valor do conserto",
        ],
        "passos": [
            "Quando um chamado precisa de peça paga, é aberto um **orçamento**.",
            "A lista de Orçamentos mostra o valor, a máquina e o chamado de origem.",
            "Gerente e Supervisor aprovam ou negam; a decisão volta para o chamado.",
        ],
        "url": "/orcamentos/",
        "ajuda": "orcamentos",
    },
    {
        "id": "tema-escuro",
        "titulo": "Trocar entre tema claro e escuro",
        "secao": "Dicas",
        "perguntas": [
            "tema escuro", "modo escuro", "dark mode", "tela clara", "mudar cor do sistema",
        ],
        "passos": [
            "O seletor de tema fica no canto superior direito.",
            "Escolha Claro, Escuro ou Sistema (acompanha a configuração do computador).",
            "A escolha fica salva no seu navegador.",
        ],
        "url": "/admin/",
        "ajuda": "dicas",
    },
]

# Índice invertido simples: palavra → ids de tópico. Montado uma vez, no import.
_INDICE = {}
for _t in TOPICOS:
    _base = " ".join([_t["titulo"], _t["secao"], " ".join(_t["perguntas"])])
    for _p in _palavras(_base):
        _INDICE.setdefault(_p, set()).add(_t["id"])

_POR_ID = {t["id"]: t for t in TOPICOS}


def buscar(pergunta, limite=3):
    """Tópicos que melhor respondem à pergunta, do mais provável ao menos.

    Pontuação: quantas palavras da pergunta batem, com peso extra quando a
    pergunta inteira aparece como uma das formas cadastradas.
    """
    palavras = _palavras(pergunta)
    if not palavras:
        return []

    normal = _normalizar(pergunta).strip()
    pontos = {}
    for palavra in palavras:
        for tid in _INDICE.get(palavra, ()):
            pontos[tid] = pontos.get(tid, 0) + 1
        # Casamento por prefixo ajuda com plural e digitação parcial
        # ("chamad", "preventiv") sem precisar de stemmer.
        if len(palavra) >= 5:
            for chave, ids in _INDICE.items():
                if chave.startswith(palavra[:5]) and chave != palavra:
                    for tid in ids:
                        pontos[tid] = pontos.get(tid, 0) + 0.5

    for tid, topico in _POR_ID.items():
        for forma in topico["perguntas"]:
            forma_n = _normalizar(forma).strip()
            if forma_n and (forma_n in normal or normal in forma_n):
                pontos[tid] = pontos.get(tid, 0) + 4

    ordenados = sorted(pontos.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        dict(_POR_ID[tid], pontuacao=round(nota, 1))
        for tid, nota in ordenados[:limite]
        if nota >= 1
    ]


def sugestoes(quantidade=6):
    """Perguntas de partida, para quem abre o assistente sem saber o que pedir."""
    destaques = [
        "esqueci-senha", "abrir-chamado", "preventiva",
        "transferir-maquina", "mapa", "estoque-pecas",
    ]
    return [
        {"id": tid, "titulo": _POR_ID[tid]["titulo"]}
        for tid in destaques[:quantidade] if tid in _POR_ID
    ]


def indice():
    """Todos os assuntos, agrupados por seção — o 'sumário' do assistente.

    Existe porque o menu "Ajuda" saiu do sistema: quem quer NAVEGAR em vez de
    perguntar precisa de uma lista completa aqui dentro.
    """
    por_secao = {}
    for t in TOPICOS:
        por_secao.setdefault(t["secao"], []).append(
            {"id": t["id"], "titulo": t["titulo"]}
        )
    return [
        {"secao": secao, "itens": itens}
        for secao, itens in sorted(por_secao.items())
    ]


def responder(pergunta):
    """Resposta pronta para a interface.

    GANCHO PARA LLM — se um dia houver chave de API, é aqui: chame o modelo
    passando os tópicos de `buscar()` como contexto e devolva o texto dele em
    `resposta_livre`, mantendo `topicos` como fonte citável. A interface já
    exibe os dois. Sugestão de setting: ASSISTENTE_LLM = "claude-…".
    """
    achados = buscar(pergunta)
    if not achados:
        logger.info("Assistente sem resposta para: %r", (pergunta or "")[:120])
    return {
        "pergunta": pergunta,
        "topicos": achados,
        "sugestoes": sugestoes() if not achados else [],
        "resposta_livre": None,
    }
