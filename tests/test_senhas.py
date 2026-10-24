import re

from src.lurkqvd import senhas


def test_hash_confere_so_com_a_senha_certa():
    h = senhas.gerar_hash("uma senha qualquer")
    assert h.startswith("scrypt$")
    assert senhas.conferir("uma senha qualquer", h)
    assert not senhas.conferir("outra senha", h)


def test_hash_usa_sal_diferente_a_cada_vez():
    assert senhas.gerar_hash("igual") != senhas.gerar_hash("igual")


def test_hash_invalido_ou_ausente_nunca_confere():
    assert not senhas.conferir("x", None)
    assert not senhas.conferir("x", "")
    assert not senhas.conferir("x", "lixo$que$nao$e$hash")
    assert not senhas.conferir_tempo_constante("x", None)


def test_senha_temporaria_tem_formato_e_sem_caracteres_ambiguos():
    for _ in range(50):
        t = senhas.temporaria()
        assert re.fullmatch(r"[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}", t)
        assert not set(t) & set("0O1lI")


def test_regras_da_senha_nova():
    assert senhas.problema("curta") is not None
    assert senhas.problema(" com espaco no inicio") is not None
    assert senhas.problema("Fulano@Empresa.com", login="fulano@empresa.com") is not None
    assert senhas.problema("mesma-senha-123", atual="mesma-senha-123") is not None
    assert senhas.problema("uma frase longa e boa") is None
