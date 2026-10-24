"""Fuso da instalação (LURKQVD_FUSO): agendamentos no fuso escolhido e recálculo da agenda ao trocar."""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.lurkqvd.pipeline.gerador_qvd import CargaQvd
from src.lurkqvd.repository import repositorio
from src.lurkqvd.repository.repositorio import Repositorio, proximas_execucoes

DEPOIS_DE = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def test_cron_sem_fuso_segue_o_da_instalacao(monkeypatch):
    monkeypatch.setattr(repositorio, "FUSO_PADRAO", "UTC")
    assert proximas_execucoes("0 6 * * *", depois_de=DEPOIS_DE)[0] == datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(repositorio, "FUSO_PADRAO", "America/Sao_Paulo")
    assert proximas_execucoes("0 6 * * *", depois_de=DEPOIS_DE)[0] == datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


def test_fuso_da_carga_vale_mais_que_o_da_instalacao(monkeypatch):
    monkeypatch.setattr(repositorio, "FUSO_PADRAO", "UTC")
    prox = proximas_execucoes("0 6 * * *", "Asia/Tokyo", depois_de=DEPOIS_DE)[0]
    assert prox.astimezone(ZoneInfo("Asia/Tokyo")).hour == 6


def test_fuso_invalido_impede_a_subida_com_mensagem_clara():
    r = subprocess.run([sys.executable, "-c", "import src.lurkqvd.fuso"], capture_output=True, text=True,
                       env={**os.environ, "LURKQVD_FUSO": "Brasil/Nao_Existe"})
    assert r.returncode != 0
    assert "LURKQVD_FUSO" in r.stderr and "IANA" in r.stderr


@pytest.fixture
def repo(ambiente):
    return Repositorio()


def _carga_agendada(repo, fuso=None):
    nome = f"fuso_{uuid.uuid4().hex[:8]}"
    cid = repo.criar_carga(CargaQvd(nome=nome, query="SELECT 1", qlik_path=f"t/{nome}.qvd", connection_id=None),
                           agendamento="0 6 * * *")
    if fuso:
        with repo._conn() as conn:
            conn.execute("UPDATE lurkqvd.cargas SET fuso = %s WHERE id = %s", (fuso, cid))
    return cid


def _proxima(repo, cid):
    with repo._conn() as conn:
        return conn.execute("SELECT proxima_execucao FROM lurkqvd.cargas WHERE id = %s", (cid,)).fetchone()[
            "proxima_execucao"]


def test_trocar_o_fuso_recalcula_a_agenda_uma_vez(repo, monkeypatch):
    monkeypatch.setattr(repositorio, "FUSO_PADRAO", "America/Sao_Paulo")
    repo.alinhar_fuso()
    segue = _carga_agendada(repo)
    propria = _carga_agendada(repo, fuso="Asia/Tokyo")
    antes_propria = _proxima(repo, propria)
    assert _proxima(repo, segue).astimezone(ZoneInfo("America/Sao_Paulo")).hour == 6

    monkeypatch.setattr(repositorio, "FUSO_PADRAO", "UTC")
    assert repo.alinhar_fuso() >= 1
    assert _proxima(repo, segue).astimezone(timezone.utc).hour == 6
    assert _proxima(repo, propria) == antes_propria  # quem tem fuso próprio não muda
    assert repo.alinhar_fuso() == 0  # mesmo fuso de novo: nada a fazer
    assert repo.status_sistema()["fuso_padrao"] == "UTC"
