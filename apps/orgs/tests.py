"""Testes do fluxo de recuperação de senha por senha temporária."""

import re

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import LogAcesso, PerfilUsuario, Person


class BackendQueFalha:
    """Backend de e-mail que sempre falha (para testar o caminho de erro)."""

    def __init__(self, *a, **k):
        pass

    def send_messages(self, messages):
        raise OSError("falha de SMTP simulada")


# O django-axes exige `request` em authenticate(); nos testes chamamos
# authenticate()/client.login() direto, então o backend de bloqueio sai de cena
# (o que está sob teste aqui é a recuperação de senha, não o anti-brute-force).
SEM_AXES = override_settings(
    AUTHENTICATION_BACKENDS=["apps.orgs.backends.EmailOuUsernameBackend"],
    AXES_ENABLED=False,
)


@SEM_AXES
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RecuperacaoSenhaTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.user = User.objects.create_user(
            username="fulano", email="pessoa@exemplo.com.br",
            password="SenhaAntigaForte9", is_staff=True, is_active=True,
        )

    def _pedir(self, identificador=None):
        return self.client.post(
            reverse("admin_password_reset"),
            {"identificador": identificador or self.user.email},
        )

    def _senha_do_email(self):
        return re.search(r"Senha temporária:\s*(\S+)", mail.outbox[-1].body).group(1)

    def test_gera_senha_temporaria_e_envia_email(self):
        r = self._pedir()
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        senha = self._senha_do_email()
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("SenhaAntigaForte9"))
        self.assertTrue(self.user.check_password(senha))
        perfil = PerfilUsuario.objects.get(usuario=self.user)
        self.assertTrue(perfil.senha_temporaria)
        self.assertIsNotNone(perfil.senha_temporaria_em)
        self.assertTrue(LogAcesso.objects.filter(
            usuario=self.user, evento=LogAcesso.Evento.RECUPERACAO).exists())

    def test_email_avisa_o_prazo_de_validade(self):
        self._pedir()
        self.assertIn("Essa senha vale por 24 horas", mail.outbox[-1].body)

    def test_aceita_o_nome_de_usuario_no_lugar_do_email(self):
        """Quem não decora o e-mail cadastrado pede pelo usuário — e o envio vai
        para o e-mail da CONTA, não para o que foi digitado."""
        r = self._pedir("fulano")
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_conta_sem_email_nao_envia_e_nao_mexe_na_senha(self):
        User.objects.create_user(username="semmail", password="SenhaAntigaForte9",
                                 is_staff=True)
        r = self._pedir("semmail")
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(
            User.objects.get(username="semmail").check_password("SenhaAntigaForte9"))

    def test_email_inexistente_nao_revela_e_nao_envia(self):
        r = self._pedir("pessoa@exemplo.com.br")
        self.assertRedirects(r, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_falha_no_envio_nao_troca_a_senha(self):
        with override_settings(EMAIL_BACKEND="apps.orgs.tests.BackendQueFalha"):
            self._pedir()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("SenhaAntigaForte9"))
        self.assertFalse(PerfilUsuario.objects.filter(
            usuario=self.user, senha_temporaria=True).exists())

    def test_falha_no_envio_aparece_na_propria_tela(self):
        """O erro tem de ser VISÍVEL: antes ele ia para a fila de mensagens e a
        tela de recuperação não renderizava mensagem nenhuma."""
        with override_settings(EMAIL_BACKEND="apps.orgs.tests.BackendQueFalha"):
            r = self._pedir()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Não foi possível enviar o e-mail agora")

    def test_rate_limit_bloqueia_apos_o_maximo(self):
        for _ in range(3):
            self._pedir()
        self.assertEqual(len(mail.outbox), 3)
        self._pedir()  # 4º pedido — deve ser barrado
        self.assertEqual(len(mail.outbox), 3)

    def test_rate_limit_nao_zera_trocando_o_cabecalho_de_proxy(self):
        """A chave do limite é o identificador, não o IP: atrás do túnel o IP
        vem de cabeçalho (forjável) e trocá-lo zerava o contador."""
        for n in range(3):
            self.client.post(reverse("admin_password_reset"),
                             {"identificador": self.user.email},
                             HTTP_X_FORWARDED_FOR="203.0.113.{}".format(n))
        self.assertEqual(len(mail.outbox), 3)
        self.client.post(reverse("admin_password_reset"),
                         {"identificador": self.user.email},
                         HTTP_X_FORWARDED_FOR="203.0.113.99")
        self.assertEqual(len(mail.outbox), 3)

    def test_senha_temporaria_expirada_nao_autentica(self):
        self._pedir()
        senha = self._senha_do_email()
        perfil = PerfilUsuario.objects.get(usuario=self.user)
        perfil.senha_temporaria_em = timezone.now() - timezone.timedelta(hours=48)
        perfil.save(update_fields=["senha_temporaria_em"])
        self.assertIsNone(authenticate(username="fulano", password=senha))

    def test_login_explica_que_a_senha_temporaria_expirou(self):
        self._pedir()
        senha = self._senha_do_email()
        perfil = PerfilUsuario.objects.get(usuario=self.user)
        perfil.senha_temporaria_em = timezone.now() - timezone.timedelta(hours=48)
        perfil.save(update_fields=["senha_temporaria_em"])
        r = self.client.post("/admin/login/", {"username": "fulano", "password": senha})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sua senha temporária expirou")

    def test_middleware_obriga_troca_e_troca_limpa_flag(self):
        self._pedir()
        senha = self._senha_do_email()
        self.assertTrue(self.client.login(username="fulano", password=senha))
        # qualquer página redireciona p/ trocar-senha
        r = self.client.get("/admin/")
        self.assertRedirects(r, reverse("trocar_senha"), target_status_code=200)
        # senha fraca é rejeitada pelos validadores → flag continua ligada
        r2 = self.client.post(reverse("trocar_senha"),
                              {"new_password1": "123", "new_password2": "123"})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(PerfilUsuario.objects.get(usuario=self.user).senha_temporaria)
        # senha forte conclui o fluxo
        r3 = self.client.post(reverse("trocar_senha"),
                              {"new_password1": "NovaSenhaForte9", "new_password2": "NovaSenhaForte9"})
        self.assertRedirects(r3, reverse("admin:index"))
        perfil = PerfilUsuario.objects.get(usuario=self.user)
        self.assertFalse(perfil.senha_temporaria)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NovaSenhaForte9"))
        self.assertTrue(LogAcesso.objects.filter(
            usuario=self.user, evento=LogAcesso.Evento.TROCA_SENHA).exists())

    def test_nao_empilha_avisos_repetidos(self):
        """Antes, cada página bloqueada enfileirava outro warning e o usuário
        levava uma pilha de avisos repetidos ao concluir a troca. Agora quem
        explica o motivo é a própria tela de troca."""
        self._pedir()
        senha = self._senha_do_email()
        self.client.login(username="fulano", password=senha)
        for _ in range(4):
            self.client.get("/admin/")
        tela = self.client.get(reverse("trocar_senha"))
        self.assertContains(tela, "Você entrou com uma senha temporária")
        r = self.client.post(
            reverse("trocar_senha"),
            {"new_password1": "NovaSenhaForte9", "new_password2": "NovaSenhaForte9"},
            follow=True,
        )
        mensagens = [str(m) for m in r.context["messages"]]
        self.assertEqual(len(mensagens), 1)
        self.assertIn("sucesso", mensagens[0])


@SEM_AXES
class TrocaDeSenhaProtegidaTests(TestCase):
    """A tela /trocar-senha/ não pode ser um atalho para trocar a senha de uma
    sessão esquecida aberta: sem senha temporária, ela exige a senha atual."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="normal", email="pessoa@exemplo.com.br",
            password="SenhaAtualForte9", is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.user)

    def test_sem_senha_temporaria_exige_a_senha_atual(self):
        r = self.client.post(reverse("trocar_senha"), {
            "new_password1": "InvasorForte99", "new_password2": "InvasorForte99",
        })
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("InvasorForte99"))
        self.assertTrue(self.user.check_password("SenhaAtualForte9"))

    def test_com_a_senha_atual_correta_a_troca_passa(self):
        r = self.client.post(reverse("trocar_senha"), {
            "old_password": "SenhaAtualForte9",
            "new_password1": "OutraSenhaForte9", "new_password2": "OutraSenhaForte9",
        })
        self.assertRedirects(r, reverse("admin:index"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OutraSenhaForte9"))

    def test_com_senha_temporaria_nao_pede_a_antiga(self):
        PerfilUsuario.objects.update_or_create(
            usuario=self.user,
            defaults={"senha_temporaria": True, "senha_temporaria_em": timezone.now()},
        )
        r = self.client.post(reverse("trocar_senha"), {
            "new_password1": "PrimeiraSenhaForte9", "new_password2": "PrimeiraSenhaForte9",
        })
        self.assertRedirects(r, reverse("admin:index"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("PrimeiraSenhaForte9"))

    def test_tem_como_sair_da_troca_obrigatoria(self):
        PerfilUsuario.objects.update_or_create(
            usuario=self.user,
            defaults={"senha_temporaria": True, "senha_temporaria_em": timezone.now()},
        )
        html = self.client.get(reverse("trocar_senha")).content.decode()
        self.assertIn(reverse("admin:logout"), html)
        r = self.client.post(reverse("admin:logout"))
        self.assertIn(r.status_code, (200, 302))


# ===========================================================================
# ACESSOS — o registro único de telas, o menu e a tela /parque/acessos/
# ===========================================================================
@SEM_AXES
class AcessoEquivalenteTests(TestCase):
    """A TRAVA DESTA MUDANÇA.

    Antes, "quem entra na tela X" estava escrito em dois lugares: a condição do
    item no menu e o `if` dentro da view. Isso virou um registro único
    (apps/orgs/acessos.py) mais uma tabela (orgs.TelaGrupo) semeada por
    migração.

    Este teste prova que o resultado é IDÊNTICO ao de antes: a lista abaixo foi
    transcrita das condições que existiam, uma por uma, e é comparada com o que
    o sistema responde agora. Se alguém mexer no registro sem querer, cai aqui.
    """

    # Transcrito de config/settings/base.py e das views, ANTES da unificação.
    ESPERADO = {
        "Estagiário": set(),
        "Desenvolvimento": {"acessos"},
        "Diretor": set(),
        "Técnico de Pós Venda": {"aprovacoes", "acessos"},
        "RH": {"dashboard", "arquivo", "registros"},
        "Supervisor": {"dashboard", "arquivo", "registros", "aprovacoes",
                       "acessos", "online", "logs"},
        "Gerente": {"dashboard", "arquivo", "registros", "aprovacoes",
                    "acessos", "online", "logs"},
        "Visão total": {"dashboard", "arquivo"},
    }

    def setUp(self):
        from django.contrib.auth.models import Group
        for nome in self.ESPERADO:
            Group.objects.get_or_create(name=nome)
        # semeia como a migração faz
        from apps.orgs.migrations import __name__ as _  # noqa: F401
        from apps.orgs.models import TelaGrupo
        from apps.orgs.acessos import TELAS
        TelaGrupo.objects.all().delete()
        for t in TELAS:
            for nome in t.grupos:
                g = Group.objects.filter(name=nome).first()
                if g:
                    TelaGrupo.objects.get_or_create(tela=t.id, grupo=g)

    def _usuario(self, grupo=None, **kw):
        from django.contrib.auth.models import Group
        u = User.objects.create_user(
            username=("u-" + (grupo or "sem")).replace(" ", "-").lower(),
            password="SenhaForte9x", is_staff=True, **kw)
        if grupo:
            u.groups.add(Group.objects.get(name=grupo))
        return u

    def test_cada_grupo_abre_exatamente_o_que_abria_antes(self):
        from apps.orgs.acessos import ABERTAS, telas_do_usuario
        abertas = {t.id for t in ABERTAS}
        for grupo, restritas in self.ESPERADO.items():
            u = self._usuario(grupo)
            self.assertEqual(
                telas_do_usuario(u), abertas | restritas,
                msg="mudou o acesso do grupo %s" % grupo)

    def test_sem_grupo_ve_so_as_abertas(self):
        from apps.orgs.acessos import ABERTAS, telas_do_usuario
        u = self._usuario()
        self.assertEqual(telas_do_usuario(u), {t.id for t in ABERTAS})

    def test_superusuario_ve_tudo_e_anonimo_nada(self):
        from django.contrib.auth.models import AnonymousUser
        from apps.orgs.acessos import POR_ID, telas_do_usuario
        su = self._usuario(is_superuser=True)
        self.assertEqual(telas_do_usuario(su), set(POR_ID))
        self.assertEqual(telas_do_usuario(AnonymousUser()), set())

    def test_tela_aberta_nao_e_trancavel_e_restrita_sem_grupo_fecha(self):
        """Os três estados: aberta por desenho, restrita com grupo, restrita
        sem ninguém. O terceiro é o que impede a tela de acessos de mentir:
        tirar todos os grupos TRANCA, não volta ao padrão do código."""
        from apps.orgs.models import TelaGrupo
        from apps.orgs.acessos import pode_ver_tela
        u = self._usuario("RH")

        # "arquivo" é o exemplo de RESTRITA aqui. Era "registros" até 13/10/2026,
        # quando o Mural passou a ser aberto a toda a equipe — e aí ele deixou
        # de servir de exemplo de tela trancável.
        self.assertTrue(pode_ver_tela(u, "mapa"))        # aberta
        self.assertTrue(pode_ver_tela(u, "arquivo"))     # restrita, tem grupo

        TelaGrupo.objects.filter(tela="arquivo").delete()
        self.assertFalse(pode_ver_tela(u, "arquivo"),
                         "tela restrita sem grupo tem de fechar, não voltar ao padrão")

    def test_a_view_e_o_menu_respondem_a_mesma_coisa(self):
        """Menu mais frouxo que a view entrega 403 na cara; menu mais restrito
        esconde tela que a pessoa pode abrir. Aqui os dois são comparados."""
        from django.conf import settings
        from apps.orgs.acessos import pode_ver_tela

        class Req:
            def __init__(self, u):
                self.user = u

        # o link de cada item -> a tela do registro
        from apps.orgs.acessos import TELAS
        por_link = {t.url: t.id for t in TELAS}
        for grupo in self.ESPERADO:
            u = self._usuario(grupo)
            for secao in settings.UNFOLD["SIDEBAR"]["navigation"]:
                for item in secao.get("items", []):
                    tela = por_link.get(item.get("link"))
                    if not tela:
                        continue
                    perm = item.get("permission")
                    no_menu = perm(Req(u)) if perm else True
                    self.assertEqual(
                        bool(no_menu), pode_ver_tela(u, tela),
                        msg="menu e regra divergem em %s para %s" % (tela, grupo))


@SEM_AXES
class TelaDeAcessosTests(TestCase):
    """A tela /parque/acessos/ e as duas gravações."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from apps.orgs.models import TelaGrupo
        from apps.orgs.acessos import TELAS
        for nome in ["Gerente", "Supervisor", "RH", "Estagiário", "Visão total",
                     "Técnico de Pós Venda", "Desenvolvimento", "Diretor"]:
            Group.objects.get_or_create(name=nome)
        TelaGrupo.objects.all().delete()
        for t in TELAS:
            for nome in t.grupos:
                g = Group.objects.filter(name=nome).first()
                if g:
                    TelaGrupo.objects.get_or_create(tela=t.id, grupo=g)

        self.su = User.objects.create_user(username="chefe", password="SenhaForte9x",
                                           is_staff=True, is_superuser=True)
        self.gerente = User.objects.create_user(username="ger", password="SenhaForte9x",
                                                is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="Gerente"))
        self.rh = User.objects.create_user(username="rh", password="SenhaForte9x",
                                           is_staff=True)
        self.rh.groups.add(Group.objects.get(name="RH"))
        self.peao = User.objects.create_user(username="peao", password="SenhaForte9x",
                                             is_staff=True)

    # -------------------------------------------------------------- a tela
    def test_abre_para_quem_pode_e_nega_o_resto(self):
        self.client.force_login(self.su)
        r = self.client.get("/parque/acessos/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuários e permissões")

        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get("/parque/acessos/").status_code, 200)

        self.client.force_login(self.rh)   # RH não tem esta tela
        self.assertIn(self.client.get("/parque/acessos/").status_code, (302, 403))

        self.client.logout()
        r = self.client.get("/parque/acessos/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

    # ------------------------------------------------------ pessoa ↔ grupo
    def test_grava_os_grupos_da_pessoa(self):
        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/pessoa/",
                             {"usuario": self.peao.pk, "grupos": ["RH", "Visão total"]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(set(self.peao.groups.values_list("name", flat=True)),
                         {"RH", "Visão total"})

    def test_grupo_inexistente_nao_passa(self):
        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/pessoa/",
                             {"usuario": self.peao.pk, "grupos": ["Chefão"]})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.peao.groups.exists())

    def test_ninguem_concede_acesso_que_nao_tem(self):
        """A trava contra promoção. Gerente não vê o Arquivo? Então não pode
        colocar ninguém no RH, que destrava o Arquivo. Sem isto, quem tem esta
        tela se promove a qualquer coisa.

        O exemplo era o Mural até 13/10/2026; ele virou tela aberta e deixou de
        poder ser tirado de alguém. A trava testada é a mesma."""
        from apps.orgs.acessos import POR_ID
        from apps.orgs.models import TelaGrupo
        # tira o Arquivo do Gerente: agora ele não vê essa tela
        TelaGrupo.objects.filter(tela="arquivo", grupo__name="Gerente").delete()

        self.client.force_login(self.gerente)
        r = self.client.post("/parque/acessos/pessoa/",
                             {"usuario": self.peao.pk, "grupos": ["RH"]})
        self.assertEqual(r.status_code, 403)
        # o aviso cita a tela pelo NOME QUE ESTÁ NO REGISTRO, não por um texto
        # fixo aqui — renomear a tela não pode quebrar este teste de novo
        self.assertIn(POR_ID["arquivo"].nome, r.json()["erro"])
        self.assertFalse(self.peao.groups.exists())

    def test_so_superusuario_mexe_em_superusuario(self):
        self.client.force_login(self.gerente)
        r = self.client.post("/parque/acessos/pessoa/",
                             {"usuario": self.su.pk, "grupos": []})
        self.assertEqual(r.status_code, 403)

    def test_acoes_exigem_post(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.get("/parque/acessos/pessoa/").status_code, 405)
        self.assertEqual(self.client.get("/parque/acessos/grupo/").status_code, 405)

    # -------------------------------------------------------- grupo → tela
    def test_so_superusuario_muda_o_que_o_grupo_destrava(self):
        from django.contrib.auth.models import Group
        g = Group.objects.get(name="Estagiário")
        self.client.force_login(self.gerente)
        r = self.client.post("/parque/acessos/grupo/",
                             {"grupo": g.pk, "telas": ["dashboard"]})
        self.assertEqual(r.status_code, 403)

        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/grupo/",
                             {"grupo": g.pk, "telas": ["dashboard"]})
        self.assertEqual(r.status_code, 200)

        from apps.orgs.acessos import grupos_da_tela
        self.assertIn("Estagiário", grupos_da_tela("dashboard"))

    def test_tela_aberta_ou_inventada_nao_entra_no_mapa(self):
        from django.contrib.auth.models import Group
        g = Group.objects.get(name="Diretor")
        self.client.force_login(self.su)
        for pedido in (["mapa"], ["tela-que-nao-existe"]):
            r = self.client.post("/parque/acessos/grupo/", {"grupo": g.pk, "telas": pedido})
            self.assertEqual(r.status_code, 400, msg=str(pedido))

    def test_diretor_ganha_acesso_pela_tela(self):
        """O caso real que a tela achou: o grupo Diretor não abria nada."""
        from django.contrib.auth.models import Group
        from apps.orgs.acessos import telas_do_usuario
        diretor = User.objects.create_user(username="dir", password="SenhaForte9x",
                                           is_staff=True)
        diretor.groups.add(Group.objects.get(name="Diretor"))
        antes = telas_do_usuario(diretor)
        self.assertNotIn("dashboard", antes)

        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/grupo/",
                             {"grupo": Group.objects.get(name="Diretor").pk,
                              "telas": ["dashboard", "arquivo", "aprovacoes"]})
        self.assertEqual(r.status_code, 200)
        depois = telas_do_usuario(diretor)
        self.assertTrue({"dashboard", "arquivo", "aprovacoes"} <= depois)


    # ------------------------------------------------------ criar e excluir
    def test_cria_grupo_pela_tela(self):
        """A tela substituiu /admin/auth/group/ no menu: sem criar aqui, ela
        substituiu pela metade e mandava a pessoa de volta ao admin."""
        from django.contrib.auth.models import Group
        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/grupo/novo/", {"nome": "Diretoria"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Group.objects.filter(name="Diretoria").exists())

    def test_cria_grupo_ja_destravando_telas(self):
        from django.contrib.auth.models import Group
        from apps.orgs.acessos import grupos_da_tela
        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/grupo/novo/",
                             {"nome": "Auditoria", "telas": ["arquivo", "dashboard"]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Group.objects.filter(name="Auditoria").exists())
        self.assertIn("Auditoria", grupos_da_tela("arquivo"))
        self.assertIn("Auditoria", grupos_da_tela("dashboard"))
        self.assertNotIn("Auditoria", grupos_da_tela("logs"))

    def test_nome_ruim_ou_repetido_nao_cria(self):
        from django.contrib.auth.models import Group
        self.client.force_login(self.su)
        for nome in ("", "A", "  "):
            r = self.client.post("/parque/acessos/grupo/novo/", {"nome": nome})
            self.assertEqual(r.status_code, 400, msg=repr(nome))
        # repetido, inclusive com outra caixa
        r = self.client.post("/parque/acessos/grupo/novo/", {"nome": "gerente"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Group.objects.filter(name__iexact="gerente").count(), 1)

    def test_criar_e_excluir_sao_de_superusuario(self):
        from django.contrib.auth.models import Group
        self.client.force_login(self.gerente)
        r = self.client.post("/parque/acessos/grupo/novo/", {"nome": "Turma do Ge"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Group.objects.filter(name="Turma do Ge").exists())

        g = Group.objects.create(name="Temporario")
        r = self.client.post("/parque/acessos/grupo/excluir/", {"grupo": g.pk})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Group.objects.filter(pk=g.pk).exists())

    def test_grupo_com_gente_nao_e_excluido(self):
        """Apagar grupo com gente dentro tira acesso de todos de uma vez e sem
        rastro. A tela recusa e diz quantas pessoas tirar antes."""
        from django.contrib.auth.models import Group
        g = Group.objects.get(name="RH")
        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/grupo/excluir/", {"grupo": g.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn("pessoa", r.json()["erro"])
        self.assertTrue(Group.objects.filter(pk=g.pk).exists())

    def test_grupo_vazio_sai_com_o_mapa_dele(self):
        from django.contrib.auth.models import Group
        from apps.orgs.models import TelaGrupo
        g = Group.objects.create(name="Sobra")
        TelaGrupo.objects.create(tela="logs", grupo=g)
        self.client.force_login(self.su)
        r = self.client.post("/parque/acessos/grupo/excluir/", {"grupo": g.pk})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Group.objects.filter(name="Sobra").exists())
        self.assertFalse(TelaGrupo.objects.filter(grupo_id=g.pk).exists())


    # ------------------------------------------------- gente errando (leigo)
    def test_id_de_letra_nao_quebra(self):
        """A varredura do usuário leigo achou 500 nas três rotas desta tela:
        `filter(pk="abc")` estoura ValueError. Agora é "não encontrado"."""
        self.client.force_login(self.su)
        casos = [
            ("/parque/acessos/pessoa/", {"usuario": "abc", "grupos": ["RH"]}),
            ("/parque/acessos/pessoa/", {"usuario": "-1"}),
            ("/parque/acessos/pessoa/", {"usuario": "99999999999999999999"}),
            ("/parque/acessos/grupo/", {"grupo": "abc", "telas": ["arquivo"]}),
            ("/parque/acessos/grupo/excluir/", {"grupo": "abc"}),
            ("/parque/acessos/grupo/novo/", {"nome": "x" * 10000}),
        ]
        for url, dados in casos:
            r = self.client.post(url, dados)
            self.assertLess(r.status_code, 500, msg=url + " " + str(dados)[:60])
            self.assertIn(r.status_code, (400, 404), msg=url + " " + str(dados)[:60])


class DesligarFechaAPortaTests(TestCase):
    """O buraco medido em 13/10/2026, antes de existir a regra: desligar a
    pessoa não desativava a conta. O Alberto Pinheiro saiu da empresa e a conta
    dele continuava abrindo 11 telas.

    Estes testes são a medição virando garantia — era a resposta à pergunta do
    dono, "quem me garante?".
    """

    SENHA = "SenhaForte9x!"

    def _pessoa_com_conta(self, nome="Fulano de Tal", usuario="fulano", **kw):
        conta = User.objects.create_user(usuario, f"{usuario}@x.com", self.SENHA,
                                         is_staff=True, **kw)
        pessoa = Person.objects.filter(user=conta).first()
        if pessoa is None:
            pessoa = Person.objects.create(full_name=nome, user=conta)
        return pessoa, conta

    # --- o vínculo novo ---------------------------------------------------

    def test_desligar_a_pessoa_desativa_a_conta(self):
        pessoa, conta = self._pessoa_com_conta()
        self.assertTrue(conta.is_active)

        pessoa.active = False
        pessoa.save()

        conta.refresh_from_db()
        self.assertFalse(conta.is_active)

    def test_data_de_desligamento_tambem_fecha(self):
        """Quem preenche a data está desligando, mesmo sem desmarcar "ativo" —
        os dois campos dizem a mesma coisa e a tela deixa usar qualquer um."""
        pessoa, conta = self._pessoa_com_conta(usuario="beltrano")
        pessoa.data_desligamento = timezone.now().date()
        pessoa.save()

        conta.refresh_from_db()
        self.assertFalse(conta.is_active)

    def test_religar_a_pessoa_nao_religa_a_conta(self):
        """Só vai num sentido, de propósito: devolver acesso é decisão de quem
        administra, não efeito colateral de uma edição de cadastro. Fechar
        errado se conserta num clique; abrir errado ninguém fica sabendo."""
        pessoa, conta = self._pessoa_com_conta(usuario="ciclano")
        pessoa.active = False
        pessoa.save()

        pessoa.active = True
        pessoa.save()

        conta.refresh_from_db()
        self.assertFalse(conta.is_active)

    def test_superusuario_nao_perde_acesso_por_edicao_de_cadastro(self):
        """Trancar quem administra, e com isso ficar sem ninguém que possa
        reabrir, tem de ser decisão explícita."""
        pessoa, conta = self._pessoa_com_conta(usuario="chefe", is_superuser=True)
        pessoa.active = False
        pessoa.save()

        conta.refresh_from_db()
        self.assertTrue(conta.is_active)

    # --- o que desativar realmente faz (medido em 13/10) -------------------

    def test_a_sessao_ja_aberta_cai_na_hora(self):
        """O caso que mais importa: a pessoa está logada quando o RH desliga."""
        pessoa, conta = self._pessoa_com_conta(usuario="logado")
        self.client.force_login(conta)
        self.assertEqual(self.client.get("/inicio/").status_code, 302)

        pessoa.active = False
        pessoa.save()

        r = self.client.get("/inicio/")
        self.assertIn("/admin/login/", r["Location"])

    def test_nao_consegue_mais_entrar(self):
        from django.test import RequestFactory

        pessoa, conta = self._pessoa_com_conta(usuario="tentando")
        pessoa.active = False
        pessoa.save()

        req = RequestFactory().post("/admin/login/")
        self.assertIsNone(
            authenticate(req, username="tentando", password=self.SENHA))

    def test_desligar_nao_encosta_no_patrimonio(self):
        """Fechar o acesso não pode apagar o rastro do que a pessoa segurava —
        é justamente aí que o sistema precisa continuar sabendo."""
        from apps.orgs.models import Location
        from apps.parque.models import Baia, Computador, Setor

        pessoa, conta = self._pessoa_com_conta(usuario="comcoisas")
        loc = Location.objects.create(name="Vilar")
        setor = Setor.objects.create(nome="Comercial", unidade=loc)
        pc = Computador.objects.create(patrimonio="PC-7001")
        baia = Baia.objects.create(nome="1 - Fulano", setor=setor,
                                   computador=pc, colaborador=pessoa)
        LogAcesso.objects.create(usuario=conta, evento=LogAcesso.Evento.LOGIN)

        pessoa.active = False
        pessoa.save()

        baia.refresh_from_db(); pc.refresh_from_db()
        self.assertEqual(baia.colaborador_id, pessoa.pk)
        self.assertEqual(pc.colaborador_id, pessoa.pk)
        self.assertEqual(LogAcesso.objects.filter(usuario=conta).count(), 1)


class ContaPelaFichaTests(TestCase):
    """Desativar, reativar e criar conta pela ficha do colaborador."""

    SENHA = "SenhaForte9x!"

    def setUp(self):
        self.su = User.objects.create_superuser("su", "su@x.com", self.SENHA)
        self.conta = User.objects.create_user("zeca", "z@x.com", self.SENHA,
                                              is_staff=True)
        self.pessoa = (Person.objects.filter(user=self.conta).first()
                       or Person.objects.create(full_name="Zeca Silva",
                                                user=self.conta))

    def _u(self, acao, pessoa=None):
        return f"/cadastros/colaborador/{(pessoa or self.pessoa).pk}/conta/{acao}/"

    # --- desativar --------------------------------------------------------

    def test_desativa_e_a_pessoa_para_de_entrar(self):
        self.client.force_login(self.su)
        r = self.client.post(self._u("desativar"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.conta.refresh_from_db()
        self.assertFalse(self.conta.is_active)

    def test_nao_desativa_duas_vezes(self):
        self.conta.is_active = False
        self.conta.save(update_fields=["is_active"])
        self.client.force_login(self.su)
        self.assertEqual(self.client.post(self._u("desativar")).status_code, 400)

    def test_ninguem_tranca_a_si_mesmo(self):
        """Depois do clique não haveria sessão para desfazer o clique."""
        eu = Person.objects.filter(user=self.su).first() or Person.objects.create(
            full_name="Super", user=self.su)
        self.client.force_login(self.su)
        r = self.client.post(self._u("desativar", eu))
        self.assertEqual(r.status_code, 400)
        self.su.refresh_from_db()
        self.assertTrue(self.su.is_active)

    def _sem_senha_temporaria(self, u):
        """Usuário recém-criado nasce devendo troca de senha, e o
        `TrocaSenhaObrigatoriaMiddleware` desvia TODO request dele para
        /trocar-senha/ — o teste mediria 302 e nunca chegaria na permissão."""
        PerfilUsuario.objects.update_or_create(
            usuario=u, defaults={"senha_temporaria": False})
        return u

    def test_quem_nao_e_superusuario_nao_mexe_em_superusuario(self):
        """A trava contra promoção: sem ela, quem tem change_user desativa quem
        manda mais e assume o sistema."""
        from django.contrib.auth.models import Permission

        chefe = User.objects.create_superuser("chefe", "c@x.com", self.SENHA)
        p_chefe = Person.objects.filter(user=chefe).first() or Person.objects.create(
            full_name="Chefe", user=chefe)
        comum = self._sem_senha_temporaria(
            User.objects.create_user("comum", "k@x.com", self.SENHA, is_staff=True))
        comum.user_permissions.add(Permission.objects.get(codename="change_user"))

        self.client.force_login(comum)
        self.assertEqual(self.client.post(self._u("desativar", p_chefe)).status_code, 403)
        chefe.refresh_from_db()
        self.assertTrue(chefe.is_active)

    def test_sem_permissao_nao_desativa(self):
        qualquer = self._sem_senha_temporaria(
            User.objects.create_user("qq", "q@x.com", self.SENHA, is_staff=True))
        self.client.force_login(qualquer)
        self.assertEqual(self.client.post(self._u("desativar")).status_code, 403)
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.is_active)

    # --- reativar ---------------------------------------------------------

    def test_reativa(self):
        self.conta.is_active = False
        self.conta.save(update_fields=["is_active"])
        self.client.force_login(self.su)
        r = self.client.post(self._u("ativar"))
        self.assertEqual(r.status_code, 200)
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.is_active)

    def test_nao_reativa_conta_de_desligado(self):
        """Senão o acesso oscila: o signal fecharia de novo no próximo save do
        cadastro, e ninguém entenderia por quê."""
        self.pessoa.active = False
        self.pessoa.save()
        self.client.force_login(self.su)
        r = self.client.post(self._u("ativar"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("desligado", r.json()["erro"])
        self.conta.refresh_from_db()
        self.assertFalse(self.conta.is_active)

    # --- criar ------------------------------------------------------------

    def test_cria_conta_para_quem_nao_tinha(self):
        sem = Person.objects.create(full_name="Marta Nogueira")
        self.client.force_login(self.su)
        r = self.client.post(self._u("criar", sem))
        self.assertEqual(r.status_code, 200)
        dados = r.json()
        self.assertEqual(dados["usuario"], "marta.nogueira")
        sem.refresh_from_db()
        self.assertIsNotNone(sem.user_id)
        # Nasce sem grupo: acesso se concede depois, um a um.
        self.assertEqual(sem.user.groups.count(), 0)
        # E a senha é temporária — trocada no primeiro acesso.
        self.assertTrue(PerfilUsuario.objects.get(usuario=sem.user).senha_temporaria)

    def test_nome_de_usuario_nao_colide(self):
        User.objects.create_user("marta.nogueira", "m@x.com", self.SENHA)
        sem = Person.objects.create(full_name="Marta Nogueira")
        self.client.force_login(self.su)
        r = self.client.post(self._u("criar", sem))
        self.assertEqual(r.json()["usuario"], "marta.nogueira2")

    def test_acento_no_nome_vira_usuario_sem_acento(self):
        sem = Person.objects.create(full_name="Caio Gonçalves")
        self.client.force_login(self.su)
        self.assertEqual(self.client.post(self._u("criar", sem)).json()["usuario"],
                         "kaua.goncalves")

    def test_nao_cria_conta_dupla(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.post(self._u("criar")).status_code, 400)

    def test_nao_cria_conta_para_desligado(self):
        sem = Person.objects.create(full_name="Saiu Daqui", active=False)
        self.client.force_login(self.su)
        r = self.client.post(self._u("criar", sem))
        self.assertEqual(r.status_code, 400)
        sem.refresh_from_db()
        self.assertIsNone(sem.user_id)

    def test_criar_so_cria_UM_cadastro(self):
        """O signal `garantir_colaborador_do_usuario` cria um Person para todo
        usuário staff. Aqui a pessoa já existe — se o vínculo não for feito na
        mão, o sistema termina com duas fichas da mesma pessoa."""
        sem = Person.objects.create(full_name="Unica Pessoa")
        self.client.force_login(self.su)
        self.client.post(self._u("criar", sem))
        self.assertEqual(
            Person.objects.filter(full_name__iexact="Unica Pessoa").count(), 1)

    # --- o básico ---------------------------------------------------------

    def test_tudo_exige_post(self):
        self.client.force_login(self.su)
        for acao in ("criar", "desativar", "ativar"):
            self.assertEqual(self.client.get(self._u(acao)).status_code, 405, msg=acao)

    def test_id_que_nao_existe_da_404(self):
        self.client.force_login(self.su)
        r = self.client.post("/cadastros/colaborador/999999/conta/desativar/")
        self.assertEqual(r.status_code, 404)


class FichaDoColaboradorMostraOsEquipamentosTests(TestCase):
    """O avesso de `Computador.colaborador`: a ficha da pessoa tem de responder
    "o que o Fulano está usando?" sem obrigar a varrer o parque."""

    def setUp(self):
        from apps.orgs.models import Location
        from apps.parque.models import Computador, Setor

        self.Computador, self.Setor = Computador, Setor
        self.su = User.objects.create_superuser("su", "su@x.com", "x1y2z3w4!A")
        self.loc = Location.objects.create(name="Vilar")
        self.pessoa = Person.objects.create(full_name="Ana Souza", location=self.loc)
        self.client.force_login(self.su)

    def _ficha(self):
        return self.client.get(
            reverse("admin:orgs_person_change", args=[self.pessoa.pk]))

    def test_sem_nada_diz_que_nao_ha_nada(self):
        """Em branco seria ambíguo — "não tem" e "não carregou" parecem iguais.

        Tem de ser alguém SEM loja: colaborador ativo com loja já ganha uma baia
        vazia de `garantir_baia_do_colaborador` (visão unificada do mapa), então
        a ficha dele nunca fica realmente vazia.
        """
        from apps.orgs.models import Person as P

        sem_loja = P.objects.create(full_name="Sem Loja")
        r = self.client.get(reverse("admin:orgs_person_change", args=[sem_loja.pk]))
        self.assertContains(r, "Nenhum equipamento vinculado.")

    def test_pessoa_nova_com_loja_aparece_so_com_a_baia_de_alocar(self):
        """A baia automática entra na lista — e é só ela. Dizer "nenhum" aqui
        seria mentira: a mesa existe no mapa."""
        html = self._ficha().content.decode()
        self.assertIn("Baia 1 - Ana Souza", html)
        self.assertNotIn("Computador", html.split("Equipamentos em uso")[1][:2000])

    def test_o_pc_da_baia_aparece_na_ficha_da_pessoa(self):
        from apps.parque.models import Baia

        setor = self.Setor.objects.create(nome="Comercial", unidade=self.loc)
        pc = self.Computador.objects.create(patrimonio="PC-0001")
        Baia.objects.create(nome="1 - Ana", setor=setor,
                            computador=pc, colaborador=self.pessoa)

        html = self._ficha().content.decode()
        self.assertIn("Computador PC-0001", html)
        self.assertIn("Baia 1 - Ana", html)
        # Link, não texto solto: é por aqui que se chega à máquina.
        self.assertIn(reverse("admin:parque_computador_change", args=[pc.pk]), html)

    def test_formulario_vazio_nao_quebra(self):
        self.client.force_login(self.su)
        for url in ("/parque/acessos/pessoa/", "/parque/acessos/grupo/",
                    "/parque/acessos/grupo/novo/", "/parque/acessos/grupo/excluir/"):
            r = self.client.post(url, {})
            self.assertLess(r.status_code, 500, msg=url)


@SEM_AXES
class RedefinirSenhaColaboradorTests(TestCase):
    """Redefinir a senha pela ficha de Cadastros.

    O que esta suíte protege: a operação gera senha TEMPORÁRIA e obriga a troca
    no próximo acesso. Se alguém um dia trocar isso por "definir a senha aqui",
    `test_marca_como_temporaria` quebra — e é para quebrar: seria a TI passando
    a conhecer a senha de quem ela atende.
    """

    def setUp(self):
        self.su = User.objects.create_superuser("chefe", "chefe@make.com", "x")
        self.conta = User.objects.create_user("maria", "maria@make.com", "AntigaDela#1")
        self.pessoa = Person.objects.create(full_name="Maria da Silva", user=self.conta)
        self.sem_conta = Person.objects.create(full_name="Jose Sem Login")

    def _url(self, pessoa):
        return reverse("redefinir_senha_colaborador", args=[pessoa.pk])

    def test_exige_permissao(self):
        comum = User.objects.create_user("comum", "c@make.com", "x")
        self.client.force_login(comum)
        r = self.client.post(self._url(self.pessoa))
        self.assertEqual(r.status_code, 403)
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.check_password("AntigaDela#1"))

    def test_anonimo_nao_entra(self):
        r = self.client.post(self._url(self.pessoa))
        self.assertEqual(r.status_code, 403)

    def test_get_nao_vale(self):
        """Operação que muda senha não pode acontecer por navegação."""
        self.client.force_login(self.su)
        r = self.client.get(self._url(self.pessoa))
        self.assertEqual(r.status_code, 405)
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.check_password("AntigaDela#1"))

    def test_colaborador_sem_conta_avisa(self):
        self.client.force_login(self.su)
        r = self.client.post(self._url(self.sem_conta))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertIn("conta de acesso", r.json()["erro"].lower())

    def test_conta_inativa_avisa(self):
        self.conta.is_active = False
        self.conta.save(update_fields=["is_active"])
        self.client.force_login(self.su)
        r = self.client.post(self._url(self.pessoa))
        self.assertEqual(r.status_code, 400)
        self.assertIn("inativa", r.json()["erro"].lower())

    def test_gera_senha_e_invalida_a_antiga(self):
        self.client.force_login(self.su)
        r = self.client.post(self._url(self.pessoa))
        self.assertEqual(r.status_code, 200)
        dados = r.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["usuario"], "maria")
        self.assertTrue(dados["senha"])

        self.conta.refresh_from_db()
        self.assertTrue(self.conta.check_password(dados["senha"]))
        self.assertFalse(self.conta.check_password("AntigaDela#1"))

    def test_marca_como_temporaria(self):
        """A senha entregue é provisória: o middleware força a troca depois."""
        self.client.force_login(self.su)
        self.client.post(self._url(self.pessoa))
        perfil = PerfilUsuario.objects.get(usuario=self.conta)
        self.assertTrue(perfil.senha_temporaria)
        self.assertIsNotNone(perfil.senha_temporaria_em)

    def test_registra_em_log(self):
        self.client.force_login(self.su)
        self.client.post(self._url(self.pessoa))
        self.assertTrue(LogAcesso.objects.filter(
            usuario=self.conta, evento=LogAcesso.Evento.RECUPERACAO).exists())

    def test_a_senha_nao_se_repete(self):
        self.client.force_login(self.su)
        primeira = self.client.post(self._url(self.pessoa)).json()["senha"]
        segunda = self.client.post(self._url(self.pessoa)).json()["senha"]
        self.assertNotEqual(primeira, segunda)
