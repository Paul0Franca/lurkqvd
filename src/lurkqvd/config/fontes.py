"""Fontes de dados: tipos de banco suportados, conexão e teste.

Cada tipo é um "driver": sabe montar a conexão, testar e rodar a consulta do gerador
(iter_lotes/query_pl -> DataFrame do Polars). O 1º motor de cada tipo é o padrão e o plano B dos outros:
se o motor escolhido falhar numa consulta, a leitura cai para ele sozinha.

SQL Server:
  - "odbc": SQLAlchemy + pyodbc (padrão).
  - "arrow-odbc": mesmo driver ODBC, mas lê direto para Arrow em lotes, sem criar um objeto
    Python por valor (é onde o pyodbc perde tempo em tabelas grandes).
  - "connectorx": driver próprio em Rust (tiberius), também direto para Arrow.
PostgreSQL (beta):
  - "psycopg": SQLAlchemy + psycopg 3, com cursor no servidor (lê em lotes, a memória não cresce com
    a tabela). Tipos que o QVD não tem (uuid, json, inet, arrays, bytea, interval, ranges) viram texto;
    data e hora com fuso (timestamptz) vira a hora local do fuso da instalação (LURKQVD_FUSO).
    O connectorx fica de fora: no PostgreSQL ele lê tudo de uma vez e derruba o processo com alguns
    tipos (ex.: interval).
MySQL e Oracle aparecem na tela como "em breve".

A senha de cada fonte fica no segredo (config/segredos.py) LURKQVD_SECRET_FONTES
(padrão: lurkqvd_fontes), em JSON {"<id da fonte>": "<senha>"}.
"""

import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import polars as pl
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL

from src.lurkqvd import fuso
from src.lurkqvd.config import segredos

logger = logging.getLogger("lurkqvd.fontes")
MOTOR_PADRAO = os.getenv("LURKQVD_MOTOR_LEITURA", "odbc")  # odbc | arrow-odbc | connectorx
# arrow-odbc: tamanho do pacote de rede (bytes; vazio = padrão do driver) e limite para VARCHAR(MAX)
PACKET_SIZE = int(os.getenv("LURKQVD_PACKET_SIZE") or 0) or None
MAX_TEXTO = int(os.getenv("LURKQVD_MAX_TEXTO", "65536"))
# arrow-odbc: teto do buffer de trânsito (MB). Ele é reservado pelo tamanho MÁXIMO declarado das colunas,
# não pelos dados, e em dobro (o próximo lote é buscado em paralelo). O padrão do arrow-odbc, 512, dá ~1 GB
# fixo por carga; 128 mede o mesmo ritmo de leitura com ~1/4 da memória.
BUFFER_LEITURA_MB = int(os.getenv("LURKQVD_BUFFER_LEITURA_MB", "128"))

DRIVER_ODBC_PADRAO = "ODBC Driver 18 for SQL Server"

TIPOS = {
    "mssql": {
        "nome": "SQL Server",
        "porta": 1433,
        "suportado": True,
        "opcoes": [
            {"chave": "encrypt", "rotulo": "Criptografar a conexão", "padrao": True},
            {"chave": "trust_cert", "rotulo": "Confiar no certificado do servidor", "padrao": True},
        ],
        "motores": ["odbc", "arrow-odbc", "connectorx"],
    },
    "postgres": {
        "nome": "PostgreSQL",
        "porta": 5432,
        "suportado": True,
        "beta": True,
        "opcoes": [
            {"chave": "ssl", "rotulo": "Exigir conexão criptografada (SSL)", "padrao": False},
        ],
        "motores": ["psycopg"],
    },
    "mysql": {"nome": "MySQL", "porta": 3306, "suportado": False, "opcoes": []},
    "oracle": {"nome": "Oracle", "porta": 1521, "suportado": False, "opcoes": []},
}


def nome_secret() -> str:
    return os.getenv("LURKQVD_SECRET_FONTES", "lurkqvd_fontes")


# ---------------------------------------------------------------------- #
# Senhas (segredos)
# ---------------------------------------------------------------------- #
def ler_senha(fonte_id: int) -> str:
    senha = segredos.ler_json(nome_secret(), vazio_se_sem_versao=True).get(str(fonte_id))
    if senha is None:
        raise RuntimeError(f"Senha da fonte {fonte_id} não encontrada no secret {nome_secret()}.")
    return senha


def gravar_senha(fonte_id: int, senha: str) -> None:
    segredos.alterar_chave(nome_secret(), str(fonte_id), senha, vazio_se_sem_versao=True)


def apagar_senha(fonte_id: int) -> None:
    segredos.alterar_chave(nome_secret(), str(fonte_id), None, vazio_se_sem_versao=True)


# ---------------------------------------------------------------------- #
# Conexão
# ---------------------------------------------------------------------- #
def _odbc(fonte: dict, senha: str) -> str:
    """String de conexão ODBC (pyodbc e arrow-odbc usam a mesma)."""
    if fonte["tipo"] != "mssql":
        raise ValueError(f"Tipo de banco ainda não suportado: {fonte['tipo']}")
    op = fonte.get("opcoes") or {}
    partes = {
        "DRIVER": "{" + (op.get("driver") or DRIVER_ODBC_PADRAO) + "}",
        "SERVER": f"{fonte['host']},{fonte['porta']}",
        "DATABASE": fonte["banco"],
        "Encrypt": "yes" if op.get("encrypt", True) else "no",
        "TrustServerCertificate": "yes" if op.get("trust_cert", True) else "no",
    }
    partes["UID"] = fonte["usuario"]
    partes["PWD"] = "{" + senha.replace("}", "}}") + "}"  # chaves protegem ; e = dentro da senha
    return ";".join(f"{k}={v}" for k, v in partes.items())


def _url(fonte: dict, senha: str):
    if fonte["tipo"] == "postgres":
        return URL.create("postgresql+psycopg", username=fonte["usuario"], password=senha,
                          host=fonte["host"], port=fonte["porta"], database=fonte["banco"])
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(_odbc(fonte, senha))}"


# PostgreSQL: tipos que viram objetos Python sem equivalente no QVD são lidos como o texto do próprio banco
_PG_COMO_TEXTO = ("uuid", "json", "jsonb", "inet", "cidr", "macaddr", "macaddr8", "interval", "xml")


def _engine_postgres(fonte: dict, senha: str, timeout_conexao: int, lote: int):
    op = fonte.get("opcoes") or {}
    engine = create_engine(
        _url(fonte, senha),
        pool_pre_ping=True,
        # cursor no servidor: o banco manda um lote por vez (sem isso, o psycopg traz tudo para a memória)
        execution_options={"stream_results": True, "max_row_buffer": lote},
        connect_args={
            "connect_timeout": timeout_conexao,
            "sslmode": "require" if op.get("ssl") else "prefer",
            "application_name": "lurkqvd",
            "options": f"-c TimeZone={fuso.FUSO}",  # timestamptz chega na hora local da instalação
        },
    )

    @event.listens_for(engine, "connect")
    def _tipos_como_texto(dbapi_conn, _registro):
        from psycopg.types.string import TextLoader

        for tipo in _PG_COMO_TEXTO:
            try:
                dbapi_conn.adapters.register_loader(tipo, TextLoader)
            except Exception:  # tipo ausente nesse servidor
                pass

    return engine


def _uri_connectorx(fonte: dict, senha: str) -> str:
    from urllib.parse import quote

    op = fonte.get("opcoes") or {}
    usuario, segredo = quote(fonte["usuario"], safe=""), quote(senha, safe="")
    args = f"encrypt={'true' if op.get('encrypt', True) else 'false'}"
    if op.get("trust_cert", True):
        args += "&trust_server_certificate=true"
    return f"mssql://{usuario}:{segredo}@{fonte['host']}:{fonte['porta']}/{quote(fonte['banco'], safe='')}?{args}"


class InterrupcaoLeitura(Exception):
    """O callback de progresso mandou parar a leitura (ex.: cancelamento). Não é falha do motor,
    então não pode cair no plano B (ODBC)."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class FonteSql:
    """Conexão de uma fonte, com a mesma interface que o gerador usa (query_pl)."""

    def __init__(self, fonte: dict, senha: str, *, timeout_conexao: int = 15) -> None:
        self.fonte = fonte
        self.tipo = fonte["tipo"]
        motores = (TIPOS.get(self.tipo) or {}).get("motores") or ["odbc"]
        motor = (fonte.get("opcoes") or {}).get("motor") or (MOTOR_PADRAO if self.tipo == "mssql" else motores[0])
        self.motor = motor if motor in motores else motores[0]
        self.motor_padrao = motores[0]
        self._senha = senha
        if self.tipo == "postgres":
            self.engine = _engine_postgres(fonte, senha, timeout_conexao, self.LOTE)
        else:
            self.engine = create_engine(
                _url(fonte, senha),
                pool_pre_ping=True,
                connect_args={"timeout": timeout_conexao},
            )
        self.ultimo_motor: str | None = None  # qual motor leu de fato na última consulta
        self.packet_size = PACKET_SIZE

    LOTE = 100_000  # linhas por lote (a cada lote: progresso e checagem de cancelamento)

    def query_pl(self, sql: str, params: dict | None = None, ao_lote=None) -> pl.DataFrame:
        """ao_lote(linhas_lidas): chamado a cada lote. Se ele levantar exceção (ex.: cancelamento),
        a leitura para ali e a exceção sobe, sem cair no plano B."""
        leitores = {"connectorx": self.query_connectorx, "arrow-odbc": self.query_arrow_odbc}
        if self.motor in leitores:
            try:
                df = leitores[self.motor](sql, params, ao_lote=ao_lote)
                self.ultimo_motor = self.motor
                return df
            except InterrupcaoLeitura as e:  # quem chamou mandou parar: não é falha do motor
                raise e.original from None
            except Exception as e:  # tipo não suportado, TLS, driver... volta para o ODBC
                logger.warning("%s falhou (%s: %s); lendo pelo ODBC", self.motor, type(e).__name__, str(e)[:200])
        df = self.query_odbc(sql, params, ao_lote=ao_lote)
        self.ultimo_motor = self.motor_padrao
        return df

    def query_arrow_odbc(self, sql: str, params: dict | None = None, ao_lote=None) -> pl.DataFrame:
        """Lê pelo driver ODBC direto para Arrow, em lotes, e devolve os MESMOS tipos do caminho ODBC.

        Diferenças tratadas aqui:
          - parâmetros (:nome) viram literais (o arrow-odbc só aceita ? posicional);
          - inteiros menores (INT, SMALLINT, TINYINT) viram Int64, como no pyodbc;
          - data e hora ficam em microssegundos, como no pyodbc.
        """
        import pyarrow as pa
        from arrow_odbc import read_arrow_batches_from_odbc

        from src.lurkqvd.pipeline.estimativa import _embutir

        leitor = read_arrow_batches_from_odbc(
            query=_embutir(sql, params or {}),
            connection_string=_odbc(self.fonte, self._senha),  # mesma string (e escape da senha) do ODBC
            batch_size=self.LOTE,
            max_text_size=MAX_TEXTO,  # sem isso, uma coluna VARCHAR(MAX) impede a leitura em lote
            max_bytes_per_batch=BUFFER_LEITURA_MB * 1024 * 1024,
            login_timeout_sec=15,
            packet_size=self.packet_size,
        )
        lotes, lidas = [], 0
        for lote in leitor:
            lotes.append(lote)
            lidas += lote.num_rows
            if ao_lote:
                try:
                    ao_lote(lidas)
                except Exception as e:
                    raise InterrupcaoLeitura(e) from e
        return _normalizar_arrow_odbc(pl.from_arrow(pa.Table.from_batches(lotes, schema=leitor.schema)))

    # ------------------------------------------------------------------ #
    # Leitura em lotes (o gerador de QVD em fluxo consome um lote por vez)
    # ------------------------------------------------------------------ #
    def iter_lotes(self, sql: str, params: dict | None = None):
        """DataFrames de até LOTE linhas, na ordem do banco. Nunca há a tabela inteira na memória.

        Se o motor escolhido falhar ANTES do primeiro lote (driver, TLS, tipo não suportado), cai
        para o ODBC. Depois que os lotes começaram a sair, uma falha sobe: recomeçar no meio
        duplicaria linhas no QVD.
        """
        leitores = {"arrow-odbc": self._lotes_arrow_odbc, "connectorx": self._lotes_connectorx}
        if self.motor in leitores:
            lotes = leitores[self.motor](sql, params)
            try:
                primeiro = next(lotes)
            except StopIteration:
                self.ultimo_motor = self.motor
                return
            except Exception as e:
                logger.warning("%s falhou (%s: %s); lendo pelo ODBC", self.motor, type(e).__name__, str(e)[:200])
            else:
                self.ultimo_motor = self.motor
                yield primeiro
                yield from lotes
                return
        self.ultimo_motor = self.motor_padrao
        yield from self._lotes_odbc(sql, params)

    def _lotes_arrow_odbc(self, sql: str, params: dict | None):
        from arrow_odbc import read_arrow_batches_from_odbc

        from src.lurkqvd.pipeline.estimativa import _embutir

        leitor = read_arrow_batches_from_odbc(
            query=_embutir(sql, params or {}),
            connection_string=_odbc(self.fonte, self._senha),
            batch_size=self.LOTE,
            max_text_size=MAX_TEXTO,
            max_bytes_per_batch=BUFFER_LEITURA_MB * 1024 * 1024,
            login_timeout_sec=15,
            packet_size=self.packet_size,
        )
        for lote in leitor:
            yield _normalizar_arrow_odbc(pl.from_arrow(lote))

    def _lotes_odbc(self, sql: str, params: dict | None):
        """Leitura pelo SQLAlchemy: pyodbc no SQL Server, psycopg no PostgreSQL."""
        for lote in pl.read_database(text(sql), connection=self.engine, iter_batches=True,
                                     batch_size=self.LOTE, execute_options={"parameters": params or {}}):
            yield self._normalizar(lote)

    def _lotes_connectorx(self, sql: str, params: dict | None):
        yield self.query_connectorx(sql, params)  # o connectorx entrega tudo de uma vez

    def query_odbc(self, sql: str, params: dict | None = None, ao_lote=None) -> pl.DataFrame:
        """A consulta inteira pelo SQLAlchemy (pyodbc no SQL Server, psycopg no PostgreSQL)."""
        if ao_lote is None:
            return self._normalizar(pl.read_database(
                text(sql), connection=self.engine, execute_options={"parameters": params or {}}
            ))
        lotes, lidas = [], 0
        for lote in self._lotes_odbc(sql, params):
            lotes.append(lote)
            lidas += lote.height
            ao_lote(lidas)
        if not lotes:  # consulta sem linhas: lê de novo (é instantâneo) só para trazer as colunas
            return self._normalizar(pl.read_database(
                text(sql), connection=self.engine, execute_options={"parameters": params or {}}
            ))
        # um lote pode ter uma coluna toda nula (tipo Null): "relaxed" acerta o tipo pelos outros
        return pl.concat(lotes, how="vertical_relaxed")

    def query_connectorx(self, sql: str, params: dict | None = None, ao_lote=None) -> pl.DataFrame:
        """Lê com o connectorx e devolve os MESMOS tipos que o caminho ODBC devolveria.

        Diferenças do connectorx tratadas aqui:
          - DATE vira data e hora no connectorx: volta para data (senão o QVD grava "2024-01-31 00:00:00");
          - parâmetros (:nome) não são suportados: viram literais.
        """
        import connectorx as cx

        from src.lurkqvd.pipeline.estimativa import _embutir

        consulta = _embutir(sql, params or {})
        df = cx.read_sql(_uri_connectorx(self.fonte, self._senha), consulta, return_type="polars")
        if ao_lote:  # o connectorx entrega tudo de uma vez: um aviso só, no fim
            try:
                ao_lote(df.height)
            except Exception as e:
                raise InterrupcaoLeitura(e) from e
        datas = self._colunas_date(consulta)
        ajustes = [pl.col(c).cast(pl.Date) for c in datas if c in df.columns and isinstance(df.schema[c], pl.Datetime)]
        return df.with_columns(ajustes) if ajustes else df

    def _colunas_date(self, consulta: str) -> list[str]:
        """Colunas do tipo DATE no resultado (TOP 0: o banco não lê nenhuma linha)."""
        import datetime as _dt

        from src.lurkqvd.pipeline.estimativa import _como_subconsulta

        bruto = self.engine.raw_connection()
        try:
            cur = bruto.cursor()
            cur.execute(f"SELECT TOP 0 * FROM (\n{_como_subconsulta(consulta)}\n) AS q")
            return [d[0] for d in cur.description if d[1] is _dt.date]
        finally:
            bruto.close()

    def _normalizar(self, df: pl.DataFrame) -> pl.DataFrame:
        return _normalizar_postgres(df) if self.tipo == "postgres" else df

    def linhas_previstas(self, sql: str, params: dict | None = None) -> int | None:
        """Linhas que o banco espera devolver, pelo plano estimado (não executa). Só para o percentual."""
        from src.lurkqvd.pipeline import estimativa

        return estimativa.linhas_previstas(self.engine, sql, params)

    def fechar(self) -> None:
        self.engine.dispose()


def _normalizar_arrow_odbc(df) -> pl.DataFrame:
    """Deixa os tipos do arrow-odbc iguais aos do caminho ODBC (pyodbc): inteiros em Int64,
    Float32 em Float64, data e hora em microssegundos."""
    if isinstance(df, pl.Series):
        df = df.to_frame()
    ajustes = []
    for nome, tipo in df.schema.items():
        if tipo.is_integer() and tipo != pl.Int64:
            ajustes.append(pl.col(nome).cast(pl.Int64))
        elif tipo == pl.Float32:
            ajustes.append(pl.col(nome).cast(pl.Float64))
        elif isinstance(tipo, pl.Datetime) and (tipo.time_unit != "us" or tipo.time_zone):
            ajustes.append(pl.col(nome).cast(pl.Datetime("us")))
    return df.with_columns(ajustes) if ajustes else df


def _normalizar_postgres(df: pl.DataFrame) -> pl.DataFrame:
    """Tipos do psycopg que o QVD não tem viram texto; timestamptz vira hora local (sem fuso).

    uuid, json, inet etc. já chegam como texto (_PG_COMO_TEXTO); aqui fica o que sobra: arrays (no
    formato do PostgreSQL, {1,2}), bytea (hex), ranges e outros objetos (texto do Python)."""
    ajustes = []
    for nome, tipo in df.schema.items():
        if isinstance(tipo, pl.Datetime) and tipo.time_zone:
            ajustes.append(pl.col(nome).dt.convert_time_zone(fuso.FUSO).dt.replace_time_zone(None))
        elif isinstance(tipo, (pl.List, pl.Array)):
            ajustes.append(pl.col(nome).map_elements(_texto_array, return_dtype=pl.String))
        elif isinstance(tipo, pl.Struct):
            ajustes.append(pl.col(nome).struct.json_encode())
        elif tipo == pl.Binary:
            ajustes.append(pl.col(nome).bin.encode("hex"))
        elif isinstance(tipo, pl.Duration) or tipo == pl.Object:
            ajustes.append(pl.col(nome).map_elements(str, return_dtype=pl.String))
    return df.with_columns(ajustes) if ajustes else df


def _texto_array(valores) -> str:
    itens = valores.to_list() if hasattr(valores, "to_list") else list(valores)
    return "{" + ",".join("NULL" if v is None else str(v) for v in itens) + "}"


def testar(fonte: dict, senha: str) -> dict:
    """Conecta e roda uma consulta mínima. Não levanta exceção."""
    resultado = {"ok": False, "erro": None, "versao": None, "latencia_ms": None,
                 "testado_em": datetime.now(timezone.utc).isoformat()}
    tipo = TIPOS.get(fonte.get("tipo"))
    if not tipo or not tipo["suportado"]:
        resultado["erro"] = "Esse tipo de banco ainda não é suportado."
        return resultado

    inicio = time.perf_counter()
    conexao = None
    try:
        conexao = FonteSql(fonte, senha, timeout_conexao=10)
        consultas = (("SELECT version()", "SELECT current_database()") if fonte["tipo"] == "postgres"
                     else ("SELECT @@VERSION", "SELECT DB_NAME()"))
        with conexao.engine.connect() as c:
            versao = c.execute(text(consultas[0])).scalar() or ""
            banco = c.execute(text(consultas[1])).scalar()
        resultado.update(
            ok=True,
            versao=versao.splitlines()[0].strip()[:120],
            latencia_ms=round((time.perf_counter() - inicio) * 1000),
            banco_conectado=banco,
        )
    except Exception as e:  # driver, rede, login...
        resultado["erro"] = _erro_amigavel(e, fonte["tipo"])
    finally:
        if conexao:
            conexao.fechar()
    return resultado


def _erro_amigavel(e: Exception, tipo: str = "mssql") -> str:
    msg = str(getattr(e, "orig", e))
    if tipo == "postgres":
        return _erro_amigavel_postgres(msg)
    baixo = msg.lower()
    if "login failed" in baixo or "18456" in baixo:
        return "Usuário ou senha recusados pelo SQL Server."
    if "cannot open database" in baixo or "4060" in baixo:
        return "O usuário entrou, mas não tem acesso a esse banco (ou o banco não existe)."
    if "data source name not found" in baixo or "can't open lib" in baixo or "im002" in baixo:
        return f"Driver ODBC não instalado no servidor do LurkQVD ({DRIVER_ODBC_PADRAO})."
    if "timeout" in baixo or "hyt00" in baixo or "08001" in baixo:
        return "Não consegui chegar ao servidor (host/porta errados, firewall ou VPN)."
    if "certificate" in baixo or "ssl" in baixo:
        return "Falha no certificado. Tente marcar “Confiar no certificado do servidor”."
    return msg.splitlines()[0][:300]


def _erro_amigavel_postgres(msg: str) -> str:
    baixo = msg.lower()
    if "password authentication failed" in baixo:
        return "Usuário ou senha recusados pelo PostgreSQL."
    if "database" in baixo and "does not exist" in baixo:
        return "Esse banco não existe no servidor (confira o nome: o PostgreSQL diferencia maiúsculas)."
    if "permission denied for database" in baixo:
        return "O usuário entrou, mas não tem permissão de CONNECT nesse banco."
    if "pg_hba.conf" in baixo:
        return ("O servidor recusou conexões desta máquina (pg_hba.conf). Peça ao DBA para liberar o IP do "
                "LurkQVD, ou marque “Exigir conexão criptografada (SSL)” se o servidor só aceita SSL.")
    if "ssl" in baixo:
        return "Falha na negociação SSL. Se o servidor não aceita SSL, desmarque “Exigir conexão criptografada”."
    if any(t in baixo for t in ("timeout", "could not translate host", "connection refused", "no route to host")):
        return "Não consegui chegar ao servidor (host/porta errados, firewall ou VPN)."
    return (msg.strip().splitlines() or [""])[0][:300]
