"""Servidor SMTP para os e-mails do LurkQVD (convites e avisos de erro).

Servidor, porta, segurança, usuário e remetente ficam no Postgres (configuração "smtp").
A senha fica no segredo (config/segredos.py) LURKQVD_SECRET_SMTP (padrão: lurkqvd_smtp),
em JSON {"senha": "..."}. Usuário vazio = servidor sem autenticação (ex.: relay por IP).

Exemplos:
  Google Workspace, conta com senha de app:  smtp.gmail.com, 587, STARTTLS
  Google Workspace, relay por IP:            smtp-relay.gmail.com, 587, STARTTLS, sem usuário
  Microsoft 365:                             smtp.office365.com, 587, STARTTLS

Variáveis de ambiente:
  LURKQVD_SECRET_SMTP   nome do secret (padrão: lurkqvd_smtp)
"""

import errno
import os
import smtplib
import socket
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from src.lurkqvd import emails, fuso
from src.lurkqvd.config import segredos
from src.lurkqvd.emails import Email

CHAVE_SENHA = "senha"
SEGURANCAS = ("starttls", "ssl", "nenhuma")
TIMEOUT = 20  # segundos: um servidor que não responde não pode travar a tela nem o worker


def nome_secret() -> str:
    return os.getenv("LURKQVD_SECRET_SMTP", "lurkqvd_smtp")


# ---------------------------------------------------------------------- #
# Senha (segredos)
# ---------------------------------------------------------------------- #
def ler_senha() -> str | None:
    return segredos.ler_json(nome_secret(), vazio_se_sem_versao=True).get(CHAVE_SENHA)


def gravar_senha(senha: str) -> None:
    segredos.alterar_chave(nome_secret(), CHAVE_SENHA, senha, vazio_se_sem_versao=True)


def apagar_senha() -> None:
    segredos.alterar_chave(nome_secret(), CHAVE_SENHA, None, vazio_se_sem_versao=True)


def mascarar(senha: str | None) -> str | None:
    return f"••••{senha[-2:]}" if senha and len(senha) > 8 else ("••••" if senha else None)


# ---------------------------------------------------------------------- #
# Conexão e envio
# ---------------------------------------------------------------------- #
def _conectar(cfg: dict, senha: str | None, timeout: float) -> smtplib.SMTP:
    host, porta = cfg["host"], int(cfg["porta"])
    contexto = ssl.create_default_context()
    if cfg.get("seguranca") == "ssl":
        servidor: smtplib.SMTP = smtplib.SMTP_SSL(host, porta, timeout=timeout, context=contexto)
    else:
        servidor = smtplib.SMTP(host, porta, timeout=timeout)
    try:
        servidor.ehlo()
        if cfg.get("seguranca") == "starttls":
            servidor.starttls(context=contexto)
            servidor.ehlo()
        if cfg.get("usuario"):
            servidor.login(cfg["usuario"], senha or "")
    except Exception:
        servidor.close()
        raise
    return servidor


def montar(cfg: dict, para: list[str], email: Email) -> EmailMessage:
    """multipart/alternative (texto + HTML), com as imagens do HTML embutidas (multipart/related, cid:)."""
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("remetente_nome") or "LurkQVD", cfg["remetente"]))
    msg["To"] = ", ".join(para)
    msg["Subject"] = email.assunto
    msg["Message-ID"] = make_msgid(domain=cfg["remetente"].rsplit("@", 1)[-1])
    msg.set_content(email.texto)
    msg.add_alternative(email.html, subtype="html")
    parte_html = msg.get_payload()[1]
    for cid, dados in email.imagens.items():
        if f"cid:{cid}" in email.html:
            parte_html.add_related(dados, "image", "png", cid=f"<{cid}>", filename=f"{cid}.png", disposition="inline")
    return msg


def enviar(cfg: dict, senha: str | None, para: list[str], email: Email, timeout: float = TIMEOUT) -> None:
    """Envia um e-mail. Levanta exceção se o servidor recusar (use mensagem_erro para exibir)."""
    if not para:
        raise ValueError("Nenhum destinatário.")
    servidor = _conectar(cfg, senha, timeout)
    try:
        servidor.send_message(montar(cfg, para, email))
    finally:
        try:
            servidor.quit()
        except Exception:
            servidor.close()


def verificar(cfg: dict, senha: str | None, timeout: float = TIMEOUT) -> dict:
    """Conecta e autentica, sem enviar nada. Não levanta exceção."""
    resultado = {"ok": False, "erro": None, "latencia_ms": None, "para": None,
                 "testado_em": datetime.now(timezone.utc).isoformat()}
    inicio = time.perf_counter()
    try:
        _conectar(cfg, senha, timeout).quit()
    except Exception as e:
        resultado["erro"] = mensagem_erro(e, cfg)
        return resultado
    resultado.update(ok=True, latencia_ms=round((time.perf_counter() - inicio) * 1000))
    return resultado


def testar(cfg: dict, senha: str | None, para: str, timeout: float = TIMEOUT) -> dict:
    """Envia um e-mail de teste para `para`. Não levanta exceção."""
    resultado = {"ok": False, "erro": None, "latencia_ms": None, "para": para,
                 "testado_em": datetime.now(timezone.utc).isoformat()}
    inicio = time.perf_counter()
    quando = datetime.now(fuso.ZONA).strftime("%d/%m/%Y %H:%M")
    try:
        enviar(cfg, senha, [para], emails.teste(host=cfg["host"], porta=cfg["porta"], seguranca=cfg.get("seguranca", ""),
                                                remetente=cfg["remetente"], quando=quando), timeout=timeout)
    except Exception as e:
        resultado["erro"] = mensagem_erro(e, cfg)
        return resultado
    resultado.update(ok=True, latencia_ms=round((time.perf_counter() - inicio) * 1000))
    return resultado


def mensagem_erro(e: Exception, cfg: dict) -> str:
    """Erro do smtplib/rede em uma frase que diga o que conferir."""
    host = f"{cfg.get('host')}:{cfg.get('porta')}"
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return ("O servidor recusou o usuário ou a senha. No Google e no Microsoft 365, use uma senha de app "
                f"(não a senha normal da conta). Resposta: {_resposta(e)}")
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"O servidor não aceita enviar como {cfg.get('remetente')}. Resposta: {_resposta(e)}"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        recusados = ", ".join(e.recipients) if e.recipients else ""
        return f"O servidor recusou o destinatário {recusados}."
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return "O servidor não oferece STARTTLS nessa porta. Tente SSL (porta 465) ou sem criptografia."
    if isinstance(e, ssl.SSLError):
        return ("Falha na criptografia. Confira a porta e a segurança: 587 costuma ser STARTTLS e 465, SSL. "
                f"({e.reason or e})")
    if isinstance(e, socket.gaierror):
        return f"Servidor {cfg.get('host')} não encontrado (DNS)."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return f"{host} não respondeu em {TIMEOUT} segundos (firewall ou porta errada?)."
    if isinstance(e, ConnectionRefusedError):
        return f"{host} recusou a conexão (porta fechada?)."
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return f"{host} fechou a conexão. Confira a porta e o tipo de segurança."
    if isinstance(e, smtplib.SMTPResponseException):
        return f"O servidor respondeu {e.smtp_code}: {_resposta(e)}"
    if isinstance(e, OSError) and e.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        # o socket tenta IPv4 e IPv6 e mostra só o último erro: quase sempre é o firewall barrando a saída
        return (f"O servidor do LurkQVD não alcança {host}: a rede (firewall) bloqueia a saída para esse endereço e porta. "
                "Peça a liberação da saída para ele ou use um servidor SMTP da rede interna (relay).")
    if isinstance(e, OSError):
        return f"Não foi possível conectar em {host} ({e.strerror or type(e).__name__})."
    return f"{type(e).__name__}: {e}"


def _resposta(e: Exception) -> str:
    erro = getattr(e, "smtp_error", b"")
    texto = erro.decode("utf-8", "replace") if isinstance(erro, bytes) else str(erro)
    return " ".join(texto.split())[:300]
