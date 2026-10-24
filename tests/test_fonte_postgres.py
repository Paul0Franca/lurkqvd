"""PostgreSQL como fonte de dados (beta), contra o Postgres de teste: conexão, tipos, leitura em lotes,
QVD gerado de ponta a ponta e estimativa."""

from datetime import date, datetime

import psycopg
import pytest
import qvd
from psycopg.conninfo import conninfo_to_dict

from src.lurkqvd.config import fontes
from src.lurkqvd.config.fontes import FonteSql
from src.lurkqvd.pipeline import estimativa
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, GeradorQvd

LINHAS_GRANDE = 60_000


@pytest.fixture(scope="module")
def origem(banco):
    """(fonte, senha): o banco de teste no papel de banco de origem, com tabelas de exemplo no schema origem."""
    with psycopg.connect(banco, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS origem CASCADE; CREATE SCHEMA origem")
        conn.execute("""
            CREATE TABLE origem.tipos (
                id int, grande bigint, valor numeric(12,2), real4 real, texto text, letra char(3), ativo boolean,
                dia date, momento timestamp, momento_tz timestamptz, hora time,
                codigo uuid, dados jsonb, ip inet, bytes bytea, duracao interval, lista int[], faixa int4range)
        """)
        conn.execute("""
            INSERT INTO origem.tipos VALUES
              (1, 9000000000, 10.50, 1.5, 'ação', 'ab', true, '2026-01-31', '2026-01-31 12:00:00',
               '2026-01-31 15:00:00+00', '08:30', 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', '{"a": 1}', '10.0.0.1',
               '\\x0102', '1 day 02:00', '{1,2,NULL}', '[1,5)'),
              (2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
        """)
        conn.execute(f"""
            CREATE TABLE origem.vendas AS
            SELECT i AS id_venda, i % 50 AS loja, (i % 1000) * 1.25 AS valor, date '2026-01-01' + (i % 300) AS dia
              FROM generate_series(1, {LINHAS_GRANDE}) i
        """)
        conn.execute("ANALYZE origem.vendas")
    c = conninfo_to_dict(banco)
    fonte = {"id": 0, "tipo": "postgres", "host": c["host"], "porta": int(c["port"]), "banco": c["dbname"],
             "usuario": c["user"], "opcoes": {}}
    return fonte, c["password"]


@pytest.fixture
def conexao(origem):
    fonte, senha = origem
    con = FonteSql(fonte, senha)
    yield con
    con.fechar()


def test_teste_de_conexao_mostra_versao_e_banco(origem):
    fonte, senha = origem
    r = fontes.testar(fonte, senha)
    assert r["ok"], r["erro"]
    assert r["versao"].startswith("PostgreSQL")
    assert r["banco_conectado"] == fonte["banco"]


def test_senha_errada_vira_mensagem_clara(origem):
    fonte, _ = origem
    r = fontes.testar(fonte, "senha-errada")
    assert not r["ok"]
    assert r["erro"] == "Usuário ou senha recusados pelo PostgreSQL."


def test_tipos_sem_equivalente_no_qvd_viram_texto(conexao, monkeypatch):
    monkeypatch.setattr(fontes.fuso, "FUSO", "America/Sao_Paulo")
    df = conexao.query_pl("SELECT * FROM origem.tipos ORDER BY id")
    um = df.row(0, named=True)
    assert um["grande"] == 9_000_000_000 and um["texto"] == "ação" and um["ativo"] is True
    assert um["dia"] == date(2026, 1, 31) and um["momento"] == datetime(2026, 1, 31, 12, 0)
    assert um["momento_tz"] == datetime(2026, 1, 31, 12, 0)  # 15h UTC = 12h em São Paulo, sem fuso
    assert um["codigo"] == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
    assert um["dados"] == '{"a": 1}' and um["ip"] == "10.0.0.1" and um["bytes"] == "0102"
    assert um["duracao"] == "1 day 02:00:00" and um["lista"] == "{1,2,NULL}" and um["faixa"] == "[1, 5)"
    assert all(v is None for k, v in df.row(1, named=True).items() if k != "id")


def test_le_em_lotes_com_cursor_no_servidor(conexao, monkeypatch):
    """O 1º lote chega antes de o banco calcular a linha que dá erro: a consulta não foi lida inteira de uma vez."""
    monkeypatch.setattr(FonteSql, "LOTE", 3)
    lotes = conexao.iter_lotes("SELECT i, 1 / (6 - i) AS x FROM generate_series(1, 10) i", {})
    assert next(lotes).height == 3
    with pytest.raises(Exception, match="division by zero|divisão por zero"):
        list(lotes)
    assert conexao.ultimo_motor == "psycopg"


def test_parametros_e_casts(conexao):
    df = conexao.query_pl("SELECT count(*)::int AS n FROM origem.vendas WHERE loja = :loja AND dia >= :desde",
                          {"loja": 7, "desde": date(2026, 6, 1)})
    assert df["n"][0] == sum(1 for i in range(1, LINHAS_GRANDE + 1) if i % 50 == 7 and i % 300 >= 151)


class QlikFalsa:
    def __init__(self):
        self.enviado = None

    def list_files(self, connection_id, pasta):
        return []

    def upload_file(self, connection_id, path, local, ao_enviar=None):
        with open(local, "rb") as f:
            self.enviado = f.read()
        return {"id": "id-novo", "size": len(self.enviado)}


def test_qvd_de_ponta_a_ponta(conexao, tmp_path, monkeypatch):
    monkeypatch.setattr(FonteSql, "LOTE", 7_000)  # vários lotes
    qlik = QlikFalsa()
    previstas = []
    carga = CargaQvd(nome="vendas_pg", query="SELECT * FROM origem.vendas ORDER BY id_venda", qlik_path="x/v.qvd",
                     connection_id=None)
    r = GeradorQvd(db=None, qlik=qlik, work_dir=tmp_path).executar(
        carga, db=conexao, progresso=lambda fase, **d: previstas.append(d.get("linhas_previstas")))
    assert r.linhas == LINHAS_GRANDE
    arquivo = tmp_path / "lido.qvd"
    arquivo.write_bytes(qlik.enviado)
    lido = qvd.read_qvd_to_polars(str(arquivo))
    assert lido.height == LINHAS_GRANDE and lido["loja"].n_unique() == 50
    assert abs(lido["valor"].sum() - sum((i % 1000) * 1.25 for i in range(1, LINHAS_GRANDE + 1))) < 1e-6
    assert any(p and abs(p - LINHAS_GRANDE) <= LINHAS_GRANDE * 0.1 for p in previstas)  # pelo EXPLAIN


def test_qvd_com_todos_os_tipos(conexao, tmp_path):
    qlik = QlikFalsa()
    carga = CargaQvd(nome="tipos_pg", query="SELECT * FROM origem.tipos ORDER BY id", qlik_path="x/t.qvd",
                     connection_id=None)
    assert GeradorQvd(db=None, qlik=qlik, work_dir=tmp_path).executar(carga, db=conexao).linhas == 2


def test_estimativa_usa_plano_estatisticas_e_sorteio(conexao):
    e = estimativa.estimar_rapida(conexao.engine, "SELECT id_venda, loja, valor FROM origem.vendas", amostra=5_000)
    assert e["origem_linhas"] == "plano" and abs(e["linhas"] - LINHAS_GRANDE) <= LINHAS_GRANDE * 0.1
    assert e["amostra_aleatoria"]  # TABLESAMPLE SYSTEM
    colunas = {c["nome"]: c for c in e["colunas"]}
    assert colunas["loja"]["origem"] == "estatística" and colunas["loja"]["distintos"] == 50
    assert colunas["id_venda"]["distintos"] >= LINHAS_GRANDE * 0.9


def test_estimativa_exata_quando_cabe_na_amostra_com_cte_e_parametro(conexao):
    sql = "WITH t AS (SELECT * FROM origem.vendas WHERE loja = :loja) SELECT loja, dia FROM t ORDER BY dia LIMIT 100"
    e = estimativa.estimar_rapida(conexao.engine, sql, {"loja": 3})
    assert e["origem_linhas"] == "exato" and e["linhas"] == 100
    assert {c["nome"]: c["distintos"] for c in e["colunas"]}["loja"] == 1


def test_estimativa_de_view_cai_para_as_primeiras_linhas(conexao, origem, banco):
    with psycopg.connect(banco, autocommit=True) as conn:
        conn.execute("CREATE OR REPLACE VIEW origem.v_vendas AS SELECT * FROM origem.vendas")
    e = estimativa.estimar_rapida(conexao.engine, "SELECT * FROM origem.v_vendas", amostra=5_000)
    assert not e["amostra_aleatoria"] and e["linhas"] >= LINHAS_GRANDE * 0.9


def test_cadastro_pela_api(cliente, origem, monkeypatch):
    monkeypatch.setenv("LURKQVD_AUTH_DEV", "1")  # admin fictício: o foco aqui é a fonte, não o login
    fonte, senha = origem
    tipos = {t["tipo"]: t for t in cliente.get("/fontes/tipos").json()}
    assert tipos["postgres"]["suportado"] and tipos["postgres"]["beta"]
    dados = {k: fonte[k] for k in ("tipo", "host", "porta", "banco", "usuario", "opcoes")} | {"nome": "PG de teste"}
    assert cliente.post("/fontes/testar", json=dados | {"senha": senha}).json()["ok"]
    r = cliente.post("/fontes", json=dados | {"senha": senha})
    assert r.status_code == 201, r.text
    criada = r.json()
    assert criada["ultimo_teste"]["ok"] and criada["ultimo_teste"]["versao"].startswith("PostgreSQL")
    r = cliente.post("/estimativa", json={"query": "SELECT loja FROM origem.vendas", "fonte_id": criada["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["colunas"][0]["distintos"] == 50
    assert cliente.delete(f"/fontes/{criada['id']}").status_code in (200, 204)
