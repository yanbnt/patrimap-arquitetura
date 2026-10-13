"""
Gera a tradução pt-BR do projeto (cobre as strings do django-unfold, que não
vem traduzido) sem depender do GNU gettext (msgfmt) — útil no Windows.

Uso:
    python locale/_build_pt_br.py

Escreve:
    locale/pt_BR/LC_MESSAGES/django.po   (legível, para edição)
    locale/pt_BR/LC_MESSAGES/django.mo   (binário, lido pelo Django)

Para adicionar/ajustar uma tradução, edite o dicionário TRADUCOES abaixo e rode
o script de novo. Depois reinicie o servidor.
"""

import os
import struct

AQUI = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(AQUI, "pt_BR", "LC_MESSAGES")

# msgid (texto original em inglês do unfold/Django) -> tradução pt-BR.
TRADUCOES = {
    "Action": "Ação",
    "Add": "Adicionar",
    "Add row": "Adicionar linha",
    "After you": "Depois de você",
    "All applications": "Todas as aplicações",
    "Apply Filters": "Aplicar filtros",
    "Cancel": "Cancelar",
    "Change": "Alterar",
    "Change password": "Alterar senha",
    "Choose file to upload": "Escolher arquivo para enviar",
    "Clear": "Limpar",
    "Clear all filters": "Limpar todos os filtros",
    "Clear selection": "Limpar seleção",
    "Click here to select the objects across all pages":
        "Clique aqui para selecionar os objetos de todas as páginas",
    "Click to cancel": "Clique para cancelar",
    "Click to download": "Clique para baixar",
    "Close": "Fechar",
    "Dark": "Escuro",
    "Date/time": "Data/hora",
    "Delete": "Excluir",
    "Expand row": "Expandir linha",
    "False": "Não",
    "Filter navigation items": "Filtrar itens de navegação",
    "Filters": "Filtros",
    "Forgotten your password or username?":
        "Esqueceu sua senha ou nome de usuário?",
    "General": "Geral",
    "Go back": "Voltar",
    "Hide counts": "Ocultar contagens",
    "History": "Histórico",
    "Home": "Início",
    "Image preview": "Pré-visualização da imagem",
    "Light": "Claro",
    "Log in": "Entrar",
    "Log in again": "Entrar novamente",
    "Log out": "Sair",
    "More actions": "Mais ações",
    "Navigate": "Navegar",
    "Next": "Próximo",
    "No data": "Sem dados",
    "No results found": "Nenhum resultado encontrado",
    "No, take me back": "Não, voltar",
    "Nothing matched your search": "Nada corresponde à sua busca",
    "Objects": "Objetos",
    "Please enter your old password, for security’s sake, and then enter "
    "your new password twice so we can verify you typed it in correctly.":
        "Digite sua senha atual, por segurança, e depois a nova senha duas "
        "vezes para confirmarmos que foi digitada corretamente.",
    "Previous": "Anterior",
    "Recent actions": "Ações recentes",
    "Recent searches": "Buscas recentes",
    "Record picture": "Foto do registro",
    "Remove": "Remover",
    "Remove from sorting": "Remover da ordenação",
    "Reset filters": "Redefinir filtros",
    "Return to site": "Voltar ao site",
    "Run": "Executar",
    "Run the selected action": "Executar a ação selecionada",
    "Save": "Salvar",
    "Save and add another": "Salvar e adicionar outro(a)",
    "Save and continue editing": "Salvar e continuar editando",
    "Save and view": "Salvar e visualizar",
    "Save as new": "Salvar como novo",
    "Search apps and models...": "Buscar apps e modelos...",
    "Select": "Selecionar",
    "Select all rows": "Selecionar todas as linhas",
    "Select value": "Selecione…",
    "Select action": "Selecionar ação",
    "Select action to run": "Selecione a ação",
    "Select record": "Selecionar registro",
    "Select currency": "Selecionar moeda",
    "Select format": "Selecionar formato",
    "All": "Todos",
    "Value": "Valor",
    "Date from": "Data de",
    "Date to": "Data até",
    "Dataset not found. No action performed.":
        "Conjunto de dados não encontrado. Nenhuma ação executada.",
    "You can not create nested object without parent":
        "Não é possível criar um objeto aninhado sem o item pai.",
    "Show all": "Mostrar tudo",
    "Show counts": "Mostrar contagens",
    "Submit": "Enviar",
    "Summary": "Resumo",
    "System": "Sistema",
    "Thanks for spending some quality time with the web site today.":
        "Obrigado por usar o sistema hoje.",
    "This item will be deleted.": "Este item será excluído.",
    "This object doesn’t have a change history. It probably wasn’t "
    "added via this admin site.":
        "Este objeto não possui histórico de alterações. Provavelmente não foi "
        "adicionado por este painel.",
    "This page yielded into no results. Create a new item or reset your "
    "filters.":
        "Esta página não retornou resultados. Crie um novo item ou redefina "
        "os filtros.",
    "Toggle password visibility": "Mostrar/ocultar senha",
    "Toggle sorting": "Alternar ordenação",
    "True": "Sim",
    "Type to search": "Digite para buscar",
    "Unknown": "Desconhecido",
    "Unknown content": "Conteúdo desconhecido",
    "User": "Usuário",
    "View": "Ver",
    "View on site": "Ver no site",
    "View site": "Ver site",
    "Yes, I’m sure": "Sim, tenho certeza",
    "You don’t have permission to view or edit anything.":
        "Você não tem permissão para ver ou editar nada.",
    "You have been successfully logged out from the administration":
        "Você saiu da administração com sucesso.",
    "Your password was changed.": "Sua senha foi alterada.",
}

CABECALHO_PO = (
    'msgid ""\n'
    'msgstr ""\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"\n'
    '"Content-Transfer-Encoding: 8bit\\n"\n'
    '"Language: pt_BR\\n"\n\n'
)


def _po_escape(texto):
    return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def escrever_po(caminho):
    linhas = [CABECALHO_PO]
    for msgid in sorted(TRADUCOES):
        linhas.append(f'msgid "{_po_escape(msgid)}"\n')
        linhas.append(f'msgstr "{_po_escape(TRADUCOES[msgid])}"\n\n')
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("".join(linhas))


def escrever_mo(caminho):
    # Inclui a entrada vazia com os metadados (charset).
    catalogo = {"": "Content-Type: text/plain; charset=UTF-8\n"}
    catalogo.update(TRADUCOES)

    chaves = sorted(catalogo.keys())
    ids, strs = b"", b""
    deslocamentos = []
    for k in chaves:
        kb = k.encode("utf-8")
        vb = catalogo[k].encode("utf-8")
        deslocamentos.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\x00"
        strs += vb + b"\x00"

    n = len(chaves)
    inicio_chaves = 7 * 4 + 16 * n
    inicio_valores = inicio_chaves + len(ids)
    koff, voff = [], []
    for o1, l1, o2, l2 in deslocamentos:
        koff += [l1, o1 + inicio_chaves]
        voff += [l2, o2 + inicio_valores]

    out = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    out += struct.pack("i" * len(koff), *koff)
    out += struct.pack("i" * len(voff), *voff)
    out += ids + strs
    with open(caminho, "wb") as f:
        f.write(out)


def main():
    os.makedirs(DEST, exist_ok=True)
    escrever_po(os.path.join(DEST, "django.po"))
    escrever_mo(os.path.join(DEST, "django.mo"))
    print(f"OK — {len(TRADUCOES)} traducoes escritas em {DEST}")


if __name__ == "__main__":
    main()
