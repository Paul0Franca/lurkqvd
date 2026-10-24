"""Login, troca obrigatória de senha, sessões, cadastro com senha temporária por e-mail e permissões."""

import re

import pytest

from src.lurkqvd import senhas
from tests.conftest import SENHA_ADMIN, texto

NOVA_ADMIN = "senha-nova-do-admin-2026"


def _entrar(cliente, login, senha):
    return cliente.post("/auth/entrar", json={"login": login, "senha": senha})


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin(cliente):
    """Token do admin padrão, já com a conta completada (nome, e-mail e senha própria)."""
    r = _entrar(cliente, "admin", SENHA_ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["usuario"]["trocar_senha"] is True
    t = r.json()["token"]
    r = cliente.post("/auth/senha", headers=_h(t),
                     json={"atual": SENHA_ADMIN, "nova": NOVA_ADMIN, "email": "chefe@empresa.com", "nome": "Chefe"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "chefe@empresa.com"
    return t


def test_rotas_protegidas_sem_login(cliente):
    """Toda rota, menos /health e /auth/entrar, exige login."""
    from src.lurkqvd.api.main import app

    publicas = {"/health", "/auth/entrar", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
    rotas = []
    for r in app.routes:
        incluido = getattr(r, "original_router", None)  # routers incluídos vêm encapsulados
        for sub in incluido.routes if incluido else [r]:
            if getattr(sub, "methods", None) and sub.path not in publicas:
                rotas.append((sorted(sub.methods)[0], re.sub(r"\{[^}]+\}", "1", sub.path)))
    assert len(rotas) > 50
    for metodo, caminho in rotas:
        r = cliente.request(metodo, caminho, json={})
        assert r.status_code == 401, f"{metodo} {caminho} respondeu {r.status_code} sem login"


def test_token_invalido(cliente):
    assert cliente.get("/resumo", headers=_h("lqs_inventado")).status_code == 401
    assert cliente.get("/resumo", headers=_h("lqvd_inventado")).status_code == 401
    assert cliente.get("/resumo", headers=_h("qualquer-coisa")).status_code == 401


def test_admin_padrao_troca_obrigatoria_e_completa_a_conta(cliente):
    r = _entrar(cliente, "admin", SENHA_ADMIN)
    if r.status_code == 401:  # a fixture admin já completou a conta
        pytest.skip("conta do admin já completada por outro teste")
    t = r.json()["token"]
    assert cliente.get("/resumo", headers=_h(t)).status_code == 403  # só /auth até trocar
    assert cliente.get("/auth/me", headers=_h(t)).status_code == 200
    r = cliente.post("/auth/senha", headers=_h(t), json={"atual": SENHA_ADMIN, "nova": "outra-senha-boa"})
    assert r.status_code == 422  # admin padrão precisa informar nome e e-mail


def test_login_errado_e_bloqueio(cliente, admin):
    assert _entrar(cliente, "chefe@empresa.com", "errada-errada").status_code == 401
    assert _entrar(cliente, "ninguem@empresa.com", "qualquer").status_code == 401  # mesma resposta
    for _ in range(5):
        _entrar(cliente, "chefe@empresa.com", "errada-errada")
    assert _entrar(cliente, "chefe@empresa.com", NOVA_ADMIN).status_code == 429


def test_login_antigo_admin_nao_vale_mais(cliente, admin):
    assert _entrar(cliente, "admin", SENHA_ADMIN).status_code == 401
    assert _entrar(cliente, "chefe@empresa.com", NOVA_ADMIN).status_code == 200


def test_sair_derruba_a_sessao(cliente, admin):
    t = _entrar(cliente, "chefe@empresa.com", NOVA_ADMIN).json()["token"]
    assert cliente.get("/resumo", headers=_h(t)).status_code == 200
    assert cliente.post("/auth/sair", headers=_h(t)).status_code == 204
    assert cliente.get("/resumo", headers=_h(t)).status_code == 401


def test_cadastro_exige_smtp(cliente, admin):
    r = cliente.post("/usuarios", headers=_h(admin), json={"email": "x@empresa.com", "nome": "X", "papel": "leitor"})
    assert r.status_code == 422
    assert "e-mail" in r.json()["detail"]
    assert all(u["email"] != "x@empresa.com" for u in cliente.get("/usuarios", headers=_h(admin)).json())


def test_cadastro_senha_temporaria_redefinicao_e_permissoes(cliente, admin, smtp_falso):
    porta, caixa = smtp_falso
    r = cliente.put("/config/smtp", headers=_h(admin), json={
        "host": "127.0.0.1", "porta": porta, "seguranca": "nenhuma", "usuario": "",
        "remetente": "lurkqvd@empresa.com", "remetente_nome": "LurkQVD"})
    assert r.status_code == 200, r.text

    # cadastro: a senha temporária chega por e-mail
    r = cliente.post("/usuarios", headers=_h(admin), json={"email": "Leitora@Empresa.com", "nome": "Leitora", "papel": "leitor"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "leitora@empresa.com" and r.json()["trocar_senha"]
    assert caixa[-1]["To"] == "leitora@empresa.com"
    temp = re.search(r"Senha temporária: (\S+)", texto(caixa[-1])).group(1)
    assert cliente.post("/usuarios", headers=_h(admin), json={"email": "leitora@empresa.com", "nome": "L", "papel": "leitor"}).status_code == 409

    # 1º login: só troca a senha
    t = _entrar(cliente, "leitora@empresa.com", temp).json()["token"]
    assert cliente.get("/cargas", headers=_h(t)).status_code == 403
    r = cliente.post("/auth/senha", headers=_h(t), json={"atual": temp, "nova": "senha-da-leitora-1"})
    assert r.status_code == 200 and not r.json()["trocar_senha"]

    # leitora: lê, mas não executa nem administra
    assert cliente.get("/cargas", headers=_h(t)).status_code == 200
    assert cliente.post("/cargas/1/executar", headers=_h(t)).status_code == 403
    assert cliente.get("/usuarios", headers=_h(t)).status_code == 403
    assert cliente.get("/config/segredos", headers=_h(t)).status_code == 403

    # redefinição pelo admin: nova temporária por e-mail, sessão antiga cai, senha antiga não vale
    uid = next(u["id"] for u in cliente.get("/usuarios", headers=_h(admin)).json() if u["email"] == "leitora@empresa.com")
    assert cliente.post(f"/usuarios/{uid}/redefinir-senha", headers=_h(admin)).status_code == 204
    assert "redefinida" in caixa[-1]["Subject"]
    assert cliente.get("/cargas", headers=_h(t)).status_code == 401
    assert _entrar(cliente, "leitora@empresa.com", "senha-da-leitora-1").status_code == 401
    temp2 = re.search(r"Senha temporária: (\S+)", texto(caixa[-1])).group(1)
    assert _entrar(cliente, "leitora@empresa.com", temp2).json()["usuario"]["trocar_senha"]

    # desativada: não entra
    assert cliente.patch(f"/usuarios/{uid}", headers=_h(admin), json={"ativo": False}).status_code == 200
    assert _entrar(cliente, "leitora@empresa.com", temp2).status_code == 403


def test_senha_atual_errada_tem_limite(cliente, admin):
    t = _entrar(cliente, "chefe@empresa.com", NOVA_ADMIN).json()["token"]
    for _ in range(5):
        assert cliente.post("/auth/senha", headers=_h(t), json={"atual": "chute-errado-1", "nova": "qualquer-coisa-boa"}).status_code == 422
    assert cliente.post("/auth/senha", headers=_h(t), json={"atual": NOVA_ADMIN, "nova": "qualquer-coisa-boa"}).status_code == 429


def test_hash_no_banco_nao_e_a_senha(banco, admin):
    import psycopg

    with psycopg.connect(banco) as conn:
        h = conn.execute("SELECT senha_hash FROM lurkqvd.usuarios WHERE email = 'chefe@empresa.com'").fetchone()[0]
        tokens = [r[0] for r in conn.execute("SELECT hash FROM lurkqvd.sessoes")]
    assert NOVA_ADMIN not in h and senhas.conferir(NOVA_ADMIN, h)
    assert all(not t.startswith("lqs_") for t in tokens)  # só o sha256 do token fica no banco


def test_qlik_instalacao_nova_tenant_antes_da_key(cliente, admin):
    r = cliente.get("/config/qlik?testar=true", headers=_h(admin))
    assert r.status_code == 200
    assert r.json()["tenant"] == "" and "tenant" in r.json()["status"]["erro"]
    # sem key salva, o tenant é gravado sem teste (não há o que testar ainda)
    r = cliente.put("/config/qlik", headers=_h(admin), json={"tenant": "minha-empresa.us"})
    assert r.status_code == 200, r.text
    cfg = cliente.get("/config/qlik", headers=_h(admin)).json()
    assert cfg["tenant"] == "minha-empresa.us" and "API key" in cfg["status"]["erro"]
    # rotas que precisam da Qlik avisam em vez de dar erro 500
    r = cliente.post("/espacos/sincronizar", headers=_h(admin))
    assert r.status_code == 422 and "Qlik Cloud" in r.json()["detail"]
