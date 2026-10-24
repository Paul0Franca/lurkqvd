"""Rotas de login (entrar, sair, trocar a senha) e de cadastro de usuários pelo admin.

Cadastro e redefinição geram uma senha temporária que vai por e-mail: sem SMTP configurado, não dá
para cadastrar (a pessoa nunca receberia a senha). No primeiro login a troca é obrigatória.
"""

import logging
import os
import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.lurkqvd import senhas
from src.lurkqvd.api.auth import (bloqueado, exigir_papel, exigir_pessoa, get_repo, limpar_erros,
                                  registrar_erro)
from src.lurkqvd.repository.repositorio import LoginJaExiste, Repositorio

logger = logging.getLogger("lurkqvd.acesso")
router = APIRouter()

Repo = Annotated[Repositorio, Depends(get_repo)]
Admin = Annotated[dict, Depends(exigir_papel("admin"))]
Pessoa = Annotated[dict, Depends(exigir_pessoa)]

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PapelTipo = Literal["admin", "editor", "leitor"]


class Usuario(BaseModel):
    id: int
    email: str
    nome: str | None
    papel: str
    ultimo_login: datetime | None
    foto_url: str | None = None
    trocar_senha: bool = False


class Entrar(BaseModel):
    login: str = Field(min_length=1, max_length=254)
    senha: str = Field(min_length=1, max_length=200)


class Sessao(BaseModel):
    token: str
    expira_em: datetime
    usuario: Usuario


class TrocarSenha(BaseModel):
    atual: str = Field(min_length=1, max_length=200)
    nova: str = Field(min_length=1, max_length=200)
    # só para o admin padrão (login "admin"), no primeiro acesso
    email: str | None = Field(default=None, pattern=EMAIL, max_length=254)
    nome: str | None = Field(default=None, max_length=120)


class UsuarioCriar(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    nome: str = Field(min_length=1, max_length=120)
    papel: PapelTipo = "leitor"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def precisa_completar(usuario: dict) -> bool:
    """O admin padrão entra com o login "admin" e informa o e-mail real na primeira troca de senha."""
    return not re.match(EMAIL, usuario["email"] or "")


# ---------------------------------------------------------------------- #
# Login
# ---------------------------------------------------------------------- #
@router.post("/auth/entrar", response_model=Sessao)
def entrar(body: Entrar, request: Request, repo: Repo):
    login, ip = body.login.strip().lower(), _ip(request)
    espera = bloqueado(login, ip)
    if espera:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Muitas tentativas. Tente de novo em {max(1, espera // 60)} min.")
    u = repo.usuario_para_login(login)
    if not senhas.conferir_tempo_constante(body.senha, u["senha_hash"] if u else None):
        registrar_erro(login, ip)
        logger.warning("login recusado: %s de %s", login, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login ou senha incorretos.")
    if not u["ativo"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado. Fale com um administrador.")
    limpar_erros(login, ip)
    token, sessao = repo.criar_sessao(u["id"], ip, request.headers.get("user-agent"))
    return {"token": token, "expira_em": sessao["expira_em"], "usuario": u}


@router.post("/auth/sair", status_code=status.HTTP_204_NO_CONTENT)
def sair(usuario: Pessoa, repo: Repo):
    if usuario.get("sessao"):
        repo.encerrar_sessao(usuario["sessao"])


@router.get("/auth/me", response_model=Usuario)
def eu(usuario: Pessoa):
    return usuario


@router.post("/auth/senha", response_model=Usuario)
def trocar_senha(body: TrocarSenha, usuario: Pessoa, repo: Repo):
    """Troca a própria senha (obrigatório quando a atual é temporária). Derruba as outras sessões."""
    chave = f"senha:{usuario['id']}"  # tentativas de adivinhar a senha atual com uma sessão roubada
    espera = bloqueado(chave, "-")
    if espera:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Muitas tentativas. Tente de novo em {max(1, espera // 60)} min.")
    atual = repo.usuario_por_id(usuario["id"])
    if not senhas.conferir(body.atual, atual["senha_hash"]):
        registrar_erro(chave, "-")
        raise HTTPException(422, "A senha atual não confere.")
    limpar_erros(chave, "-")
    completar = precisa_completar(atual)
    if completar and not (body.email and (body.nome or "").strip()):
        raise HTTPException(422, "Informe o seu nome e e-mail: eles substituem o login \"admin\".")
    login = body.email if completar else atual["email"]
    motivo = senhas.problema(body.nova, login=login, atual=body.atual)
    if motivo:
        raise HTTPException(422, motivo)

    if completar:
        try:
            repo.completar_conta(usuario["id"], body.email, body.nome)
        except LoginJaExiste as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    repo.definir_senha(usuario["id"], senhas.gerar_hash(body.nova), trocar_senha=False, por=usuario["id"],
                       manter_sessao=usuario.get("sessao"))
    if completar:
        senhas.ARQUIVO_SENHA_INICIAL.unlink(missing_ok=True)  # a senha sorteada da instalação não vale mais
    return repo.usuario_por_id(usuario["id"])


# ---------------------------------------------------------------------- #
# Cadastro pelo admin (senha temporária por e-mail)
# ---------------------------------------------------------------------- #
def _enviar_acesso(repo: Repositorio, email: str, papel: str, senha: str, quem: dict, *, redefinida: bool) -> None:
    from src.lurkqvd.notificacoes import Notificador, SemEmail

    try:
        Notificador(repo).acesso(email, papel, senha, quem.get("nome") or quem.get("email"), redefinida=redefinida)
    except SemEmail as e:
        raise HTTPException(422, str(e))


@router.post("/usuarios", response_model=Usuario, status_code=status.HTTP_201_CREATED)
def criar_usuario(body: UsuarioCriar, repo: Repo, usuario: Admin):
    """Cadastra a pessoa e manda o login e a senha temporária por e-mail. Sem e-mail enviado, não cadastra."""
    email = body.email.strip().lower()
    if repo.usuario_para_login(email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um usuário com esse e-mail.")
    senha = senhas.temporaria()
    _enviar_acesso(repo, email, body.papel, senha, usuario, redefinida=False)
    try:
        return repo.criar_usuario(email, body.nome, body.papel, senhas.gerar_hash(senha), criado_por=usuario["id"])
    except LoginJaExiste as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.post("/usuarios/{usuario_id}/redefinir-senha", status_code=status.HTTP_204_NO_CONTENT)
def redefinir_senha(usuario_id: int, repo: Repo, usuario: Admin):
    """Sorteia uma senha temporária, manda por e-mail e derruba as sessões da pessoa."""
    alvo = repo.usuario_por_id(usuario_id)
    if not alvo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    if alvo["id"] == usuario["id"]:
        raise HTTPException(422, "Para trocar a sua própria senha, use o menu do seu perfil.")
    if precisa_completar(alvo):
        raise HTTPException(422, "Esse login não tem e-mail para receber a senha. Use o comando definir-senha no servidor.")
    senha = senhas.temporaria()
    _enviar_acesso(repo, alvo["email"], alvo["papel"], senha, usuario, redefinida=True)
    repo.definir_senha(alvo["id"], senhas.gerar_hash(senha), trocar_senha=True, por=usuario["id"])


# ---------------------------------------------------------------------- #
# Instalação: admin padrão
# ---------------------------------------------------------------------- #
def conferir_migracoes() -> None:
    """Na subida da API: com migração faltando, não sobe (as rotas dariam 500 em colunas que não existem).
    Postgres fora do ar não impede a subida: o /health avisa até ele voltar."""
    from src.lurkqvd import migracoes

    try:
        migracoes.exigir_em_dia(get_repo().dsn)
    except migracoes.BancoDesatualizado:
        raise
    except Exception:
        logger.warning("não consegui conferir as migrações do banco (o Postgres está no ar?)", exc_info=True)


def preparar_admin_padrao() -> None:
    """Na subida da API: banco sem usuários -> cria o login "admin" (veja src/lurkqvd/senhas.py)."""
    if os.getenv("LURKQVD_AUTH_DEV") == "1":
        logger.critical("LURKQVD_AUTH_DEV=1: a API aceita QUALQUER chamada como admin. Só para teste local; "
                        "nunca use em produção.")
    senha = os.getenv("LURKQVD_ADMIN_SENHA", "").strip()
    sorteada = not senha
    senha = senha or senhas.temporaria()
    try:
        criado = get_repo().garantir_admin_padrao(senhas.LOGIN_ADMIN, senhas.gerar_hash(senha))
    except Exception:
        logger.exception("não consegui verificar/criar o admin padrão (o Postgres está no ar?)")
        return
    if not criado:
        return
    if sorteada:
        try:
            senhas.ARQUIVO_SENHA_INICIAL.write_text(
                f"Login: {senhas.LOGIN_ADMIN}\nSenha: {senha}\n\n"
                "Senha temporária: no primeiro login o LurkQVD pede uma senha nova (e este arquivo é apagado).\n",
                encoding="utf-8",
            )
            senhas.ARQUIVO_SENHA_INICIAL.chmod(0o600)  # só o dono lê (no Windows, só tira a escrita dos outros)
        except OSError:
            logger.warning("não consegui gravar %s", senhas.ARQUIVO_SENHA_INICIAL)
    logger.warning(
        "\n" + "=" * 64 + "\n  LurkQVD: admin padrão criado\n  Login: %s\n  Senha: %s\n"
        "  No primeiro login será pedida uma senha nova.\n" + "=" * 64,
        senhas.LOGIN_ADMIN, senha if sorteada else "(a de LURKQVD_ADMIN_SENHA)",
    )
