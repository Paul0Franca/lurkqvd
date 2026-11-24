"""Envio do QVD para a Qlik: direto (arquivo pequeno) e, se cair, em pedaços (sem rede: sessões falsas)."""

import json

import pytest
import requests

from src.lurkqvd.clients import qlik as modulo
from src.lurkqvd.clients.qlik import QlikCredentials, QlikQvd


class _Resposta:
    def __init__(self, status=200, corpo=None):
        self.status_code = status
        self._corpo = corpo or {}
        self.headers = {}
        self.ok = status < 400
        self.content = json.dumps(self._corpo).encode()
        self.text = self.content.decode()

    def json(self):
        return self._corpo


class _Sessao:
    """Registra os pedidos; `falhar` = quantos pedidos com arquivo levantam ConnectionError."""

    def __init__(self, registro, falhar=0, resposta=None):
        self.registro, self.falhar, self.resposta = registro, falhar, resposta
        self.headers = {"Authorization": "Bearer x"}

    def request(self, metodo, url, files=None, timeout=None):
        com_arquivo = "File" in files
        if com_arquivo:
            files["File"][1].read()  # como o requests: lê o arquivo para montar o corpo
        self.registro.append({"metodo": metodo, "arquivo": com_arquivo, "timeout": timeout,
                              "json": json.loads(files["Json"][1])})
        if com_arquivo and self.registro.falhas < self.falhar:
            self.registro.falhas += 1
            raise requests.ConnectionError("('Connection aborted.', TimeoutError('The write operation timed out'))")
        return self.resposta()

    def close(self):
        pass


class _Registro(list):
    falhas = 0


@pytest.fixture
def qvd(tmp_path):
    def criar(mb: float):
        p = tmp_path / "carga.qvd"
        p.write_bytes(b"\0" * int(mb * 1024 * 1024))
        return str(p)
    return criar


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(modulo.time, "sleep", lambda s: None)
    c = QlikQvd(QlikCredentials("x"), "teste")
    c.registro = _Registro()
    c.temporarios = []

    def preparar(falhar=0, tamanho=None):
        resposta = lambda: _Resposta(200, {"id": "f1", "name": "a/carga.qvd", "size": tamanho})  # noqa: E731
        sessao = _Sessao(c.registro, falhar, resposta)
        c._session = sessao
        monkeypatch.setattr(c, "_sessao_sem_repeticao", lambda: sessao)

        def temporario(local, ao_enviar=None):
            c.temporarios.append(local)
            return "tmp-1"
        monkeypatch.setattr(c, "_enviar_temporario", temporario)
    c.preparar = preparar
    return c


def test_arquivo_pequeno_vai_direto_com_tempo_proporcional(client, qvd):
    arq = qvd(60)
    client.preparar(tamanho=60 * 1024 * 1024)
    client.replace_file("f1", "con", arq, path="a/carga.qvd")
    (pedido,) = client.registro
    assert pedido["arquivo"] and pedido["metodo"] == "PUT"
    assert pedido["timeout"][1] >= 120  # 60 MB a ~0,5 MB/s, não os 30 s padrão
    assert client.temporarios == []


def test_acima_do_limite_vai_em_pedacos(client, qvd, monkeypatch):
    monkeypatch.setattr(modulo, "LIMITE_ENVIO_DIRETO", 1024 * 1024)
    arq = qvd(2)
    client.preparar(tamanho=2 * 1024 * 1024)
    client.replace_file("f1", "con", arq, path="a/carga.qvd")
    (pedido,) = client.registro
    assert not pedido["arquivo"] and pedido["json"]["tempContentFileId"] == "tmp-1"


def test_envio_direto_que_cai_passa_para_pedacos(client, qvd):
    arq = qvd(5)
    client.preparar(falhar=99, tamanho=5 * 1024 * 1024)
    r = client.replace_file("f1", "con", arq, path="a/carga.qvd")
    assert r["id"] == "f1"
    diretos = [p for p in client.registro if p["arquivo"]]
    assert len(diretos) == modulo.TENTATIVAS_ENVIO_DIRETO  # não repete o arquivo inteiro 6 (ou 24) vezes
    assert client.temporarios == [arq]
    assert client.registro[-1]["json"]["tempContentFileId"] == "tmp-1"
    assert client.registro[-1]["json"]["connectionId"] == "con"


def test_post_que_caiu_mas_criou_nao_duplica(client, qvd, monkeypatch):
    """O POST direto criou o arquivo e a resposta se perdeu: o POST pelos pedaços dá 409 e é reconhecido."""
    arq = qvd(5)
    client.preparar(falhar=99)
    client._session.resposta = lambda: _Resposta(409, {"errors": [{"code": "DF-409"}]})
    criado = {"id": "f9", "name": "a/carga.qvd", "size": 5 * 1024 * 1024}
    monkeypatch.setattr(client, "_achar_por_caminho", lambda con, path: criado)
    assert client.upload_file("con", "a/carga.qvd", arq) == criado
