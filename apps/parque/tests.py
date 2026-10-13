"""Testes de acesso às telas do parque.

Cobre as regressões achadas na auditoria de 2026-09 (telas que respondiam 500
para visitante anônimo, endpoint de import que escrevia sem autenticação) e uma
rede de fumaça que abre todas as telas com dado real — é ela que pega erro de
sintaxe de template introduzido por mudança de layout.
"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

SEM_AXES = override_settings(
    AUTHENTICATION_BACKENDS=["apps.orgs.backends.EmailOuUsernameBackend"],
    AXES_ENABLED=False,
)


@SEM_AXES
class AcessoAnonimoTests(TestCase):
    """Nenhuma tela do parque pode estourar erro para quem não está logado."""

    def test_mapa_situacao_manda_anonimo_para_o_login(self):
        """Antes: o helper _ctx_transferencia era decorado e devolvia um
        redirect, que a view tentava expandir com ** → TypeError/500 com
        traceback (DEBUG=True vaza settings)."""
        r = self.client.get("/parque/mapa-situacao/defeito/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

    def test_mapa_situacao_status_invalido_e_404(self):
        u = User.objects.create_user(username="staff1", password="SenhaForte9x",
                                     is_staff=True, is_superuser=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get("/parque/mapa-situacao/naoexiste/").status_code, 404)

    def test_mapas_com_transferencia_abrem_para_staff(self):
        u = User.objects.create_user(username="staff2", password="SenhaForte9x",
                                     is_staff=True, is_superuser=True)
        self.client.force_login(u)
        for url in ("/parque/mapa-situacao/defeito/", "/parque/mapa-criticos/",
                    "/parque/mapa-score/", "/parque/mapa-preventiva/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


@SEM_AXES
@override_settings(DEBUG=True)
class ImportSheetProtegidoTests(TestCase):
    """O endpoint de import reescreve o parque inteiro: exige superusuário.

    Antes era @csrf_exempt, sem login, e respondia com
    `Access-Control-Allow-Origin: *` + `Allow-Private-Network: true` — qualquer
    página aberta no navegador do usuário podia chamá-lo.

    A view é chamada direto (RequestFactory) porque a rota só é registrada
    quando DEBUG=True no momento em que o urls.py é importado — `override_settings`
    não reimporta o URLconf.
    """

    def setUp(self):
        from django.test import RequestFactory
        self.rf = RequestFactory()

    def _chamar(self, usuario):
        from apps.parque.views import import_sheet
        req = self.rf.post("/parque/import-sheet/?sheet=ignorado",
                           data=b"", content_type="text/csv")
        req.user = usuario
        return import_sheet(req)

    def test_anonimo_nao_entra(self):
        from django.contrib.auth.models import AnonymousUser
        r = self._chamar(AnonymousUser())
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])
        self.assertNotIn("Access-Control-Allow-Origin", r)

    def test_staff_comum_nao_entra(self):
        u = User.objects.create_user(username="comum", password="SenhaForte9x", is_staff=True)
        from django.http import Http404
        with self.assertRaises(Http404):
            self._chamar(u)

    def test_superusuario_entra_e_sem_cors(self):
        u = User.objects.create_user(username="root", password="SenhaForte9x",
                                     is_staff=True, is_superuser=True)
        r = self._chamar(u)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", r)
        self.assertNotIn("Access-Control-Allow-Private-Network", r)


@SEM_AXES
class FumacaDasTelasTests(TestCase):
    """Abre TODAS as telas do sistema com dado real e exige 200.

    Barato e alto retorno: um `{% if %}` sem `{% endif %}`, uma variável de
    contexto renomeada ou um include quebrado derrubam a tela na hora, e este
    teste avisa antes do usuário. Foi escrito junto com a varredura de design
    de 09/2026, quando 60+ templates mudaram de uma vez.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.orgs.models import Location, Person
        from apps.parque.models import Baia, Computador, Peca, Reparo, Setor

        cls.admin = User.objects.create_user(
            username="fumaca", password="SenhaForte9x", email="fumaca@x.com",
            is_staff=True, is_superuser=True,
        )
        cls.loja = Location.objects.create(name="Loja Teste", city="Curitiba", state="PR")
        setor = Setor.objects.create(nome="Vendas", unidade=cls.loja)
        pessoa = Person.objects.create(full_name="Colaborador Teste", active=True)
        cls.baia = Baia.objects.create(setor=setor, nome="1 - Teste", colaborador=pessoa)
        if not cls.baia.computador_id:
            cls.baia.computador = Computador.objects.create(
                marca="Dell", processador="Intel i5-10400", memoria_ram="8 GB",
                armazenamento="SSD 480GB", sistema_operacional="Windows 11 Pro",
            )
            cls.baia.save()
        cls.peca = Peca.objects.create(tipo="Memória 8GB DDR4", quantidade=5, unidade=cls.loja)
        cls.reparo = Reparo.objects.create(baia=cls.baia, tipo="corretiva",
                                           descricao="teste de fumaça")

    def setUp(self):
        self.client.force_login(self.admin)

    def _abrir(self, url):
        resposta = self.client.get(url, follow=True)
        self.assertEqual(
            resposta.status_code, 200,
            msg="{} devolveu {} (esperado 200)".format(url, resposta.status_code),
        )

    def test_telas_gerais(self):
        # /ajuda/ saiu desta lista: a Central de Ajuda foi removida em 09/2026
        # (era a única tela do sistema aberta a visitante, e servia 141 KB com
        # nome de colaborador e patrimônio no HTML). Toda a ajuda passou a ser
        # o assistente, testado mais abaixo em /ajuda/assistente/.
        for url in ("/admin/", "/dashboard/", "/orcamentos/"):
            with self.subTest(url=url):
                self._abrir(url)

    def test_telas_de_estoque_e_tabelas(self):
        for url in ("/parque/estoque/", "/parque/tabela-computadores/",
                    "/parque/tabela-notebooks/", "/parque/tabela-pecas/",
                    "/parque/tabela-estoque-computadores/", "/parque/fora-de-uso/",
                    "/parque/etiquetas/", "/parque/montar-caixa/"):
            with self.subTest(url=url):
                self._abrir(url)

    def test_telas_de_mapa(self):
        for url in ("/parque/mapa-completo/", "/parque/mapa-notebooks/",
                    "/parque/mapa-score/", "/parque/mapa-preventiva/",
                    "/parque/mapa-criticos/", "/parque/mapa-situacao/defeito/",
                    "/parque/mapa-situacao/sem_pc/", "/parque/setores/",
                    "/parque/mapa/{}/".format(self.loja.pk)):
            with self.subTest(url=url):
                self._abrir(url)

    def test_telas_de_chamado_e_preventiva(self):
        for url in ("/parque/reparos/", "/parque/preventiva/", "/parque/aprovacoes/",
                    "/parque/escanear-chamado/",
                    "/parque/chamado/{}/".format(self.baia.pk),
                    "/parque/chamado-detalhe/{}/".format(self.reparo.pk)):
            with self.subTest(url=url):
                self._abrir(url)

    def test_telas_de_transferencia_e_autorizada(self):
        for url in ("/parque/transferencias/", "/parque/transferencia-lojas/",
                    "/parque/transferencia-notebooks/", "/parque/autorizadas/",
                    "/parque/autorizadas/enviar/", "/parque/agente/",
                    "/parque/peca/{}/transferir/".format(self.peca.pk)):
            with self.subTest(url=url):
                self._abrir(url)

    def test_telas_de_autenticacao(self):
        self.client.logout()
        for url in ("/admin/login/", "/admin/password_reset/",
                    "/admin/password_reset/done/"):
            with self.subTest(url=url):
                self._abrir(url)

    def test_admin_dos_modelos_principais(self):
        for url in ("/admin/auth/user/", "/admin/orgs/person/", "/admin/orgs/location/",
                    "/admin/parque/reparo/", "/admin/parque/autorizada/add/"):
            with self.subTest(url=url):
                self._abrir(url)


@SEM_AXES
class TransacaoTests(TestCase):
    """Onda 1, item 1.4: operação multi-passo é tudo-ou-nada.

    O critério de 'pronto' da auditoria: injetar uma exceção no ÚLTIMO passo e
    provar que nenhum dos anteriores ficou gravado.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.orgs.models import Location, Person
        from apps.parque.models import Baia, Computador, Setor

        cls.loja = Location.objects.create(name="Loja Tx", city="Curitiba", state="PR")
        setor = Setor.objects.create(nome="TI", unidade=cls.loja)
        cls.a = Baia.objects.create(setor=setor, nome="1 - A",
                                    colaborador=Person.objects.create(full_name="Pessoa A"))
        cls.b = Baia.objects.create(setor=setor, nome="2 - B",
                                    colaborador=Person.objects.create(full_name="Pessoa B"))
        for baia, marca in ((cls.a, "Dell"), (cls.b, "Lenovo")):
            if not baia.computador_id:
                baia.computador = Computador.objects.create(
                    marca=marca, processador="Intel i5", memoria_ram="8 GB",
                    armazenamento="SSD 480GB",
                )
                baia.save()

    def test_troca_de_pcs_nao_deixa_as_duas_baias_sem_computador(self):
        """Era o pior caso do sistema: `_aplicar_troca` desvincula os DOIS
        computadores antes de religar cruzado. Falha no meio perdia os dois."""
        from unittest.mock import patch
        from apps.parque.models import Baia, MovimentacaoBaia

        antes_a = self.a.computador_id
        antes_b = self.b.computador_id
        self.assertTrue(antes_a and antes_b and antes_a != antes_b)

        mov = MovimentacaoBaia.objects.create(
            baia=self.a, baia_parceira=self.b, tipo=MovimentacaoBaia.Tipo.TROCAR,
        )
        # Explode no ÚLTIMO save da troca.
        original = Baia.save
        chamadas = {"n": 0}

        def save_que_falha(self, *args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] >= 4:
                raise RuntimeError("falha simulada no último passo")
            return original(self, *args, **kwargs)

        with patch.object(Baia, "save", save_que_falha):
            with self.assertRaises(RuntimeError):
                mov._aplicar_troca()

        # Nada foi persistido: cada baia continua com o computador que tinha.
        self.assertEqual(Baia.objects.get(pk=self.a.pk).computador_id, antes_a)
        self.assertEqual(Baia.objects.get(pk=self.b.pk).computador_id, antes_b)

    def test_transferencia_entre_lojas_nao_deixa_pc_no_limbo(self):
        from unittest.mock import patch
        from apps.orgs.models import Location
        from apps.parque.models import Baia, Setor, Transferencia

        outra = Location.objects.create(name="Loja Tx2", city="Curitiba", state="PR")
        destino_setor = Setor.objects.create(nome="Vendas", unidade=outra)
        destino = Baia.objects.create(setor=destino_setor, nome="1 - Dest")
        comp_id = self.a.computador_id

        t = Transferencia.objects.create(
            baia_origem=self.a, baia_destino=destino, entre_lojas=True,
            computador_id=comp_id,
        )
        with patch.object(Baia, "save", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                t.aplicar_transferencia_loja()

        # A origem continua com o computador; o destino continua vazio.
        self.assertEqual(Baia.objects.get(pk=self.a.pk).computador_id, comp_id)
        self.assertIsNone(Baia.objects.get(pk=destino.pk).computador_id)

    def test_estoque_de_peca_nao_fica_negativo(self):
        """Item 1.5: `select_for_update` + revalidação dentro da transação."""
        from apps.parque.models import Peca

        peca = Peca.objects.create(tipo="Memória 8GB", quantidade=1, unidade=self.loja)
        u = User.objects.create_user(username="txuser", password="SenhaForte9x",
                                     is_staff=True, is_superuser=True)
        self.client.force_login(u)
        destino = self.loja  # mesma unidade → rejeitado antes de mexer no estoque
        r = self.client.post(f"/parque/peca/{peca.pk}/transferir/", {
            "unidade_destino": destino.pk, "quantidade": "5",
            "bitrix_task_id": "T-1",
        })
        self.assertEqual(r.status_code, 200)
        peca.refresh_from_db()
        self.assertEqual(peca.quantidade, 1)


@SEM_AXES
class MudancaDeEstadoExigePostTests(TestCase):
    """Onda 1, item 1.2: nenhuma dessas URLs pode agir num GET.

    Um `<img src=".../autorizar/">` num e-mail rodava a ação com a sessão da
    vítima — sem CSRF, porque GET não passa pelo middleware.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="gestor", password="SenhaForte9x", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def test_get_nas_urls_de_decisao_devolve_405(self):
        for url in ("/parque/transferencia/1/autorizar/",
                    "/parque/transferencia-notebook/1/autorizar/",
                    "/parque/solicitacao/1/autorizar/",
                    "/parque/adiamento/1/aprovar/",
                    "/parque/reparo/1/finalizar/",
                    "/orcamentos/1/aprovar/"):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url).status_code, 405,
                    msg=f"{url} ainda aceita GET (mudança de estado por link)",
                )


@SEM_AXES
class RedirecionamentoSeguroTests(TestCase):
    """Onda 1, item 1.6: Referer/next externos não podem virar redirect."""

    def test_destino_externo_cai_no_padrao(self):
        from django.test import RequestFactory
        from apps.parque.utils import destino_seguro, voltar_para

        rf = RequestFactory()
        req = rf.post("/x/", {"next": "https://site-malicioso.example/roubar"})
        req.META["HTTP_REFERER"] = "https://outro-site.example/"
        self.assertEqual(voltar_para(req, padrao="/parque/"), "/parque/")
        self.assertEqual(
            destino_seguro(req, "//evil.example/x", padrao="/admin/"), "/admin/")

    def test_destino_interno_e_respeitado(self):
        from django.test import RequestFactory
        from apps.parque.utils import voltar_para

        req = RequestFactory().post("/x/", {"next": "/parque/tabela-pecas/"})
        self.assertEqual(voltar_para(req, padrao="/admin/"), "/parque/tabela-pecas/")


@SEM_AXES
class SenhaDeMaquinaCifradaTests(TestCase):
    """Onda 1, item 1.12: senha de máquina/AnyDesk não fica em claro no banco."""

    def test_grava_cifrado_e_le_em_claro(self):
        from django.db import connection
        from apps.parque.models import Notebook

        nb = Notebook.objects.create(
            marca="Dell", modelo="Vostro", patrimonio="NB-CRIPTO-1",
            senha="SenhaDaMaquina123", anydesk_senha="AnyDesk987",
        )
        # Pela ORM, em claro (a TI precisa ler para acessar a máquina).
        nb.refresh_from_db()
        self.assertEqual(nb.senha, "SenhaDaMaquina123")
        self.assertEqual(nb.anydesk_senha, "AnyDesk987")

        # No banco (e portanto em qualquer backup), cifrado.
        with connection.cursor() as cur:
            cur.execute("SELECT senha, anydesk_senha FROM parque_notebook WHERE id = %s",
                        [nb.pk])
            senha_bruta, anydesk_bruta = cur.fetchone()
        self.assertNotIn("SenhaDaMaquina123", senha_bruta)
        self.assertNotIn("AnyDesk987", anydesk_bruta)
        self.assertTrue(senha_bruta.startswith("enc1:"))

    def test_valor_antigo_em_claro_continua_legivel(self):
        """Registro gravado antes da migração não pode sumir da tela."""
        from django.db import connection
        from apps.parque.models import Notebook

        nb = Notebook.objects.create(marca="HP", modelo="ProBook",
                                     patrimonio="NB-CRIPTO-2")
        with connection.cursor() as cur:
            cur.execute("UPDATE parque_notebook SET senha = %s WHERE id = %s",
                        ["senha-antiga-em-claro", nb.pk])
        nb.refresh_from_db()
        self.assertEqual(nb.senha, "senha-antiga-em-claro")


@SEM_AXES
class AssistenteDeAjudaTests(TestCase):
    """O menu 'Ajuda' saiu do sistema: o assistente é a porta única."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="aprendiz", password="SenhaForte9x", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def test_pergunta_em_portugues_do_dia_a_dia_acha_o_topico(self):
        casos = [
            ("esqueci minha senha", "esqueci-senha"),
            ("minha maquina travou", "abrir-chamado"),
            ("como transfiro um pc para outra loja", "transferir-maquina"),
            ("quantas memórias tem no estoque", "estoque-pecas"),
            ("o que é o score da máquina", "score"),
            ("como instalo o agente", "telemetria"),
        ]
        for pergunta, esperado in casos:
            with self.subTest(pergunta=pergunta):
                r = self.client.get("/ajuda/assistente/", {"q": pergunta})
                self.assertEqual(r.status_code, 200)
                ids = [t["id"] for t in r.json()["topicos"]]
                self.assertIn(esperado, ids, msg=f"{pergunta!r} → {ids}")

    def test_pergunta_fora_do_dominio_oferece_caminho(self):
        r = self.client.get("/ajuda/assistente/", {"q": "receita de bolo de cenoura"})
        dados = r.json()
        self.assertEqual(dados["topicos"], [])
        self.assertTrue(dados["sugestoes"], "sem resposta deve oferecer sugestões")

    def test_sem_pergunta_devolve_sugestoes(self):
        dados = self.client.get("/ajuda/assistente/").json()
        self.assertTrue(dados["sugestoes"])

    def test_indice_lista_todos_os_assuntos(self):
        from apps.parque.assistente import TOPICOS

        dados = self.client.get("/ajuda/assistente/", {"todos": "1"}).json()
        total = sum(len(s["itens"]) for s in dados["indice"])
        self.assertEqual(total, len(TOPICOS))

    def test_anonimo_nao_acessa(self):
        self.client.logout()
        r = self.client.get("/ajuda/assistente/", {"q": "senha"})
        self.assertEqual(r.status_code, 302)

    def test_todo_topico_tem_passos_e_destino_valido(self):
        """Um tópico sem passo ou com link quebrado é pior que não existir."""
        from apps.parque.assistente import TOPICOS

        for t in TOPICOS:
            with self.subTest(topico=t["id"]):
                self.assertTrue(t["passos"], "tópico sem passo a passo")
                self.assertTrue(t["url"].startswith("/"), "url deve ser interna")


class SemLinkGetParaAcaoTests(TestCase):
    """Nenhum template pode ter <a href> para URL que exige POST.

    Depois que as views de decisão viraram POST-only (auditoria 1.2), um link
    remanescente vira 405 no clique — o usuário aperta "Autorizar" e não
    acontece nada. Este teste é estático: lê os templates, não abre tela.
    """

    ACOES = (
        "parque_decidir_transferencia",
        "parque_decidir_transferencia_notebook",
        "parque_decidir_solicitacao",
        "parque_decidir_adiamento",
        "parque_finalizar_reparo_admin",
        "orcamentos_decidir",
    )

    def test_nenhum_link_get_para_view_post_only(self):
        import os
        import re
        from django.conf import settings

        raiz = settings.BASE_DIR / "templates"
        padrao_url = re.compile(
            r"/(parque/(transferencia|transferencia-notebook|solicitacao|adiamento)/"
            r"[^\"']*/(autorizar|negar|aprovar)/"
            r"|parque/reparo/[^\"']*/finalizar/"
            r"|orcamentos/[^\"']*/(aprovar|negar)/)"
        )
        achados = []
        for pasta, _, arquivos in os.walk(raiz):
            for nome in arquivos:
                if not nome.endswith(".html"):
                    continue
                caminho = os.path.join(pasta, nome)
                with open(caminho, encoding="utf-8", errors="ignore") as fh:
                    conteudo = fh.read()
                for m in re.finditer(r"<a\b[^>]*>", conteudo, re.I):
                    tag = m.group(0)
                    if padrao_url.search(tag) or any(a in tag for a in self.ACOES):
                        linha = conteudo[:m.start()].count("\n") + 1
                        achados.append(
                            f"{os.path.relpath(caminho, raiz)}:{linha}")
        self.assertEqual(
            achados, [],
            msg="Estes links precisam virar <form method=\"post\"> com "
                "{% csrf_token %} — a view exige POST: " + ", ".join(achados),
        )


@SEM_AXES
class PatrimonioSemColisaoTests(TestCase):
    """Onda 1, item 1.9: patrimônio duplicado em criação concorrente.

    `proximo_patrimonio` lê o maior número e soma 1 — duas criações simultâneas
    calculam o MESMO. O campo é `unique`, então a segunda estourava
    IntegrityError e a criação falhava. Agora recalcula e tenta de novo.
    """

    def test_colisao_de_patrimonio_e_resolvida_com_novo_numero(self):
        from unittest.mock import patch
        from apps.parque.models import Computador

        primeiro = Computador.objects.create(marca="Dell", processador="i5")
        self.assertTrue(primeiro.patrimonio)

        # Simula a corrida: a 1ª tentativa devolve um patrimônio JÁ existente.
        real = Computador.objects.filter  # noqa: F841 (documenta a intenção)
        sequencia = [primeiro.patrimonio, "PC-CORRIDA-OK"]

        with patch("apps.parque.models.proximo_patrimonio",
                   side_effect=lambda *a, **k: sequencia.pop(0)):
            segundo = Computador.objects.create(marca="Dell", processador="i7")

        self.assertEqual(segundo.patrimonio, "PC-CORRIDA-OK")
        self.assertEqual(Computador.objects.count(), 2)

    def test_erro_de_integridade_de_outro_campo_nao_e_engolido(self):
        """O retry é só para o patrimônio: outra violação tem de estourar."""
        from django.db import IntegrityError
        from unittest.mock import patch
        from apps.parque.models import Computador

        with patch.object(Computador, "save",
                          side_effect=IntegrityError("UNIQUE constraint failed: parque_computador.serial")):
            with self.assertRaises(IntegrityError):
                Computador(marca="Dell").save()


class FormatacaoDeTemplateTests(TestCase):
    """Pega os erros de formatação que o Django NÃO reclama, mas que vazam
    sintaxe de template para dentro do HTML entregue ao navegador.

    O caso real: `{# … #}` no Django é comentário de **uma linha só**. Um
    comentário de duas linhas não é reconhecido — o texto aparece na tela e
    qualquer `{% tag %}` dentro dele é EXECUTADA (isso já causou recursão
    infinita e já vazou texto de comentário na tela de detalhe do chamado).
    """

    def _templates(self):
        import os
        from django.conf import settings

        raiz = settings.BASE_DIR / "templates"
        for pasta, _, arquivos in os.walk(raiz):
            for nome in sorted(arquivos):
                if nome.endswith(".html"):
                    caminho = os.path.join(pasta, nome)
                    with open(caminho, encoding="utf-8", errors="ignore") as fh:
                        yield os.path.relpath(caminho, raiz), fh.read()

    def test_nenhum_comentario_de_uma_linha_atravessa_linha(self):
        import re

        achados = []
        for rel, conteudo in self._templates():
            for m in re.finditer(r"\{#", conteudo):
                resto = conteudo[m.end():]
                fim_linha = resto.find("\n")
                fecha = resto.find("#}")
                if fecha == -1 or (fim_linha != -1 and fecha > fim_linha):
                    linha = conteudo[:m.start()].count("\n") + 1
                    achados.append(f"{rel}:{linha}")
        self.assertEqual(
            achados, [],
            msg="`{# … #}` só vale numa linha. Use {% comment %}…{% endcomment %} em: "
                + ", ".join(achados),
        )

    def test_tags_de_bloco_estao_balanceadas(self):
        import re

        def sem_comentario(texto):
            """Remove o conteúdo de {% comment %} e {% verbatim %}.

            Sem isso, um comentário que CITA `{% if %}` na prosa (o que o
            override do badge faz, para explicar o bug que corrigiu) contaria
            como tag de verdade — falso positivo.
            """
            texto = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}",
                           "", texto, flags=re.S)
            texto = re.sub(r"\{%\s*verbatim.*?\{%\s*endverbatim\s*%\}",
                           "", texto, flags=re.S)
            return texto

        PARES = {
            "if": "endif", "for": "endfor", "block": "endblock",
            "with": "endwith", "spaceless": "endspaceless",
            "autoescape": "endautoescape", "blocktrans": "endblocktrans",
            "blocktranslate": "endblocktranslate", "filter": "endfilter",
        }
        FECHA = {v: k for k, v in PARES.items()}
        problemas = []
        for rel, conteudo in self._templates():
            conteudo = sem_comentario(conteudo)
            pilha = []
            for m in re.finditer(r"\{%\s*(\w+)", conteudo):
                tag = m.group(1)
                linha = conteudo[:m.start()].count("\n") + 1
                if tag in PARES:
                    pilha.append((tag, linha))
                elif tag in FECHA:
                    esperado = FECHA[tag]
                    if not pilha:
                        problemas.append(f"{rel}:{linha} {{% {tag} %}} sem abertura")
                    elif pilha[-1][0] != esperado:
                        aberto, la = pilha[-1]
                        problemas.append(
                            f"{rel}:{linha} {{% {tag} %}} fecha {{% {aberto} %}} da linha {la}")
                        pilha.pop()
                    else:
                        pilha.pop()
            for aberto, linha in pilha:
                problemas.append(f"{rel}:{linha} {{% {aberto} %}} nunca fechou")
        self.assertEqual(problemas, [], msg="Tags desbalanceadas: " + " · ".join(problemas))


@SEM_AXES
class ArquivoDoPatrimonioTests(TestCase):
    """O arquivo do patrimônio (/parque/arquivo/).

    O que estes testes protegem é a regra que dá sentido à tela: o dossiê é
    DERIVADO do que aconteceu com o equipamento. Se alguém trocar isso por uma
    lista fixa de documentos, o "0 de 3" passa a mentir e ninguém percebe —
    porque a tela continua bonita.
    """

    def setUp(self):
        from apps.orgs.models import Person
        from apps.parque.models import Notebook

        self.chefe = User.objects.create_user(
            username="rh1", password="SenhaForte9x", is_staff=True, is_superuser=True)
        self.client.force_login(self.chefe)
        self.pessoa = Person.objects.create(full_name="Raniele Teste")
        self.nb = Notebook.objects.create(marca="Dell", modelo="Vostro",
                                          colaborador=self.pessoa)

    def _pasta(self, ident):
        from apps.parque.arquivo import _pastas_equipamento
        return [p for p in _pastas_equipamento() if p["id"] == ident][0]

    def _pdf(self, nome="nota.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nome, b"%PDF-1.4 teste", content_type="application/pdf")

    # --------------------------------------------------------------- a regra
    def test_dossie_sai_do_que_aconteceu_com_o_equipamento(self):
        """Notebook com dono exige nota fiscal E termo de entrega. Um PC novo
        exige só a nota. A lista não é fixa: cresce com o histórico."""
        from apps.parque.models import Computador, Transferencia

        pasta = self._pasta("nb%s" % self.nb.pk)
        nomes = [e["nome"] for e in pasta["exigidos"]]
        self.assertIn("Nota fiscal de compra", nomes)
        self.assertIn("Termo de entrega assinado", nomes)
        self.assertEqual(pasta["de"], 2)
        self.assertEqual(pasta["ok"], 0)

        pc = Computador.objects.create(marca="Dell", processador="i5")
        self.assertEqual(self._pasta("pc%s" % pc.pk)["de"], 1)

        # Uma transferência acontece: o dossiê do PC passa a exigir o protocolo.
        Transferencia.objects.create(computador=pc)
        depois = self._pasta("pc%s" % pc.pk)
        self.assertEqual(depois["de"], 2)
        self.assertTrue(any(e["tipo"] == "protocolo" for e in depois["exigidos"]))

    def test_devolucao_entra_no_dossie_quando_o_notebook_volta(self):
        """Enquanto está com alguém exige-se o termo de ENTREGA; quando volta,
        passa a exigir o de DEVOLUÇÃO. É a pergunta que o RH precisa responder."""
        r = self.client.post("/parque/remover-notebook-colaborador/",
                             {"notebook": self.nb.pk})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

        nomes = [e["nome"] for e in self._pasta("nb%s" % self.nb.pk)["exigidos"]]
        self.assertIn("Termo de devolução assinado", nomes)
        self.assertNotIn("Termo de entrega assinado", nomes)

    # ------------------------------------------------------------- as ações
    def test_anexar_fecha_a_pendencia_e_validar_registra_quem_conferiu(self):
        from apps.parque.models import DocumentoEquipamento

        alvo = "nb%s" % self.nb.pk
        r = self.client.post("/parque/arquivo/anexar/",
                             {"alvo": alvo, "tipo": "nota_compra", "arquivo": self._pdf()})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(self._pasta(alvo)["ok"], 1)

        doc = DocumentoEquipamento.objects.get(notebook=self.nb, tipo="nota_compra")
        r = self.client.post("/parque/arquivo/validar/", {"doc": doc.pk})
        self.assertEqual(r.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.validado_por_id, self.chefe.pk)
        self.assertIsNotNone(doc.validado_em)

    def test_anexo_com_tipo_errado_nao_fecha_a_pendencia_da_nota(self):
        """O tipo é o que faz o documento contar. Anexo solto entra como
        "Outro" e a nota fiscal continua faltando — que é a verdade."""
        alvo = "nb%s" % self.nb.pk
        self.client.post("/parque/arquivo/anexar/",
                         {"alvo": alvo, "tipo": "outro", "arquivo": self._pdf("foto.pdf")})
        self.assertEqual(self._pasta(alvo)["ok"], 0)

    def test_anexar_recusa_formato_e_destino_invalidos(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        exe = SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")
        r = self.client.post("/parque/arquivo/anexar/",
                             {"alvo": "nb%s" % self.nb.pk, "tipo": "outro", "arquivo": exe})
        self.assertEqual(r.status_code, 400)

        r = self.client.post("/parque/arquivo/anexar/",
                             {"alvo": "zz9", "tipo": "outro", "arquivo": self._pdf()})
        self.assertEqual(r.status_code, 400)

        r = self.client.post("/parque/arquivo/anexar/", {"alvo": "nb%s" % self.nb.pk})
        self.assertEqual(r.status_code, 400)

    def test_subir_o_termo_pelo_arquivo_marca_como_assinado(self):
        from apps.parque.models import TermoResponsabilidade

        termo = TermoResponsabilidade.objects.create(
            notebook=self.nb, colaborador=self.pessoa,
            colaborador_nome=self.pessoa.full_name, equipamento_desc="Notebook Dell")
        self.assertEqual(termo.status, TermoResponsabilidade.Status.PENDENTE)

        r = self.client.post("/parque/arquivo/anexar/",
                             {"alvo": "tm%s" % termo.pk, "tipo": "termo",
                              "arquivo": self._pdf("termo.pdf")})
        self.assertEqual(r.status_code, 200)
        termo.refresh_from_db()
        self.assertEqual(termo.status, TermoResponsabilidade.Status.ASSINADO)
        self.assertTrue(termo.arquivo_assinado)
        self.assertEqual(self._pasta("nb%s" % self.nb.pk)["ok"], 1)

    def test_retirada_gera_um_termo_de_devolucao_e_so_um(self):
        from apps.parque.models import TermoResponsabilidade

        def devolucoes():
            return TermoResponsabilidade.objects.filter(
                notebook=self.nb, tipo=TermoResponsabilidade.Tipo.DEVOLUCAO).count()

        self.client.post("/parque/remover-notebook-colaborador/", {"notebook": self.nb.pk})
        self.nb.refresh_from_db()
        self.assertIsNone(self.nb.colaborador_id)
        self.assertEqual(devolucoes(), 1)

        # Retirar de novo (ou clicar duas vezes) não empilha termo pendente.
        self.client.post("/parque/remover-notebook-colaborador/", {"notebook": self.nb.pk})
        self.assertEqual(devolucoes(), 1)

    def test_retirada_continua_valendo_se_o_termo_falhar(self):
        """O termo é consequência; a retirada é o fato. Se o termo falhar, o
        notebook já saiu do colaborador — e é isso que o parque precisa."""
        from unittest.mock import patch
        from apps.parque.models import TermoResponsabilidade

        with patch.object(TermoResponsabilidade.objects, "create",
                          side_effect=RuntimeError("banco caiu")):
            r = self.client.post("/parque/remover-notebook-colaborador/",
                                 {"notebook": self.nb.pk})
        self.assertEqual(r.status_code, 200)
        self.nb.refresh_from_db()
        self.assertIsNone(self.nb.colaborador_id)

    # ---------------------------------------------------------------- a tela
    def test_tela_abre_para_quem_pode_e_nega_o_resto(self):
        r = self.client.get("/parque/arquivo/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Arquivo do patrim")

        self.client.logout()
        r = self.client.get("/parque/arquivo/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

        peao = User.objects.create_user(username="peao", password="SenhaForte9x",
                                        is_staff=True)
        self.client.force_login(peao)
        self.assertIn(self.client.get("/parque/arquivo/").status_code, (302, 403))

    def test_acoes_exigem_post_e_permissao(self):
        self.assertEqual(self.client.get("/parque/arquivo/anexar/").status_code, 405)
        self.assertEqual(self.client.get("/parque/arquivo/validar/").status_code, 405)

        peao = User.objects.create_user(username="peao2", password="SenhaForte9x",
                                        is_staff=True)
        self.client.force_login(peao)
        r = self.client.post("/parque/arquivo/anexar/",
                             {"alvo": "nb%s" % self.nb.pk, "tipo": "nota_compra",
                              "arquivo": self._pdf()})
        self.assertEqual(r.status_code, 403)


@SEM_AXES
class UsuarioLeigoTests(TestCase):
    """Gente errando não pode receber 500.

    Esta classe é a trava dos oito pontos que a varredura do usuário leigo
    (deploy/varredura.py e o irmão dela) achou em 4.872 requisições de
    formulário vazio, letra no lugar de número, clique duplo, id inventado e
    filtro editado à mão. Pode dar 400, 403, 404, pode redirecionar, pode
    mostrar mensagem — 500 é o sistema quebrando na mão de quem só errou.
    """

    def setUp(self):
        self.chefe = User.objects.create_user(username="leigo-chefe", password="SenhaForte9x",
                                              is_staff=True, is_superuser=True)
        self.client.force_login(self.chefe)

    def test_id_gigante_na_url_da_404_e_nao_500(self):
        """<int:pk> aceita qualquer sequência de dígitos e o SQLite estoura
        acima de 8 bytes. O conserto está no CONVERSOR (config/urls.py), então
        vale para as 26 rotas com id — não só para esta."""
        for url in ("/parque/mapa-criticos/99999999999999999999/",
                    "/parque/mapa/99999999999999999999/",
                    "/parque/termo/99999999999999999999/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 404, msg=url)

    def test_id_que_nao_existe_da_404(self):
        for url in ("/parque/mapa-criticos/999999/", "/parque/termo/999999/"):
            self.assertIn(self.client.get(url).status_code, (404, 302), msg=url)

    def test_ano_fora_de_faixa_na_preventiva_nao_quebra(self):
        """O guard conferia o mês e esquecia o ano: ?ano=-5 estourava em
        monthdatescalendar(-5, 9)."""
        for q in ("?ano=-5", "?ano=99999", "?ano=abc", "?mes=99", "?mes=0"):
            r = self.client.get("/parque/preventiva/" + q)
            self.assertEqual(r.status_code, 200, msg=q)

    def test_querystring_lixo_nao_quebra_tela(self):
        lixos = ["?q=%3Cscript%3E", "?pagina=-1", "?unidade=abc", "?unidade=999999",
                 "?vista=inventada", "?vence_ate=32/13/2026", "?ordem=;drop"]
        telas = ["/parque/preventiva/", "/parque/registros/", "/parque/reparos/",
                 "/parque/estoque/", "/parque/transferencias/", "/parque/arquivo/",
                 "/parque/leitura-executiva/", "/parque/mapa-criticos/"]
        for tela in telas:
            for lixo in lixos:
                r = self.client.get(tela + lixo)
                self.assertLess(r.status_code, 500, msg=tela + lixo)

    def test_preview_de_patrimonio_com_unidade_invalida(self):
        for q in ("?unidade=abc", "?unidade=-1", "?unidade=999999999999999999999", ""):
            r = self.client.get("/parque/proximo-patrimonio/" + q)
            self.assertEqual(r.status_code, 200, msg=q)

    def test_validar_documento_com_id_invalido(self):
        for valor in ("abc", "-1", "", "99999999999999999999"):
            r = self.client.post("/parque/arquivo/validar/", {"doc": valor})
            self.assertEqual(r.status_code, 404, msg=repr(valor))

    def test_anexar_com_alvo_de_letra(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf = SimpleUploadedFile("x.pdf", b"%PDF-1.4", content_type="application/pdf")
        r = self.client.post("/parque/arquivo/anexar/", {"alvo": "nbabc", "arquivo": pdf})
        self.assertEqual(r.status_code, 400)

    def test_formulario_vazio_em_rota_de_escrita_nao_quebra(self):
        for url in ("/parque/arquivo/anexar/", "/parque/arquivo/validar/",
                    "/parque/remover-notebook-colaborador/"):
            r = self.client.post(url, {})
            self.assertLess(r.status_code, 500, msg=url)


@SEM_AXES
class MuralTests(TestCase):
    """MURAL — a tela de Registros virou feed.

    O que estes testes travam é a única coisa que, se quebrar, quebra em
    silêncio: a REGRA DE ACESSO. O mural junta dez fontes; se ele mostrasse
    tudo para quem abre a tela, o estagiário passaria a ver termo e documento,
    que hoje só o Arquivo mostra. A regra é "o post só entra se a pessoa pode
    abrir a tela que já o mostrava" — e é isso que se prova aqui.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group
        from apps.orgs.models import Location, PerfilUsuario, Person
        from apps.parque.models import Baia, Computador, Reparo, Setor

        from apps.orgs.models import TelaGrupo

        cls.chefe = User.objects.create_user("chefe", password="x", is_staff=True)
        gerente = Group.objects.create(name="Gerente")
        cls.chefe.groups.add(gerente)
        cls.estag = User.objects.create_user("estag", password="x", is_staff=True)
        cls.estag.groups.add(Group.objects.create(name="Estagiário"))
        cls.su = User.objects.create_superuser("su", "su@x.com", "x")

        # No banco de teste os grupos nascem agora, então nenhuma linha de
        # TelaGrupo aponta para eles — e tela restrita sem linha não abre para
        # ninguém, de propósito (apps/orgs/acessos.py). Aqui eu dou ao Gerente
        # exatamente as três telas que o mural usa.
        for tela in ("registros", "online", "logs"):
            TelaGrupo.objects.get_or_create(tela=tela, grupo=gerente)
        # O sinal de criação liga senha_temporaria, e o middleware manda todo
        # mundo para a troca de senha — o que faria estes testes medirem 302.
        PerfilUsuario.objects.filter(
            usuario__in=[cls.chefe, cls.estag, cls.su]).update(senha_temporaria=False)

        # Um acontecimento de verdade, para os testes de escrita terem card.
        loja = Location.objects.create(name="Loja Mural", city="Curitiba", state="PR")
        setor = Setor.objects.create(nome="Vendas", unidade=loja)
        baia = Baia.objects.create(
            setor=setor, nome="1 - Mural",
            colaborador=Person.objects.create(full_name="Colab Mural", active=True))
        if not baia.computador_id:
            baia.computador = Computador.objects.create(
                marca="Dell", processador="Intel i5", memoria_ram="8 GB",
                armazenamento="SSD 480GB", sistema_operacional="Windows 11 Pro",
                patrimonio="PC-MURAL1")
            baia.save()
        cls.reparo = Reparo.objects.create(baia=baia, tipo="reparo",
                                           titulo="Chamado do mural",
                                           descricao="teste do mural")

    # ---------------------------------------------------------------- acesso
    def test_o_mural_abre_para_toda_a_equipe(self):
        """Mudou em 13/10/2026, a pedido do dono.

        Antes este teste exigia o grupo RH/Gerente/Supervisor — herança de
        quando a tela se chamava "Registros". O efeito era no INÍCIO: quem não
        abria o Mural caía no painel, e a mesma pessoa via telas iniciais
        diferentes conforme a conta. O dono viu e pediu para corrigir.

        Abrir não afrouxa nada: o que cada um VÊ continua filtrado por
        `TELA_DO_TIPO` (test_nenhum_post_escapa_da_tela_que_o_mostrava), e
        ESCREVER continua preso à permissão de modelo
        (test_quem_nao_pode_publicar_nao_publica).
        """
        for quem in (self.estag, self.chefe):
            self.client.force_login(quem)
            self.assertEqual(self.client.get("/parque/mural/").status_code, 200,
                             msg=quem.username)

    def test_anonimo_vai_para_o_login(self):
        r = self.client.get("/parque/mural/")
        self.assertIn(r.status_code, (301, 302))
        for url in ("/parque/mural/comentar/", "/parque/mural/marcar/",
                    "/parque/mural/apagar-comentario/"):
            self.assertIn(self.client.post(url, {}).status_code, (301, 302), msg=url)

    def test_nenhum_post_escapa_da_tela_que_o_mostrava(self):
        """A trava de fundo: para TODO usuário, todo tipo de post que aparece
        tem que ter a tela dele liberada. É o teste que impede o mural de
        virar porta nova sem ninguém perceber."""
        from apps.orgs.acessos import pode_ver_tela
        from apps.parque.mural import TELA_DO_TIPO, montar_eventos
        for u in (self.chefe, self.estag, self.su):
            for tipo in {e["tipo"] for e in montar_eventos(u)}:
                self.assertTrue(
                    pode_ver_tela(u, TELA_DO_TIPO[tipo]),
                    msg="%s viu %s sem abrir %s" % (u, tipo, TELA_DO_TIPO[tipo]))

    def test_tipo_restrito_nao_entra_para_quem_nao_ve_o_arquivo(self):
        from apps.parque.mural import TELA_DO_TIPO, montar_eventos
        self.assertEqual(TELA_DO_TIPO["termo"], "arquivo")
        vistos = {e["tipo"] for e in montar_eventos(self.estag)}
        self.assertNotIn("termo", vistos)
        self.assertNotIn("documento", vistos)

    def test_presenca_e_log_seguem_as_telas_online_e_logs(self):
        from apps.parque.mural import montar_logs, montar_presenca
        self.assertEqual(montar_presenca(self.estag), [])
        self.assertEqual(montar_logs(self.estag)["logs"], [])
        self.assertIsInstance(montar_presenca(self.chefe), list)

    # -------------------------------------------------------------- escrever
    def _um_card(self, user):
        from apps.parque.mural import montar_eventos
        evs = montar_eventos(user)
        return evs[0]["id"] if evs else None

    def test_comentario_em_card_inventado_da_404(self):
        self.client.force_login(self.su)
        r = self.client.post("/parque/mural/comentar/",
                             {"chave": "nao-existe-1", "texto": "oi"})
        self.assertEqual(r.status_code, 404)

    def test_comentario_vazio_e_gigante_sao_recusados(self):
        self.client.force_login(self.su)
        chave = self._um_card(self.su)
        if not chave:
            self.skipTest("banco de teste sem acontecimento")
        self.assertEqual(self.client.post(
            "/parque/mural/comentar/", {"chave": chave, "texto": "  "}).status_code, 400)
        self.assertEqual(self.client.post(
            "/parque/mural/comentar/",
            {"chave": chave, "texto": "a" * 4001}).status_code, 400)

    def test_comentar_grava_e_passa_a_acompanhar(self):
        from apps.parque.models import ComentarioEvento, MarcaEvento
        self.client.force_login(self.su)
        chave = self._um_card(self.su)
        if not chave:
            self.skipTest("banco de teste sem acontecimento")
        r = self.client.post("/parque/mural/comentar/",
                             {"chave": chave, "texto": "conferido"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertTrue(ComentarioEvento.objects.filter(
            chave=chave, autor=self.su, texto="conferido").exists())
        # quem comenta entra na conversa: é o que a pessoa espera
        self.assertTrue(MarcaEvento.objects.filter(
            chave=chave, usuario=self.su,
            marca=MarcaEvento.Marca.SEGUINDO).exists())

    def test_assumir_liga_desliga_e_nao_duplica(self):
        from apps.parque.models import MarcaEvento
        self.client.force_login(self.su)
        chave = self._um_card(self.su)
        if not chave:
            self.skipTest("banco de teste sem acontecimento")
        self.client.post("/parque/mural/marcar/",
                         {"chave": chave, "marca": "assumido"})
        self.assertEqual(MarcaEvento.objects.filter(
            chave=chave, marca="assumido").count(), 1)
        # assumir também faz acompanhar
        self.assertTrue(MarcaEvento.objects.filter(
            chave=chave, marca="seguindo").exists())
        r = self.client.post("/parque/mural/marcar/",
                             {"chave": chave, "marca": "assumido"})
        self.assertFalse(r.json()["ligado"])
        self.assertEqual(MarcaEvento.objects.filter(
            chave=chave, marca="assumido").count(), 0)

    def test_marca_inventada_e_recusada(self):
        self.client.force_login(self.su)
        chave = self._um_card(self.su) or "x"
        r = self.client.post("/parque/mural/marcar/",
                             {"chave": chave, "marca": "dono"})
        self.assertEqual(r.status_code, 400)

    def test_so_o_autor_apaga_o_proprio_comentario(self):
        from apps.parque.models import ComentarioEvento
        c = ComentarioEvento.objects.create(chave="rep1", autor=self.chefe,
                                            texto="meu")
        self.client.force_login(self.su)  # superusuário pode apagar de outro
        self.assertEqual(self.client.post(
            "/parque/mural/apagar-comentario/", {"id": c.pk}).status_code, 200)

        c2 = ComentarioEvento.objects.create(chave="rep1", autor=self.su,
                                             texto="do outro")
        self.client.force_login(self.chefe)
        self.assertEqual(self.client.post(
            "/parque/mural/apagar-comentario/", {"id": c2.pk}).status_code, 403)
        self.assertTrue(ComentarioEvento.objects.filter(pk=c2.pk).exists())

    def test_id_de_letra_e_id_gigante_nao_estouram(self):
        """A lição da varredura de usuário leigo: id que não é número."""
        self.client.force_login(self.su)
        for valor in ("abc", "", "-1", "9" * 40, "1 OR 1=1"):
            r = self.client.post("/parque/mural/apagar-comentario/", {"id": valor})
            self.assertEqual(r.status_code, 404, msg=repr(valor))

    def test_mudanca_de_estado_exige_post(self):
        self.client.force_login(self.su)
        for url in ("/parque/mural/comentar/", "/parque/mural/marcar/",
                    "/parque/mural/apagar-comentario/"):
            self.assertEqual(self.client.get(url).status_code, 405, msg=url)

    def test_foto_de_formato_recusado(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.su)
        chave = self._um_card(self.su)
        if not chave:
            self.skipTest("banco de teste sem acontecimento")
        r = self.client.post("/parque/mural/comentar/", {
            "chave": chave,
            "foto": SimpleUploadedFile("virus.exe", b"MZ",
                                       content_type="application/exe"),
        })
        self.assertEqual(r.status_code, 400)

    def test_a_tela_abre_com_o_banco_vazio(self):
        """Mural sem nenhum acontecimento não pode dividir por zero nem
        estourar no gráfico — é como ela nasce numa instalação nova."""
        self.client.force_login(self.chefe)
        r = self.client.get("/parque/mural/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'id="mu"', r.content)
        self.assertIn(b"mu-dados", r.content)


@SEM_AXES
class MuralPublicacaoTests(TestCase):
    """PUBLICAR no mural — o que a pessoa escreve, sem evento por trás.

    O que estes testes travam:
      · a publicação presa a um patrimônio APARECE NA FICHA daquela máquina
        (é a razão de a amarra existir; sem isso é feed de empresa);
      · patrimônio inventado é recusado, senão a publicação some numa ficha
        que não existe e ninguém descobre por quê;
      · só o autor (ou superusuário) edita e apaga;
      · a marca "editada" não pode sumir depois que gente já leu.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group
        from apps.orgs.models import Location, PerfilUsuario, TelaGrupo
        from apps.parque.models import Baia, Computador, Setor

        gerente = Group.objects.create(name="Gerente")
        for tela in ("registros", "online", "logs"):
            TelaGrupo.objects.get_or_create(tela=tela, grupo=gerente)
        # As permissões de escrever no mural vêm da migração 0066 (que roda
        # antes de o grupo existir, no banco de teste). Aqui eu dou as mesmas.
        from django.contrib.auth.models import Permission
        gerente.permissions.add(*Permission.objects.filter(
            content_type__app_label="parque",
            codename__in=["add_comentarioevento", "add_publicacaomural",
                          "change_publicacaomural", "add_documentoequipamento"]))

        cls.eu = User.objects.create_user("eu", password="x", is_staff=True)
        cls.eu.groups.add(gerente)
        cls.outro = User.objects.create_user("outro", password="x", is_staff=True)
        cls.outro.groups.add(gerente)
        cls.su = User.objects.create_superuser("su2", "su2@x.com", "x")
        PerfilUsuario.objects.filter(
            usuario__in=[cls.eu, cls.outro, cls.su]).update(senha_temporaria=False)

        cls.loja = Location.objects.create(name="Loja Pub", city="Curitiba", state="PR")
        setor = Setor.objects.create(nome="TI", unidade=cls.loja)
        cls.baia = Baia.objects.create(setor=setor, nome="1 - Pub")
        if not cls.baia.computador_id:
            cls.baia.computador = Computador.objects.create(
                marca="Dell", processador="i5", memoria_ram="8 GB",
                armazenamento="SSD 480GB", sistema_operacional="Windows 11 Pro",
                patrimonio="PC-PUB001")
            cls.baia.save()

    def _publicar(self, **extra):
        dados = {"texto": "Chegaram 12 SSD."}
        dados.update(extra)
        return self.client.post("/parque/mural/publicar/", dados)

    # ------------------------------------------------------------ publicar
    def test_publicar_grava_e_entra_no_feed(self):
        from apps.parque.models import PublicacaoMural
        from apps.parque.mural import montar_eventos
        self.client.force_login(self.eu)
        r = self._publicar()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(PublicacaoMural.objects.count(), 1)
        pk = r.json()["publicacao"]["id"]
        ids = {e["id"] for e in montar_eventos(self.eu)}
        self.assertIn("pub%s" % pk, ids)

    def _um_registro(self, com_maquina=True):
        """Um card do feed para a publicação citar."""
        from apps.parque.models import Reparo
        Reparo.objects.get_or_create(baia=self.baia, tipo="reparo",
                                     titulo="Chamado para citar")
        from apps.parque.mural import montar_eventos
        for e in montar_eventos(self.eu):
            if not com_maquina or e.get("maquina"):
                return e
        return None

    def test_publicacao_citando_registro_entra_na_ficha_da_maquina(self):
        """A razão de citar existir: o post fica na ficha da máquina do
        registro, sem ninguém digitar patrimônio."""
        from apps.parque.mural import montar_eventos
        self.client.force_login(self.eu)
        reg = self._um_registro()
        if not reg:
            self.skipTest("sem registro com máquina no banco de teste")
        r = self._publicar(alvo=reg["id"])
        self.assertEqual(r.status_code, 200)
        # o patrimônio VEIO do registro
        self.assertEqual(r.json()["publicacao"]["patrimonio"], reg["maquina"])
        pk = r.json()["publicacao"]["id"]
        da_maquina = [e for e in montar_eventos(self.eu)
                      if e.get("maquina") == reg["maquina"]]
        self.assertIn("pub%s" % pk, {e["id"] for e in da_maquina})

    def test_o_card_guarda_o_retrato_do_registro_citado(self):
        """Se o registro mudar de nome (ou sumir), o card continua legível."""
        self.client.force_login(self.eu)
        reg = self._um_registro()
        if not reg:
            self.skipTest("sem registro no banco de teste")
        r = self._publicar(alvo=reg["id"])
        self.assertEqual(r.json()["publicacao"]["alvo"], reg["id"])
        self.assertEqual(r.json()["publicacao"]["alvo_titulo"],
                         (reg["titulo"] or "")[:160])

    def test_registro_citado_inventado_e_recusado(self):
        self.client.force_login(self.eu)
        r = self._publicar(alvo="nao-existe-99")
        self.assertEqual(r.status_code, 404)
        self.assertIn("não encontrado", r.json()["erro"])

    def test_ninguem_cita_registro_que_nao_ve(self):
        """A mesma trava do comentário: citar um registro de tela que não abre
        revelaria o título dele."""
        from django.contrib.auth.models import Group
        from apps.orgs.models import PerfilUsuario, TelaGrupo
        from apps.parque.models import TermoResponsabilidade
        from apps.parque.mural import montar_eventos

        # o termo só entra no feed de quem abre o Arquivo
        t = TermoResponsabilidade.objects.create(
            tipo="entrega", colaborador_nome="Fulano",
            equipamento_desc="ASUS", criado_por=self.eu)
        chave = "tm%s" % t.pk
        self.client.force_login(self.eu)   # eu (Gerente) não tenho "arquivo"
        self.assertNotIn(chave, {e["id"] for e in montar_eventos(self.eu)})
        r = self._publicar(alvo=chave)
        self.assertEqual(r.status_code, 404)

    def test_a_loja_vem_da_tag(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        from apps.parque.mural import tag
        r = self._publicar(texto="Rede cai amanhã #" + tag(self.loja.name))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PublicacaoMural.objects.get().unidade_id, self.loja.pk)
        self.assertEqual(r.json()["publicacao"]["loja"], self.loja.name)

    def test_texto_vazio_e_gigante(self):
        self.client.force_login(self.eu)
        self.assertEqual(self._publicar(texto="   ").status_code, 400)
        self.assertEqual(self._publicar(texto="a" * 6001).status_code, 400)

    def test_mencao_no_texto_vira_vinculo(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        self._publicar(texto="@outro confere isso aí")
        pub = PublicacaoMural.objects.get()
        self.assertIn(self.outro, list(pub.mencionados.all()))

    def test_arquivo_proibido_e_recusado_e_pdf_passa(self):
        """Virou ARQUIVO, não foto: PDF e planilha valem, executável não."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.eu)
        r = self._publicar(arquivo=SimpleUploadedFile(
            "x.exe", b"MZ", content_type="application/exe"))
        self.assertEqual(r.status_code, 400)

        r = self._publicar(arquivo=SimpleUploadedFile(
            "nota.pdf", b"%PDF-1.4 teste", content_type="application/pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["publicacao"]["arquivo"])
        self.assertFalse(r.json()["publicacao"]["e_imagem"])

    # -------------------------------------------------------------- editar
    def test_so_o_autor_edita_e_apaga(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        pk = self._publicar().json()["publicacao"]["id"]

        self.client.force_login(self.outro)
        r = self.client.post("/parque/mural/editar/", {"id": pk, "texto": "invadindo"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post("/parque/mural/apagar/",
                                          {"id": pk}).status_code, 403)
        self.assertEqual(PublicacaoMural.objects.get(pk=pk).texto, "Chegaram 12 SSD.")

        # superusuário modera
        self.client.force_login(self.su)
        self.assertEqual(self.client.post(
            "/parque/mural/editar/", {"id": pk, "texto": "moderado"}).status_code, 200)

    def test_editar_deixa_a_marca_de_editada(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        pk = self._publicar().json()["publicacao"]["id"]
        self.assertIsNone(PublicacaoMural.objects.get(pk=pk).editado_em)
        r = self.client.post("/parque/mural/editar/", {"id": pk, "texto": "outro texto"})
        self.assertTrue(r.json()["publicacao"]["editada"])
        self.assertIsNotNone(PublicacaoMural.objects.get(pk=pk).editado_em)

    def test_id_ruim_no_editar_e_no_apagar(self):
        self.client.force_login(self.eu)
        for valor in ("abc", "", "-1", "9" * 40, "1 OR 1=1"):
            self.assertEqual(self.client.post(
                "/parque/mural/editar/", {"id": valor, "texto": "x"}).status_code,
                404, msg=repr(valor))
            self.assertEqual(self.client.post(
                "/parque/mural/apagar/", {"id": valor}).status_code, 404, msg=repr(valor))

    def test_apagar_leva_os_comentarios_da_publicacao(self):
        from apps.parque.models import ComentarioEvento, PublicacaoMural
        self.client.force_login(self.eu)
        pk = self._publicar().json()["publicacao"]["id"]
        chave = "pub%s" % pk
        self.client.post("/parque/mural/comentar/", {"chave": chave, "texto": "ok"})
        self.assertTrue(ComentarioEvento.objects.filter(chave=chave).exists())
        self.client.post("/parque/mural/apagar/", {"id": pk})
        self.assertFalse(PublicacaoMural.objects.filter(pk=pk).exists())
        self.assertFalse(ComentarioEvento.objects.filter(chave=chave).exists())

    def test_mudanca_de_estado_exige_post(self):
        self.client.force_login(self.eu)
        for url in ("/parque/mural/publicar/", "/parque/mural/editar/",
                    "/parque/mural/apagar/"):
            self.assertEqual(self.client.get(url).status_code, 405, msg=url)

    def test_quem_nao_pode_publicar_nao_publica(self):
        """Desde 13/10/2026 o Mural ABRE para toda a equipe — mas ler e
        escrever são coisas diferentes.

        Antes a trava era a tela: o estagiário nem entrava. Agora ele entra,
        lê o que lhe diz respeito, e esbarra na permissão de modelo
        `add_publicacaomural`, que a migração 0066 deu só a RH, Gerente e
        Supervisor. É a trava que passou a sustentar sozinha o que duas
        sustentavam antes — por isso ela precisa de teste próprio.
        """
        from django.contrib.auth.models import Group
        from apps.parque.models import PublicacaoMural

        peao = User.objects.create_user("peao", password="x", is_staff=True)
        peao.groups.add(Group.objects.create(name="Estagiário"))
        from apps.orgs.models import PerfilUsuario
        PerfilUsuario.objects.filter(usuario=peao).update(senha_temporaria=False)
        self.client.force_login(peao)

        # Entra na tela...
        self.assertEqual(self.client.get("/parque/mural/").status_code, 200)
        # ...e não escreve nela.
        r = self.client.post("/parque/mural/publicar/", {"texto": "oi"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(PublicacaoMural.objects.filter(autor=peao).count(), 0)

    def test_publicacao_e_pesquisavel_pelo_texto_e_pela_mencao(self):
        """A busca da tela olha o card inteiro; aqui provo que o texto e o
        nome do mencionado chegam no que a tela vai filtrar."""
        from apps.parque.mural import montar_eventos
        self.client.force_login(self.eu)
        self._publicar(texto="Rede cai amanhã na @outro loja do Centro")
        e = [x for x in montar_eventos(self.eu) if x["tipo"] == "aviso"][0]
        self.assertIn("Rede cai", e["titulo"])
        self.assertIn("outro", " ".join(e.get("mencionados") or []))


@SEM_AXES
class MuralTagTests(TestCase):
    """As TAGS do mural — o eixo que o "tipo" não alcança.

    O que estes testes travam:
      · TODO post tem tag (foi o pedido: "todas as postagens aparecer essa
        informação também");
      · a tag automática sai de CAMPO QUE EXISTE, não de lista escrita à mão —
        mudar Reparo.tipo muda a tag;
      · rótulo de sistema virou tag curta, e literal meu não foi encurtado
        ("entre-lojas" não pode virar "lojas" porque "entre" é ligação);
      · "#Transferência" e "#transferencia" são a MESMA tag;
      · a tag da publicação é gravada em campo próprio, não relida do texto.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group, Permission
        from apps.orgs.models import Location, PerfilUsuario, TelaGrupo
        from apps.parque.models import Baia, Computador, Notebook, Setor

        gerente = Group.objects.create(name="Gerente")
        # "arquivo" também: o termo só entra no feed de quem abre o Arquivo,
        # que é a regra de acesso do mural. Sem essa linha o teste da tag
        # transversal mediria a trava, não a tag.
        for tela in ("registros", "arquivo"):
            TelaGrupo.objects.get_or_create(tela=tela, grupo=gerente)
        gerente.permissions.add(*Permission.objects.filter(
            content_type__app_label="parque",
            codename__in=["add_publicacaomural", "change_publicacaomural",
                          "add_comentarioevento"]))
        cls.eu = User.objects.create_user("tagueiro", password="x", is_staff=True)
        cls.eu.groups.add(gerente)
        PerfilUsuario.objects.filter(usuario=cls.eu).update(senha_temporaria=False)

        cls.loja = Location.objects.create(name="Loja Tag", city="Curitiba", state="PR")
        setor = Setor.objects.create(nome="TI", unidade=cls.loja)
        cls.baia = Baia.objects.create(setor=setor, nome="1 - Tag")
        if not cls.baia.computador_id:
            cls.baia.computador = Computador.objects.create(
                marca="Dell", processador="i5", memoria_ram="8 GB",
                armazenamento="SSD 480GB", sistema_operacional="Windows 11 Pro",
                patrimonio="PC-TAG001")
            cls.baia.save()
        cls.nb = Notebook.objects.create(
            marca="ASUS", modelo="X1504", patrimonio="NB-TAG001")

    # ------------------------------------------------------ o normalizador
    def test_a_mesma_tag_escrita_de_dois_jeitos_e_uma_so(self):
        from apps.parque.mural import tag
        self.assertEqual(tag("Transferência"), "transferencia")
        self.assertEqual(tag("#Movimentação de PC"), "movimentacao-de-pc")
        self.assertEqual(tag("  SEM   CONSERTO "), "sem-conserto")
        self.assertEqual(tag(""), "")
        self.assertEqual(tag(None), "")

    def test_rotulo_de_sistema_encurta_e_literal_meu_nao(self):
        """A regra que impede "entre-lojas" de virar "lojas"."""
        from apps.parque.mural import _encurta
        # rótulo humano (tem espaço/parêntese): encurta
        self.assertEqual(_encurta("Trocar computadores entre baias"),
                         "trocar-computadores")
        self.assertEqual(_encurta("Score de desempenho baixo"), "score-desempenho")
        self.assertEqual(_encurta("Armazenamento (HD / SSD)"), "armazenamento-hd")
        # literal já em forma de slug: passa intacto
        self.assertEqual(_encurta("entre-lojas"), "entre-lojas")
        self.assertEqual(_encurta("sem-documento"), "sem-documento")
        self.assertEqual(_encurta("movimentacao-de-baia"), "movimentacao-de-baia")

    def test_tag_inutil_nao_entra(self):
        from apps.parque.mural import _tags
        self.assertNotIn("outro", _tags(["Outro", "peca"]))
        self.assertIn("peca", _tags(["Outro", "peca"]))

    def test_prefixo_do_patrimonio_diz_o_equipamento(self):
        from apps.parque.mural import _tag_maquina
        self.assertEqual(_tag_maquina("NB-0029"), "notebook")
        self.assertEqual(_tag_maquina("PC-B0031"), "pc")
        self.assertEqual(_tag_maquina(""), "")
        self.assertEqual(_tag_maquina("XX-1"), "")

    # -------------------------------------------------- o feed inteiro
    def test_todo_post_tem_tag(self):
        """O pedido literal: a informação aparece em todas as postagens."""
        from apps.parque.models import Reparo
        Reparo.objects.create(baia=self.baia, tipo="reparo",
                              titulo="Chamado com tag", descricao="teste")
        from apps.parque.mural import montar_eventos
        evs = montar_eventos(self.eu)
        if not evs:
            self.skipTest("sem acontecimento no banco de teste")
        sem = [e["id"] for e in evs if not e.get("tags")]
        self.assertEqual(sem, [], msg="posts sem tag: %s" % sem)

    def test_a_tag_do_chamado_sai_do_campo_tipo(self):
        from apps.parque.models import Reparo
        from apps.parque.mural import montar_eventos
        r = Reparo.objects.create(baia=self.baia, tipo="upgrade",
                                  titulo="Upgrade de RAM")
        evs = {e["id"]: e for e in montar_eventos(self.eu)}
        tags = evs["rep%s" % r.pk]["tags"]
        self.assertIn("chamado", tags)
        self.assertIn("em-aberto", tags)
        self.assertIn("pc", tags)          # do prefixo do patrimônio
        self.assertIn(tag_de(r.get_tipo_display()), tags)

    def test_sem_documento_e_transversal(self):
        """A tag que atravessa tipo: termo pendente e envio sem laudo."""
        from apps.parque.models import TermoResponsabilidade
        from apps.parque.mural import montar_eventos
        t = TermoResponsabilidade.objects.create(
            tipo="entrega", notebook=self.nb, colaborador_nome="Fulano",
            equipamento_desc="ASUS X1504", criado_por=self.eu)
        evs = {e["id"]: e for e in montar_eventos(self.eu)}
        tags = evs["tm%s" % t.pk]["tags"]
        self.assertIn("termo", tags)
        self.assertIn("sem-assinatura", tags)
        self.assertIn("sem-documento", tags)
        self.assertIn("notebook", tags)

    def test_temas_saem_com_contagem(self):
        from apps.parque.models import Reparo
        from apps.parque.mural import montar
        Reparo.objects.create(baia=self.baia, tipo="reparo", titulo="X")
        d = montar(self.eu)
        self.assertTrue(d["temas"])
        nomes = {x["t"] for x in d["temas"]}
        self.assertIn("chamado", nomes)
        for x in d["temas"]:
            self.assertGreater(x["n"], 0)

    # --------------------------------------------------- a publicação
    def test_a_tag_escrita_no_texto_e_gravada_em_campo(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        r = self.client.post("/parque/mural/publicar/", {
            "texto": "Rede cai amanhã #Transferência #externa #transferencia"})
        self.assertEqual(r.status_code, 200)
        pub = PublicacaoMural.objects.get()
        # normalizada e sem repetido, mesmo escrita de dois jeitos
        self.assertEqual(pub.tags.split(), ["transferencia", "externa"])
        self.assertEqual(r.json()["publicacao"]["tags"],
                         ["transferencia", "externa"])

    def test_editar_recalcula_as_tags(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        pk = self.client.post("/parque/mural/publicar/",
                              {"texto": "aviso #rede"}).json()["publicacao"]["id"]
        self.client.post("/parque/mural/editar/",
                         {"id": pk, "texto": "aviso corrigido #switch #rede"})
        self.assertEqual(PublicacaoMural.objects.get(pk=pk).tags.split(),
                         ["switch", "rede"])

    def test_a_publicacao_entra_no_feed_com_as_tags(self):
        """A tag escrita entra, e a #pc vem do patrimônio do registro citado."""
        from apps.parque.models import Reparo
        from apps.parque.mural import montar_eventos
        Reparo.objects.create(baia=self.baia, tipo="reparo", titulo="Para citar")
        self.client.force_login(self.eu)
        reg = [e for e in montar_eventos(self.eu) if e.get("maquina")][0]
        pk = self.client.post("/parque/mural/publicar/", {
            "texto": "chegaram SSD #estoque",
            "alvo": reg["id"]}).json()["publicacao"]["id"]
        evs = {e["id"]: e for e in montar_eventos(self.eu)}
        tags = evs["pub%s" % pk]["tags"]
        self.assertIn("publicacao", tags)
        self.assertIn("estoque", tags)
        self.assertIn("pc", tags)   # veio do patrimônio do registro citado

    def test_tag_gigante_no_texto_nao_estoura_o_campo(self):
        from apps.parque.models import PublicacaoMural
        self.client.force_login(self.eu)
        r = self.client.post("/parque/mural/publicar/",
                             {"texto": "x #" + "a" * 400})
        self.assertEqual(r.status_code, 200)
        pub = PublicacaoMural.objects.get()
        self.assertLessEqual(len(pub.tags), 240)
        for t in pub.tags.split():
            self.assertLessEqual(len(t), 32)


def tag_de(texto):
    from apps.parque.mural import _encurta
    return _encurta(texto)


@SEM_AXES
class MuralConversaTests(TestCase):
    """A CONVERSA de duas pessoas — a aba "Usuários" virou chat.

    O teste que mais importa aqui é o de vazamento: SÓ AS DUAS PESSOAS leem.
    Superusuário não lê conversa alheia — um canal privado que o admin abre
    por padrão não é canal privado. Se algum dia alguém "melhorar" a view
    aceitando um parâmetro de terceiro, este teste cai.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group, Permission
        from apps.orgs.models import Location, PerfilUsuario, TelaGrupo
        from apps.parque.models import Baia, Computador, Setor

        gerente = Group.objects.create(name="Gerente")
        TelaGrupo.objects.get_or_create(tela="registros", grupo=gerente)
        gerente.permissions.add(*Permission.objects.filter(
            content_type__app_label="parque",
            codename__in=["add_publicacaomural", "add_comentarioevento"]))

        cls.ana = User.objects.create_user("ana", password="x", is_staff=True)
        cls.bia = User.objects.create_user("bia", password="x", is_staff=True)
        cls.caio = User.objects.create_user("caio", password="x", is_staff=True)
        cls.su = User.objects.create_superuser("su3", "su3@x.com", "x")
        for u in (cls.ana, cls.bia, cls.caio):
            u.groups.add(gerente)
        PerfilUsuario.objects.filter(
            usuario__in=[cls.ana, cls.bia, cls.caio, cls.su]).update(
            senha_temporaria=False)

        loja = Location.objects.create(name="Loja Chat", city="Curitiba", state="PR")
        setor = Setor.objects.create(nome="TI", unidade=loja)
        cls.baia = Baia.objects.create(setor=setor, nome="1 - Chat")
        if not cls.baia.computador_id:
            cls.baia.computador = Computador.objects.create(
                marca="Dell", processador="i5", memoria_ram="8 GB",
                armazenamento="SSD 480GB", sistema_operacional="Windows 11 Pro",
                patrimonio="PC-CHAT01")
            cls.baia.save()

    # ------------------------------------------------------------- mandar
    def test_mandar_e_ler(self):
        from apps.parque.models import MensagemDireta
        self.client.force_login(self.ana)
        r = self.client.post("/parque/mural/mandar/",
                             {"com": self.bia.pk, "texto": "a baia 12 pode?"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["mensagem"]["meu"])
        self.assertEqual(MensagemDireta.objects.count(), 1)

        self.client.force_login(self.bia)
        r = self.client.post("/parque/mural/conversa/", {"com": self.ana.pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["mensagens"]), 1)
        self.assertFalse(r.json()["mensagens"][0]["meu"])

    def test_abrir_a_conversa_marca_como_lida(self):
        from apps.parque.models import MensagemDireta
        self.client.force_login(self.ana)
        self.client.post("/parque/mural/mandar/",
                         {"com": self.bia.pk, "texto": "oi"})
        self.assertEqual(MensagemDireta.objects.filter(
            para=self.bia, lida_em=None).count(), 1)

        self.client.force_login(self.bia)
        r = self.client.post("/parque/mural/conversa/", {"com": self.ana.pk})
        self.assertEqual(r.json()["nao_lidas"], 0)
        self.assertEqual(MensagemDireta.objects.filter(
            para=self.bia, lida_em=None).count(), 0)

    def test_a_mensagem_pode_citar_um_registro(self):
        from apps.parque.models import MensagemDireta, Reparo
        from apps.parque.mural import montar_eventos
        Reparo.objects.create(baia=self.baia, tipo="reparo", titulo="Chamado do chat")
        self.client.force_login(self.ana)
        reg = [e for e in montar_eventos(self.ana) if e.get("maquina")][0]
        r = self.client.post("/parque/mural/mandar/", {
            "com": self.bia.pk, "texto": "isso aqui pode?", "alvo": reg["id"]})
        self.assertEqual(r.status_code, 200)
        m = MensagemDireta.objects.get()
        self.assertEqual(m.alvo, reg["id"])
        self.assertEqual(m.alvo_titulo, (reg["titulo"] or "")[:160])

    def test_registro_citado_inventado_ou_invisivel(self):
        from apps.parque.models import TermoResponsabilidade
        self.client.force_login(self.ana)
        r = self.client.post("/parque/mural/mandar/", {
            "com": self.bia.pk, "texto": "x", "alvo": "nao-existe-1"})
        self.assertEqual(r.status_code, 404)
        # termo só entra no feed de quem abre o Arquivo; ana não abre
        t = TermoResponsabilidade.objects.create(
            tipo="entrega", colaborador_nome="F", criado_por=self.ana)
        r = self.client.post("/parque/mural/mandar/", {
            "com": self.bia.pk, "texto": "x", "alvo": "tm%s" % t.pk})
        self.assertEqual(r.status_code, 404)

    def test_o_que_o_servidor_recusa(self):
        self.client.force_login(self.ana)
        for rot, dados, esperado in [
                ("vazio", {"com": self.bia.pk, "texto": "  "}, 400),
                ("gigante", {"com": self.bia.pk, "texto": "a" * 4001}, 400),
                ("comigo mesmo", {"com": self.ana.pk, "texto": "oi"}, 400),
                ("sem com", {"texto": "oi"}, 400),
                ("com de letra", {"com": "abc", "texto": "oi"}, 400),
                ("pessoa inexistente", {"com": 999999, "texto": "oi"}, 404),
        ]:
            r = self.client.post("/parque/mural/mandar/", dados)
            self.assertEqual(r.status_code, esperado, msg=rot)

    def test_arquivo_proibido_na_conversa(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.ana)
        r = self.client.post("/parque/mural/mandar/", {
            "com": self.bia.pk,
            "arquivo": SimpleUploadedFile("x.exe", b"MZ")})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/parque/mural/mandar/", {
            "com": self.bia.pk,
            "arquivo": SimpleUploadedFile("nota.pdf", b"%PDF-1.4")})
        self.assertEqual(r.status_code, 200)

    # ------------------------------------------------- O TESTE QUE IMPORTA
    def test_ninguem_le_conversa_alheia(self):
        """Terceiro não lê, e superusuário TAMBÉM NÃO."""
        self.client.force_login(self.ana)
        self.client.post("/parque/mural/mandar/",
                         {"com": self.bia.pk, "texto": "segredo do par"})

        for quem in (self.caio, self.su):
            self.client.force_login(quem)
            # pedindo a conversa "com a ana", o que volta é a conversa
            # (quem, ana) — que está vazia — e nunca a de (ana, bia)
            r = self.client.post("/parque/mural/conversa/", {"com": self.ana.pk})
            self.assertEqual(r.status_code, 200, msg=str(quem))
            textos = " ".join(m["texto"] or "" for m in r.json()["mensagens"])
            self.assertNotIn("segredo do par", textos, msg=str(quem))
            r = self.client.post("/parque/mural/conversa/", {"com": self.bia.pk})
            textos = " ".join(m["texto"] or "" for m in r.json()["mensagens"])
            self.assertNotIn("segredo do par", textos, msg=str(quem))

    def test_a_lista_traz_todo_mundo_e_conta_o_nao_lido(self):
        from apps.parque.mural import montar_conversas
        self.client.force_login(self.ana)
        self.client.post("/parque/mural/mandar/",
                         {"com": self.bia.pk, "texto": "primeira"})
        lista = montar_conversas(self.bia)
        # todo mundo ativo menos eu — a lista é a porta para COMEÇAR conversa
        self.assertEqual(len(lista), User.objects.filter(
            is_active=True).exclude(pk=self.bia.pk).count())
        da_ana = [c for c in lista if c["id"] == self.ana.pk][0]
        self.assertEqual(da_ana["nao_lidas"], 1)
        self.assertEqual(da_ana["ultima"], "primeira")
        self.assertFalse(da_ana["ultima_minha"])
        # quem tem conversa vem primeiro
        self.assertEqual(lista[0]["id"], self.ana.pk)

    def test_conversar_segue_quem_abre_o_mural(self):
        """A aba Conversas nasce de quem abre o Mural — e o Mural abriu para
        toda a equipe em 13/10/2026. Logo, toda a equipe conversa.

        Isto é CONSEQUÊNCIA da decisão, não um efeito à parte, e por isso está
        escrito: abrir a tela de leitura abriu junto a mensagem direta. O
        sigilo não mudou — `test_ninguem_le_conversa_alheia` continua valendo,
        inclusive para superusuário.
        """
        from django.contrib.auth.models import Group
        from apps.orgs.models import PerfilUsuario
        from apps.parque.models import MensagemDireta

        peao = User.objects.create_user("peao2", password="x", is_staff=True)
        peao.groups.add(Group.objects.create(name="Estagiário"))
        PerfilUsuario.objects.filter(usuario=peao).update(senha_temporaria=False)

        self.client.force_login(peao)
        r = self.client.post("/parque/mural/mandar/",
                             {"com": self.ana.pk, "texto": "oi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(MensagemDireta.objects.filter(de=peao).count(), 1)

    def test_mudanca_de_estado_exige_post(self):
        self.client.force_login(self.ana)
        for url in ("/parque/mural/mandar/", "/parque/mural/conversa/"):
            self.assertEqual(self.client.get(url).status_code, 405, msg=url)

    def test_anonimo_vai_para_o_login(self):
        for url in ("/parque/mural/mandar/", "/parque/mural/conversa/"):
            self.assertIn(self.client.post(url, {}).status_code, (301, 302), msg=url)


@SEM_AXES
class CadastroMandaSobreTelemetriaTests(TestCase):
    """21/09/2026 — "atualizo o cadastro da máquina e no parque não sobe".

    Eram dois mecanismos somados, os dois silenciosos:

      1. as specs efetivas liam `tel_* or cadastro`, então a leitura do agente
         SOMBREAVA o que a pessoa digitava (o mapa usa `Baia.eff_cpu`, que
         delega para `Computador.cpu_efetivo`);
      2. `aplicar_na_maquina` reescrevia o cadastro a cada coleta — e o agente
         coleta a cada 30 minutos —, então o valor digitado também era apagado
         do banco, sem aviso e sem deixar rastro de quem apagou.

    Decisão do Jonas: o cadastro manda; o agente só completa campo vazio. Onde
    os dois discordam, a tela mostra os dois lados em vez de um deles sumir.
    """

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone
        from apps.orgs.models import Location, Person
        from apps.parque.models import Baia, Computador, Setor, TelemetriaMaquina

        cls.loja = Location.objects.create(name="Loja Telemetria", city="Rio", state="RJ")
        setor = Setor.objects.create(nome="Vendas", unidade=cls.loja)
        cls.pessoa = Person.objects.create(full_name="Marta Ribeiro")
        # Criar baia dispara `gerar_computador_da_baia` no pre_save, que já
        # cria um Computador. Reaproveito o que vier, em vez de criar outro.
        cls.baia = Baia.objects.create(setor=setor, nome="7 - Marta",
                                       colaborador=cls.pessoa)
        cls.baia.refresh_from_db()
        pc = cls.baia.computador or Computador.objects.create()
        pc.serial = "SN-TEL-1"
        pc.processador = "Intel i7-8700"
        pc.memoria_ram = "16 GB"
        pc.armazenamento = "SSD 512GB"
        pc.sistema_operacional = "Windows 11"
        pc.save()
        if not cls.baia.computador_id:
            cls.baia.computador = pc
            cls.baia.save()
        cls.pc = pc
        # O agente leu OUTRO hardware (máquina trocada de mesa, por exemplo).
        cls.tel = TelemetriaMaquina.objects.create(
            serial="SN-TEL-1", hostname="MAQ-MARTA", computador=pc,
            cpu_modelo="Intel i3-4130", ram_gb=4, ram_tipo="DDR3",
            disco_tipo="HDD", disco_total_gb=500, so="Windows 10",
            ip_local="192.168.16.77", geo_cidade="Rio de Janeiro",
            visto_em=timezone.now(),
        )
        # É isto que o `telemetria_ingest` faz a cada coleta: espelha a leitura
        # nos campos `tel_*` da máquina. Sem esta linha o cenário não é o real —
        # a máquina ficaria com agente vinculado e telemetria em branco.
        cls.tel.aplicar_na_maquina()
        cls.pc.refresh_from_db()

    # ---------------------------------------------------- precedência de leitura
    def test_o_que_foi_digitado_e_o_que_o_parque_mostra(self):
        """O defeito relatado, na sua forma mais curta."""
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.cpu_efetivo, "Intel i7-8700")
        self.assertEqual(self.pc.ram_efetivo, "16 GB")
        self.assertEqual(self.pc.disco_efetivo, "SSD 512GB")
        self.assertEqual(self.pc.so_efetivo, "Windows 11")

    def test_o_mapa_ve_o_mesmo_que_o_cadastro(self):
        """O card do mapa lê `Baia.eff_*`, que delega para o dispositivo."""
        self.baia.refresh_from_db()
        self.assertEqual(self.baia.eff_cpu, "Intel i7-8700")
        self.assertEqual(self.baia.eff_ram, "16 GB")
        self.assertEqual(self.baia.eff_so, "Windows 11")

    def test_telemetria_aparece_quando_o_cadastro_esta_vazio(self):
        """A leitura do agente não se perde: ela preenche o que ninguém digitou."""
        self.pc.processador = ""
        self.pc.memoria_ram = ""
        self.pc.save()
        self.assertEqual(self.pc.cpu_efetivo, self.pc.tel_cpu)
        self.assertTrue(self.pc.cpu_efetivo, "sem cadastro, a telemetria tem de aparecer")

    # ------------------------------------------------------- escrita do agente
    def test_coleta_nao_apaga_o_que_foi_digitado(self):
        """O agente roda a cada 30 min; antes, era isso que sumia com a edição."""
        self.assertTrue(self.tel.aplicar_na_maquina())
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.processador, "Intel i7-8700")
        self.assertEqual(self.pc.memoria_ram, "16 GB")
        self.assertEqual(self.pc.armazenamento, "SSD 512GB")
        self.assertEqual(self.pc.sistema_operacional, "Windows 11")

    def test_coleta_completa_campo_em_branco(self):
        """Máquina nova, recém-vinculada, tem de nascer com as specs certas."""
        self.pc.processador = ""
        self.pc.armazenamento = ""
        self.pc.save(update_fields=["processador", "armazenamento"])
        self.tel.aplicar_na_maquina()
        self.pc.refresh_from_db()
        self.assertIn("i3-4130", self.pc.processador)
        self.assertTrue(self.pc.armazenamento)
        # e o que estava preenchido continua intacto
        self.assertEqual(self.pc.memoria_ram, "16 GB")

    def test_coleta_sempre_grava_os_campos_tel(self):
        """A medição continua guardada inteira, para score e para o aviso."""
        self.tel.aplicar_na_maquina()
        self.pc.refresh_from_db()
        self.assertIn("i3-4130", self.pc.tel_cpu)
        self.assertIsNotNone(self.pc.tel_visto_em)

    # -------------------------------------------------------------- divergência
    def test_divergencia_e_relatada_em_vez_de_escondida(self):
        self.pc.refresh_from_db()
        rotulos = [d[0] for d in self.pc.divergencias_telemetria]
        self.assertIn("Processador", rotulos)
        self.assertIn("Sistema", rotulos)
        par = [d for d in self.pc.divergencias_telemetria if d[0] == "Processador"][0]
        self.assertEqual(par[1], "Intel i7-8700")   # o que está no cadastro
        self.assertIn("i3-4130", par[2])            # o que o agente mediu

    def test_mesmo_valor_escrito_diferente_nao_e_divergencia(self):
        self.pc.memoria_ram = "  4   gb "
        self.pc.tel_ram = "4 GB"
        self.pc.save()
        rotulos = [d[0] for d in self.pc.divergencias_telemetria]
        self.assertNotIn("Memória", rotulos)

    def test_sem_agente_nao_ha_divergencia(self):
        from apps.parque.models import Computador
        solto = Computador.objects.create(processador="Ryzen 5")
        self.assertEqual(solto.divergencias_telemetria, [])


@SEM_AXES
class BuscaDaTelaDeTelemetriaTests(TestCase):
    """21/09/2026 — "o campo de Busca da tela de telemetria não funciona".

    Procurava em quatro campos (serial, hostname, cpu_modelo, geo_cidade) numa
    tabela de treze colunas. Quem digitava o PATRIMÔNIO — o número da etiqueta,
    e a primeira coluna da tabela — não achava nada. Idem colaborador, loja, IP
    e MAC, todos na tela e nenhum na busca.
    """

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone
        from apps.orgs.models import Location, Person
        from apps.parque.models import Baia, Computador, Setor, TelemetriaMaquina

        cls.staff = User.objects.create_superuser(
            "chefe.tel", "pessoa@exemplo.com.br", "x1Y2z3A4b5")
        cls.loja = Location.objects.create(name="Bonsucesso", city="Rio", state="RJ")
        setor = Setor.objects.create(nome="Balcão", unidade=cls.loja)
        cls.pessoa = Person.objects.create(full_name="Ana Clara Souza")
        cls.baia = Baia.objects.create(setor=setor, nome="3 - Ana",
                                       colaborador=cls.pessoa)
        cls.baia.refresh_from_db()
        pc = cls.baia.computador or Computador.objects.create()
        pc.patrimonio = "PC-B0142"
        pc.serial = "SN-BUSCA-1"
        pc.save()
        if not cls.baia.computador_id:
            cls.baia.computador = pc
            cls.baia.save()
        cls.pc = pc
        cls.tel = TelemetriaMaquina.objects.create(
            serial="SN-BUSCA-1", hostname="MAQ-ANA", computador=pc,
            mac="A1B2C3D4E5F6", cpu_modelo="Intel i5-10400",
            so="Windows 11 Pro", ip_local="192.168.16.42",
            geo_cidade="Rio de Janeiro", visto_em=timezone.now(),
        )
        # uma segunda coleta, para provar que a busca separa
        cls.outra = TelemetriaMaquina.objects.create(
            serial="SN-BUSCA-2", hostname="MAQ-OUTRA",
            cpu_modelo="AMD Ryzen 3", so="Windows 10",
            geo_cidade="Niterói", visto_em=timezone.now(),
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def _seriais(self, termo):
        r = self.client.get("/parque/agente/", {"q": termo})
        self.assertEqual(r.status_code, 200, msg=f"busca «{termo}» estourou")
        return {c.serial for c in r.context["coletas"]}

    def test_acha_pelo_patrimonio(self):
        """O caso relatado: o número da etiqueta é o que a pessoa tem na mão."""
        self.assertEqual(self._seriais("PC-B0142"), {"SN-BUSCA-1"})

    def test_acha_pelo_colaborador(self):
        self.assertEqual(self._seriais("Ana Clara"), {"SN-BUSCA-1"})

    def test_acha_pela_loja(self):
        self.assertEqual(self._seriais("Bonsucesso"), {"SN-BUSCA-1"})

    def test_acha_pelo_ip(self):
        self.assertEqual(self._seriais("192.168.16.42"), {"SN-BUSCA-1"})

    def test_acha_pelo_mac_com_dois_pontos(self):
        """A tela mostra o MAC com `:`; o banco guarda só os dígitos."""
        self.assertEqual(self._seriais("A1:B2:C3:D4:E5:F6"), {"SN-BUSCA-1"})

    def test_acha_pelo_sistema_operacional(self):
        self.assertIn("SN-BUSCA-1", self._seriais("Windows 11"))

    def test_continua_achando_pelo_serial_e_host(self):
        self.assertEqual(self._seriais("SN-BUSCA-2"), {"SN-BUSCA-2"})
        self.assertEqual(self._seriais("MAQ-ANA"), {"SN-BUSCA-1"})

    def test_duas_palavras_somam_condicoes(self):
        """«ryzen niteroi» é a Ryzen DE Niterói, não tudo que é Ryzen mais
        tudo que é de Niterói."""
        self.assertEqual(self._seriais("Ryzen Niterói"), {"SN-BUSCA-2"})
        self.assertEqual(self._seriais("Ryzen Bonsucesso"), set())

    def test_busca_sem_resultado_nao_estoura_e_conta_zero(self):
        r = self.client.get("/parque/agente/", {"q": "zzz-nao-existe"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["coletas"]), 0)
        self.assertEqual(r.context["achados"], 0)
        # e o total do parque continua visível, para a tela poder explicar
        self.assertEqual(r.context["total_coletas"], 2)

    def test_sem_busca_mostra_tudo(self):
        r = self.client.get("/parque/agente/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["coletas"]), 2)

    def test_nao_repete_a_mesma_coleta(self):
        """Os JOINs de baia/colaborador podem duplicar linha sem o distinct."""
        seriais = [c.serial for c in
                   self.client.get("/parque/agente/", {"q": "Ana"}).context["coletas"]]
        self.assertEqual(len(seriais), len(set(seriais)))


# ---------------------------------------------------------------------------
# casar_notebooks — liga o TEXTO `usuario` ao VÍNCULO `colaborador`
# ---------------------------------------------------------------------------
class CasarNotebooksTests(TestCase):
    """O comando que conserta o descasamento entre os dois campos de "quem usa".

    O defeito que ele ataca: a tabela de notebooks lê `usuario` (texto da
    planilha) e o formulário edita `colaborador` (FK). O importador só
    preenchia o texto, então a mesma máquina aparecia atribuída numa tela e
    livre na outra.
    """

    def setUp(self):
        from apps.orgs.models import Person
        from apps.parque.models import Notebook

        self.Person, self.Notebook = Person, Notebook
        self.arthur = Person.objects.create(full_name="Arthur Souza")
        self.maria = Person.objects.create(full_name="Maria da Silva")
        # Dois "Carlos": qualquer escolha automática seria chute.
        Person.objects.create(full_name="Carlos Lima")
        Person.objects.create(full_name="Carlos Prado")

    def _rodar(self, *args):
        from io import StringIO

        from django.core.management import call_command

        saida = StringIO()
        call_command("casar_notebooks", *args, stdout=saida)
        return saida.getvalue()

    def _descasado(self, texto):
        """Cria um notebook COM texto e SEM vínculo.

        Criar pelo ORM não serve: o sinal `pre_save` liga na hora, que é o
        comportamento correto hoje. O estado que este comando conserta é o das
        linhas gravadas ANTES do sinal funcionar — reproduzido aqui com
        `update()`, que não dispara sinal.
        """
        nb = self.Notebook.objects.create(usuario=texto)
        self.Notebook.objects.filter(pk=nb.pk).update(colaborador=None)
        nb.refresh_from_db()
        return nb

    def test_sem_aplicar_nao_grava(self):
        """O padrão é relatório. Gravar exige pedir."""
        nb = self._descasado("Arthur Souza")
        self._rodar()
        nb.refresh_from_db()
        self.assertIsNone(nb.colaborador)

    def test_nome_exato_liga(self):
        nb = self._descasado("Arthur Souza")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertEqual(nb.colaborador, self.arthur)

    def test_ignora_caixa_e_espaco(self):
        nb = self._descasado("  MARIA DA SILVA ")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertEqual(nb.colaborador, self.maria)

    def test_primeiro_nome_liga_quando_e_unico(self):
        """"Arthur" na planilha contra "Arthur Souza" no cadastro.

        Era exatamente isto que o fallback quebrado NÃO fazia: ele comparava
        "Arthur" com o full_name inteiro, então só casaria com alguém
        cadastrado literalmente como "Arthur".
        """
        nb = self._descasado("Arthur")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertEqual(nb.colaborador, self.arthur)

    def test_nome_parecido_nao_liga(self):
        """"Alberto" não é "Arthur": apelido e erro de digitação continuam
        sem vínculo, para decisão humana. Casar por prefixo colocaria a
        máquina na mão errada sem ninguém perceber."""
        nb = self._descasado("Alberto")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertIsNone(nb.colaborador)

    def test_prefixo_nao_engole_outro_nome(self):
        """"Ana" não pode casar com "Anatolio Prado"."""
        self.Person.objects.create(full_name="Anatolio Prado")
        nb = self._descasado("Ana")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertIsNone(nb.colaborador)

    def test_ambiguo_fica_de_fora(self):
        """Dois Carlos: ligar seria entregar a máquina à pessoa errada."""
        nb = self._descasado("Carlos")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertIsNone(nb.colaborador)

    def test_rotulo_nao_vira_pessoa(self):
        """"Vazio" e "Caixa" são rótulos da planilha, não gente."""
        nb = self._descasado("Vazio")
        self._rodar("--aplicar", "--criar-pessoas")
        nb.refresh_from_db()
        self.assertIsNone(nb.colaborador)
        self.assertFalse(self.Person.objects.filter(full_name__iexact="Vazio").exists())

    def test_nao_sobrescreve_vinculo_existente(self):
        """Vínculo feito à mão vence o texto da planilha."""
        nb = self.Notebook.objects.create(usuario="Arthur Souza", colaborador=self.maria)
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertEqual(nb.colaborador, self.maria)

    def test_nao_altera_o_texto(self):
        """`usuario` continua como veio — é o que permite rodar de novo."""
        nb = self._descasado("Alberto")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertEqual(nb.usuario, "Alberto")

    def test_criar_pessoas_so_quando_pedido(self):
        nb = self._descasado("Fulana Inexistente")
        self._rodar("--aplicar")
        nb.refresh_from_db()
        self.assertIsNone(nb.colaborador)
        self.assertFalse(self.Person.objects.filter(full_name__icontains="Inexistente").exists())

        self._rodar("--aplicar", "--criar-pessoas")
        nb.refresh_from_db()
        self.assertIsNotNone(nb.colaborador)
        self.assertEqual(nb.colaborador.full_name, "Fulana Inexistente")

    def test_relatorio_conta_certo(self):
        self._descasado("Arthur Souza")
        self._descasado("Carlos")
        self.Notebook.objects.create(usuario="")
        saida = self._rodar()
        self.assertIn("COM texto e SEM vínculo", saida)
        self.assertIn("ambíguo", saida)
        self.assertIn("MODO RELATÓRIO", saida)


@SEM_AXES
class AtalhoExcluirRelacionadoTests(TestCase):
    """O botão ao lado de um campo de seleção NÃO pode apagar o registro.

    Caso real: alguém abriu um notebook e usou o atalho ao lado de
    "Colaborador" achando que estava tirando a pessoa daquele notebook. O
    cadastro da pessoa sumiu do sistema. Só voltou porque o sinal
    `garantir_colaborador_do_usuario` recria o Person no login — para quem não
    tem conta de acesso, teria sumido em silêncio.

    A proteção vive em `apps/admin_base.py`. Ela precisa estar em
    `formfield_for_dbfield`: o wrapper com os atalhos é montado DEPOIS de
    `formfield_for_foreignkey`, então mexer lá não tem efeito nenhum — e não
    levanta erro, o que torna a regressão silenciosa.
    """

    def setUp(self):
        from apps.orgs.models import Person
        from apps.parque.models import Notebook

        self.su = User.objects.create_superuser("chefe_atalho", "a@b.com", "x")
        self.pessoa = Person.objects.create(full_name="Alvo Do Atalho")
        self.nb = Notebook.objects.create(serial="ATALHO-1", marca="Dell")
        self.client.force_login(self.su)

    def _html(self, url):
        return self.client.get(url).content.decode("utf-8", "ignore")

    def test_notebook_nao_oferece_excluir_colaborador(self):
        h = self._html("/admin/parque/notebook/%d/change/" % self.nb.pk)
        self.assertNotIn("delete_id_colaborador", h)
        self.assertNotIn("delete-related", h)

    def test_colaborador_nao_oferece_excluir_a_conta(self):
        h = self._html("/admin/orgs/person/%d/change/" % self.pessoa.pk)
        self.assertNotIn("delete_id_user", h)

    def test_baia_nao_oferece_excluir_a_maquina(self):
        """Na baia o estrago seria maior: apagaria o computador com histórico."""
        from apps.parque.models import Baia, Setor
        from apps.orgs.models import Location

        loc = Location.objects.create(name="Loja Teste")
        setor = Setor.objects.create(nome="TI", unidade=loc)
        baia = Baia.objects.create(nome="1", setor=setor)
        h = self._html("/admin/parque/baia/%d/change/" % baia.pk)
        for campo in ("computador", "notebook", "colaborador"):
            self.assertNotIn("delete_id_%s" % campo, h)

    def test_continua_dando_para_adicionar_e_alterar(self):
        """Tirar o excluir não pode tirar o resto: cadastrar pessoa nova
        direto do notebook continua valendo."""
        h = self._html("/admin/parque/notebook/%d/change/" % self.nb.pk)
        self.assertIn("add_id_colaborador", h)
        self.assertIn("change_id_colaborador", h)


class CasarBaiasTests(TestCase):
    """Liga o nome escrito na baia ao colaborador.

    Os casos vieram do servidor de produção (42 baias sem vínculo em 05/10/2026):
    38 eram posição ("Direita", "Vazio") e só 4 eram gente. Esta suíte guarda
    essa distinção — se um dia "Direita" voltar a ser tratado como pessoa, a
    auditoria volta a gritar 42 onde há 4, e ninguém mais lê o relatório.
    """

    def setUp(self):
        from apps.orgs.models import Location, Person
        from apps.parque.models import Baia, Setor

        self.Person, self.Baia = Person, Baia
        self.loc = Location.objects.create(name="Vilar")
        self.setor = Setor.objects.create(nome="Comercial", unidade=self.loc)
        self.juliana = Person.objects.create(full_name="Juliana Alves")
        self.simone = Person.objects.create(full_name="Simone Ribeiro")

    def _baia(self, nome):
        """Cria a baia e desfaz o vínculo que o signal faz, para reproduzir o
        estado das linhas gravadas antes de o casamento funcionar."""
        b = self.Baia.objects.create(nome=nome, setor=self.setor)
        self.Baia.objects.filter(pk=b.pk).update(colaborador=None)
        b.refresh_from_db()
        return b

    def _rodar(self, *args):
        from io import StringIO

        from django.core.management import call_command

        saida = StringIO()
        call_command("casar_baias", *args, stdout=saida)
        return saida.getvalue()

    def test_lado_da_mesa_nao_e_pessoa(self):
        for nome in ("3 - Direita", "2 - esquerda", "1 - Esquerda"):
            b = self._baia(nome)
            self._rodar("--aplicar")
            b.refresh_from_db()
            self.assertIsNone(b.colaborador, msg=nome)

    def test_vazio_nao_e_pessoa(self):
        b = self._baia("8 - Vazio")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)

    def test_acento_casa(self):
        """"9 - Juliana" tem de achar "Juliana Alves"."""
        b = self._baia("9 - Juliana")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertEqual(b.colaborador, self.juliana)

    def test_parentese_nao_atrapalha(self):
        """"3 - Simone (Marketing)" é a Simone; o setor entre parênteses
        impedia o casamento."""
        b = self._baia("3 - Simone (Marketing)")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertEqual(b.colaborador, self.simone)

    def test_sobrenome_sem_ficha_nao_e_ambiguo(self):
        """Medido no servidor em 05/10/2026, com o parque de verdade.

        "2 - Paula Andrade" saía como AMBÍGUO oferecendo "Paula Moreira |
        Paula Pinto | Paula Castro" e o rótulo "precisa de você".
        Nenhuma das três é a Gustavo — não há disputa, há ausência. O relatório
        estava servindo três respostas erradas para um humano escolher,
        desfazendo na leitura o que o código tinha acertado na escrita.
        """
        for nome in ("Paula Moreira", "Paula Pinto", "Paula Castro"):
            self.Person.objects.create(full_name=nome)
        b = self._baia("2 - Paula Andrade")

        saida = self._rodar("--detalhe")

        b.refresh_from_db()
        self.assertIsNone(b.colaborador)
        self.assertIn("nome sem ficha no cadastro .........     1", saida)
        self.assertIn("ambíguo (2+ pessoas) ...............     0", saida)
        # E a lista de quase-iguais sai com o aviso colado, nunca solta.
        self.assertIn("nenhuma é esta", saida)

    def test_primeiro_nome_disputado_continua_ambiguo(self):
        """O outro lado: "Paula" sozinha É disputa de verdade — duas fichas
        atendem pelo mesmo nome. Esse caso tem de continuar pedindo decisão."""
        self.Person.objects.create(full_name="Paula Moreira")
        self.Person.objects.create(full_name="Paula Pinto")
        b = self._baia("2 - Paula")

        saida = self._rodar("--aplicar")

        b.refresh_from_db()
        self.assertIsNone(b.colaborador)
        self.assertIn("ambíguo (2+ pessoas) ...............     1", saida)

    def test_duas_pessoas_numa_baia_fica_de_fora(self):
        """"2 - Paula Andrade" parece duas pessoas; nenhum automatismo
        resolve isso sem chutar."""
        self.Person.objects.create(full_name="Paula Lima")
        b = self._baia("2 - Paula Andrade")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)

    def test_sem_aplicar_nao_grava(self):
        b = self._baia("9 - Juliana")
        self._rodar()
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)

    def test_numero_puro_nao_vira_nada(self):
        b = self._baia("7")
        saida = self._rodar()
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)
        self.assertIn("só o número", saida)

    def test_relatorio_separa_rotulo_de_pessoa(self):
        self._baia("3 - Direita")
        self._baia("8 - Vazio")
        self._baia("9 - Juliana")
        saida = self._rodar()
        self.assertIn("rótulo de posição", saida)
        self.assertIn("NOME DE PESSOA que casa", saida)

    def test_desempata_pela_loja(self):
        """Tres Paulas no cadastro: Gustavo em Vilar, Lima na Taquara e
        Moreno. Pelo nome "Paula" nada casa — e nao pode casar mesmo. Mas
        uma baia DE VILAR so pode ser a Paula de Vilar.

        Caso real do servidor, contado pelo dono em 05/10/2026.
        """
        from apps.orgs.models import Location

        taquara = Location.objects.create(name="Taquara")
        pat_vilar = self.Person.objects.create(full_name="Paula Andrade", location=self.loc)
        self.Person.objects.create(full_name="Paula Lima", location=taquara)
        self.Person.objects.create(full_name="Paula Moreira")

        b = self._baia("2 - Paula")          # baia do setor de Vilar
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertEqual(b.colaborador, pat_vilar)

    def test_duas_na_mesma_loja_continua_ambiguo(self):
        """Desempatar pela loja so vale quando sobra UMA. Duas Paulas no
        mesmo lugar continuam sendo decisao humana."""
        self.Person.objects.create(full_name="Paula Andrade", location=self.loc)
        self.Person.objects.create(full_name="Paula Moreira", location=self.loc)

        b = self._baia("2 - Paula")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)

    def test_pessoa_sem_loja_nao_desempata(self):
        """O desempate exige a loja DOS DOIS lados.

        Baia sempre tem loja (setor e unidade sao obrigatorios no schema), mas
        a PESSOA pode nao ter — a auditoria achou 5 assim. Nesse caso nao da
        para desempatar, e nao se inventa.
        """
        from apps.orgs.models import Location

        taquara = Location.objects.create(name="Taquara")
        self.Person.objects.create(full_name="Paula Andrade")          # sem loja
        self.Person.objects.create(full_name="Paula Lima", location=taquara)

        b = self._baia("2 - Paula")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)

    def test_loja_nao_atropela_sobrenome(self):
        """REGRESSAO REAL (05/10/2026, servidor de producao).

        A baia "2 - Paula Andrade" em Vilar foi parar na "Paula Moreira"
        porque a Moreno e de Vilar e sobrou so ela naquela loja. O desempate por
        loja passou por cima da protecao de sobrenome: o texto dizia "Gustavo" e
        o sistema entregou a mesa para outra pessoa.

        A loja serve para escolher entre HOMONIMAS, nao para atropelar um
        sobrenome que nao bate. Com sobrenome no texto e nenhuma ficha
        correspondente, a resposta certa e "essa pessoa nao tem cadastro".
        """
        moreno = self.Person.objects.create(full_name="Paula Moreira", location=self.loc)
        b = self._baia("2 - Paula Andrade")
        self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertIsNone(
            b.colaborador,
            msg="ligou a baia da Paula Andrade a %s" % (b.colaborador,))
        self.assertNotEqual(b.colaborador, moreno)

    def test_rotulos_vistos_no_servidor_nao_sao_pessoas(self):
        """Casos reais do servidor (05/10/2026): de 11 baias acusadas como
        "pessoa sem cadastro", 8 eram rotulo de funcao ou local."""
        for nome in ("1 - Direção", "1 - Treinamento", "Monitoramento", "Teste",
                     "3 - PC perto do banheiro", "3 - direta"):
            b = self._baia(nome)
            self._rodar("--aplicar")
            b.refresh_from_db()
            self.assertIsNone(b.colaborador, msg=nome)

    def test_prefixo_baia_e_entendido(self):
        """"Baia 3 - Direita" e "Baia 5" existem no banco. Sem reconhecer o
        prefixo, o nome inteiro virava "ocupante" e o sistema procurava uma
        pessoa chamada "Baia 3 - Direita"."""
        from apps.parque.signals import partes_do_nome_da_baia

        self.assertEqual(partes_do_nome_da_baia("Baia 3 - Direita"), (3, "Direita"))
        self.assertEqual(partes_do_nome_da_baia("Baia 5"), (5, ""))
        self.assertEqual(partes_do_nome_da_baia("9 - Juliana"), (9, "Juliana"))

    def test_rotulo_com_prefixo_baia_e_ignorado(self):
        b = self._baia("Baia 3 - Direita")
        saida = self._rodar("--aplicar")
        b.refresh_from_db()
        self.assertIsNone(b.colaborador)
        self.assertIn("rótulo de posição", saida)


class QuemUsaOComputadorTests(TestCase):
    """A regra que o dono ditou em 05/10/2026, palavra por palavra:

        "Se a gente tem um computador, a gente tem que botar ele numa baia. E
        quando o computador tá na baia, ele não tem ninguém utilizando, certo?
        Se a gente quiser colocar um colaborador qualquer nessa baia, o sistema
        deve permitir (...) quando a gente retirar aquele colaborador, o PC
        continua na baia, porém sem nenhum colaborador vinculado a ele."

    Daí os três fatos que esta suíte guarda: a baia é RÓTULO (some da conta na
    hora de dizer quem usa), o vínculo nasce e morre com o colaborador da mesa,
    e máquina fora de mesa fica SEM dono — não guarda o último que a usou.
    """

    def setUp(self):
        from apps.orgs.models import Location, Person
        from apps.parque.models import Baia, Computador, Setor

        self.Baia, self.Computador = Baia, Computador
        self.loc = Location.objects.create(name="Vilar")
        self.setor = Setor.objects.create(nome="Comercial", unidade=self.loc)
        self.ana = Person.objects.create(full_name="Ana Souza")
        self.bruno = Person.objects.create(full_name="Bruno Dias")

    def _pc(self, patrimonio="PC-0001"):
        return self.Computador.objects.create(patrimonio=patrimonio)

    def _baia(self, nome="1 - Vazio", **kw):
        return self.Baia.objects.create(nome=nome, setor=self.setor, **kw)

    # --- o PC entra na mesa ---------------------------------------------

    def test_pc_na_baia_vazia_fica_sem_usuario(self):
        """Primeira frase da regra: computador numa mesa sem gente não está
        sendo usado por ninguém. Nada de inventar dono."""
        pc = self._pc()
        self._baia(computador=pc)
        pc.refresh_from_db()
        self.assertIsNone(pc.colaborador)

    def test_colaborador_na_baia_passa_a_maquina_para_ele(self):
        pc = self._pc()
        b = self._baia(computador=pc)
        b.colaborador = self.ana
        b.save()
        pc.refresh_from_db()
        self.assertEqual(pc.colaborador, self.ana)

    def test_baia_ja_nasce_com_as_duas_pontas(self):
        """Mesa criada de uma vez com PC e pessoa também vincula — o caminho de
        quem cadastra tudo numa tela só."""
        pc = self._pc()
        self._baia(computador=pc, colaborador=self.ana)
        pc.refresh_from_db()
        self.assertEqual(pc.colaborador, self.ana)

    # --- a pessoa sai, o PC fica -----------------------------------------

    def test_tirar_o_colaborador_deixa_o_pc_na_baia_sem_ninguem(self):
        """A frase que define o recurso. O PC NÃO sai da mesa; só perde o dono."""
        pc = self._pc()
        b = self._baia(computador=pc, colaborador=self.ana)
        b.colaborador = None
        b.save()

        pc.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(b.computador, pc)      # continua na baia
        self.assertIsNone(pc.colaborador)       # sem ninguém vinculado

    def test_trocar_o_colaborador_troca_o_dono_da_maquina(self):
        pc = self._pc()
        b = self._baia(computador=pc, colaborador=self.ana)
        b.colaborador = self.bruno
        b.save()
        pc.refresh_from_db()
        self.assertEqual(pc.colaborador, self.bruno)

    # --- o PC sai da mesa -------------------------------------------------

    def test_pc_que_sai_da_baia_nao_guarda_o_ultimo_usuario(self):
        """Máquina recolhida para estoque/conserto fica sem dono. Guardar o
        último seria rastro falso: o relatório diria que a Ana tem uma máquina
        que está na prateleira."""
        pc = self._pc()
        b = self._baia(computador=pc, colaborador=self.ana)
        b.computador = None
        b.save()
        pc.refresh_from_db()
        self.assertIsNone(pc.colaborador)

    def test_trocar_a_maquina_da_mesa_move_o_dono_junto(self):
        """O PC velho sai limpo e o novo assume a pessoa da mesa — tudo no
        mesmo save."""
        velho, novo = self._pc("PC-0001"), self._pc("PC-0002")
        b = self._baia(computador=velho, colaborador=self.ana)

        b.computador = novo
        b.save()

        velho.refresh_from_db()
        novo.refresh_from_db()
        self.assertIsNone(velho.colaborador)
        self.assertEqual(novo.colaborador, self.ana)

    def test_pc_fora_de_qualquer_baia_nao_tem_dono(self):
        pc = self._pc()
        self.assertIsNone(pc.colaborador)

    # --- o caminho de volta: da pessoa para os bens ------------------------

    def test_a_pessoa_enxerga_as_maquinas_dela(self):
        """`related_name="computadores"` é o que responde "o que a Ana usa?"
        sem passar por baia — a pergunta que a tela de cadastro faz."""
        pc = self._pc()
        self._baia(computador=pc, colaborador=self.ana)
        self.assertEqual(list(self.ana.computadores.all()), [pc])

    def test_apagar_a_baia_nao_apaga_o_computador(self):
        """Regra dita pelo dono em 13/10/2026: "caso exclua, o pc saia da baia,
        mas sem ser apagado"."""
        pc = self._pc()
        b = self._baia(computador=pc, colaborador=self.ana)

        b.delete()

        pc.refresh_from_db()                     # não estourou: continua existindo
        self.assertEqual(self.Computador.objects.filter(pk=pc.pk).count(), 1)
        self.assertIsNone(pc.colaborador)        # sem mesa, sem usuário
        self.assertEqual(pc.status, self.Computador.Status.EM_ESTOQUE)

    def test_apagar_a_baia_nao_mexe_em_maquina_com_defeito(self):
        """Defeito e Desativado são decisão de gente; apagar uma mesa não pode
        "consertar" o status de uma máquina quebrada mandando-a para o estoque."""
        pc = self._pc()
        self.Computador.objects.filter(pk=pc.pk).update(
            status=self.Computador.Status.DEFEITO)
        b = self._baia(computador=pc)

        b.delete()

        pc.refresh_from_db()
        self.assertEqual(pc.status, self.Computador.Status.DEFEITO)

    def test_excluir_pelo_mapa_apaga_a_mesa_e_devolve_o_pc(self):
        """O caminho real do botão da ficha: POST em parque_excluir_dispositivos.
        Vale a pena provar a rota inteira, não só o signal — foi o signal que eu
        escrevi, mas é o botão que o Jonas vai clicar."""
        from django.contrib.auth.models import User

        su = User.objects.create_superuser("su2", "su2@x.com", "x1y2z3w4!A")
        pc = self._pc()
        b = self._baia(computador=pc, colaborador=self.ana)

        self.client.force_login(su)
        r = self.client.post("/parque/excluir-dispositivos/", {
            "modelo": "baia", "itens": [str(b.pk)],
            "next": "/parque/mapa-completo/",
        })

        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.Baia.objects.filter(pk=b.pk).exists())
        pc.refresh_from_db()
        self.assertEqual(pc.status, self.Computador.Status.EM_ESTOQUE)
        self.assertIsNone(pc.colaborador)

    def test_quem_nao_pode_excluir_nao_excui_pela_rota(self):
        """O `{% if %}` do template só esconde o botão. A trava é o servidor."""
        from django.contrib.auth.models import User

        comum = User.objects.create_user("comum", "c@x.com", "x1y2z3w4!A",
                                         is_staff=True)
        b = self._baia(nome="Teste")

        self.client.force_login(comum)
        self.client.post("/parque/excluir-dispositivos/", {
            "modelo": "baia", "itens": [str(b.pk)],
        })

        self.assertTrue(self.Baia.objects.filter(pk=b.pk).exists())

    def test_apagar_baia_vazia_nao_quebra(self):
        """O caso que motivou tudo: as baias "Teste" e "Monitoramento", sem
        equipamento nenhum."""
        b = self._baia(nome="Teste")
        b.delete()
        self.assertFalse(self.Baia.objects.filter(pk=b.pk).exists())

    def test_salvar_a_baia_sem_mudar_nada_nao_remexe_no_pc(self):
        """Espelhamento não é edição: um save qualquer da baia (mudar o nome,
        por exemplo) não pode marcar o computador como alterado agora — senão
        toda a auditoria de "atualizado em" vira ruído."""
        pc = self._pc()
        b = self._baia(computador=pc, colaborador=self.ana)
        pc.refresh_from_db()
        carimbo = pc.atualizado_em

        b.nome = "1 - Ana"
        b.save()

        pc.refresh_from_db()
        self.assertEqual(pc.atualizado_em, carimbo)
