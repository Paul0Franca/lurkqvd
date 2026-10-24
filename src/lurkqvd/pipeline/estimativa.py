"""Estimativa do tamanho do QVD antes de gerar.

O QVD tem duas partes (calibrado contra arquivos gerados pelo qvdrs):
  1. Tabela de símbolos: cada valor DISTINTO de cada coluna, uma vez.
       inteiro (cabe em 32 bits) ......... 5 bytes   (1 de tipo + 4)
       inteiro grande / decimal / float .. 9 bytes   (1 de tipo + 8, vira double)
       texto ............................. tamanho + 2
       data .............................. 20 bytes  (número + "2024-01-31")
       data e hora ....................... 29 bytes  (número + "2024-01-31 12:00:00")
  2. Índice: por linha, cada coluna usa ceil(log2(distintos [+1 se tiver nulo])) bits;
     os bits de todas as colunas se somam e arredondam para bytes. Coluna com 1 valor = 0 bits.
  + cabeçalho XML: ~750 bytes + ~610 por coluna.

De onde vêm os números, sem varrer a tabela:
  - carga que já rodou: medidos no DataFrame da própria execução (custo zero no banco);
  - consulta nova: linhas pelo PLANO ESTIMADO (não executa), distintos pelas ESTATÍSTICAS do banco
    para colunas que vêm direto da tabela, e uma AMOSTRA (TOP N / LIMIT N) para as calculadas.
    Se a amostra trouxer tudo, o resultado é exato.
      SQL Server:  SHOWPLAN_XML, sys.stats + DBCC SHOW_STATISTICS, TABLESAMPLE SYSTEM (n PERCENT)
      PostgreSQL:  EXPLAIN (FORMAT JSON), pg_stats.n_distinct, TABLESAMPLE SYSTEM (n)
    O dialeto sai do engine do SQLAlchemy (engine.dialect.name).
"""

import math
import os
import random
import re
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal

CABECALHO_FIXO = 750
CABECALHO_POR_COLUNA = 610
COTA_GB = float(os.getenv("LURKQVD_COTA_GB", "250"))
TIMEOUT_ESTIMATIVA = int(os.getenv("LURKQVD_TIMEOUT_ESTIMATIVA", "60"))  # segundos
TAMANHO_AMOSTRA = int(os.getenv("LURKQVD_AMOSTRA_ESTIMATIVA", "50000"))
INT32 = 2**31 - 1


# ---------------------------------------------------------------------- #
# Fórmula
# ---------------------------------------------------------------------- #
def bytes_simbolo(categoria: str, tamanho_medio: float | None = None, int_grande: bool = False) -> float:
    if categoria == "inteiro":
        return 9 if int_grande else 5
    if categoria == "decimal":
        return 9
    if categoria == "data":
        return 20
    if categoria == "data_hora":
        return 29
    if categoria == "hora":
        return 18
    return (tamanho_medio or 0) + 2  # texto


def bits_indice(distintos: int, tem_nulo: bool) -> int:
    simbolos = distintos + (1 if tem_nulo else 0)
    return math.ceil(math.log2(simbolos)) if simbolos > 1 else 0


def calcular(linhas: int, colunas: list[dict]) -> dict:
    """colunas: [{nome, categoria, distintos, tem_nulo, tamanho_medio?, int_grande?}]"""
    total_bits = 0
    for c in colunas:
        c["bytes_simbolos"] = round(c["distintos"] * bytes_simbolo(c["categoria"], c.get("tamanho_medio"), c.get("int_grande", False)))
        c["bits"] = bits_indice(c["distintos"], c.get("tem_nulo", False))
        total_bits += c["bits"]

    bytes_por_linha = math.ceil(total_bits / 8)
    indice = linhas * bytes_por_linha
    simbolos = sum(c["bytes_simbolos"] for c in colunas)
    cabecalho = CABECALHO_FIXO + CABECALHO_POR_COLUNA * len(colunas)
    total = simbolos + indice + cabecalho

    for c in colunas:
        # parte do índice de cada coluna: proporcional aos bits dela
        c["bytes_indice"] = round(indice * c["bits"] / total_bits) if total_bits else 0
        c["bytes_total"] = c["bytes_simbolos"] + c["bytes_indice"]
        c["pct"] = round(100 * c["bytes_total"] / total, 1) if total else 0
        c["unica_por_linha"] = linhas > 0 and c["distintos"] >= 0.9 * linhas

    colunas.sort(key=lambda c: c["bytes_total"], reverse=True)
    return {
        "linhas": linhas,
        "tamanho_bytes": total,
        "simbolos_bytes": simbolos,
        "indice_bytes": indice,
        "cabecalho_bytes": cabecalho,
        "bytes_por_linha": bytes_por_linha,
        "pct_cota": round(100 * total / (COTA_GB * 1024**3), 4),
        "cota_gb": COTA_GB,
        "colunas": colunas,
        "sugestoes": _sugestoes(colunas, total),
    }


def _sugestoes(colunas: list[dict], total: int) -> list[str]:
    dicas = []
    for c in colunas[:3]:
        if c["pct"] >= 20 and c["unica_por_linha"]:
            dicas.append(
                f"{c['nome']} tem um valor diferente por linha e pesa {c['pct']:.0f}% do arquivo. "
                "Se os apps não usam essa coluna, tirá-la do SELECT reduz bem o QVD."
            )
        elif c["pct"] >= 20 and c["categoria"] == "data_hora":
            dicas.append(
                f"{c['nome']} é data e hora e pesa {c['pct']:.0f}%. Se só a data importa, "
                "CAST(... AS date) corta muito os valores distintos."
            )
        elif c["pct"] >= 20 and c["categoria"] == "decimal" and c["distintos"] > 10_000:
            dicas.append(
                f"{c['nome']} tem muitos valores decimais distintos ({c['distintos']:,}). "
                "Arredondar (ROUND) para as casas que os apps usam diminui o arquivo.".replace(",", ".")
            )
    return dicas


# ---------------------------------------------------------------------- #
# Estatística a partir de um DataFrame (usado nos testes e como conferência)
# ---------------------------------------------------------------------- #
def colunas_de_dataframe(df, com_f1: bool = False) -> list[dict]:
    import polars as pl

    cols = []
    for nome, tipo in df.schema.items():
        s = df[nome]
        nao_nulos = s.drop_nulls()
        c = {"nome": nome, "distintos": nao_nulos.n_unique(), "tem_nulo": s.null_count() > 0}
        if com_f1:
            contagem = nao_nulos.value_counts()
            c["f1"] = int((contagem["count"] == 1).sum()) if len(contagem) else 0
            c["f2"] = int((contagem["count"] == 2).sum()) if len(contagem) else 0
        if tipo.is_integer() or tipo == pl.Boolean:
            c["categoria"] = "inteiro"
            c["int_grande"] = bool(len(nao_nulos)) and tipo.is_integer() and (abs(nao_nulos.max()) > INT32 or abs(nao_nulos.min()) > INT32)
        elif tipo.is_float() or isinstance(tipo, pl.Decimal):
            c["categoria"] = "decimal"
        elif tipo == pl.Date:
            c["categoria"] = "data"
        elif isinstance(tipo, pl.Datetime):
            c["categoria"] = "data_hora"
        else:
            c["categoria"] = "texto"
            unicos = nao_nulos.cast(pl.String).unique()
            c["tamanho_medio"] = unicos.str.len_bytes().mean() if len(unicos) else 0
        cols.append(c)
    return cols


# ---------------------------------------------------------------------- #
# Composição medida na própria execução (custo zero no banco)
# ---------------------------------------------------------------------- #
def composicao_dataframe(df) -> dict:
    """Composição do QVD a partir do DataFrame que acabou de ser extraído."""
    inicio = time.perf_counter()
    resultado = calcular(df.height, colunas_de_dataframe(df))
    for c in resultado["colunas"]:
        c["origem"] = "medido"
    resultado["segundos"] = round(time.perf_counter() - inicio, 2)
    return resultado


def composicao_medida(info: dict, tamanho_arquivo: int) -> dict:
    """Composição EXATA do QVD a partir do que o gerador em fluxo gravou (qvd_fluxo.finalizar):
    símbolos em bytes e bits por linha de cada coluna, sem estimar nada."""
    inicio = time.perf_counter()
    linhas, bytes_linha = info["linhas"], info["bytes_linha"]
    indice = linhas * bytes_linha
    simbolos = sum(info["bytes_simbolos"].values())
    total_bits = sum(info["larguras"].values())
    colunas = []
    for nome, distintos in info["distintos"].items():
        tipo = info["tipos"][nome]
        if tipo.startswith(("int", "uint", "bool")):
            categoria = "inteiro"
        elif tipo.startswith(("double", "float", "halffloat", "decimal")):
            categoria = "decimal"
        elif tipo.startswith("date"):
            categoria = "data"
        elif tipo.startswith("timestamp"):
            categoria = "data_hora"
        elif tipo.startswith("time"):
            categoria = "hora"
        else:
            categoria = "texto"
        bits = info["larguras"][nome]
        bytes_indice = round(indice * bits / total_bits) if total_bits else 0
        colunas.append({
            "nome": nome, "categoria": categoria, "distintos": distintos,
            "tem_nulo": info["tem_nulo"][nome], "bytes_simbolos": info["bytes_simbolos"][nome],
            "bits": bits, "bytes_indice": bytes_indice,
            "bytes_total": info["bytes_simbolos"][nome] + bytes_indice,
            "unica_por_linha": linhas > 0 and distintos >= 0.9 * linhas, "origem": "medido",
        })
    for c in colunas:
        c["pct"] = round(100 * c["bytes_total"] / tamanho_arquivo, 1) if tamanho_arquivo else 0
    colunas.sort(key=lambda c: c["bytes_total"], reverse=True)
    return {
        "linhas": linhas,
        "tamanho_bytes": tamanho_arquivo,
        "simbolos_bytes": simbolos,
        "indice_bytes": indice,
        "cabecalho_bytes": tamanho_arquivo - simbolos - indice,
        "bytes_por_linha": bytes_linha,
        "pct_cota": round(100 * tamanho_arquivo / (COTA_GB * 1024**3), 4),
        "cota_gb": COTA_GB,
        "colunas": colunas,
        "sugestoes": _sugestoes(colunas, tamanho_arquivo),
        "segundos": round(time.perf_counter() - inicio, 2),
    }


# ---------------------------------------------------------------------- #
# Estimativa rápida no SQL Server (sem varrer a tabela)
# ---------------------------------------------------------------------- #
class ConsultaNaoSuportada(ValueError):
    pass


def _como_subconsulta(sql: str, dialeto: str = "mssql") -> str:
    """A consulta vira subconsulta: tira ';' e, no SQL Server, um ORDER BY final (proibido em subconsulta
    sem TOP). O PostgreSQL aceita WITH e ORDER BY (com LIMIT) dentro da subconsulta: fica como está."""
    q = sql.strip().rstrip(";").strip()
    if dialeto == "postgresql":
        return q
    if re.match(r"(?is)^\s*with\b", q):
        raise ConsultaNaoSuportada(
            "Consultas com WITH (CTE) ainda não podem ser estimadas. A composição real aparece "
            "na página da carga depois da primeira execução."
        )
    m = re.search(r"(?is)\border\s+by\b[^()]*$", q)
    if m and not re.match(r"(?is)^\s*select\s+top\b", q):
        q = q[: m.start()].rstrip()
    return q


def _literal(v, dialeto: str = "mssql") -> str:
    pg = dialeto == "postgresql"
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return ("TRUE" if v else "FALSE") if pg else ("1" if v else "0")
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%dT%H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.isoformat() + "'"
    return ("'" if pg else "N'") + str(v).replace("'", "''") + "'"


def _embutir(sql: str, params: dict, dialeto: str = "mssql") -> str:
    """Parâmetros :nome viram literais (o plano estimado e as funções de metadados não aceitam '?').
    O '::' dos casts do PostgreSQL não é parâmetro."""
    return re.sub(r"(?<![:\w]):(\w+)",
                  lambda m: _literal(params[m.group(1)], dialeto) if m.group(1) in params else m.group(0), sql)


def _q(nome: str) -> str:
    return "[" + nome.replace("]", "]]") + "]"


def _dialeto(engine) -> str:
    return getattr(getattr(engine, "dialect", None), "name", "mssql")


def _categoria_python(tipo) -> str:
    if tipo is bool or tipo is int:
        return "inteiro"
    if tipo in (float, Decimal):
        return "decimal"
    if tipo is datetime:
        return "data_hora"
    if tipo is date:
        return "data"
    if tipo is dtime:
        return "hora"
    return "texto"


def distintos_por_amostra(d: int, f1: int, n: int, total: int, f2: int = 0) -> int:
    """Distintos na tabela inteira a partir de uma amostra de n linhas com d distintos.

    A coluna tem um "universo" de D valores possíveis e a tabela é um sorteio de `total` linhas dele:
    distintos esperados = D·(1 − e^(−total/D)). D é estimado de dois jeitos e vale o maior:
      - modelo uniforme: resolve d = D·(1 − e^(−n/D));
      - Chao1: d + f1²/(2·f2) (f1/f2 = valores vistos 1 e 2 vezes), melhor para distribuições desiguais.
    Coluna praticamente única na amostra (ex.: ids) cresce junto com as linhas.
    Calibrado em testes: ~1% de erro em colunas uniformes; subestima cauda muito longa.
    """
    if n <= 0 or total <= n or d == 0:
        return d
    if d >= 0.98 * n:  # quase tudo único: cresce com as linhas
        return min(total, round(d * total / n))

    def visto(universo: float, linhas: int) -> float:
        return universo * (1 - math.exp(-linhas / universo))

    baixo, alto = float(d), float(d) * 1e6
    for _ in range(200):  # bissecção: visto(D, n) cresce com D
        meio = (baixo + alto) / 2
        if visto(meio, n) < d:
            baixo = meio
        else:
            alto = meio
    chao1 = d + (f1 * f1 / (2 * f2) if f2 else f1 * max(f1 - 1, 0) / 2)
    universo = max(alto, chao1)
    return int(min(total, max(d, round(visto(universo, total)))))


_PALAVRAS = {"where", "with", "group", "order", "option", "union", "cross", "outer", "inner", "left", "right",
             "full", "join", "tablesample", "having", "for", "except", "intersect", "pivot", "unpivot"}


def _com_tablesample(sql: str, porcento: float, dialeto: str = "mssql") -> str | None:
    """Põe TABLESAMPLE SYSTEM na tabela da consulta, para a amostra vir de páginas sorteadas
    da tabela inteira (e não só das primeiras linhas). Só para consulta de UMA tabela, sem JOIN."""
    if re.search(r"(?is)\bjoin\b|\bapply\b|\bunion\b|\blateral\b", sql) or len(re.findall(r"(?is)\bfrom\b", sql)) != 1:
        return None
    nome = r'(?:\[[^\]]+\]|"(?:[^"]|"")+"|[A-Za-z_][\w$#@]*)'
    m = re.search(rf"(?is)\bfrom\s+({nome}(?:\s*\.\s*{nome}){{0,2}})(\s+(?:as\s+)?({nome}))?", sql)
    if not m:
        return None
    fim = m.end(1)
    if m.group(3) and m.group(3).strip('[]"').lower() not in _PALAVRAS | {"limit", "offset", "fetch", "window"}:
        fim = m.end(2)  # tem alias: o TABLESAMPLE vem depois dele
    tamanho = f"{porcento:.4f}" if dialeto == "postgresql" else f"{porcento:.4f} PERCENT"
    return f"{sql[:fim]} TABLESAMPLE SYSTEM ({tamanho}){sql[fim:]}"


def _ajuste_potencia(pts: list[tuple[float, float]]):
    """d(x) = c·x^β (lei de Heaps): bom para colunas que crescem sem teto (ids, clientes)."""
    xs = [math.log(x) for x, _ in pts]
    ys = [math.log(max(y, 1e-9)) for _, y in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs) or 1e-9
    beta = max(0.0, min(1.0, sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx))
    c = math.exp(my - beta * mx)
    return lambda x: c * x**beta


def _ajuste_saturacao(pts: list[tuple[float, float]]):
    """d(x) = D·(1 − e^(−a·x/D)): bom para colunas com teto (produtos, datas, lojas)."""
    ymax = max(y for _, y in pts)
    a0 = pts[0][1] / pts[0][0]
    melhor = None
    for i in range(80):
        teto = ymax * (1.0001 + (10 ** (i / 10) - 1))
        for j in range(25):
            a = a0 * (0.5 + j / 12)
            erro = sum((teto * (1 - math.exp(-a * x / teto)) - y) ** 2 for x, y in pts)
            if melhor is None or erro < melhor[0]:
                melhor = (erro, teto, a)
    _, teto, a = melhor
    return lambda x: teto * (1 - math.exp(-a * x / teto))


def distintos_por_curva(serie, linhas_por_bloco: int, total_linhas: int, semente: int = 7) -> tuple[int, str]:
    """Distintos na tabela inteira a partir de uma amostra de PÁGINAS (TABLESAMPLE).

    Página sorteada traz linhas vizinhas juntas (ex.: itens do mesmo pedido), então não dá para tratar
    como linhas independentes. Mede quantos distintos aparecem com 1/16, 1/8, 1/4, 1/2 e todas as
    páginas da amostra, ajusta dois modelos (potência e saturação) com os pontos menores, fica com o
    que melhor PREVÊ o ponto completo e extrapola para todas as páginas da tabela.
    """
    import polars as pl

    n = len(serie)
    d_obs = serie.drop_nulls().n_unique()
    bloco = pl.Series([i // linhas_por_bloco for i in range(n)])
    m = int(bloco.max()) + 1 if n else 0
    if m < 8 or d_obs == 0:
        return d_obs, "poucas páginas"
    rnd = random.Random(semente)
    pts = []
    for fracao in (1 / 16, 1 / 8, 1 / 4, 1 / 2):
        k = max(1, round(m * fracao))
        soma = 0
        for _ in range(3):
            escolhidos = pl.Series(rnd.sample(range(m), k))
            soma += serie.filter(bloco.is_in(escolhidos)).drop_nulls().n_unique()
        pts.append((k, soma / 3))
    pts.append((m, d_obs))
    treino, alvo = pts[:-1], pts[-1]
    modelos = {"crescente": _ajuste_potencia, "com teto": _ajuste_saturacao}
    erros = {nome: abs(ajuste(treino)(alvo[0]) - alvo[1]) for nome, ajuste in modelos.items()}
    escolhido = min(erros, key=erros.get)
    previsto = modelos[escolhido](pts)(total_linhas / linhas_por_bloco)
    return int(min(total_linhas, max(d_obs, round(previsto)))), escolhido


def _linhas_pelo_plano(cur, sql: str) -> tuple[float | None, float | None]:
    """(linhas estimadas, bytes médios por linha) pelo plano. SHOWPLAN_XML não executa a consulta."""
    try:
        cur.execute("SET SHOWPLAN_XML ON")
    except Exception:
        return None, None
    try:
        cur.execute(sql)
        xml = cur.fetchone()[0] or ""
        linhas = re.search(r'StatementEstRows="([0-9.eE+-]+)"', xml)
        tamanho = re.search(r'<RelOp [^>]*AvgRowSize="([0-9.eE+-]+)"', xml)
        return (float(linhas.group(1)) if linhas else None, float(tamanho.group(1)) if tamanho else None)
    except Exception:
        return None, None
    finally:
        try:
            cur.execute("SET SHOWPLAN_XML OFF")
        except Exception:
            pass


def _origens(cur, sql: str) -> dict[str, tuple[str, str, str]]:
    """Coluna do resultado -> (schema, tabela, coluna) de origem, quando vem direto de uma tabela."""
    try:
        cur.execute(
            "SELECT name, source_schema, source_table, source_column "
            "FROM sys.dm_exec_describe_first_result_set(?, NULL, 1)",
            sql,
        )
        return {r[0]: (r[1] or "dbo", r[2], r[3]) for r in cur.fetchall() if r[2] and r[3]}
    except Exception:
        return {}


def _distintos_pela_estatistica(cur, schema: str, tabela: str, coluna: str) -> int | None:
    """Distintos da coluna pelas estatísticas do SQL Server (1 / densidade). None se não houver."""
    objeto = f"{_q(schema)}.{_q(tabela)}"
    try:
        cur.execute(
            """
            SELECT TOP 1 s.name
              FROM sys.stats s
              JOIN sys.stats_columns sc ON sc.object_id = s.object_id AND sc.stats_id = s.stats_id AND sc.stats_column_id = 1
              JOIN sys.columns c ON c.object_id = sc.object_id AND c.column_id = sc.column_id
             WHERE s.object_id = OBJECT_ID(?) AND c.name = ?
             ORDER BY s.auto_created, s.stats_id
            """,
            objeto, coluna,
        )
        linha = cur.fetchone()
        if not linha:
            return None
        alvo = objeto.replace("'", "''")
        cur.execute(f"DBCC SHOW_STATISTICS ('{alvo}', {_q(linha[0])}) WITH DENSITY_VECTOR, NO_INFOMSGS")
        primeira = cur.fetchone()
        densidade = float(primeira[0]) if primeira and primeira[0] else 0
        return round(1 / densidade) if densidade > 0 else None
    except Exception:
        return None


# PostgreSQL ------------------------------------------------------------ #
_PG_CATEGORIAS = {16: "inteiro", 20: "inteiro", 21: "inteiro", 23: "inteiro", 700: "decimal", 701: "decimal",
                  1700: "decimal", 1082: "data", 1114: "data_hora", 1184: "data_hora", 1083: "hora", 1266: "hora"}


def _linhas_pelo_plano_pg(cur, sql: str) -> tuple[float | None, float | None]:
    """(linhas estimadas, bytes médios por linha) pelo EXPLAIN, que não executa a consulta."""
    import json

    try:
        cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
        plano = cur.fetchone()[0]
        plano = json.loads(plano) if isinstance(plano, str) else plano
        raiz = plano[0]["Plan"]
        return float(raiz["Plan Rows"]), float(raiz["Plan Width"])
    except Exception:
        return None, None


def _distintos_pg(cur) -> dict[str, int]:
    """Distintos das colunas que vêm direto de uma tabela, pelas estatísticas (pg_stats.n_distinct).

    Usa o resultado da última consulta do cursor (o LIMIT 0): o libpq diz de que tabela e coluna veio
    cada coluna do resultado. n_distinct negativo é fração das linhas (−0,5 = metade das linhas)."""
    origem = {}
    res = cur.pgresult
    for i, d in enumerate(cur.description):
        tabela, coluna = res.ftable(i), res.ftablecol(i)
        if tabela and coluna:
            origem[d.name] = (tabela, coluna)
    distintos = {}
    for nome, (tabela, coluna) in origem.items():
        try:
            cur.execute(
                """
                SELECT s.n_distinct, c.reltuples
                  FROM pg_attribute a
                  JOIN pg_class c ON c.oid = a.attrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                  JOIN pg_stats s ON s.schemaname = n.nspname AND s.tablename = c.relname AND s.attname = a.attname
                 WHERE a.attrelid = %s AND a.attnum = %s
                """,
                (tabela, coluna),
            )
            linha = cur.fetchone()
        except Exception:
            continue
        if not linha or linha[0] is None:
            continue
        n_distinct, reltuples = float(linha[0]), float(linha[1] or 0)
        valor = n_distinct if n_distinct > 0 else -n_distinct * reltuples
        if valor >= 1:
            distintos[nome] = round(valor)
    return distintos


def linhas_previstas(engine, sql: str, params: dict | None = None) -> int | None:
    """Linhas que o banco espera devolver (plano estimado, não executa). None se não der."""
    dialeto = _dialeto(engine)
    bruto = engine.raw_connection()
    try:
        cur = bruto.cursor()
        consulta = _embutir(sql, params or {}, dialeto)
        if dialeto == "postgresql":
            linhas, _ = _linhas_pelo_plano_pg(cur, consulta)
            bruto.rollback()
        else:
            linhas, _ = _linhas_pelo_plano(cur, consulta)
    finally:
        bruto.close()
    return round(linhas) if linhas else None


def estimar_rapida(engine, sql: str, params: dict | None = None, *, amostra: int = TAMANHO_AMOSTRA,
                   timeout: int = TIMEOUT_ESTIMATIVA) -> dict:
    """Estimativa sem varrer a tabela: plano estimado + estatísticas + amostra TOP N."""
    import polars as pl

    inicio = time.perf_counter()
    dialeto = _dialeto(engine)
    pg = dialeto == "postgresql"
    sub = _embutir(_como_subconsulta(sql, dialeto), params or {}, dialeto)
    avisos: list[str] = []

    def limitada(consulta: str, n: int) -> str:
        return f"SELECT * FROM (\n{consulta}\n) AS q LIMIT {int(n)}" if pg else f"SELECT TOP ({int(n)}) * FROM (\n{consulta}\n) AS q"

    bruto = engine.raw_connection()
    con = getattr(bruto, "driver_connection", None) or bruto.connection
    try:
        if pg:
            con.autocommit = True  # uma consulta recusada (ex.: TABLESAMPLE em view) não aborta as seguintes
            cur = con.cursor()
            cur.execute(f"SET statement_timeout = {int(timeout) * 1000}")
        else:
            con.timeout = timeout  # pyodbc
            cur = con.cursor()

        cur.execute(f"SELECT * FROM (\n{sub}\n) AS q LIMIT 0" if pg else f"SELECT TOP 0 * FROM (\n{sub}\n) AS q")
        if pg:
            descricao = [(d.name, d.type_code) for d in cur.description]
        else:
            descricao = [(d[0], d[1]) for d in cur.description]
        nomes = [n for n, _ in descricao]
        if not nomes or any(not n for n in nomes) or len({n.lower() for n in nomes}) != len(nomes):
            raise ConsultaNaoSuportada("Toda coluna precisa de um nome único (use AS nas expressões).")

        if pg:
            stats = _distintos_pg(cur)  # antes de outra consulta: usa a origem das colunas do LIMIT 0
            linhas_plano, bytes_linha = _linhas_pelo_plano_pg(cur, sub)
        else:
            linhas_plano, bytes_linha = _linhas_pelo_plano(cur, sub)
            origens = _origens(cur, sub)
            stats = {}
            for nome in nomes:
                if nome in origens:
                    d = _distintos_pela_estatistica(cur, *origens[nome])
                    if d:
                        stats[nome] = d

        # amostra: de preferência páginas sorteadas da tabela inteira (TABLESAMPLE); se não der
        # (JOIN, view, consulta complexa), as primeiras N linhas que a consulta devolver.
        linhas_amostra, aleatoria = None, False
        if linhas_plano and linhas_plano > amostra * 1.5:
            # usa TUDO o que o sorteio trouxer: cortar com TOP pegaria só o começo da tabela
            # (o banco devolve as páginas sorteadas na ordem física). O TOP só protege contra exageros.
            porcento = min(100.0, max(0.01, 100 * amostra / linhas_plano))
            com_sorteio = _com_tablesample(sub, porcento, dialeto)
            if com_sorteio:
                try:
                    cur.execute(limitada(com_sorteio, amostra * 4))
                    obtidas = [tuple(r) for r in cur.fetchall()]
                    if len(obtidas) >= amostra * 0.2:  # sorteio trouxe o suficiente
                        linhas_amostra, aleatoria = obtidas, True
                except Exception:
                    pass  # ex.: view (TABLESAMPLE só vale para tabela)
        if linhas_amostra is None:
            cur.execute(limitada(sub, amostra))
            linhas_amostra = [tuple(r) for r in cur.fetchall()]
    finally:
        if pg:
            try:
                cur.execute("RESET statement_timeout")
                con.autocommit = False
            except Exception:
                pass
        bruto.close()

    df = pl.DataFrame(linhas_amostra, schema=nomes, orient="row", infer_schema_length=None)
    if pg:  # os mesmos tipos que a carga vai gravar (arrays, bytea... viram texto)
        from src.lurkqvd.config.fontes import _normalizar_postgres

        df = _normalizar_postgres(df)
    df = df.with_columns([pl.col(c).cast(pl.Float64) for c, t in df.schema.items() if isinstance(t, pl.Decimal)])
    n = df.height
    completa = not aleatoria and n < amostra  # a consulta inteira coube na amostra: resultado exato

    if completa:
        total, origem_linhas = n, "exato"
    elif linhas_plano:
        total, origem_linhas = max(n, round(linhas_plano)), "plano"
    else:
        total, origem_linhas = n, "amostra"
        avisos.append(
            "Não consegui o plano estimado (EXPLAIN): o total de linhas ficou no tamanho da amostra (subestimado)."
            if pg else
            "Sem permissão para ver o plano estimado: o total de linhas ficou no tamanho da amostra (subestimado). "
            "Peça ao DBA: GRANT SHOWPLAN TO [usuário do LurkQVD]."
        )

    colunas = colunas_de_dataframe(df, com_f1=True)
    tipos = dict(descricao)
    # linhas por página: 8 KB / bytes médios da linha (do plano). O dobro, por segurança:
    # bloco maior que a página real não atrapalha; menor faz subestimar colunas agrupadas.
    linhas_por_bloco = max(10, min(2000, round(2 * 8060 / bytes_linha))) if bytes_linha else 100
    for c in colunas:
        if c["categoria"] == "texto" and c["distintos"] == 0:  # o tipo do banco ajuda quando a amostra veio vazia/nula
            tipo = tipos.get(c["nome"])
            c["categoria"] = _PG_CATEGORIAS.get(tipo, "texto") if pg else _categoria_python(tipo)
        if completa:
            c["origem"] = "exato"
        else:
            if aleatoria:  # páginas sorteadas: curva de crescimento por página
                pela_amostra, c["modelo"] = distintos_por_curva(df[c["nome"]], linhas_por_bloco, total)
            else:          # primeiras linhas: modelo por linha (menos preciso se a tabela estiver ordenada)
                pela_amostra = distintos_por_amostra(c["distintos"], c.get("f1", 0), n, total, c.get("f2", 0))
            if c["nome"] in stats:
                # estatística do SQL Server costuma vir de amostragem e SUBESTIMAR; vale o maior dos dois
                c["distintos"] = int(min(total, max(stats[c["nome"]], pela_amostra)))
                c["origem"] = "estatística"
            else:
                c["distintos"] = int(pela_amostra)
                c["origem"] = "amostra"
        c.pop("f1", None)
        c.pop("f2", None)
        c.pop("modelo", None)

    if not completa and any(c["origem"] == "amostra" for c in colunas):
        if aleatoria:
            avisos.append(
                f"Colunas marcadas como “amostra” foram extrapoladas de {n:,} linhas em páginas sorteadas da tabela "
                "(TABLESAMPLE), pela curva de crescimento de cada coluna. Margem típica de ±10%.".replace(",", ".")
            )
        else:
            avisos.append(
                f"Colunas marcadas como “amostra” foram extrapoladas das primeiras {n:,} linhas (a consulta tem JOIN, "
                "view ou não permite sorteio). Se a tabela estiver ordenada, essas colunas saem abaixo do real.".replace(",", ".")
            )

    resultado = calcular(total, colunas)
    resultado.update(
        segundos=round(time.perf_counter() - inicio, 1),
        origem_linhas=origem_linhas,
        amostra=n,
        amostra_aleatoria=aleatoria,
        avisos=avisos,
    )
    return resultado
