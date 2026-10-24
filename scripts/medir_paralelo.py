"""Mede se ler uma carga em faixas simultâneas acelera a extração (sem gerar QVD).

Uso, na raiz do projeto:
    python -m scripts.medir_paralelo fct_vendas_item DATA_VENDA
    python -m scripts.medir_paralelo fct_vendas_item DATA_VENDA 1 2 4 8     (quantidades de faixas)

A coluna (de data ou número) divide a consulta em faixas de valores do mesmo tamanho, entre o
mínimo e o máximo dela, mais uma faixa para os nulos. Cada faixa é lida por uma conexão própria,
ao mesmo tempo; os lotes são descartados (só interessa o tempo de chegar).

No fim confere que a soma das linhas das faixas é igual à leitura em uma faixa só: a divisão
não pode perder nem duplicar linhas.
"""

import datetime as dt
import sys
import threading
import time

from sqlalchemy import text

from src.lurkqvd.config import fontes
from src.lurkqvd.pipeline.estimativa import _como_subconsulta, _embutir
from src.lurkqvd.repository.repositorio import Repositorio


def _literal(v) -> str:
    if isinstance(v, dt.datetime):
        return f"'{v.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}'"  # ISO com T: sem ambiguidade no SQL Server
    if isinstance(v, dt.date):
        return f"'{v.strftime('%Y%m%d')}'"
    return repr(v)


def faixas(minimo, maximo, n: int) -> list[tuple]:
    """n faixas [ini, fim) de mesmo tamanho; a última inclui o máximo."""
    if n == 1 or minimo == maximo:
        return [(None, None)]
    if isinstance(minimo, dt.date) and not isinstance(minimo, dt.datetime):
        ini, fim = dt.datetime.combine(minimo, dt.time()), dt.datetime.combine(maximo, dt.time())
        passo = (fim - ini) / n
        cortes = [(ini + passo * k).date() for k in range(1, n)]
    elif isinstance(minimo, dt.datetime):
        passo = (maximo - minimo) / n
        cortes = [minimo + passo * k for k in range(1, n)]
    else:
        passo = (maximo - minimo) / n
        cortes = [minimo + passo * k for k in range(1, n)]
        if isinstance(minimo, int):
            cortes = [int(c) for c in cortes]
    cortes = sorted(set(cortes))
    limites = [None] + cortes + [None]
    return list(zip(limites[:-1], limites[1:]))


def consulta_da_faixa(base: str, coluna: str, ini, fim) -> str:
    cond = []
    if ini is not None:
        cond.append(f"q.[{coluna}] >= {_literal(ini)}")
    if fim is not None:
        cond.append(f"q.[{coluna}] < {_literal(fim)}")
    if not cond:  # faixa única: a consulta inteira (nulos inclusos)
        return f"SELECT * FROM (\n{base}\n) AS q"
    return f"SELECT * FROM (\n{base}\n) AS q WHERE " + " AND ".join(cond)


def ler(fonte: dict, senha: str, sql: str, resultado: dict, chave) -> None:
    from arrow_odbc import read_arrow_batches_from_odbc

    inicio = time.perf_counter()
    linhas = 0
    try:
        leitor = read_arrow_batches_from_odbc(
            query=sql, connection_string=fontes._odbc(fonte, senha), batch_size=100_000,
            max_text_size=fontes.MAX_TEXTO, login_timeout_sec=15,
        )
        for lote in leitor:
            linhas += lote.num_rows
            del lote
        resultado[chave] = (linhas, time.perf_counter() - inicio, None)
    except Exception as e:
        resultado[chave] = (linhas, time.perf_counter() - inicio, f"{type(e).__name__}: {str(e)[:200]}")


def rodada(fonte, senha, base, coluna, minimo, maximo, n) -> int:
    lista = faixas(minimo, maximo, n)
    consultas = [consulta_da_faixa(base, coluna, ini, fim) for ini, fim in lista]
    if len(lista) > 1:  # os nulos da coluna não caem em nenhuma faixa de valores: faixa própria
        consultas.append(f"SELECT * FROM (\n{base}\n) AS q WHERE q.[{coluna}] IS NULL")
    resultado: dict = {}
    inicio = time.perf_counter()
    threads = [threading.Thread(target=ler, args=(fonte, senha, sql, resultado, i)) for i, sql in enumerate(consultas)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seg = time.perf_counter() - inicio
    total = sum(r[0] for r in resultado.values())
    erros = [r[2] for r in resultado.values() if r[2]]
    por_faixa = " · ".join(f"{resultado[i][0]:,}".replace(",", ".") for i in range(len(consultas)))
    print(f"{n:>2} faixa(s): {seg:6.1f}s  {total / seg:>9,.0f} linhas/s  [{por_faixa}]".replace(",", "."))
    for e in erros:
        print("     ERRO:", e)
    return total


def main(nome: str, coluna: str, quantidades: list[int]) -> None:
    repo = Repositorio()
    achada = repo.buscar_carga_por_nome(nome)
    if not achada:
        sys.exit(f"Carga '{nome}' não encontrada.")
    _, carga = achada
    fonte = repo.fonte_para_execucao(carga.fonte_id)
    if not fonte:
        sys.exit("A carga não tem fonte cadastrada (nem fonte padrão).")
    senha = fontes.ler_senha(fonte["id"])
    base = _como_subconsulta(_embutir(carga.query, carga.params or {}))

    conexao = fontes.FonteSql(fonte, senha)
    with conexao.engine.connect() as c:
        minimo, maximo = c.execute(text(f"SELECT MIN(q.[{coluna}]), MAX(q.[{coluna}]) FROM (\n{base}\n) AS q")).one()
    conexao.fechar()
    print(f"Carga {nome} · divisão por [{coluna}] de {minimo} a {maximo}\n")

    totais = {n: rodada(fonte, senha, base, coluna, minimo, maximo, n) for n in quantidades}
    if len(set(totais.values())) == 1:
        print(f"\nOK: todas as rodadas leram as mesmas {next(iter(totais.values())):,} linhas.".replace(",", "."))
    else:
        print(f"\nATENÇÃO: totais diferentes entre as rodadas: {totais} "
              "(se a tabela recebe gravações agora, pequenas diferenças são esperadas)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Uso: python -m scripts.medir_paralelo <carga> <coluna de data ou número> [1 2 4 ...]")
    main(sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]] or [1, 2, 4])
