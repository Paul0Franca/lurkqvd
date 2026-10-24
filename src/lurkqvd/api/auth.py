"""Autenticação da API: login próprio (e-mail + senha) e tokens de API.

Fluxo:
  1. O front chama POST /auth/entrar com login e senha e recebe um token de sessão (prefixo lqs_).
  2. Toda chamada envia:  Authorization: Bearer <token>
  3. Sistemas (Airflow) usam um token de API (prefixo lqvd_), criado em Configurações › API.

Quem está com senha temporária (trocar_senha) só consegue usar as rotas de /auth até trocar.

Variáveis de ambiente:
  LURKQVD_AUTH_DEV=1       SÓ PARA TESTE LOCAL: aceita qualquer chamada como um admin fictício.
  LURKQVD_SESSAO_INATIVA_H, LURKQVD_SESSAO_MAX_DIAS: validade da sessão (repository/acesso.py).
"""

import logging
import os
import threading
import time
from functools import lru_cache
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.lurkqvd.repository.acesso import PREFIXO_SESSAO
from src.lurkqvd.repository.repositorio import Repositorio

logger = logging.getLogger(__name__)

PAPEIS = {"leitor": 1, "editor": 2, "admin": 3}

_bearer = HTTPBearer(auto_error=False)  # também cria o botão "Authorize" no /docs

# rotas liberadas para quem ainda precisa trocar a senha temporária
ROTAS_TROCA_SENHA = {"/auth/me", "/auth/senha", "/auth/sair"}


@lru_cache
def get_repo() -> Repositorio:
    return Repositorio()


# ---------------------------------------------------------------------- #
# Tentativas de login: 5 erros em 15 min por login+IP bloqueiam por 15 min
# ---------------------------------------------------------------------- #
MAX_TENTATIVAS = 5
JANELA_S = 15 * 60
_tentativas: dict[tuple[str, str], list[float]] = {}
_trava = threading.Lock()


def bloqueado(login: str, ip: str) -> int:
    """Segundos até liberar (0 = pode tentar)."""
    agora = time.monotonic()
    with _trava:
        recentes = [t for t in _tentativas.get((login, ip), []) if agora - t < JANELA_S]
        _tentativas[(login, ip)] = recentes
        return int(JANELA_S - (agora - recentes[0])) + 1 if len(recentes) >= MAX_TENTATIVAS else 0


def registrar_erro(login: str, ip: str) -> None:
    with _trava:
        _tentativas.setdefault((login, ip), []).append(time.monotonic())


def limpar_erros(login: str, ip: str) -> None:
    with _trava:
        _tentativas.pop((login, ip), None)


# ---------------------------------------------------------------------- #
# Quem está chamando
# ---------------------------------------------------------------------- #
# Token de API (sistemas como o Airflow): permissão -> papel equivalente. Nunca admin.
PAPEL_DO_TOKEN = {"executar": "editor", "leitura": "leitor"}

_NAO_LOGADO = {"WWW-Authenticate": "Bearer"}


def _principal_token(token: str, repo: Repositorio, request: Request | None) -> dict:
    ip = request.client.host if request and request.client else None
    t = repo.validar_token_api(token, ip)
    if not t:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de API inválido, revogado ou vencido.", headers=_NAO_LOGADO)
    # mesmo formato do usuário, para as rotas não precisarem diferenciar
    return {"id": None, "tipo": "token", "token_id": t["id"], "nome": t["nome"], "email": None,
            "papel": PAPEL_DO_TOKEN[t["permissao"]], "ativo": True, "trocar_senha": False}


def _usuario_dev(repo: Repositorio) -> dict:
    """LURKQVD_AUTH_DEV=1: um admin fictício (criado na 1ª chamada), sem senha."""
    u = repo.usuario_para_login("dev@local")
    if not u:
        from src.lurkqvd.repository.acesso import LoginJaExiste

        try:
            repo.criar_usuario("dev@local", "Dev Local", "admin", "", trocar_senha=False)
        except LoginJaExiste:
            pass
        u = repo.usuario_para_login("dev@local")
    return {**u, "senha_hash": None}


def usuario_atual(
    request: Request,
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    repo: Annotated[Repositorio, Depends(get_repo)],
) -> dict:
    """Dependência das rotas: a pessoa logada (sessão) ou um token de API (prefixo lqvd_)."""
    token = credenciais.credentials if credenciais else None
    if token and token.startswith(repo.PREFIXO_TOKEN):
        return _principal_token(token, repo, request)

    if os.getenv("LURKQVD_AUTH_DEV") == "1":
        return _usuario_dev(repo)

    if not token or not token.startswith(PREFIXO_SESSAO):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login.", headers=_NAO_LOGADO)
    usuario = repo.usuario_da_sessao(token)
    if not usuario:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada. Faça login novamente.", headers=_NAO_LOGADO)
    if not usuario["ativo"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado.")
    if usuario["trocar_senha"] and request.url.path not in ROTAS_TROCA_SENHA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Troque a senha temporária para continuar.")
    return {**usuario, "tipo": "pessoa", "sessao": token}


UsuarioAtual = Annotated[dict, Depends(usuario_atual)]


def exigir_pessoa(usuario: UsuarioAtual) -> dict:
    """Rotas só para pessoas logadas (não aceitam token de API)."""
    if usuario.get("tipo") == "token":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rota disponível só para pessoas logadas.")
    return usuario


def exigir_papel(minimo: str) -> Callable[[dict], dict]:
    """Uso: usuario: Annotated[dict, Depends(exigir_papel("editor"))]"""

    def _checar(usuario: UsuarioAtual) -> dict:
        if PAPEIS[usuario["papel"]] < PAPEIS[minimo]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requer papel '{minimo}'.")
        return usuario

    return _checar
