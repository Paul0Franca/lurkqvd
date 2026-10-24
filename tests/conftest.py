"""Fixtures da suíte: banco descartável (com as migrações aplicadas), API de teste e um SMTP falso.

Os testes de banco precisam de um Postgres. Por padrão usam o do docker-compose.dev.yml; outro servidor:
    LURKQVD_TESTE_PG=postgresql://usuario:senha@host:porta/postgres  pytest
Sem Postgres acessível, esses testes são pulados (os de unidade rodam do mesmo jeito).
"""

import os
import socketserver
import threading
import uuid
from email import message_from_bytes

import psycopg
import pytest
from cryptography.fernet import Fernet

SERVIDOR = os.getenv("LURKQVD_TESTE_PG", "postgresql://lurkqvd:lurkqvd_dev@127.0.0.1:5433/postgres")
SENHA_ADMIN = "senha-do-admin-de-teste"


def _com_banco(nome: str) -> str:
    base, _, _ = SERVIDOR.rpartition("/")
    return f"{base}/{nome}"


@pytest.fixture(scope="session")
def banco():
    """DSN de um banco novo, migrado, apagado no fim da sessão."""
    nome = f"lurkqvd_pytest_{uuid.uuid4().hex[:8]}"
    try:
        with psycopg.connect(SERVIDOR, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f'CREATE DATABASE "{nome}"')
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres de teste indisponível ({SERVIDOR}): {e}")
    dsn = _com_banco(nome)
    from src.lurkqvd import migracoes

    migracoes.migrar(dsn)
    yield dsn
    with psycopg.connect(SERVIDOR, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)')


@pytest.fixture(scope="session")
def ambiente(banco):
    """Variáveis de ambiente do LurkQVD apontando para o banco de teste (sem nada do .env de quem roda)."""
    anteriores = {k: os.environ.get(k) for k in ("LURKQVD_PG_DSN", "LURKQVD_FERNET_KEY", "LURKQVD_ADMIN_SENHA", "LURKQVD_AUTH_DEV")}
    os.environ.update(LURKQVD_PG_DSN=banco, LURKQVD_FERNET_KEY=Fernet.generate_key().decode(), LURKQVD_ADMIN_SENHA=SENHA_ADMIN)
    os.environ.pop("LURKQVD_AUTH_DEV", None)
    yield
    for k, v in anteriores.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="session")
def cliente(ambiente):
    """TestClient da API (a subida cria o admin padrão no banco de teste)."""
    from fastapi.testclient import TestClient

    from src.lurkqvd.api import auth
    from src.lurkqvd.api.main import app, get_qlik

    auth.get_repo.cache_clear()
    get_qlik.cache_clear()
    with TestClient(app) as c:
        yield c
    auth.get_repo.cache_clear()


@pytest.fixture(autouse=True)
def _sem_bloqueio_de_login():
    """Cada teste começa sem tentativas de login acumuladas."""
    from src.lurkqvd.api import auth

    auth._tentativas.clear()
    yield


# ---------------------------------------------------------------------- #
# SMTP falso: aceita tudo e guarda as mensagens
# ---------------------------------------------------------------------- #
class _Smtp(socketserver.StreamRequestHandler):
    caixa: list = []

    def handle(self):
        def w(s):
            self.wfile.write((s + "\r\n").encode())

        w("220 smtp falso")
        while True:
            linha = self.rfile.readline().decode(errors="replace").strip()
            if not linha:
                return
            cmd = linha.split(" ")[0].upper()
            if cmd == "EHLO":
                w("250-smtp falso")
                w("250 OK")
            elif cmd == "DATA":
                w("354 pode mandar")
                corpo = []
                while (lin := self.rfile.readline()) not in (b".\r\n", b".\n", b""):
                    corpo.append(lin)
                _Smtp.caixa.append(message_from_bytes(b"".join(corpo)))
                w("250 OK")
            elif cmd == "QUIT":
                w("221 tchau")
                return
            else:
                w("250 OK")


@pytest.fixture(scope="session")
def smtp_falso():
    """(porta, caixa de entrada). Cada item da caixa é um email.message.Message."""
    servidor = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Smtp)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield servidor.server_address[1], _Smtp.caixa
    servidor.shutdown()


def texto(msg) -> str:
    """Parte text/plain de um e-mail recebido pelo SMTP falso."""
    parte = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    return parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8")
