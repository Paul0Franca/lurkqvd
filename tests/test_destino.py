"""Mover o destino de uma carga (espaço e/ou pasta)."""

import uuid

import psycopg
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


@pytest.fixture(scope="module")
def espaco(banco):
    """Um espaço compartilhado no cache de espaços (como se viesse da Qlik)."""
    cid = str(uuid.uuid4())
    with psycopg.connect(banco) as conn:
        conn.execute("INSERT INTO lurkqvd.espacos (connection_id, space_id, nome, tipo) VALUES (%s, %s, 'Vendas', 'shared')",
                      (cid, uuid.uuid4().hex[:24]))
    return cid


def _criar(cliente, admin, nome, pasta="origem"):
    r = cliente.post("/cargas", headers=_h(admin), json={"nome": nome, "query": "SELECT 1", "qlik_path": f"{pasta}/{nome}.qvd"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_move_para_outro_espaco_e_pasta(cliente, admin, espaco, banco):
    cid = _criar(cliente, admin, "carga_movida")
    with psycopg.connect(banco) as conn:  # como se já tivesse publicado uma vez
        conn.execute("UPDATE lurkqvd.cargas SET file_id = %s WHERE id = %s", (str(uuid.uuid4()), cid))

    r = cliente.post(f"/cargas/{cid}/destino", headers=_h(admin), json={"connection_id": espaco, "pasta": "  dw / vendas /"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["connection_id"] == espaco
    assert c["qlik_path"] == "dw/vendas/carga_movida.qvd"  # o nome do arquivo não muda
    assert c["file_id"] is None  # a próxima execução publica no destino novo

    aud = cliente.get("/auditoria?categoria=cargas", headers=_h(admin)).json()["itens"]
    assert any(a["acao"] == "carga.destino" and a["alvo_id"] == str(cid) for a in aud)

    # de volta para o pessoal, na raiz
    c = cliente.post(f"/cargas/{cid}/destino", headers=_h(admin), json={"connection_id": None, "pasta": ""}).json()
    assert c["connection_id"] is None and c["qlik_path"] == "carga_movida.qvd"


def test_recusa_com_execucao_ativa_e_pasta_invalida(cliente, admin, banco):
    cid = _criar(cliente, admin, "carga_ocupada")
    with psycopg.connect(banco) as conn:
        conn.execute("INSERT INTO lurkqvd.execucoes (carga_id, status, origem) VALUES (%s, 'pendente', 'manual')", (cid,))
    r = cliente.post(f"/cargas/{cid}/destino", headers=_h(admin), json={"connection_id": None, "pasta": "nova"})
    assert r.status_code == 409 and "fila ou rodando" in r.json()["detail"]

    livre = _criar(cliente, admin, "carga_livre")
    assert cliente.post(f"/cargas/{livre}/destino", headers=_h(admin), json={"pasta": "a/../b"}).status_code == 422
    assert cliente.post(f"/cargas/{livre}/destino", headers=_h(admin), json={"pasta": "a:b"}).status_code == 422
    assert cliente.post("/cargas/999999/destino", headers=_h(admin), json={"pasta": "x"}).status_code == 404


def test_conflito_real_no_espaco_pessoal(cliente, admin, banco):
    a = _criar(cliente, admin, "carga_dup1", pasta="p1")
    b = _criar(cliente, admin, "carga_dup2", pasta="p2")
    with psycopg.connect(banco) as conn:  # mesmo nome de arquivo nas duas (só dá para forçar no banco)
        conn.execute("UPDATE lurkqvd.cargas SET qlik_path = 'p2/igual.qvd' WHERE id = %s", (b,))
        conn.execute("UPDATE lurkqvd.cargas SET qlik_path = 'p1/igual.qvd' WHERE id = %s", (a,))
    r = cliente.post(f"/cargas/{a}/destino", headers=_h(admin), json={"connection_id": None, "pasta": "p2"})
    assert r.status_code == 409 and "carga_dup2" in r.json()["detail"]


def test_so_admin_move(cliente, admin):
    cid = _criar(cliente, admin, "carga_protegida")
    assert cliente.post(f"/cargas/{cid}/destino", json={"pasta": "x"}).status_code == 401
