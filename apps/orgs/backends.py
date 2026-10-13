"""
Backend de autenticação que aceita login por **usuário OU e-mail**.

No formulário de login o campo "username" pode receber o nome de usuário ou o
e-mail (case-insensitive). Mantém o comportamento padrão de senha/permissões.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOuUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None

        # Barreira anti-DoS: senha absurdamente longa não é senha real. Rejeita
        # ANTES de hashear — gerar PBKDF2 de uma string gigante gasta CPU à toa
        # (vetor de negação de serviço). Nenhuma senha legítima passa de 128.
        if len(password) > 128:
            return None

        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email__iexact=username)
            except (User.DoesNotExist, User.MultipleObjectsReturned):
                # Roda o hasher mesmo sem achar (mitiga ataque de tempo).
                User().set_password(password)
                return None
        except User.MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            # Senha temporária vencida não autentica: o usuário precisa pedir
            # uma nova recuperação (evita senha esquecida no e-mail valer p/ sempre).
            perfil = getattr(user, "perfil", None)
            if perfil is not None and perfil.senha_temp_expirada:
                # Marca no request para o formulário de login explicar o motivo.
                # Sem isso, quem digita a senha temporária CERTA depois do prazo
                # recebe "usuário ou senha incorretos" e fica tentando de novo
                # (até o anti-brute-force travar a conta).
                if request is not None:
                    request.senha_temp_expirada = True
                return None
            return user
        return None
