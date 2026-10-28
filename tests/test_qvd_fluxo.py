"""Gerador de QVD em fluxo: o arquivo tem de sair idêntico ao do qvdrs (sem banco nem Qlik).

Cada caso gera o mesmo DataFrame pelos dois caminhos (qvd.write_arrow de uma vez e
EscritorQvdFluxo em lotes) e compara os bytes. Só a data de criação do cabeçalho é ignorada.
"""

import datetime as dt
import random
import re

import polars as pl
import pytest
import qvd

from src.lurkqvd.pipeline import qvd_fluxo
from src.lurkqvd.pipeline.gerador_qvd import GeradorQvd
from src.lurkqvd.pipeline.qvd_fluxo import EscritorQvdFluxo, conferir_arquivo


def _sem_data(dados: bytes) -> bytes:
    return re.sub(rb"<CreateUtcTime>.*?</CreateUtcTime>", b"<CreateUtcTime></CreateUtcTime>", dados, count=1)


def _pelo_fluxo(tmp_path, lotes: list[pl.DataFrame], nome="fluxo.qvd", ao_progredir=None):
    destino = tmp_path / nome
    with EscritorQvdFluxo(destino, "tabela", dir_temp=tmp_path) as esc:
        for lote in lotes:
            esc.adicionar(lote)
        info = esc.finalizar(ao_progredir=ao_progredir)
    return destino, info


def _em_lotes(df: pl.DataFrame, tamanhos) -> list[pl.DataFrame]:
    lotes, ini = [], 0
    for t in tamanhos:
        lotes.append(df.slice(ini, t))
        ini += t
    if ini < df.height:
        lotes.append(df.slice(ini))
    return lotes


def _conferir_igual(tmp_path, df: pl.DataFrame, lotes: list[pl.DataFrame]) -> None:
    ref = tmp_path / "qvdrs.qvd"
    qvd.write_arrow(df.to_arrow(), str(ref), table_name="tabela")
    gerado, info = _pelo_fluxo(tmp_path, lotes)
    assert _sem_data(gerado.read_bytes()) == _sem_data(ref.read_bytes())
    assert info["linhas"] == df.height
    conferir_arquivo(gerado, df.height)


def _misturado(n: int, semente: int) -> pl.DataFrame:
    rnd = random.Random(semente)

    def talvez(v, p=0.15):
        return None if rnd.random() < p else v

    base = dt.datetime(2024, 1, 1)
    return pl.DataFrame({
        "id": list(range(n)),
        "inteiro": [talvez(rnd.randint(-50, 50)) for _ in range(n)],
        "valor": [talvez(round(rnd.uniform(-1e6, 1e6), 2)) for _ in range(n)],
        "texto": [talvez(rnd.choice(["São Paulo", "Belém", "日本", "", "a;b", "x" * 300])) for _ in range(n)],
        "data": [talvez(dt.date(2024, 1, 1) + dt.timedelta(days=rnd.randint(0, 400))) for _ in range(n)],
        "data_hora": [talvez(base + dt.timedelta(seconds=rnd.randint(0, 10**6))) for _ in range(n)],
        "constante": ["fixo"] * n,
    })


@pytest.mark.parametrize("semente", [1, 2, 3])
@pytest.mark.parametrize("tamanhos", [[], [1, 1, 1], [7, 300, 2], [999]], ids=["um", "unitarios", "irregulares", "quase-tudo"])
def test_tipos_misturados_em_qualquer_divisao_de_lotes(tmp_path, semente, tamanhos):
    df = _misturado(1_000, semente)
    _conferir_igual(tmp_path, df, _em_lotes(df, tamanhos))


def test_indices_de_8_16_e_32_bits(tmp_path):
    # 70 mil distintos: o índice temporário passa por uint8 (1º lote), uint16 e uint32
    n = 70_000
    df = pl.DataFrame({"id": [n - i for i in range(n)], "par": [i % 2 for i in range(n)]})
    _conferir_igual(tmp_path, df, _em_lotes(df, [100, 60_000]))


def test_data_hora_que_o_qvdrs_junta_por_milissegundos(tmp_path):
    # o qvdrs junta valores que só diferem nos milissegundos: o fluxo usa a "tradução"
    base = dt.datetime(2024, 5, 1, 10, 0, 0)
    valores = [base + dt.timedelta(microseconds=1000 * (i % 7)) + dt.timedelta(seconds=i // 7) for i in range(500)]
    valores[3] = None
    df = pl.DataFrame({"t": valores})
    _conferir_igual(tmp_path, df, _em_lotes(df, [10, 250]))


def test_texto_com_muitos_distintos_escrito_direto(tmp_path, monkeypatch):
    monkeypatch.setattr(qvd_fluxo, "LIMITE_TEXTO_DIRETO", 20)  # o caminho direto sem precisar de 50 mil valores
    df = pl.DataFrame({"s": [None if i % 11 == 0 else f"código-{i % 97}" for i in range(2_000)]})
    _conferir_igual(tmp_path, df, _em_lotes(df, [500, 500]))


@pytest.mark.parametrize("tamanhos", [[1, 1, 1], [7, 300, 2], [100, 100, 100]], ids=["unitarios", "irregulares", "iguais"])
def test_muitos_distintos_passam_para_o_disco(tmp_path, monkeypatch, tamanhos):
    # limite baixo: as colunas com muitos distintos saem da tabela do Python no meio da leitura
    monkeypatch.setattr(qvd_fluxo, "DISTINTOS_PYTHON", 50)
    df = _misturado(1_000, 7)
    lotes = _em_lotes(df, tamanhos)
    destino = tmp_path / "fluxo.qvd"
    with EscritorQvdFluxo(destino, "tabela", dir_temp=tmp_path) as esc:
        for lote in lotes:
            esc.adicionar(lote)
        brutos = {c.nome for c in esc._brutos}
        assert {"id", "data_hora", "valor"} <= brutos
        esc.finalizar()
    ref = tmp_path / "qvdrs.qvd"
    qvd.write_arrow(df.to_arrow(), str(ref), table_name="tabela")
    assert _sem_data(destino.read_bytes()) == _sem_data(ref.read_bytes())
    conferir_arquivo(destino, df.height)


def test_modo_bruto_com_valores_que_voltam_e_nulos(tmp_path, monkeypatch):
    # valores vistos antes da troca reaparecem depois dela; lote todo nulo já no modo bruto
    monkeypatch.setattr(qvd_fluxo, "DISTINTOS_PYTHON", 20)
    n = 3_000
    df = pl.DataFrame({
        "volta": [(i * 7919) % 900 for i in range(n)],
        "nulos": [None if (i % 5 == 0 or 1_000 <= i < 1_200) else i for i in range(n)],
        "texto": [None if i % 9 == 0 else f"t-{(i * 31) % 1_500}" for i in range(n)],
    })
    _conferir_igual(tmp_path, df, _em_lotes(df, [40, 960, 200, 800]))


def test_modo_bruto_com_texto_direto_e_simbolos_em_disco(tmp_path, monkeypatch):
    monkeypatch.setattr(qvd_fluxo, "DISTINTOS_PYTHON", 30)
    monkeypatch.setattr(qvd_fluxo, "LIMITE_TEXTO_DIRETO", 40)
    monkeypatch.setattr(qvd_fluxo, "SIMBOLOS_EM_DISCO", 100)
    df = pl.DataFrame({"s": [f"código-{i}" for i in range(2_000)], "n": list(range(2_000))})
    _conferir_igual(tmp_path, df, _em_lotes(df, [100, 900]))


@pytest.mark.parametrize("limite", [3, 10**9], ids=["bruto", "python"])
def test_ponto_flutuante_com_zero_negativo_nan_e_infinito(tmp_path, monkeypatch, limite):
    # o Python junta 0.0 e -0.0 e separa os NaN; o Arrow faz o contrário: quem decide é o qvdrs
    monkeypatch.setattr(qvd_fluxo, "DISTINTOS_PYTHON", limite)
    especiais = [0.0, -0.0, float("nan"), float("inf"), float("-inf"), 1.5, None]
    rnd = random.Random(5)
    valores = [rnd.choice(especiais) if i % 3 else rnd.uniform(-1e3, 1e3) for i in range(3_000)]
    valores[0], valores[1] = -0.0, 0.0
    df = pl.DataFrame({"f": valores}, schema={"f": pl.Float64})
    _conferir_igual(tmp_path, df, _em_lotes(df, [5, 400, 1_000, 95]))


def test_modo_bruto_codificado_em_varios_blocos(tmp_path, monkeypatch):
    # blocos pequenos: os símbolos conhecidos crescem bloco a bloco e valores voltam entre blocos
    monkeypatch.setattr(qvd_fluxo, "DISTINTOS_PYTHON", 10)
    monkeypatch.setattr(qvd_fluxo, "BLOCO_BRUTO", 250)
    df = _misturado(2_000, 9).with_columns(volta=pl.Series([(i * 37) % 700 for i in range(2_000)]))
    _conferir_igual(tmp_path, df, _em_lotes(df, [30, 100, 100, 7, 500, 263]))


def test_lote_com_coluna_toda_nula_antes_do_tipo_aparecer(tmp_path):
    # o 1º lote chega com a coluna de tipo Null (o banco devolveu só nulos ali)
    lote1 = pl.DataFrame({"k": [1, 2], "s": [None, None]})
    lote2 = pl.DataFrame({"k": [3, 4, 5], "s": ["a", None, "b"]})
    assert lote1.schema["s"] == pl.Null
    df = pl.concat([lote1, lote2], how="vertical_relaxed")
    _conferir_igual(tmp_path, df, [lote1, lote2])


def test_coluna_toda_nula_e_coluna_constante(tmp_path):
    df = pl.DataFrame({"nada": pl.Series([None] * 50, dtype=pl.String), "um": [7] * 50, "k": list(range(50))})
    _conferir_igual(tmp_path, df, _em_lotes(df, [20]))


def test_um_valor_com_nulos_preserva_os_nulos(tmp_path):
    # aqui o fluxo difere do qvdrs de propósito (ele grava 0 bits e os nulos viram o valor)
    df = pl.DataFrame({"s": ["a", None, "a", None, None], "k": [1, 2, 3, 4, 5]})
    gerado, info = _pelo_fluxo(tmp_path, _em_lotes(df, [2]))
    assert info["larguras"]["s"] == 1
    lido = qvd.read_qvd_to_polars(str(gerado))
    assert lido.get_column("s").to_list() == ["a", None, "a", None, None]
    conferir_arquivo(gerado, 5)


def test_tipos_preparados_pelo_gerador(tmp_path):
    from decimal import Decimal

    bruto = pl.DataFrame({
        "preco": pl.Series([Decimal("1.10"), Decimal("2.25"), None], dtype=pl.Decimal(10, 2)),
        "ativo": [True, False, None],
    })
    df = GeradorQvd.preparar_para_qvd(bruto)
    assert df.schema["preco"] == pl.Float64 and df.schema["ativo"] == pl.Int8
    _conferir_igual(tmp_path, df, _em_lotes(df, [1]))


def test_sem_linhas_nao_gera(tmp_path):
    with EscritorQvdFluxo(tmp_path / "vazio.qvd", "tabela", dir_temp=tmp_path) as esc:
        esc.adicionar(pl.DataFrame({"a": pl.Series([], dtype=pl.Int64)}))
        with pytest.raises(ValueError, match="nenhuma linha"):
            esc.finalizar()
    assert not (tmp_path / "vazio.qvd").exists()


def test_lote_com_colunas_diferentes_e_recusado(tmp_path):
    with EscritorQvdFluxo(tmp_path / "x.qvd", "tabela", dir_temp=tmp_path) as esc:
        esc.adicionar(pl.DataFrame({"a": [1]}))
        with pytest.raises(ValueError, match="colunas diferentes"):
            esc.adicionar(pl.DataFrame({"b": [1]}))


def test_cancelar_na_montagem_nao_deixa_arquivo(tmp_path):
    df = pl.DataFrame({"k": list(range(50))})

    def cancelar(feito, total):
        raise RuntimeError("cancelado")

    with pytest.raises(RuntimeError, match="cancelado"):
        _pelo_fluxo(tmp_path, _em_lotes(df, [10] * 5), nome="cancelado.qvd", ao_progredir=cancelar)
    assert not list(tmp_path.glob("cancelado.qvd*"))


def test_temporarios_sao_apagados(tmp_path):
    _pelo_fluxo(tmp_path, [pl.DataFrame({"k": [1, 2, 3]})])
    assert not list(tmp_path.glob("lurkqvd_fluxo_*"))


def test_conferir_arquivo_pega_linhas_erradas_e_arquivo_cortado(tmp_path):
    gerado, _ = _pelo_fluxo(tmp_path, [pl.DataFrame({"k": list(range(100))})])
    conferir_arquivo(gerado, 100)
    with pytest.raises(ValueError, match="linhas"):
        conferir_arquivo(gerado, 99)
    cortado = tmp_path / "cortado.qvd"
    cortado.write_bytes(gerado.read_bytes()[:-1])
    with pytest.raises(ValueError, match="bytes"):
        conferir_arquivo(cortado, 100)