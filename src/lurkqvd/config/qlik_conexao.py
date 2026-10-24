"""Conexão com a Qlik Cloud: ler/gravar a API key e testar a conexão.

A API key é um segredo (guardado criptografado no Postgres, veja config/segredos.py),
em JSON com a chave "qvd_token". A configuração da Qlik no Postgres NUNCA guarda a key: só o
resultado do último teste (dono, vencimento), para o painel avisar antes da key expirar.

Variáveis de ambiente:
  LURKQVD_SECRET_QLIK     nome do segredo (padrão: qlik_qvd)
  LURKQVD_QLIK_TENANT     tenant inicial, se ainda não houver um salvo pela tela (ex.: minha-empresa.us)

"""

import base64
import json
import os
import time
from datetime import datetime, timezone

import requests

from src.lurkqvd.config import segredos

CHAVE_TOKEN = "qvd_token"
TENANT_PADRAO = os.getenv("LURKQVD_QLIK_TENANT", "").strip().lower()


def nome_secret() -> str:
    return os.getenv("LURKQVD_SECRET_QLIK", "qlik_qvd")


def tem_token() -> bool:
    """Já existe uma API key salva? (False também quando os segredos estão inacessíveis.)"""
    try:
        return bool(ler_token())
    except RuntimeError:
        return False


def ler_token() -> str:
    """API key atual (sempre a versão mais recente do secret)."""
    token = segredos.ler_json(nome_secret()).get(CHAVE_TOKEN)
    if not token:
        raise RuntimeError(f"O secret {nome_secret()} não tem a chave '{CHAVE_TOKEN}'.")
    return token


def gravar_token(token: str) -> None:
    """Cria uma versão nova do secret trocando só a key; as outras chaves do JSON são mantidas."""
    segredos.alterar_chave(nome_secret(), CHAVE_TOKEN, token)


# ---------------------------------------------------------------------- #
# Teste de conexão
# ---------------------------------------------------------------------- #
def claims_token(token: str) -> dict:
    """Lê o conteúdo da API key (é um JWT) sem validar a assinatura: só para exibir id e vencimento."""
    try:
        meio = token.split(".")[1]
        meio += "=" * (-len(meio) % 4)
        return json.loads(base64.urlsafe_b64decode(meio))
    except (IndexError, ValueError):
        return {}


def mascarar(token: str) -> str:
    # toda key da Qlik começa igual (eyJhbG...), então só o final ajuda a reconhecer
    return f"••••{token[-6:]}" if len(token) > 12 else "••••"


def _data(valor) -> datetime | None:
    if not valor:
        return None
    if isinstance(valor, (int, float)):
        return datetime.fromtimestamp(valor, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


def testar(tenant: str, token: str, timeout: float = 10) -> dict:
    """Chama a Qlik com a key e devolve dono, vencimento e latência. Não levanta exceção."""
    if not tenant:
        return {"ok": False, "erro": "Informe o tenant da Qlik Cloud (ex.: minha-empresa.us) antes da API key.",
                "tenant": tenant, "verificado_em": datetime.now(timezone.utc)}
    base = f"https://{tenant}.qlikcloud.com/api/v1"
    cabecalho = {"Authorization": f"Bearer {token}"}
    claims = claims_token(token)
    resultado = {
        "ok": False,
        "erro": None,
        "tenant": tenant,
        "latencia_ms": None,
        "dono_nome": None,
        "dono_email": None,
        "chave_id": claims.get("jti"),
        "chave_descricao": None,
        "chave_status": None,
        "expira_em": _data(claims.get("exp")),
        "token_mascara": mascarar(token),
        "verificado_em": datetime.now(timezone.utc),
    }

    inicio = time.perf_counter()
    try:
        r = requests.get(f"{base}/users/me", headers=cabecalho, timeout=timeout)
    except requests.RequestException as e:
        resultado["erro"] = f"Não foi possível chegar em {tenant}.qlikcloud.com ({type(e).__name__})."
        return resultado
    resultado["latencia_ms"] = round((time.perf_counter() - inicio) * 1000)

    if r.status_code == 401:
        resultado["erro"] = "A Qlik recusou a API key (inválida, revogada ou expirada)."
        return resultado
    if r.status_code == 404:
        resultado["erro"] = f"Tenant {tenant}.qlikcloud.com não encontrado."
        return resultado
    if not r.ok:
        resultado["erro"] = f"A Qlik respondeu {r.status_code}."
        return resultado

    eu = r.json()
    resultado.update(ok=True, dono_nome=eu.get("name"), dono_email=eu.get("email"))

    # detalhes da key (vencimento oficial, descrição); se não puder ler, fica o 'exp' do JWT
    if resultado["chave_id"]:
        try:
            k = requests.get(f"{base}/api-keys/{resultado['chave_id']}", headers=cabecalho, timeout=timeout)
            if k.ok:
                chave = k.json()
                resultado["chave_descricao"] = chave.get("description")
                resultado["chave_status"] = chave.get("status")
                resultado["expira_em"] = _data(chave.get("expiry")) or resultado["expira_em"]
        except requests.RequestException:
            pass
    return resultado


def para_cache(resultado: dict) -> dict:
    """O que pode ir para o Postgres (sem a key)."""
    def iso(v):
        return v.isoformat() if isinstance(v, datetime) else v

    campos = ("ok", "erro", "tenant", "latencia_ms", "dono_nome", "dono_email", "chave_id",
              "chave_descricao", "chave_status", "expira_em", "token_mascara", "verificado_em")
    return {c: iso(resultado.get(c)) for c in campos}
