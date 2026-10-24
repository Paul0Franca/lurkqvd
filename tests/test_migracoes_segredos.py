import psycopg
import pytest
from cryptography.fernet import Fernet

from src.lurkqvd import migracoes
from src.lurkqvd.config import segredos


def test_banco_novo_recebe_todas_as_migracoes(banco):
    with psycopg.connect(banco) as conn:
        aplicadas = [r[0] for r in conn.execute("SELECT versao FROM lurkqvd.migracoes ORDER BY versao")]
    assert aplicadas == [v for v, _ in migracoes.arquivos()]


def test_migrar_de_novo_nao_faz_nada(banco):
    assert migracoes.migrar(banco) == []


def test_banco_sem_a_ultima_migracao_e_recusado_com_o_comando(banco):
    ultima_versao, ultima = migracoes.arquivos()[-1]
    migracoes.exigir_em_dia(banco)  # em dia: não levanta
    with psycopg.connect(banco) as conn:
        conn.execute("DELETE FROM lurkqvd.migracoes WHERE versao = %s", (ultima_versao,))
    try:
        assert migracoes.pendentes(banco) == [ultima.name]
        with pytest.raises(migracoes.BancoDesatualizado, match="cli migrar"):
            migracoes.exigir_em_dia(banco)
    finally:
        with psycopg.connect(banco) as conn:
            conn.execute("INSERT INTO lurkqvd.migracoes (versao, arquivo) VALUES (%s, %s)", (ultima_versao, ultima.name))
    assert migracoes.pendentes(banco) == []


def test_segredo_fica_criptografado_e_volta_igual(ambiente, banco):
    segredos.alterar_chave("teste_cripto", "senha", "valor-secreto-123")
    segredos.alterar_chave("teste_cripto", "outra", "x")
    segredos.alterar_chave("teste_cripto", "outra", None)
    assert segredos.ler_json("teste_cripto") == {"senha": "valor-secreto-123"}
    with psycopg.connect(banco) as conn:
        bruto = conn.execute("SELECT valor FROM lurkqvd.segredos WHERE nome = 'teste_cripto'").fetchone()[0]
    assert "valor-secreto" not in bruto


def test_segredo_inexistente(ambiente):
    assert segredos.ler_json("nao_existe", vazio_se_sem_versao=True) == {}
    with pytest.raises(RuntimeError):
        segredos.ler_json("nao_existe")


def test_rotacao_de_chave(ambiente, monkeypatch):
    segredos.alterar_chave("teste_rotacao", "k", "v")
    antiga = __import__("os").environ["LURKQVD_FERNET_KEY"]
    nova = Fernet.generate_key().decode()
    monkeypatch.setenv("LURKQVD_FERNET_KEY", f"{nova},{antiga}")
    assert segredos.ler_json("teste_rotacao") == {"k": "v"}  # a antiga ainda lê
    segredos._rotacionar()
    monkeypatch.setenv("LURKQVD_FERNET_KEY", nova)
    assert segredos.ler_json("teste_rotacao") == {"k": "v"}  # recriptografado com a nova


def test_chave_errada_ou_ausente_da_erro_claro(ambiente, monkeypatch):
    segredos.alterar_chave("teste_chave", "k", "v")
    monkeypatch.setenv("LURKQVD_FERNET_KEY", Fernet.generate_key().decode())
    with pytest.raises(segredos.ChaveErrada):
        segredos.ler_json("teste_chave")
    monkeypatch.setenv("LURKQVD_FERNET_KEY", "")
    with pytest.raises(segredos.SemChave):
        segredos.ler_json("teste_chave")
    assert segredos.mensagem_erro(segredos.SemChave("x"), "teste_chave")[0] == 503
