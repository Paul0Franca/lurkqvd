"""Publicação na Qlik quando o arquivo do ID guardado sumiu ou foi movido (sem rede: Qlik falsa)."""

from pathlib import Path

import pytest
import requests

from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, GeradorQvd


class QlikFalsa:
    def __init__(self, erro_no_id=None, arquivos_no_destino=()):
        self.erro_no_id = erro_no_id  # (file_id, exceção) que replace_file levanta para esse id
        self.arquivos = list(arquivos_no_destino)
        self.chamadas = []

    def replace_file(self, file_id, connection_id, local, path=None, ao_enviar=None):
        self.chamadas.append(("replace", file_id))
        if self.erro_no_id and self.erro_no_id[0] == file_id:
            raise self.erro_no_id[1]
        return {"id": file_id}

    def upload_file(self, connection_id, path, local, ao_enviar=None):
        self.chamadas.append(("upload", path))
        return {"id": "novo-id"}

    def list_files(self, connection_id, pasta):
        return self.arquivos


def _http(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status}", response=resp)


def _carga(file_id="id-antigo"):
    return CargaQvd(nome="minha_carga", query="SELECT 1", qlik_path="pasta/minha_carga.qvd", connection_id=None, file_id=file_id)


def _subir(qlik, carga):
    return GeradorQvd(db=None, qlik=qlik, work_dir="tmp_qvd_teste")._subir(carga, Path("x.qvd"))


def test_substitui_pelo_id_guardado():
    qlik = QlikFalsa()
    assert _subir(qlik, _carga()) == ({"id": "id-antigo"}, False)
    assert qlik.chamadas == [("replace", "id-antigo")]


@pytest.mark.parametrize("erro", [_http(403), FileNotFoundError("sumiu")])
def test_arquivo_movido_ou_apagado_e_publicado_de_novo_no_destino(erro):
    qlik = QlikFalsa(erro_no_id=("id-antigo", erro))
    info, criado = _subir(qlik, _carga())
    assert criado and info == {"id": "novo-id"}
    assert qlik.chamadas == [("replace", "id-antigo"), ("upload", "pasta/minha_carga.qvd")]


def test_se_ja_existe_arquivo_no_destino_substitui_esse():
    qlik = QlikFalsa(erro_no_id=("id-antigo", _http(403)),
                     arquivos_no_destino=[{"is_folder": False, "base_name": "minha_carga.qvd", "id": "id-no-destino"}])
    assert _subir(qlik, _carga()) == ({"id": "id-no-destino"}, False)


def test_outros_erros_da_qlik_nao_sao_escondidos():
    qlik = QlikFalsa(erro_no_id=("id-antigo", _http(500)))
    with pytest.raises(requests.HTTPError):
        _subir(qlik, _carga())
