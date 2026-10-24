"""Senhas do login do LurkQVD: hash, senha temporária e o admin padrão da instalação.

Hash: scrypt da biblioteca padrão, guardado como "scrypt$n$r$p$<sal base64>$<hash base64>".

Admin padrão (como o Airflow): na primeira subida da API, com o banco sem nenhum usuário, é criado o
login "admin". A senha vem de LURKQVD_ADMIN_SENHA ou é sorteada; sorteada, aparece no log da API e no
arquivo admin_senha_inicial.txt (na raiz do projeto), que some quando ela for trocada. No primeiro
login o admin é obrigado a trocar a senha e informar nome e e-mail reais.

Variáveis de ambiente:
  LURKQVD_ADMIN_SENHA   senha inicial do admin padrão (vazio = sorteada)
"""

import base64
import hashlib
import hmac
import secrets
from pathlib import Path

LOGIN_ADMIN = "admin"
TAMANHO_MINIMO = 10
ARQUIVO_SENHA_INICIAL = Path(__file__).resolve().parents[2] / "admin_senha_inicial.txt"

_N, _R, _P = 2**14, 8, 1  # ~16 MB e alguns ms por verificação: caro para força bruta, barato para um login
_ALFABETO = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/l/I


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def conferir(senha: str, guardado: str | None) -> bool:
    if not guardado:
        return False
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p),
                                   dklen=len(base64.b64decode(h)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado, base64.b64decode(h))


# para gastar o mesmo tempo quando o login não existe (não revela quais e-mails têm conta)
_HASH_FALSO = gerar_hash(secrets.token_urlsafe(12))


def conferir_tempo_constante(senha: str, guardado: str | None) -> bool:
    if guardado:
        return conferir(senha, guardado)
    conferir(senha, _HASH_FALSO)
    return False


def temporaria() -> str:
    """Senha sorteada, fácil de digitar: xxxx-xxxx-xxxx (sem caracteres que se confundem)."""
    return "-".join("".join(secrets.choice(_ALFABETO) for _ in range(4)) for _ in range(3))


def problema(senha: str, *, login: str = "", atual: str | None = None) -> str | None:
    """Motivo para recusar a senha nova, ou None se ela serve."""
    if len(senha) < TAMANHO_MINIMO:
        return f"A senha precisa ter pelo menos {TAMANHO_MINIMO} caracteres."
    if senha.strip() != senha:
        return "A senha não pode começar nem terminar com espaço."
    if login and senha.lower() == login.lower():
        return "A senha não pode ser igual ao login."
    if atual is not None and senha == atual:
        return "A senha nova precisa ser diferente da atual."
    return None
