"""Mede tempo e memória do escritor de QVD (qvd_fluxo) com uma tabela sintética, sem banco nem Qlik.

O perfil imita uma tabela de vendas larga: colunas de texto únicas por linha (ids), colunas com muitos
distintos (documentos, pedidos), decimais com centenas de milhares de valores e dezenas de colunas com
poucos valores. Os lotes são gerados aos poucos, como chegariam do banco.

    python -m scripts.medir_escritor                  # 2 milhões de linhas
    python -m scripts.medir_escritor 5000000 --manter # mais linhas; --manter guarda o QVD
    python -m scripts.medir_escritor --pasta /tmp/x   # temporários e QVD em outra pasta (padrão tmp_qvd/)

Mostra o pico de memória do processo (RSS) e o tempo de cada fase. Rodar num processo novo: o pico conta
desde o início do processo.
"""

import argparse
import threading
import time
from pathlib import Path

import numpy as np
import polars as pl
import psutil

from src.lurkqvd.pipeline.qvd_fluxo import EscritorQvdFluxo

LOTE = 100_000


def lote(ini: int, n: int, total: int) -> pl.DataFrame:
    i = np.arange(ini, ini + n, dtype=np.int64)
    rnd = np.random.default_rng(ini)

    def embaralhado(fracao: float, semente: int) -> pl.Series:
        # valor repetido a cada ~1/fracao linhas, em ordem não sequencial
        return pl.Series(((i * 2654435761 + semente * 97) % max(int(total * fracao), 1)))

    def texto(nome: str, s: pl.Series, prefixo: str, largura: int) -> pl.Series:
        return (pl.lit(prefixo) + s.cast(pl.String).str.zfill(largura)).alias(nome)

    df = pl.DataFrame({"_": i}).select(
        texto("ID_LINHA", pl.Series(i), "LJV-0001-0000-", 18),
        texto("CODIGO_DOCITEM", pl.Series(i), "DOCITEM|0001|2024|0000000|", 24),
        *[texto(f"CODIGO_{k}", embaralhado(0.42, k), f"C{k}|", 10) for k in range(4)],
        *[texto(f"PEDIDO_{k}", embaralhado(0.12, 10 + k), "P", 9) for k in range(8)],
        *[pl.Series(f"VALOR_{k}", (embaralhado(0.009, 20 + k) * 0.37).round(2)) for k in range(10)],
        *[pl.Series(f"DATA_{k}", embaralhado(0.0002, 30 + k).cast(pl.Int32).cast(pl.Date)) for k in range(4)],
        *[texto(f"POUCOS_{k}", embaralhado(0.00001 * (k + 1), 40 + k), "cat ", 3) for k in range(30)],
        *[pl.Series(f"QTDE_{k}", embaralhado(0.000002 * (k + 1), 70 + k)) for k in range(16)],
    )
    # um pouco de nulo em algumas colunas
    nulos = pl.Series(rnd.random(n) < 0.05)
    return df.with_columns(pl.when(nulos).then(None).otherwise(pl.col(c)).alias(c)
                           for c in ("PEDIDO_0", "VALOR_0", "CODIGO_3"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("linhas", nargs="?", type=int, default=2_000_000)
    ap.add_argument("--manter", action="store_true")
    ap.add_argument("--pasta", default="tmp_qvd")
    a = ap.parse_args()

    proc = psutil.Process()
    pico = [proc.memory_info().rss]
    fim = threading.Event()

    def amostrar():
        while not fim.wait(0.05):
            pico[0] = max(pico[0], proc.memory_info().rss)

    threading.Thread(target=amostrar, daemon=True).start()
    destino = Path(a.pasta) / "medir_escritor.qvd"
    destino.parent.mkdir(parents=True, exist_ok=True)
    inicio_rss = proc.memory_info().rss
    t0 = time.perf_counter()
    t_gerar = 0.0
    with EscritorQvdFluxo(destino, "medir", dir_temp=destino.parent) as esc:
        for ini in range(0, a.linhas, LOTE):
            tg = time.perf_counter()
            df = lote(ini, min(LOTE, a.linhas - ini), a.linhas)
            t_gerar += time.perf_counter() - tg
            esc.adicionar(df)
        t1 = time.perf_counter()
        pico_leitura = pico[0]
        info = esc.finalizar()
        t2 = time.perf_counter()
    fim.set()
    mb = 1024**2
    print(f"linhas {info['linhas']:,} · colunas {info['colunas']} · QVD {info['bytes'] / mb:,.0f} MB")
    print(f"leitura  {t1 - t0 - t_gerar:7.1f}s (sem os {t_gerar:.1f}s gerando dados) · pico {pico_leitura / mb:,.0f} MB")
    print(f"montagem {t2 - t1:7.1f}s · pico total {pico[0] / mb:,.0f} MB (processo começou com {inicio_rss / mb:,.0f} MB)")
    if not a.manter:
        destino.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
