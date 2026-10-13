"""Criptografia E2EE da telemetria (agente → servidor).

Esquema híbrido compatível com o PowerShell 5.1 das máquinas (.NET Framework):
  - AES-256-CBC (PKCS7) cifra o JSON;
  - HMAC-SHA256 (encrypt-then-MAC) garante integridade;
  - a chave AES + a chave HMAC (64 bytes) são embrulhadas com RSA-OAEP-SHA1
    usando a CHAVE PÚBLICA do servidor.
Só o servidor (chave privada no .env) decifra — nem a Cloudflare lê o conteúdo.
"""
import base64

from django.conf import settings
from cryptography.hazmat.primitives import hashes, hmac as chmac, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def ativa():
    """True se a chave privada está configurada (E2EE obrigatório no endpoint)."""
    return bool((getattr(settings, "TELEMETRIA_PRIV_KEY", "") or "").strip())


def _privada():
    raw = (getattr(settings, "TELEMETRIA_PRIV_KEY", "") or "").strip()
    if not raw:
        return None
    return serialization.load_pem_private_key(base64.b64decode(raw), password=None)


def _int_b64(n):
    return base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode()


def publica_xml():
    """Chave pública no formato RSA XML do .NET (p/ o agente PowerShell/Windows)."""
    priv = _privada()
    if priv is None:
        return ""
    nums = priv.public_key().public_numbers()
    return (f"<RSAKeyValue><Modulus>{_int_b64(nums.n)}</Modulus>"
            f"<Exponent>{_int_b64(nums.e)}</Exponent></RSAKeyValue>")


def publica_pem():
    """Chave pública em PEM (SubjectPublicKeyInfo) — p/ o agente Linux via openssl."""
    priv = _privada()
    if priv is None:
        return ""
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def decifrar(envelope):
    """Decifra o envelope {k, iv, ct, mac} e devolve os bytes do JSON original.
    Levanta exceção se a chave não estiver configurada, o MAC não bater ou o
    padding for inválido."""
    priv = _privada()
    if priv is None:
        raise ValueError("Chave privada de telemetria não configurada.")
    k = base64.b64decode(envelope["k"])
    iv = base64.b64decode(envelope["iv"])
    ct = base64.b64decode(envelope["ct"])
    mac = base64.b64decode(envelope["mac"])

    keymat = priv.decrypt(k, padding.OAEP(
        mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
    if len(keymat) < 64:
        raise ValueError("Material de chave inválido.")
    aes_key, mac_key = keymat[:32], keymat[32:64]

    h = chmac.HMAC(mac_key, hashes.SHA256())
    h.update(iv + ct)
    h.verify(mac)  # InvalidSignature se o conteúdo foi adulterado

    dec = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    n = padded[-1]
    if n < 1 or n > 16 or padded[-n:] != bytes([n]) * n:
        raise ValueError("Padding PKCS7 inválido.")
    return padded[:-n]
