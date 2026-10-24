"""Mede o teto de leitura (banco + rede + driver), sem o resto do LurkQVD.

Lê a consulta de uma carga pelo driver ODBC em lotes e descarta cada lote: não monta
DataFrame, não gera QVD, não guarda nada na memória. O tempo que sobra é o do SQL Server
mandando os dados, da rede trazendo e do driver decodificando.

Uso, na raiz do projeto:
    python -m scripts.medir_leitura minha_carga
    python -m scripts.medir_leitura minha_carga 32767   (Packet Size maior)

Comparando com o tempo de extração da carga no LurkQVD:
  - parecidos  -> o limite é banco/rede/máquina; o código não é o gargalo
  - teto bem mais rápido -> o gargalo é montar a tabela em memória; aí vale otimizar o código
"""

import sys
import time

from src.lurkqvd.config import fontes
from src.lurkqvd.pipeline.estimativa import _embutir
from src.lurkqvd.repository.repositorio import Repositorio


def main(nome: str, packet_size: int | None) -> None:
    from arrow_odbc import read_arrow_batches_from_odbc

    repo = Repositorio()
    achada = repo.buscar_carga_por_nome(nome)
    if not achada:
        sys.exit(f"Carga '{nome}' não encontrada.")
    _, carga = achada
    fonte = repo.fonte_para_execucao(carga.fonte_id)
    if not fonte:
        sys.exit("A carga não tem fonte cadastrada (nem fonte padrão).")
    senha = fontes.ler_senha(fonte["id"])
    print(f"Carga {nome} · fonte {fonte['nome']} ({fonte['host']})"
          f"{f' · Packet Size {packet_size}' if packet_size else ''}\n")

    inicio = time.perf_counter()
    leitor = read_arrow_batches_from_odbc(
        query=_embutir(carga.query, carga.params or {}),
        connection_string=fontes._odbc(fonte, senha),
        batch_size=100_000,
        max_text_size=fontes.MAX_TEXTO,
        login_timeout_sec=15,
        packet_size=packet_size,
    )
    primeiro = None
    linhas = bytes_ = 0
    proximo_log = inicio + 10
    for lote in leitor:
        agora = time.perf_counter()
        if primeiro is None:
            primeiro = agora - inicio
            print(f"primeiro lote em {primeiro:.1f}s (tempo do banco preparar a consulta)")
        linhas += lote.num_rows
        bytes_ += lote.nbytes
        if agora >= proximo_log:
            seg = agora - inicio
            print(f"  {linhas:>12,} linhas · {linhas / seg:>9,.0f}/s · {bytes_ / seg / 1024**2:5.1f} MB/s".replace(",", "."))
            proximo_log = agora + 10
        del lote  # descarta: só interessa o tempo de chegar

    seg = time.perf_counter() - inicio
    print(f"\nTotal: {linhas:,} linhas em {seg:.1f}s".replace(",", "."))
    print(f"Ritmo: {linhas / seg:,.0f} linhas/s · {bytes_ / seg / 1024**2:.1f} MB/s de dados".replace(",", "."))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python -m scripts.medir_leitura <nome da carga> [packet size]")
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
