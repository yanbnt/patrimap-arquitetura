"""
Campo de texto CIFRADO no banco (Fernet / AES-128-CBC + HMAC-SHA256).

Motivo (auditoria, item 1.12): `Notebook.senha` e `Notebook.anydesk_senha`
guardavam a senha da máquina em texto claro — legível por qualquer membro da
equipe com acesso ao admin e presente em **todo backup** do banco.

Não dá para usar hash (como na senha de login): a TI precisa LER essa senha para
acessar a máquina. Então é cifragem simétrica reversível.

A CHAVE
-------
Vem de `settings.CAMPO_CRIPTO_KEY` (env `CAMPO_CRIPTO_KEY`). Se não houver, é
derivada do `SECRET_KEY` — o que funciona, mas amarra os dois: **trocar o
SECRET_KEY torna as senhas ilegíveis**. Em produção defina a chave própria:

    python manage.py gerar_chave_campos     # imprime uma chave nova
    # cole no .env:  CAMPO_CRIPTO_KEY=...

PERDER A CHAVE = PERDER OS DADOS. Guarde-a junto com os backups (e fora deles).

Compatibilidade
---------------
Valor que não estiver cifrado é devolvido como está — assim o sistema continua
lendo registros antigos mesmo antes/depois da migração de dados.
"""

import base64
import hashlib
import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

# Marca no começo do texto guardado, para saber o que já está cifrado.
PREFIXO = "enc1:"


def _chave():
    """Chave Fernet (32 bytes urlsafe-base64) a partir das settings."""
    bruta = (getattr(settings, "CAMPO_CRIPTO_KEY", "") or "").strip()
    if bruta:
        return bruta.encode()
    # Sem chave dedicada: deriva do SECRET_KEY (documentado no topo).
    digest = hashlib.sha256(
        ("campo-cripto:" + settings.SECRET_KEY).encode()
    ).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(_chave())


def cifrar(texto):
    """Texto claro → 'enc1:<token>'. Vazio continua vazio."""
    if texto is None or texto == "":
        return texto
    if isinstance(texto, str) and texto.startswith(PREFIXO):
        return texto  # já cifrado
    token = _fernet().encrypt(str(texto).encode()).decode()
    return PREFIXO + token


def decifrar(guardado):
    """'enc1:<token>' → texto claro. Qualquer outra coisa volta como está."""
    if not guardado or not isinstance(guardado, str):
        return guardado
    if not guardado.startswith(PREFIXO):
        return guardado  # registro antigo, ainda em claro
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(guardado[len(PREFIXO):].encode()).decode()
    except (InvalidToken, ValueError):
        # Chave trocada ou dado corrompido: não derruba a tela.
        logger.error(
            "Não foi possível decifrar um campo protegido — a CAMPO_CRIPTO_KEY "
            "mudou? O valor original não é recuperável sem a chave antiga."
        )
        return ""


class CampoTextoCifrado(models.CharField):
    """CharField que grava cifrado e devolve em claro.

    Fica maior no banco que o `max_length` do formulário (o token do Fernet é
    ~100 caracteres + o texto em base64), por isso o `max_length` do banco é
    calculado com folga.
    """

    def __init__(self, *args, **kwargs):
        # Comprimento visível para formulário/validação.
        self.max_length_claro = kwargs.get("max_length", 120)
        # Espaço real no banco: base64 do token cresce ~2,5× + cabeçalho.
        kwargs["max_length"] = max(255, self.max_length_claro * 3 + 120)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        nome, caminho, args, kwargs = super().deconstruct()
        kwargs["max_length"] = self.max_length_claro
        return nome, caminho, args, kwargs

    def from_db_value(self, value, expression, connection):
        return decifrar(value)

    def to_python(self, value):
        return decifrar(value) if isinstance(value, str) else value

    def get_prep_value(self, value):
        return cifrar(super().get_prep_value(value))

    def formfield(self, **kwargs):
        kwargs.setdefault("max_length", self.max_length_claro)
        return super().formfield(**kwargs)
