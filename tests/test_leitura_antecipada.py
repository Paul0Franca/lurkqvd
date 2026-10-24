"""Leitura antecipada do gerador: o banco manda o próximo lote enquanto o atual vira QVD (sem banco nem Qlik)."""

import re
import threading

import polars as pl
import pytest

from src.lurkqvd.pipeline import gerador_qvd
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, GeradorQvd


class BancoFalso:
    """Entrega `n_lotes` lotes pelo iter_lotes e registra o que aconteceu com a leitura."""

    def __init__(self, n_lotes=5, erro_no_lote=None):
        self.n_lotes = n_lotes
        self.erro_no_lote = erro_no_lote
        self.lidos = 0
        self.fechado = False
        self.leu_o_segundo = threading.Event()

    def iter_lotes(self, sql, params):
        try:
            for k in range(self.n_lotes):
                if k == self.erro_no_lote:
                    raise ConnectionError("conexão caiu no meio")
                self.lidos += 1
                if k == 1:
                    self.leu_o_segundo.set()
                yield pl.DataFrame({"k": list(range(k * 10, k * 10 + 10)), "s": [f"v{k}"] * 10})
        finally:
            self.fechado = True


class QlikFalsa:
    def __init__(self):
        self.enviado: bytes | None = None

    def list_files(self, connection_id, pasta):
        return []

    def upload_file(self, connection_id, path, local, ao_enviar=None):
        with open(local, "rb") as f:
            self.enviado = f.read()
        return {"id": "id-novo", "size": len(self.enviado)}


def _executar(tmp_path, banco, progresso=None):
    qlik = QlikFalsa()
    carga = CargaQvd(nome="teste", query="SELECT 1", qlik_path="x/teste.qvd", connection_id=None)
    resultado = GeradorQvd(db=None, qlik=qlik, work_dir=tmp_path).executar(carga, db=banco, progresso=progresso)
    return resultado, qlik


def _sem_data(dados: bytes) -> bytes:
    return re.sub(rb"<CreateUtcTime>.*?</CreateUtcTime>", b"", dados, count=1)


def _leitoras_vivas():
    return [t for t in threading.enumerate() if t.name.startswith("leitura-")]


def test_gera_o_mesmo_qvd_que_a_leitura_em_sequencia(tmp_path, monkeypatch):
    antecipado, qlik_a = _executar(tmp_path, BancoFalso())
    monkeypatch.setattr(gerador_qvd, "LOTES_ANTECIPADOS", 0)
    sequencia, qlik_s = _executar(tmp_path, BancoFalso())
    assert antecipado.linhas == sequencia.linhas == 50
    assert _sem_data(qlik_a.enviado) == _sem_data(qlik_s.enviado)


def test_le_o_proximo_lote_enquanto_o_atual_e_gravado(tmp_path):
    banco = BancoFalso()
    esperou = []

    def progresso(fase, **dados):
        # ainda processando o 1º lote: o 2º já tem de ter sido lido (em sequência, travaria aqui)
        if fase == "lendo" and dados.get("linhas") == 10:
            esperou.append(banco.leu_o_segundo.wait(timeout=5))

    _executar(tmp_path, banco, progresso)
    assert esperou == [True]


def test_erro_na_leitura_sobe_e_nada_e_publicado(tmp_path):
    banco = BancoFalso(erro_no_lote=3)
    with pytest.raises(ConnectionError, match="caiu no meio"):
        _executar(tmp_path, banco)
    assert banco.fechado
    assert not _leitoras_vivas()
    assert not list(tmp_path.glob("**/*.qvd"))


def test_cancelamento_para_a_leitura_e_fecha_a_conexao(tmp_path):
    banco = BancoFalso(n_lotes=1000)

    class Cancelada(Exception):
        pass

    def progresso(fase, **dados):
        if fase == "lendo" and dados.get("linhas") == 20:
            raise Cancelada()

    with pytest.raises(Cancelada):
        _executar(tmp_path, banco, progresso)
    assert banco.fechado
    assert banco.lidos <= 2 + gerador_qvd.LOTES_ANTECIPADOS + 1  # parou logo, não leu a tabela toda
    assert not _leitoras_vivas()


def test_consulta_sem_linhas(tmp_path):
    with pytest.raises(ValueError, match="não retornou linhas"):
        _executar(tmp_path, BancoFalso(n_lotes=0))
    assert not _leitoras_vivas()
