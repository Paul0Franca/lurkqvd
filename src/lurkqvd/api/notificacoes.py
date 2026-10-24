"""Rotas de Configurações › Notificações: servidor SMTP (senha nos segredos) e o que avisar."""

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.lurkqvd.api.auth import exigir_papel, get_repo
from src.lurkqvd.repository.repositorio import Repositorio

router = APIRouter()
logger = logging.getLogger("lurkqvd.api")

Repo = Annotated[Repositorio, Depends(get_repo)]
Admin = Annotated[dict, Depends(exigir_papel("admin"))]

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SmtpDados(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=r"^[^\s/:]+$")
    porta: int = Field(ge=1, le=65535)
    seguranca: Literal["starttls", "ssl", "nenhuma"] = "starttls"
    usuario: str = Field(default="", max_length=254)  # vazio = servidor sem autenticação
    remetente: str = Field(pattern=EMAIL, max_length=254)
    remetente_nome: str = Field(default="LurkQVD", max_length=80)


class SmtpSalvar(SmtpDados):
    senha: str | None = Field(default=None, max_length=512)  # vazio = mantém a atual


class SmtpTestar(SmtpSalvar):
    para: str | None = Field(default=None, pattern=EMAIL, max_length=254)  # vazio = o seu e-mail


class EnviarTeste(BaseModel):
    para: str | None = Field(default=None, pattern=EMAIL, max_length=254)


class TesteSmtp(BaseModel):
    ok: bool | None = None
    erro: str | None = None
    latencia_ms: int | None = None
    para: str | None = None
    testado_em: datetime | None = None


class SmtpConfig(SmtpDados):
    senha_mascara: str | None = None


class Preferencias(BaseModel):
    erros_cargas: bool = True
    erros_aplicacoes: bool = True
    recuperacao: bool = True
    qlik: bool = True
    so_mudanca: bool = True
    para_admins: bool = True
    extras: list[Annotated[str, Field(pattern=EMAIL, max_length=254)]] = Field(default_factory=list, max_length=30)


class Envio(BaseModel):
    id: int
    tipo: str
    assunto: str
    destinatarios: list[str]
    ok: bool
    erro: str | None
    criado_em: datetime


class ConfigNotificacoes(BaseModel):
    smtp: SmtpConfig | None
    status: TesteSmtp | None
    alterado_em: datetime | None
    alterado_por: str | None
    secret: str
    preferencias: Preferencias
    admins: list[str]
    url_app: str
    historico: list[Envio]


def _config(repo: Repositorio) -> dict:
    from src.lurkqvd.config import smtp
    from src.lurkqvd.notificacoes import url_app

    cfg = repo.config_smtp()
    return {
        **cfg,
        "secret": smtp.nome_secret(),
        "preferencias": repo.config_notificacoes(),
        "admins": repo.emails_admins(),
        "url_app": url_app(),
        "historico": repo.notificacoes_recentes(20),
    }


def _senha(body: SmtpSalvar, repo: Repositorio) -> str | None:
    """A senha digitada ou, se ficou vazia, a salva (só quando o servidor pede usuário)."""
    from src.lurkqvd.config import segredos, smtp

    if not body.usuario.strip():
        return None
    if body.senha:
        return body.senha
    if not repo.config_smtp()["smtp"]:
        raise HTTPException(422, "Informe a senha.")
    try:
        senha = smtp.ler_senha()
    except Exception as e:
        logger.exception("falha ao ler a senha do SMTP")
        codigo, msg = segredos.mensagem_erro(e, smtp.nome_secret())
        raise HTTPException(codigo, msg)
    if not senha:
        raise HTTPException(422, "Não há senha salva: informe a senha.")
    return senha


def _dados(body: SmtpDados) -> dict:
    d = body.model_dump(include=set(SmtpDados.model_fields))
    d["host"] = d["host"].strip().lower()
    d["usuario"] = d["usuario"].strip()
    d["remetente"] = d["remetente"].strip().lower()
    d["remetente_nome"] = d["remetente_nome"].strip() or "LurkQVD"
    return d


@router.get("/config/notificacoes", response_model=ConfigNotificacoes)
def ver_notificacoes(repo: Repo, _: Admin):
    return _config(repo)


@router.post("/config/smtp/testar", response_model=TesteSmtp)
def testar_smtp(body: SmtpTestar, repo: Repo, usuario: Admin):
    """Envia um e-mail de teste com os dados do formulário (nada é gravado)."""
    from src.lurkqvd.config import smtp

    return smtp.testar(_dados(body), _senha(body, repo), body.para or usuario["email"])


@router.put("/config/smtp", response_model=ConfigNotificacoes)
def salvar_smtp(body: SmtpSalvar, repo: Repo, usuario: Admin):
    """Salva o servidor. Só grava se conectar e autenticar; a senha vai para os segredos."""
    from src.lurkqvd.config import segredos, smtp

    dados = _dados(body)
    senha = _senha(body, repo)
    teste = smtp.verificar(dados, senha)
    if not teste["ok"]:
        raise HTTPException(422, f"Não salvei: {teste['erro']}")

    atual = repo.config_smtp()["smtp"] or {}
    if body.senha and dados["usuario"]:
        try:
            smtp.gravar_senha(body.senha)
        except Exception as e:
            logger.exception("falha ao gravar a senha do SMTP")
            codigo, msg = segredos.mensagem_erro(e, smtp.nome_secret())
            raise HTTPException(codigo, msg)
        dados["senha_mascara"] = smtp.mascarar(body.senha)
    elif dados["usuario"]:
        dados["senha_mascara"] = atual.get("senha_mascara")
    repo.salvar_smtp(usuario["id"], dados, senha_trocada=bool(body.senha and dados["usuario"]), status=teste)
    return _config(repo)


@router.post("/config/smtp/enviar-teste", response_model=TesteSmtp)
def enviar_teste(body: EnviarTeste, repo: Repo, usuario: Admin):
    """Envia um e-mail de teste com o servidor salvo e guarda o resultado."""
    from src.lurkqvd.config import segredos, smtp

    cfg = repo.config_smtp()["smtp"]
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "O SMTP ainda não foi configurado.")
    try:
        senha = smtp.ler_senha() if cfg.get("usuario") else None
    except Exception as e:
        codigo, msg = segredos.mensagem_erro(e, smtp.nome_secret())
        raise HTTPException(codigo, msg)
    para = body.para or usuario["email"]
    teste = smtp.testar(cfg, senha, para)
    repo.salvar_status_smtp(teste)
    repo.registrar_notificacao("teste", "LurkQVD: e-mail de teste", [para], teste["ok"], teste["erro"])
    return teste


@router.delete("/config/smtp", status_code=status.HTTP_204_NO_CONTENT)
def remover_smtp(repo: Repo, usuario: Admin):
    """Desliga o envio de e-mails (as preferências ficam guardadas)."""
    from src.lurkqvd.config import smtp

    cfg = repo.config_smtp()["smtp"] or {}
    if not repo.remover_smtp(usuario["id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "O SMTP não está configurado.")
    if not cfg.get("usuario"):  # servidor sem autenticação: não há senha guardada
        return
    try:
        smtp.apagar_senha()
    except Exception:  # a configuração já saiu; a senha órfã não é usada por ninguém
        logger.warning("SMTP removido, mas a senha não saiu dos segredos", exc_info=True)


@router.put("/config/notificacoes", response_model=ConfigNotificacoes)
def alterar_notificacoes(body: Preferencias, repo: Repo, usuario: Admin):
    valor = body.model_dump()
    valor["extras"] = sorted({e.strip().lower() for e in valor["extras"] if e.strip()})
    repo.alterar_notificacoes(usuario["id"], valor)
    return _config(repo)
