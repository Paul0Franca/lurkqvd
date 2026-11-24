"""Avisos dentro da ferramenta: público por papel, leitura por pessoa, expiração e o que só o admin faz."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import SENHA_ADMIN

NOVA = "senha-nova-do-admin-2026"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin(cliente):
    """Token de admin (completa a conta do admin padrão se outro módulo ainda não completou)."""
    r = cliente.post("/auth/entrar", json={"login": "chefe@empresa.com", "senha": NOVA})
    if r.status_code == 200:
        return r.json()["token"]
    t = cliente.post("/auth/entrar", json={"login": "admin", "senha": SENHA_ADMIN}).json()["token"]
    cliente.post("/auth/senha", headers=_h(t), json={"atual": SENHA_ADMIN, "nova": NOVA, "email": "chefe@empresa.com", "nome": "Chefe"})
    return t


def _pessoa(papel: str) -> str:
    """Sessão de uma pessoa nova com o papel pedido (criada direto no banco)."""
    from src.lurkqvd.api import auth

    repo = auth.get_repo()
    u = repo.criar_usuario(f"{papel}-{uuid.uuid4().hex[:6]}@empresa.com", papel.title(), papel, "x", trocar_senha=False)
    token, _ = repo.criar_sessao(u["id"], "127.0.0.1", "pytest")
    return token


def _meus(cliente, token):
    r = cliente.get("/avisos", headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_novidade_da_instalacao_aparece_para_todos(cliente, admin):
    leitor = _pessoa("leitor")
    avisos = _meus(cliente, leitor)
    pagina = [a for a in avisos["avisos"] if a["origem"] == "sistema"]
    assert pagina and pagina[0]["link_url"] == "https://datalurk.com.br/lurkqvd"
    assert pagina[0]["abrir_ao_entrar"] and not pagina[0]["lido"]
    assert avisos["nao_lidos"] >= 1


def test_publico_por_papel_e_leitura_por_pessoa(cliente, admin):
    r = cliente.post("/config/avisos", headers=_h(admin),
                     json={"titulo": "  Manutenção no sábado ", "texto": "O worker para das 8h às 10h.", "publico": "editor"})
    assert r.status_code == 201, r.text
    aviso = r.json()
    assert aviso["titulo"] == "Manutenção no sábado"

    leitor, editor, outro_editor = _pessoa("leitor"), _pessoa("editor"), _pessoa("editor")
    assert aviso["id"] not in [a["id"] for a in _meus(cliente, leitor)["avisos"]]
    meus = _meus(cliente, editor)
    assert next(a for a in meus["avisos"] if a["id"] == aviso["id"])["lido"] is False

    # quem publicou já tem como lido (o balão não abre para ele mesmo)
    assert next(a for a in _meus(cliente, admin)["avisos"] if a["id"] == aviso["id"])["lido"] is True

    assert cliente.post("/avisos/lidos", headers=_h(editor), json={"ids": [aviso["id"]]}).status_code == 204
    assert next(a for a in _meus(cliente, editor)["avisos"] if a["id"] == aviso["id"])["lido"] is True
    assert next(a for a in _meus(cliente, outro_editor)["avisos"] if a["id"] == aviso["id"])["lido"] is False

    # "marcar todos" zera a contagem
    assert cliente.post("/avisos/lidos", headers=_h(outro_editor), json={}).status_code == 204
    assert _meus(cliente, outro_editor)["nao_lidos"] == 0

    lista = cliente.get("/config/avisos", headers=_h(admin)).json()
    linha = next(a for a in lista if a["id"] == aviso["id"])
    assert linha["leituras"] >= 3 and linha["publico_total"] >= 3


def test_aviso_expirado_some_e_remover(cliente, admin):
    from src.lurkqvd.api import auth

    r = cliente.post("/config/avisos", headers=_h(admin), json={"titulo": "Some logo", "texto": "x"})
    aviso_id = r.json()["id"]
    leitor = _pessoa("leitor")
    assert aviso_id in [a["id"] for a in _meus(cliente, leitor)["avisos"]]

    with auth.get_repo()._conn() as conn:
        conn.execute("UPDATE lurkqvd.avisos SET expira_em = now() - interval '1 minute' WHERE id = %s", (aviso_id,))
    assert aviso_id not in [a["id"] for a in _meus(cliente, leitor)["avisos"]]
    assert next(a for a in cliente.get("/config/avisos", headers=_h(admin)).json() if a["id"] == aviso_id)["expirado"]

    assert cliente.delete(f"/config/avisos/{aviso_id}", headers=_h(admin)).status_code == 204
    assert cliente.delete(f"/config/avisos/{aviso_id}", headers=_h(admin)).status_code == 404
    acoes = [a["acao"] for a in cliente.get("/auditoria?categoria=sistema", headers=_h(admin)).json()["itens"]]
    assert "aviso.publicar" in acoes and "aviso.remover" in acoes


def test_validacoes_e_permissoes(cliente, admin):
    editor = _pessoa("editor")
    assert cliente.post("/config/avisos", headers=_h(editor), json={"titulo": "a", "texto": "b"}).status_code == 403
    assert cliente.get("/config/avisos", headers=_h(editor)).status_code == 403
    # link só http(s): vira <a href> na tela de todo mundo
    assert cliente.post("/config/avisos", headers=_h(admin),
                        json={"titulo": "a", "texto": "b", "link_url": "javascript:alert(1)"}).status_code == 422
    passado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert cliente.post("/config/avisos", headers=_h(admin),
                        json={"titulo": "a", "texto": "b", "expira_em": passado}).status_code == 422
    assert cliente.get("/avisos").status_code == 401
