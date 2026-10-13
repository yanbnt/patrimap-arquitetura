"""Validadores de documento e contato dos cadastros.

Por que aqui e não no `models.py`: o `makemigrations` grava a REFERÊNCIA à
função de validação dentro da migração, então ela precisa morar num módulo
estável. Função definida dentro de `models.py` também funciona, mas qualquer
renomeação depois quebra migrações antigas — um módulo próprio deixa isso
explícito.

Todos guardam SÓ DÍGITOS no banco. Máscara é assunto de formulário: guardar
"00.000.000/0000-00" impede comparar, indexar e cruzar com o Sankhya.
"""

from django.core.exceptions import ValidationError

UFS = [
    ("AC", "AC"), ("AL", "AL"), ("AP", "AP"), ("AM", "AM"), ("BA", "BA"),
    ("CE", "CE"), ("DF", "DF"), ("ES", "ES"), ("GO", "GO"), ("MA", "MA"),
    ("MT", "MT"), ("MS", "MS"), ("MG", "MG"), ("PA", "PA"), ("PB", "PB"),
    ("PR", "PR"), ("PE", "PE"), ("PI", "PI"), ("RJ", "RJ"), ("RN", "RN"),
    ("RS", "RS"), ("RO", "RO"), ("RR", "RR"), ("SC", "SC"), ("SP", "SP"),
    ("SE", "SE"), ("TO", "TO"),
]


def so_digitos(texto):
    """Devolve apenas os dígitos de um texto (None e "" viram "")."""
    return "".join(c for c in str(texto or "") if c.isdigit())


def valida_cnpj(valor):
    """CNPJ de 14 dígitos com os dois dígitos verificadores corretos.

    Aceita vazio (o campo é opcional no banco; quem exige é o formulário da
    tela, conforme o tipo da unidade).
    """
    num = so_digitos(valor)
    if not num:
        return
    if len(num) != 14:
        raise ValidationError("CNPJ deve ter 14 dígitos.")
    if num == num[0] * 14:
        raise ValidationError("CNPJ inválido.")

    def digito(base, pesos):
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    if num[12] != digito(num[:12], p1) or num[13] != digito(num[:13], p2):
        raise ValidationError("CNPJ inválido: dígitos verificadores não conferem.")


def valida_cpf(valor):
    """CPF de 11 dígitos com dígitos verificadores corretos. Vazio passa."""
    num = so_digitos(valor)
    if not num:
        return
    if len(num) != 11:
        raise ValidationError("CPF deve ter 11 dígitos.")
    if num == num[0] * 11:
        raise ValidationError("CPF inválido.")
    for tamanho in (9, 10):
        soma = sum(int(num[i]) * (tamanho + 1 - i) for i in range(tamanho))
        resto = (soma * 10) % 11
        esperado = "0" if resto == 10 else str(resto)
        if num[tamanho] != esperado:
            raise ValidationError("CPF inválido: dígitos verificadores não conferem.")


def valida_telefone(valor):
    """Telefone brasileiro com DDD: 10 dígitos (fixo) ou 11 (celular)."""
    num = so_digitos(valor)
    if not num:
        return
    if len(num) not in (10, 11):
        raise ValidationError("Telefone deve ter DDD + número (10 ou 11 dígitos).")


def valida_cep(valor):
    """CEP com 8 dígitos."""
    num = so_digitos(valor)
    if not num:
        return
    if len(num) != 8:
        raise ValidationError("CEP deve ter 8 dígitos.")
