"""Memória do worker: limite do container, medição do pico e reserva de memória na fila."""

import threading
import time
import uuid

import numpy as np
import psycopg
import pytest

from src.lurkqvd.pipeline import memoria
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, ResultadoCarga
from src.lurkqvd.pipeline.memoria import Pendente, escolher

GB = 1024**3


# ---------------------------------------------------------------------- #
# Regra de escolha (sem banco)
# ---------------------------------------------------------------------- #
def _p(id, gb, espera_min=0):
    return Pendente(id, int(gb * GB), espera_min * 60.0)


def test_pega_a_primeira_que_cabe():
    assert escolher([_p(1, 1), _p(2, 1)], reservado=0, capacidade=4 * GB, espera_max_s=900).id == 1


def test_a_que_nao_cabe_deixa_a_menor_passar():
    assert escolher([_p(1, 3), _p(2, 1)], reservado=2 * GB, capacidade=4 * GB, espera_max_s=900).id == 2


def test_depois_de_esperar_demais_ninguem_passa_na_frente():
    assert escolher([_p(1, 3, espera_min=20), _p(2, 1)], reservado=2 * GB, capacidade=4 * GB, espera_max_s=900) is None


def test_maquina_vazia_roda_mesmo_maior_que_a_capacidade():
    assert escolher([_p(1, 10)], reservado=0, capacidade=4 * GB, espera_max_s=900).id == 1


def test_nada_cabe_e_nada_pendente():
    assert escolher([_p(1, 3)], reservado=2 * GB, capacidade=4 * GB, espera_max_s=900) is None
    assert escolher([], reservado=0, capacidade=4 * GB, espera_max_s=900) is None


# ---------------------------------------------------------------------- #
# Limite do container e medidor
# ---------------------------------------------------------------------- #
def test_ram_total_respeita_o_limite_do_container(tmp_path):
    v2, v1 = tmp_path / "memory.max", tmp_path / "limit_in_bytes"
    assert memoria._ram_total(32 * GB, (v2, v1)) == 32 * GB  # sem cgroup
    v2.write_text("max\n")
    assert memoria._ram_total(32 * GB, (v2, v1)) == 32 * GB  # container sem limite
    v2.write_text(str(4 * GB))
    assert memoria._ram_total(32 * GB, (v2, v1)) == 4 * GB
    v2.unlink()
    v1.write_text(str(2**63 - 4096))  # v1 sem limite: número enorme
    assert memoria._ram_total(32 * GB, (v2, v1)) == 32 * GB


def test_medidor_mede_o_crescimento():
    with memoria.Medidor(intervalo=0.05) as m:
        bloco = np.ones(300 * 1024**2, dtype=np.uint8)  # escreve as páginas: entram no RSS
        time.sleep(0.3)
        del bloco
    assert m.incremento is not None and m.incremento > 200 * 1024**2


# ---------------------------------------------------------------------- #
# Fila com reserva (banco de teste)
# ---------------------------------------------------------------------- #
@pytest.fixture
def repo(banco):
    from src.lurkqvd.repository.repositorio import Repositorio

    with psycopg.connect(banco) as conn:  # cada teste começa com a fila vazia
        conn.execute("UPDATE lurkqvd.execucoes SET status = 'erro' WHERE status IN ('pendente', 'rodando')")
    return Repositorio(banco)


def _carga(repo, pico_gb=None):
    nome = f"mem_{uuid.uuid4().hex[:8]}"
    cid = repo.criar_carga(CargaQvd(nome=nome, query="SELECT 1", qlik_path=f"t/{nome}.qvd", connection_id=None))
    if pico_gb is not None:
        with repo._conn() as conn:
            conn.execute(
                """INSERT INTO lurkqvd.execucoes (carga_id, status, iniciado_em, finalizado_em, memoria_pico_bytes)
                   VALUES (%s, 'sucesso', now(), now(), %s)""",
                (cid, int(pico_gb * GB)),
            )
    return cid


def _pendente(repo, carga_id, ha_min=0.0):
    with repo._conn() as conn:
        return conn.execute(
            """INSERT INTO lurkqvd.execucoes (carga_id, solicitado_em)
               VALUES (%s, now() - make_interval(secs => %s)) RETURNING id""",
            (carga_id, ha_min * 60),
        ).fetchone()["id"]


def _pegar(repo, maquina="m1", capacidade_gb=4, espera_max_min=15):
    r = repo.pegar_proxima(maquina=maquina, capacidade=int(capacidade_gb * GB), reserva_padrao=1 * GB,
                           espera_max_s=espera_max_min * 60)
    return r[0] if r else None


def _execucao(repo, eid):
    with repo._conn() as conn:
        return conn.execute("SELECT * FROM lurkqvd.execucoes WHERE id = %s", (eid,)).fetchone()


def test_sem_capacidade_segue_a_ordem_de_chegada(repo):
    e1 = _pendente(repo, _carga(repo, pico_gb=50), ha_min=2)
    _pendente(repo, _carga(repo), ha_min=1)
    eid, _, _ = repo.pegar_proxima()
    assert eid == e1
    assert _execucao(repo, e1)["memoria_reservada_bytes"] is None


def test_reserva_o_maior_pico_recente_ou_o_padrao(repo):
    com_historico = _carga(repo, pico_gb=1.5)
    with repo._conn() as conn:  # um pico menor mais recente não esconde o maior
        conn.execute("""INSERT INTO lurkqvd.execucoes (carga_id, status, iniciado_em, finalizado_em, memoria_pico_bytes)
                        VALUES (%s, 'sucesso', now(), now() + interval '1 s', %s)""", (com_historico, GB // 2))
    e1 = _pendente(repo, com_historico, ha_min=2)
    e2 = _pendente(repo, _carga(repo), ha_min=1)
    assert _pegar(repo) == e1
    assert _pegar(repo) == e2
    assert _execucao(repo, e1)["memoria_reservada_bytes"] == int(1.5 * GB)
    assert _execucao(repo, e2)["memoria_reservada_bytes"] == 1 * GB
    assert _execucao(repo, e1)["maquina"] == "m1"


def test_carga_que_nao_cabe_espera_e_a_menor_passa(repo):
    _pendente(repo, _carga(repo, pico_gb=3), ha_min=5)
    rodando = _pegar(repo)                              # 3 GB reservados de 4
    grande = _pendente(repo, _carga(repo, pico_gb=2), ha_min=2)
    pequena = _pendente(repo, _carga(repo, pico_gb=0.5), ha_min=1)
    assert rodando is not None
    assert _pegar(repo) == pequena
    assert _execucao(repo, grande)["status"] == "pendente"


def test_espera_longa_trava_quem_vem_atras(repo):
    _pendente(repo, _carga(repo, pico_gb=3), ha_min=60)
    _pegar(repo)
    _pendente(repo, _carga(repo, pico_gb=2), ha_min=30)  # esperando há mais que o limite
    _pendente(repo, _carga(repo, pico_gb=0.5), ha_min=1)
    assert _pegar(repo, espera_max_min=15) is None


def test_outra_maquina_tem_a_propria_memoria(repo):
    _pendente(repo, _carga(repo, pico_gb=3), ha_min=2)
    _pegar(repo, maquina="m1")
    outra = _pendente(repo, _carga(repo, pico_gb=3), ha_min=1)
    assert _pegar(repo, maquina="m1") is None
    assert _pegar(repo, maquina="m2") == outra


def test_dois_workers_da_mesma_maquina_nao_reservam_alem_da_capacidade(repo):
    for _ in range(2):
        _pendente(repo, _carga(repo, pico_gb=1))
    largada = threading.Barrier(2)
    pegas = []

    def worker():
        largada.wait()
        pegas.append(_pegar(repo, capacidade_gb=1.5))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(p is not None for p in pegas) == 1  # um pegou, o outro esperou a reserva do primeiro


def test_worker_grava_o_pico_da_execucao(repo):
    from src.lurkqvd.worker import Worker

    class GeradorQueAloca:
        def executar(self, carga, db=None, progresso=None):
            bloco = np.ones(300 * 1024**2, dtype=np.uint8)
            time.sleep(1.2)  # o medidor amostra a cada 0,5 s
            del bloco
            return ResultadoCarga(nome=carga.nome, file_id=str(uuid.uuid4()), criado=True, linhas=1, colunas=1,
                                  tamanho_bytes=1, seg_extracao=0, seg_geracao=0, seg_upload=0)

    eid = _pendente(repo, _carga(repo))
    assert Worker(repo, gerador=GeradorQueAloca()).processar_uma()
    e = _execucao(repo, eid)
    assert e["status"] == "sucesso", e["erro"]
    assert e["memoria_pico_bytes"] > 200 * 1024**2
    assert e["memoria_reservada_bytes"] == 1 * GB  # sem histórico: a reserva padrão


def test_previsao_de_linhas_ignora_execucao_de_outra_consulta(repo):
    cid = _carga(repo)

    def sucesso(linhas, daqui_s=0):
        with repo._conn() as conn:
            conn.execute("""INSERT INTO lurkqvd.execucoes (carga_id, status, iniciado_em, finalizado_em, linhas)
                            VALUES (%s, 'sucesso', now() + make_interval(secs => %s), now(), %s)""",
                         (cid, daqui_s, linhas))

    assert repo.linhas_da_ultima(cid) is None
    sucesso(100, daqui_s=-60)
    assert repo.linhas_da_ultima(cid) == 100
    repo.atualizar_carga(cid, None, agendamento=None)    # mudar a agenda não muda a contagem
    assert repo.linhas_da_ultima(cid) == 100
    repo.atualizar_carga(cid, None, query="SELECT 2")
    assert repo.linhas_da_ultima(cid) is None
    sucesso(70, daqui_s=60)
    assert repo.linhas_da_ultima(cid) == 70


def test_medidor_separa_o_pico_por_fase():
    if memoria._processo is None:
        pytest.skip("sem psutil")
    with memoria.Medidor(intervalo=0.01) as m:
        m.fase = "lendo"
        time.sleep(0.05)
        m.fase = "gerando"
        bloco = np.ones(64 * 1024 * 1024, dtype=np.uint8)  # páginas tocadas: entra no RSS
        time.sleep(0.05)
        del bloco
    assert set(m.picos) >= {"lendo", "gerando"}
    assert m.picos["gerando"] >= m.picos["lendo"] + 32 * 1024 * 1024
    assert m.pico == max(m.picos.values())
