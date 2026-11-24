"""Excluir cargas e aplicações (com ou sem o QVD na Qlik)."""

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


class _QlikFalsa:
    def __init__(self, falhar: set[str] = frozenset()):
        self.apagados: list[str] = []
        self.falhar = falhar

    def delete_file(self, file_id: str) -> bool:
        if file_id in self.falhar:
            raise RuntimeError("DF-500 erro da Qlik")
        self.apagados.append(file_id)
        return True


@pytest.fixture
def qlik(monkeypatch):
    from src.lurkqvd.api import main

    falsa = _QlikFalsa()
    monkeypatch.setattr(main, "get_qlik", lambda: falsa)
    return falsa


def _criar(cliente, admin, nome, banco, *, publicada=True, execucoes=("sucesso",)):
    r = cliente.post("/cargas", headers=_h(admin), json={"nome": nome, "query": "SELECT 1", "qlik_path": f"rm/{nome}.qvd"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    file_id = str(uuid.uuid4()) if publicada else None
    with psycopg.connect(banco) as conn:
        conn.execute("UPDATE lurkqvd.cargas SET file_id = %s WHERE id = %s", (file_id, cid))
        for st in execucoes:
            conn.execute("INSERT INTO lurkqvd.execucoes (carga_id, status, origem) VALUES (%s, %s, 'manual')", (cid, st))
    return cid, file_id


def _existe(banco, carga_id) -> bool:
    with psycopg.connect(banco) as conn:
        return conn.execute("SELECT 1 FROM lurkqvd.cargas WHERE id = %s", (carga_id,)).fetchone() is not None


def test_exclui_carga_sem_mexer_na_qlik(cliente, admin, banco, qlik):
    cid, _ = _criar(cliente, admin, "rm_so_lurk", banco, execucoes=("sucesso", "erro"))
    r = cliente.delete(f"/cargas/{cid}", headers=_h(admin))
    assert r.status_code == 200, r.text
    assert r.json() == {"nome": "rm_so_lurk", "qlik": None}
    assert not _existe(banco, cid)
    assert qlik.apagados == []
    with psycopg.connect(banco) as conn:
        assert conn.execute("SELECT count(*) FROM lurkqvd.execucoes WHERE carga_id = %s", (cid,)).fetchone()[0] == 0

    aud = cliente.get("/auditoria?categoria=cargas", headers=_h(admin)).json()["itens"]
    reg = next(a for a in aud if a["acao"] == "carga.remover" and a["alvo_id"] == str(cid))
    assert reg["alvo_nome"] == "rm_so_lurk" and reg["detalhes"]["execucoes"] == 2
    assert cliente.delete(f"/cargas/{cid}", headers=_h(admin)).status_code == 404


def test_exclui_carga_e_o_arquivo_na_qlik(cliente, admin, banco, qlik):
    cid, file_id = _criar(cliente, admin, "rm_com_qlik", banco)
    r = cliente.delete(f"/cargas/{cid}?apagar_qlik=true", headers=_h(admin))
    assert r.status_code == 200, r.text
    assert r.json()["qlik"]["apagados"] == ["rm_com_qlik"]
    assert qlik.apagados == [file_id]

    # nunca publicada: nada a apagar na Qlik
    nova, _ = _criar(cliente, admin, "rm_nunca_publicou", banco, publicada=False, execucoes=())
    r = cliente.delete(f"/cargas/{nova}?apagar_qlik=true", headers=_h(admin))
    assert r.json()["qlik"] == {"apagados": [], "nao_existiam": [], "erros": []}


def test_falha_na_qlik_nao_desfaz_a_exclusao(cliente, admin, banco, qlik):
    cid, file_id = _criar(cliente, admin, "rm_qlik_falha", banco)
    qlik.falhar = {file_id}
    r = cliente.delete(f"/cargas/{cid}?apagar_qlik=true", headers=_h(admin))
    assert r.status_code == 200
    assert r.json()["qlik"]["erros"][0]["nome"] == "rm_qlik_falha"
    assert not _existe(banco, cid)


def test_recusa_carga_na_fila_e_quem_nao_e_admin(cliente, admin, banco, qlik):
    cid, _ = _criar(cliente, admin, "rm_na_fila", banco, execucoes=("pendente",))
    r = cliente.delete(f"/cargas/{cid}", headers=_h(admin))
    assert r.status_code == 409 and "fila ou rodando" in r.json()["detail"]
    assert _existe(banco, cid)
    assert cliente.delete(f"/cargas/{cid}").status_code == 401


def test_recusa_carga_em_aplicacao_executando(cliente, admin, banco, qlik):
    cid, _ = _criar(cliente, admin, "rm_app_rodando", banco)
    app = cliente.post("/aplicacoes", headers=_h(admin), json={"nome": "App rodando", "carga_ids": [cid]}).json()
    with psycopg.connect(banco) as conn:
        conn.execute("INSERT INTO lurkqvd.execucoes_aplicacao (aplicacao_id, status, origem) VALUES (%s, 'pendente', 'manual')",
                     (app["id"],))
    r = cliente.delete(f"/cargas/{cid}", headers=_h(admin))
    assert r.status_code == 409 and "App rodando" in r.json()["detail"]


def test_remover_aplicacao_mantem_ou_leva_as_cargas(cliente, admin, banco, qlik):
    so_a, fa = _criar(cliente, admin, "rm_so_em_a", banco)
    compartilhada, _ = _criar(cliente, admin, "rm_em_a_e_b", banco)
    a = cliente.post("/aplicacoes", headers=_h(admin), json={"nome": "App A", "carga_ids": [so_a, compartilhada]}).json()
    cliente.post("/aplicacoes", headers=_h(admin), json={"nome": "App B", "carga_ids": [compartilhada]})
    c = cliente.post("/aplicacoes", headers=_h(admin), json={"nome": "App C", "carga_ids": [so_a]}).json()

    # sem levar: as cargas ficam
    r = cliente.delete(f"/aplicacoes/{c['id']}", headers=_h(admin))
    assert r.status_code == 200 and r.json()["cargas_removidas"] == []
    assert _existe(banco, so_a)

    # levando: só a que estava apenas em A sai (a que também está em B continua)
    r = cliente.delete(f"/aplicacoes/{a['id']}?levar_cargas=true&apagar_qlik=true", headers=_h(admin))
    assert r.status_code == 200, r.text
    assert r.json()["cargas_removidas"] == ["rm_so_em_a"]
    assert r.json()["qlik"]["apagados"] == ["rm_so_em_a"]
    assert qlik.apagados == [fa]
    assert not _existe(banco, so_a) and _existe(banco, compartilhada)
