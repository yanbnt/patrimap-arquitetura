"""Formulários customizados de autenticação para o admin."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from unfold.forms import AdminPasswordChangeForm


class LoginUsuarioOuEmailForm(AuthenticationForm):
    """Tela de login: o campo aceita o usuário OU o e-mail."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["username"]
        campo.label = "Usuário ou e-mail"
        campo.widget.attrs.update({"placeholder": "Usuário ou e-mail", "autofocus": True})

    def get_invalid_login_error(self):
        """Senha temporária vencida ganha um erro que explica o que fazer.

        O backend (apps.orgs.backends) marca `request.senha_temp_expirada` quando
        a senha digitada estava CERTA mas fora do prazo de validade. Sem essa
        mensagem o usuário recebe "usuário ou senha incorretos" e não tem como
        saber que precisa pedir uma nova senha temporária.
        """
        if getattr(self.request, "senha_temp_expirada", False):
            return forms.ValidationError(
                "Sua senha temporária expirou. Clique em “Esqueceu sua senha?” "
                "para receber uma nova por e-mail.",
                code="senha_temporaria_expirada",
            )
        return super().get_invalid_login_error()


class SenhaComAntigaForm(AdminPasswordChangeForm):
    """
    Exige a senha ATUAL do usuário antes de definir uma nova — proteção contra
    alterações indevidas (ex.: alguém numa sessão aberta tentando trocar a senha).
    """

    old_password = forms.CharField(
        label="Senha atual",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        help_text="Informe a senha atual deste usuário para confirmar a alteração.",
    )

    field_order = ["old_password", "password1", "password2"]

    def clean_old_password(self):
        old_password = self.cleaned_data.get("old_password", "")
        if not self.user.check_password(old_password):
            raise forms.ValidationError(
                "A senha atual está incorreta. A alteração foi bloqueada."
            )
        return old_password


# ---------------------------------------------------------------------------
# CADASTRO: documento e contato aceitos COM máscara
# ---------------------------------------------------------------------------
#
# O banco guarda só dígitos (é o que permite cruzar com o Sankhya e impede o
# mesmo CNPJ entrar duas vezes com pontuação diferente). Só que o `max_length`
# do campo roda ANTES do validador: quem colava "529.982.247-25" — o formato em
# que o número existe em toda nota, contrato e planilha — recebia
# "certifique-se de que o valor tenha no máximo 11 caracteres (ele possui 14)".
# Mensagem que não diz nada e culpa quem digitou certo.
#
# Aqui a máscara é retirada no `clean_<campo>`, antes de qualquer validação de
# tamanho. Digitar com ou sem pontuação passa a dar no mesmo.
class CadastroComMascaraForm(forms.ModelForm):
    """Tira pontuação de documento, telefone e CEP antes de validar."""

    CAMPOS_SO_DIGITOS = ("cnpj", "cpf", "telefone", "cep")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # O `max_length` viaja do modelo para o CAMPO do formulário, e é
        # conferido em `_clean_fields()` — antes de qualquer `clean()` nosso.
        # Sem folgar esse limite aqui, "11.222.333/0001-81" (18 caracteres)
        # morre com erro de tamanho e a limpeza abaixo nunca roda. A folga de 6
        # é o que a maior máscara usa (pontos, barra, hífen, parênteses).
        # O `maxlength` do widget sai junto: senão o navegador corta a
        # digitação no meio antes de chegar aqui.
        from django.core.validators import MaxLengthValidator
        for nome in self.CAMPOS_SO_DIGITOS:
            campo = self.fields.get(nome)
            if not campo or not campo.max_length:
                continue
            folgado = campo.max_length + 6
            campo.max_length = folgado
            campo.validators = [
                v for v in campo.validators
                if not isinstance(v, MaxLengthValidator)
            ] + [MaxLengthValidator(folgado)]
            campo.widget.attrs.pop("maxlength", None)

    def _limpar(self, nome):
        valor = self.cleaned_data.get(nome)
        if not valor:
            return valor
        return "".join(c for c in str(valor) if c.isdigit())

    def clean(self):
        dados = super().clean()
        for nome in self.CAMPOS_SO_DIGITOS:
            if nome in self.fields:
                dados[nome] = self._limpar(nome)
        return dados

    def _post_clean(self):
        # O `max_length` do modelo é conferido aqui, no `full_clean` da
        # instância — por isso a limpeza tem de acontecer ANTES, no clean()
        # acima, e ser refletida na instância. É o que este trecho garante.
        for nome in self.CAMPOS_SO_DIGITOS:
            if nome in self.fields and nome in self.cleaned_data:
                setattr(self.instance, nome, self.cleaned_data[nome] or "")
        super()._post_clean()
