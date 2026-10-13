"""Roteamento de URLs do Patrimap — gestão de ativos de TI da Make Distribuidora."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import (
    path, re_path, register_converter, reverse, reverse_lazy,
)
from django.utils.http import url_has_allowed_host_and_scheme

from apps.notificacoes.views import abrir as notif_abrir
from apps.notificacoes.views import marcar_todas as notif_marcar_todas
from apps.notificacoes.views import excluir as notif_excluir
from apps.notificacoes.views import limpar as notif_limpar
from apps.dashboard import dashboard_completo
from apps.parque.arquivo import arquivo_anexar, arquivo_central, arquivo_validar
from apps.parque.mural import (inicio, mural, mural_apagar_comentario,
                               mural_apagar_publicacao, mural_comentar,
                               mural_conversa, mural_editar_publicacao,
                               mural_lista, mural_mandar, mural_marcar,
                               mural_publicar)
from apps.parque.executivo import leitura_executiva
from apps.orcamentos.views import orcamentos_lista, decidir_orcamento
from apps.orgs.views_acessos import (
    acessos, acessos_criar_grupo, acessos_excluir_grupo,
    acessos_salvar_grupo, acessos_salvar_pessoa,
)
from apps.orgs.views import (
    recuperar_senha, redefinir_senha_colaborador, TrocarSenhaView,
)
from apps.orgs.views_conta import conta_ativar, conta_criar, conta_desativar
from apps.parque.views import (
    cadastros_hub,
    abrir_chamado,
    assistente_perguntar, alocar_computador_baia, alocar_notebook_baia, aprovacoes_pendentes,
    atribuir_colaborador_baia, atribuir_notebook, remover_dispositivo_baia,
    baia_specs, chamado_de_computador, chamado_detalhe, chamado_realocar,
    desativar_para_troca, remover_colaborador_baia,
    decidir_solicitacao, decidir_transferencia, decidir_transferencia_notebook,
    etiquetas_patrimonio, finalizar_reparo, agenda_eventos, logs_unificados, setor_criar,
    finalizar_reparo_admin, gerar_termo_notebook, termo_imprimir, media_protegida,
    abrir_chamado_notebook, escanear_chamado, resolver_patrimonio, telemetria_ingest,
    agente_baixar, agente_baixar_linux, agente_pagina, agente_este_computador,
    local_ignorar, telemetria_vincular,
    mapa_completo, mapa_criticos, mapa_loja, mapa_notebooks,
    mapa_situacao, mapa_score, mapa_preventiva, estoque_hub,
    tabela_computadores, tabela_notebooks, tabela_pecas, tabela_estoque_computadores,
    fora_de_uso,
    excluir_dispositivos, montar_caixa, mover_baia,
    protocolo_notebook, protocolo_peca, protocolo_remessa, protocolo_transferencia,
    proximo_patrimonio_preview, reativar_computador, remover_notebook_colaborador,
    reparos_kanban, preventiva_kanban, preventiva_registros, registrar_preventiva, tarefa_acao, setores_lista, transferencia_lojas,
    grupo_criar, grupo_detalhe, grupo_editar_membros, grupo_concluir_todos, grupo_excluir,
    solicitar_adiamento, decidir_adiamento,
    excluir_transferencia, excluir_transferencias_lote, transferencia_notebooks,
    transferencias_todas, transferir_entre_lojas, transferir_notebook_entre_lojas,
    transferir_peca, trocar_pcs,
    enviar_autorizada, autorizadas_kanban, envio_autorizada_detalhe, protocolo_autorizada,
)

# 403 amigável: em vez da página crua "403 Forbidden", quem está logado é levado
# ao dashboard com o toast "Acesso negado" (mesmo do bloqueio de Usuários/Grupos).
def acesso_negado(request, exception=None):
    if getattr(request, "user", None) and request.user.is_authenticated and request.user.is_staff:
        return redirect(reverse("admin:index") + "?negado=1")
    return HttpResponseForbidden("Acesso negado.")


handler403 = "config.urls.acesso_negado"


# ---------------------------------------------------------------------------
# ID GIGANTE NA URL VIRA 404, NÃO 500
#
# `<int:pk>` aceita qualquer sequência de dígitos, e o SQLite estoura com
# OverflowError acima de 8 bytes: /parque/mapa-criticos/99999999999999999999/
# dava erro de servidor. São 26 rotas com id, e corrigir uma por uma deixaria a
# 27ª de fora — então o conserto é no conversor, que é o lugar por onde todas
# passam. `to_python` levantando ValueError faz a URL simplesmente NÃO CASAR,
# e o Django responde 404, que é a verdade: não existe registro com esse id.
# ---------------------------------------------------------------------------
class IntDoBanco:
    regex = "[0-9]+"
    LIMITE = 9223372036854775807

    def to_python(self, value):
        n = int(value)
        if n > self.LIMITE:
            raise ValueError("id acima do que o banco guarda")
        return n

    def to_url(self, value):
        return str(value)


register_converter(IntDoBanco, "int")


def voltar_ou_dashboard(request, *args, **kwargs):
    """Intercepta as 'app index' do admin (lista crua de modelos) e volta para a
    tela anterior do usuário (ou o dashboard) — em vez daquela página estranha."""
    ref = request.META.get("HTTP_REFERER") or ""
    # Cadastro de Autorizada / Envio → sempre o quadro "Assistência externa"
    # (evita o "voltar inteligente" jogar o usuário no mapa de computadores).
    if "/admin/parque/autorizada" in ref or "/admin/parque/envioautorizada" in ref:
        return redirect("/parque/autorizadas/")
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()}):
        # Evita laço se o referer for a própria app index.
        if "/admin/" not in ref or ref.rstrip("/").split("/")[-1] not in {"parque", "orgs", "orcamentos", "auth"}:
            return redirect(ref)
    return redirect("admin:index")

# Branding do admin (back-office principal do sistema).
admin.site.site_header = "Patrimap · Make Distribuidora"
admin.site.site_title = "Patrimap"
admin.site.index_title = "Gestão de Ativos de TI"
# Remove o link "Voltar ao site" / "Ver site" do admin e da tela de login.
admin.site.site_url = None
# Login aceita usuário OU e-mail (backend em apps.orgs.backends + rótulo do campo).
from apps.orgs.forms import LoginUsuarioOuEmailForm  # noqa: E402
admin.site.login_form = LoginUsuarioOuEmailForm


urlpatterns = [
    # Raiz → vai para o sistema (admin); se não estiver logado, cai no login.
    path("", lambda request: redirect("admin:index")),
    # Tela "Dashboard" (gráficos analíticos) — separada da "Início".
    path("dashboard/", dashboard_completo, name="dashboard_completo"),
    # Recuperação de senha por e-mail (link "Esqueci a senha" no login):
    # envia uma SENHA TEMPORÁRIA; o usuário troca obrigatoriamente após entrar.
    path("admin/password_reset/", recuperar_senha, name="admin_password_reset"),
    path("admin/password_reset/done/", auth_views.PasswordResetDoneView.as_view(),
         name="password_reset_done"),
    # Tela de definir nova senha (forçada após login com senha temporária).
    path("trocar-senha/", TrocarSenhaView.as_view(), name="trocar_senha"),
    # As "app index" do admin (lista de modelos) voltam p/ a tela anterior.
    path("admin/parque/", voltar_ou_dashboard),
    path("admin/orgs/", voltar_ou_dashboard),
    path("admin/orcamentos/", voltar_ou_dashboard),
    path("admin/auth/", voltar_ou_dashboard),
    path("orcamentos/", orcamentos_lista, name="orcamentos_lista"),
    path("orcamentos/<int:pk>/<str:acao>/", decidir_orcamento, name="orcamentos_decidir"),
    # A LISTA antiga do admin (changelist) some: vai para a nova tabela uniforme.
    path("admin/parque/baia/", lambda r: redirect("/parque/tabela-computadores/")),
    path("admin/parque/notebook/", lambda r: redirect("/parque/tabela-notebooks/")),
    path("admin/parque/peca/", lambda r: redirect("/parque/tabela-pecas/")),
    path("admin/parque/computador/", lambda r: redirect("/parque/tabela-estoque-computadores/")),
    path("admin/parque/telemetriamaquina/", lambda r: redirect("/parque/agente/")),
    path("admin/parque/reparo/", lambda r: redirect("/parque/reparos/")),
    path("admin/parque/setor/", lambda r: redirect("/parque/setores/")),
    # Autorizada / Envio: a "lista" é o quadro Assistência externa (não o admin cru).
    path("admin/parque/autorizada/", lambda r: redirect("/parque/autorizadas/")),
    path("admin/parque/envioautorizada/", lambda r: redirect("/parque/autorizadas/")),
    # Colaborador e Loja ficaram de fora desta lista quando a Central de
    # Cadastros nasceu, e o buraco aparecia no caminho mais comum: quem abria
    # uma ficha em /cadastros/, clicava em "Editar dados" e depois voltava caía
    # na CHANGELIST CRUA do admin — outra tela, com outras colunas e outro
    # visual, para o mesmo dado que acabara de ver. Relatado pelo Jonas em
    # 30/09/2026. O `?aba=` leva de volta à aba de onde a pessoa saiu.
    path("admin/orgs/person/", lambda r: redirect("/cadastros/?aba=colab")),
    path("admin/orgs/location/", lambda r: redirect("/cadastros/?aba=loja")),
    path("admin/", admin.site.urls),
    path("parque/mapa/<int:unidade_id>/", mapa_loja, name="parque_mapa"),
    path("parque/mapa-situacao/<str:status>/", mapa_situacao, name="parque_mapa_situacao"),
    # LEITURA EXECUTIVA — a tela de diretoria e RH (apps/parque/executivo.py).
    path("parque/leitura-executiva/", leitura_executiva, name="parque_executivo"),
    # ARQUIVO DO PATRIMÔNIO — todo documento do parque, e o que falta.
    # A tela é de leitura + duas ações que ALTERAM (anexar e validar), por isso
    # as duas são POST separado, com permissão própria (arquivo.py).
    path("parque/arquivo/", arquivo_central, name="parque_arquivo"),
    path("parque/arquivo/anexar/", arquivo_anexar, name="parque_arquivo_anexar"),
    path("parque/arquivo/validar/", arquivo_validar, name="parque_arquivo_validar"),

    # USUÁRIOS E ACESSOS — uma tela no lugar de três (lista de usuários, lista
    # de grupos e o mapa grupo→tela, que não tinha tela nenhuma).
    # As duas gravações são POST separado porque têm permissões diferentes:
    # pessoa↔grupo para quem abre a tela, grupo→tela só para superusuário.
    path("parque/acessos/", acessos, name="orgs_acessos"),
    path("parque/acessos/pessoa/", acessos_salvar_pessoa, name="orgs_acessos_pessoa"),
    path("parque/acessos/grupo/", acessos_salvar_grupo, name="orgs_acessos_grupo"),
    path("parque/acessos/grupo/novo/", acessos_criar_grupo, name="orgs_acessos_criar"),
    path("parque/acessos/grupo/excluir/", acessos_excluir_grupo, name="orgs_acessos_excluir"),
    path("parque/mapa-completo/", mapa_completo, name="parque_mapa_completo"),
    path("parque/mapa-notebooks/", mapa_notebooks, name="parque_mapa_notebooks"),
    path("parque/mapa-score/", mapa_score, name="parque_mapa_score"),
    path("parque/mapa-preventiva/", mapa_preventiva, name="parque_mapa_preventiva"),
    path("parque/estoque/", estoque_hub, name="parque_estoque"),
    path("parque/tabela-computadores/", tabela_computadores, name="parque_tabela_computadores"),
    path("parque/tabela-notebooks/", tabela_notebooks, name="parque_tabela_notebooks"),
    path("parque/tabela-pecas/", tabela_pecas, name="parque_tabela_pecas"),
    path("parque/tabela-estoque-computadores/", tabela_estoque_computadores, name="parque_tabela_estoque_computadores"),
    path("parque/fora-de-uso/", fora_de_uso, name="parque_fora_de_uso"),
    path("parque/excluir-dispositivos/", excluir_dispositivos, name="parque_excluir_dispositivos"),
    path("parque/mapa-criticos/", mapa_criticos, name="parque_mapa_criticos"),
    path("parque/mapa-criticos/<int:unidade_id>/", mapa_criticos, name="parque_mapa_criticos_unidade"),
    path("parque/etiquetas/", etiquetas_patrimonio, name="parque_etiquetas"),
    path("parque/mover-baia/", mover_baia, name="parque_mover_baia"),
    path("parque/trocar-pcs/", trocar_pcs, name="parque_trocar_pcs"),
    path("parque/transferencia-lojas/", transferencia_lojas, name="parque_transferencia_lojas"),
    path("parque/transferencia-lojas/<int:unidade_id>/", transferencia_lojas, name="parque_transferencia_lojas_unidade"),
    path("parque/transferir-entre-lojas/", transferir_entre_lojas, name="parque_transferir_entre_lojas"),
    path("parque/protocolo-transferencia/<int:pk>/", protocolo_transferencia, name="parque_protocolo_transferencia"),
    path("parque/transferencia-notebooks/", transferencia_notebooks, name="parque_transferencia_notebooks"),
    path("parque/transferir-notebook/", transferir_notebook_entre_lojas, name="parque_transferir_notebook"),
    path("parque/protocolo-notebook/<int:pk>/", protocolo_notebook, name="parque_protocolo_notebook"),
    path("parque/atribuir-notebook/", atribuir_notebook, name="parque_atribuir_notebook"),
    path("parque/remover-notebook-colaborador/", remover_notebook_colaborador, name="parque_remover_notebook_colaborador"),
    path("parque/gerar-termo-notebook/", gerar_termo_notebook, name="parque_gerar_termo_notebook"),
    path("parque/termo/<int:pk>/", termo_imprimir, name="parque_termo_imprimir"),
    path("parque/atribuir-colaborador-baia/", atribuir_colaborador_baia, name="parque_atribuir_colaborador_baia"),
    path("parque/remover-colaborador-baia/", remover_colaborador_baia, name="parque_remover_colaborador_baia"),
    path("parque/alocar-computador-baia/", alocar_computador_baia, name="parque_alocar_computador_baia"),
    path("parque/alocar-notebook-baia/", alocar_notebook_baia, name="parque_alocar_notebook_baia"),
    path("parque/remover-dispositivo-baia/", remover_dispositivo_baia, name="parque_remover_dispositivo_baia"),
    path("parque/desativar-para-troca/", desativar_para_troca, name="parque_desativar_para_troca"),
    path("parque/chamado-detalhe/<int:pk>/", chamado_detalhe, name="parque_chamado_detalhe"),
    path("parque/chamado/<int:pk>/realocar/", chamado_realocar, name="parque_chamado_realocar"),
    path("parque/chamado-notebook/<int:pk>/", abrir_chamado_notebook, name="parque_abrir_chamado_notebook"),
    path("parque/escanear-chamado/", escanear_chamado, name="parque_escanear_chamado"),
    path("parque/resolver-patrimonio/", resolver_patrimonio, name="parque_resolver_patrimonio"),
    # Ingestão de telemetria do agente (POST JSON + token no header; sem sessão).
    path("api/telemetria/", telemetria_ingest, name="telemetria_ingest"),
    path("parque/agente/", agente_pagina, name="parque_agente"),
    path("parque/agente/baixar/", agente_baixar, name="parque_agente_baixar"),
    path("parque/agente/baixar-linux/", agente_baixar_linux, name="parque_agente_baixar_linux"),
    path("parque/agente/ignorar/<int:pk>/", local_ignorar, name="parque_local_ignorar"),
    path("parque/agente/vincular/<int:pk>/", telemetria_vincular, name="parque_telemetria_vincular"),
    path("parque/agente/este-computador/", agente_este_computador, name="parque_agente_este"),
    path("parque/reativar/<int:pk>/", reativar_computador, name="parque_reativar_computador"),
    path("parque/peca/<int:pk>/transferir/", transferir_peca, name="parque_transferir_peca"),
    path("parque/protocolo-peca/<int:pk>/", protocolo_peca, name="parque_protocolo_peca"),
    path("parque/transferencias/", transferencias_todas, name="parque_transferencias"),
    path("parque/transferencias/excluir/", excluir_transferencia, name="parque_excluir_transferencia"),
    path("parque/transferencias/excluir-lote/", excluir_transferencias_lote, name="parque_excluir_transferencias_lote"),
    path("parque/montar-caixa/", montar_caixa, name="parque_montar_caixa"),
    path("parque/protocolo-remessa/<int:pk>/", protocolo_remessa, name="parque_protocolo_remessa"),
    # Envio para autorizada / assistência externa
    path("parque/autorizadas/", autorizadas_kanban, name="parque_autorizadas_kanban"),
    path("parque/autorizadas/enviar/", enviar_autorizada, name="parque_enviar_autorizada"),
    path("parque/autorizadas/envio/<int:pk>/editar/", enviar_autorizada, name="parque_editar_autorizada"),
    path("parque/autorizadas/envio/<int:pk>/", envio_autorizada_detalhe, name="parque_envio_autorizada_detalhe"),
    path("parque/autorizadas/protocolo/<int:pk>/", protocolo_autorizada, name="parque_protocolo_autorizada"),
    path("parque/chamado-computador/<int:pk>/<str:tipo>/", chamado_de_computador, name="parque_chamado_computador"),
    path("parque/baia-specs/<int:pk>/", baia_specs, name="parque_baia_specs"),
    path("parque/proximo-patrimonio/", proximo_patrimonio_preview, name="parque_proximo_patrimonio"),
    path("parque/reparos/", reparos_kanban, name="parque_reparos_kanban"),
    path("parque/preventiva/", preventiva_kanban, name="parque_preventiva_kanban"),
    path("parque/registrar-preventiva/", registrar_preventiva, name="parque_registrar_preventiva"),
    # Calendário do que JÁ FOI FEITO — tela de conferência do RH. Só leitura;
    # o acesso é checado na view (GRUPOS_REGISTROS).
    # MURAL: a tela de Registros virou feed (apps/parque/mural.py). Comeu os
    # itens de menu "Usuarios online" e "Logs" — as duas rotas antigas
    # continuam de pe' para quem tem link salvo, so' sairam do menu.
    # Para onde o login manda: o Mural para quem o abre, o painel de sempre
    # para quem nao o abre. Ver apps/parque/mural.py:inicio.
    path("inicio/", inicio, name="inicio"),
    path("parque/mural/", mural, name="parque_mural"),
    path("parque/mural/comentar/", mural_comentar, name="parque_mural_comentar"),
    path("parque/mural/marcar/", mural_marcar, name="parque_mural_marcar"),
    path("parque/mural/apagar-comentario/", mural_apagar_comentario,
         name="parque_mural_apagar_comentario"),
    path("parque/mural/publicar/", mural_publicar, name="parque_mural_publicar"),
    path("parque/mural/editar/", mural_editar_publicacao,
         name="parque_mural_editar"),
    path("parque/mural/apagar/", mural_apagar_publicacao,
         name="parque_mural_apagar"),
    # A conversa de duas pessoas. Só as duas leem — ver apps/parque/mural.py.
    path("parque/mural/conversas/", mural_lista, name="parque_mural_lista"),
    path("parque/mural/conversa/", mural_conversa, name="parque_mural_conversa"),
    path("parque/mural/mandar/", mural_mandar, name="parque_mural_mandar"),
    # O calendario antigo fica alcancavel por URL enquanto o mural nao provar
    # que substitui tudo que o RH usava nele.
    path("parque/registros/", preventiva_registros, name="parque_preventiva_registros"),
    path("parque/tarefa/acao/", tarefa_acao, name="parque_tarefa_acao"),
    path("parque/grupo-manutencao/criar/", grupo_criar, name="parque_grupo_criar"),
    path("parque/grupo-manutencao/<int:pk>/", grupo_detalhe, name="parque_grupo_detalhe"),
    path("parque/grupo-manutencao/<int:pk>/membros/", grupo_editar_membros, name="parque_grupo_editar_membros"),
    path("parque/grupo-manutencao/<int:pk>/concluir-todos/", grupo_concluir_todos, name="parque_grupo_concluir_todos"),
    path("parque/grupo-manutencao/<int:pk>/excluir/", grupo_excluir, name="parque_grupo_excluir"),
    path("parque/adiamento/solicitar/", solicitar_adiamento, name="parque_solicitar_adiamento"),
    path("parque/adiamento/<int:pk>/<str:acao>/", decidir_adiamento, name="parque_decidir_adiamento"),
    path("parque/setores/", setores_lista, name="parque_setores_lista"),
    path("parque/chamado/<int:baia_id>/", abrir_chamado, name="parque_abrir_chamado"),
    path("parque/finalizar-reparo/<int:baia_id>/", finalizar_reparo, name="parque_finalizar_reparo"),
    path("parque/reparo/<int:pk>/finalizar/", finalizar_reparo_admin, name="parque_finalizar_reparo_admin"),
    path("parque/solicitacao/<int:pk>/<str:acao>/", decidir_solicitacao, name="parque_decidir_solicitacao"),
    path("parque/transferencia/<int:pk>/<str:acao>/", decidir_transferencia, name="parque_decidir_transferencia"),
    path("parque/transferencia-notebook/<int:pk>/<str:acao>/", decidir_transferencia_notebook, name="parque_decidir_transferencia_notebook"),
    path("parque/aprovacoes/", aprovacoes_pendentes, name="parque_aprovacoes"),
    # Assistente de ajuda (widget flutuante): busca na base de tópicos.
    path("ajuda/assistente/", assistente_perguntar, name="assistente_perguntar"),
    # Agenda do topo (calendário + avisos): só JSON, buscado quando o painel abre.
    path("agenda/eventos/", agenda_eventos, name="agenda_eventos"),
    # Logs num lugar só: acessos + ações (substitui as duas telas do admin).
    path("logs/", logs_unificados, name="logs_unificados"),
    # Central de Cadastros: uma tela para colaboradores, setores, lojas,
    # computadores e notebooks (pedido do dono de unificar essas visoes).
    path("cadastros/", cadastros_hub, name="cadastros_hub"),
    # Redefinir a senha da conta ligada a um colaborador, pela ficha de
    # Cadastros. Gera senha TEMPORÁRIA (a definitiva quem escolhe é a pessoa,
    # no próximo acesso) — ver o comentário em apps/orgs/views.py.
    path("cadastros/colaborador/<int:pk>/senha/", redefinir_senha_colaborador,
         name="redefinir_senha_colaborador"),
    # A CONTA de acesso, pela mesma ficha. Desativar era só por
    # /admin/auth/user/, tela que saiu do menu e à qual ninguém chegava — e o
    # banco mostrava o resultado: contas ativas de quem não trabalha mais aqui.
    # Ver apps/orgs/views_conta.py.
    path("cadastros/colaborador/<int:pk>/conta/criar/", conta_criar,
         name="conta_criar"),
    path("cadastros/colaborador/<int:pk>/conta/desativar/", conta_desativar,
         name="conta_desativar"),
    path("cadastros/colaborador/<int:pk>/conta/ativar/", conta_ativar,
         name="conta_ativar"),
    # Novo setor pelo popup (sem abrir a tela do admin para dois campos).
    path("parque/setor/criar/", setor_criar, name="parque_setor_criar"),
    path("notificacoes/<int:pk>/abrir/", notif_abrir, name="notif_abrir"),
    path("notificacoes/marcar-todas/", notif_marcar_todas, name="notif_marcar_todas"),
    path("notificacoes/<int:pk>/excluir/", notif_excluir, name="notif_excluir"),
    path("notificacoes/limpar/", notif_limpar, name="notif_limpar"),
]

# Mídia (uploads: termos, documentos): servida com LOGIN em qualquer ambiente —
# inclusive com DEBUG=False (túnel), onde o runserver não serve /media/ sozinho.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", media_protegida, name="media_protegida"),
]

# Endpoint de import da planilha: só em desenvolvimento.
if settings.DEBUG:
    from apps.parque.views import import_sheet

    urlpatterns += [path("parque/import-sheet/", import_sheet)]
