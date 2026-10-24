"""Compara os motores de leitura numa carga real, sem publicar nada.

Uso, na raiz do projeto:
    python -m scripts.comparar_motores fct_vendas_item
    python -m scripts.comparar_motores fct_vendas_item odbc arrow-odbc     (só alguns motores)

Para cada motor mostra o tempo, as linhas por segundo e se o DataFrame, já preparado para o
QVD, é IDÊNTICO ao do ODBC (mesmas colunas, tipos e valores). Só troque o motor de uma fonte
para um que deu "idêntico".

Antes de medir, faz um aquecimento (COUNT(*) da consulta) para o cache do SQL Server não
favorecer o motor que rodar por último.
"""

import sys
import time

import polars as pl
from sqlalchemy import text

from src.lurkqvd.config import fontes
from src.lurkqvd.pipeline.estimativa import _como_subconsulta
from src.lurkqvd.pipeline.gerador_qvd import GeradorQvd
from src.lurkqvd.repository.repositorio import Repositorio

PACOTE_GRANDE = 32767  # maior Packet Size aceito pelo SQL Server

MOTORES = {
    "odbc": lambda c, q, p: c.query_odbc(q, p),
    "arrow-odbc": lambda c, q, p: c.query_arrow_odbc(q, p),
    "arrow-odbc+pacote": None,  # arrow-odbc com Packet Size 32767 (montado abaixo)
    "connectorx": lambda c, q, p: c.query_connectorx(q, p),
}


def _arrow_pacote(c, q, p):
    antes, c.packet_size = c.packet_size, PACOTE_GRANDE
    try:
        return c.query_arrow_odbc(q, p)
    finally:
        c.packet_size = antes


MOTORES["arrow-odbc+pacote"] = _arrow_pacote


def diferencas(base: pl.DataFrame, outro: pl.DataFrame) -> list[str]:
    if base.columns != outro.columns:
        return [f"colunas diferentes: {set(base.columns) ^ set(outro.columns)}"]
    problemas = [f"tipo de {c}: ODBC {base.schema[c]} x {outro.schema[c]}"
                 for c in base.columns if base.schema[c] != outro.schema[c]]
    if base.height != outro.height:
        problemas.append(f"linhas: ODBC {base.height} x {outro.height}")
    if problemas:
        return problemas
    # mesma ordem não é garantida sem ORDER BY: compara ordenando por todas as colunas
    a = base.sort(base.columns, nulls_last=True)
    b = outro.sort(outro.columns, nulls_last=True)
    for c in base.columns:
        if a.schema[c] == pl.Float64:
            iguais = ((a[c] - b[c]).abs().fill_null(0) < 1e-9).all() and a[c].null_count() == b[c].null_count()
        else:
            iguais = a[c].equals(b[c])
        if not iguais:
            exemplo = a.select(c).with_columns(b[c].alias("outro")).filter(pl.col(c).ne_missing(pl.col("outro"))).head(3)
            problemas.append(f"valores de {c} diferem, ex.:\n{exemplo}")
    return problemas


def main(nome: str, escolhidos: list[str]) -> None:
    repo = Repositorio()
    achada = repo.buscar_carga_por_nome(nome)
    if not achada:
        sys.exit(f"Carga '{nome}' não encontrada.")
    carga_id, carga = achada
    fonte = repo.fonte_para_execucao(carga.fonte_id)
    if not fonte:
        sys.exit("A carga não tem fonte cadastrada (nem fonte padrão). Cadastre em Configurações › Fontes de dados.")
    conexao = fontes.FonteSql(fonte, fontes.ler_senha(fonte["id"]))
    print(f"Carga {nome} (id {carga_id}) · fonte {fonte['nome']}")

    t = time.perf_counter()
    with conexao.engine.connect() as c:
        linhas = c.execute(text(f"SELECT COUNT(*) FROM (\n{_como_subconsulta(carga.query)}\n) AS q"),
                           carga.params or {}).scalar()
    print(f"aquecimento: {linhas:,} linhas em {time.perf_counter() - t:.1f}s\n".replace(",", "."))

    base, resultados = None, []
    for motor in ["odbc"] + [m for m in escolhidos if m != "odbc"]:
        t = time.perf_counter()
        try:
            df = GeradorQvd.preparar_para_qvd(MOTORES[motor](conexao, carga.query, carga.params))
        except Exception as e:
            print(f"{motor:<18} ERRO: {type(e).__name__}: {str(e)[:200]}")
            continue
        seg = time.perf_counter() - t
        if base is None:
            base, t_base = df, seg
            veredito = "(referência)"
        else:
            problemas = diferencas(base, df)
            veredito = "IDÊNTICO" if not problemas else "DIFERENTE"
        print(f"{motor:<18} {seg:6.1f}s  {df.height / seg:>9,.0f} linhas/s  {t_base / seg:4.1f}x  {veredito}".replace(",", "."))
        if veredito == "DIFERENTE":
            for p in problemas:
                print("     -", p)
        resultados.append((motor, seg, veredito))
        del df

    validos = [r for r in resultados if r[2] != "DIFERENTE"]
    if validos:
        melhor = min(validos, key=lambda r: r[1])
        print(f"\nMais rápido com resultado idêntico: {melhor[0]} ({melhor[1]:.1f}s)")
    conexao.fechar()


if __name__ == "__main__":
    args = sys.argv[1:]
    nome = args[0] if args else "fct_vendas_item"
    escolhidos = [m for m in args[1:] if m in MOTORES] or list(MOTORES)
    main(nome, escolhidos)
