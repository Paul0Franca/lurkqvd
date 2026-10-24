"""Mede a leitura antecipada numa carga real: gera o QVD com e sem antecipação, sem publicar nada.

Para cada modo (LURKQVD_LOTES_ANTECIPADOS), roda a leitura e a geração completas do gerador e
apaga o QVD no fim. Mostra o tempo de extração e quanto dele foi gravando os lotes no QVD: é
esse o tempo que a antecipação consegue esconder atrás da leitura do banco.

Uso, na raiz do projeto:
    python -m scripts.medir_antecipacao fct_vendas_item
    python -m scripts.medir_antecipacao fct_vendas_item 2 0 2     (modos e ordem; padrão: 0 2)

O cache do SQL Server favorece quem roda depois: rode nas duas ordens (ou "0 2 0") antes de concluir.
"""

import logging
import sys
import time
import uuid

from src.lurkqvd.config import fontes
from src.lurkqvd.pipeline import gerador_qvd, qvd_fluxo
from src.lurkqvd.pipeline.gerador_qvd import GeradorQvd
from src.lurkqvd.repository.repositorio import Repositorio


def main(nome: str, modos: list[int]) -> None:
    repo = Repositorio()
    achada = repo.buscar_carga_por_nome(nome)
    if not achada:
        sys.exit(f"Carga '{nome}' não encontrada.")
    _, carga = achada
    fonte = repo.fonte_para_execucao(carga.fonte_id)
    if not fonte:
        sys.exit("A carga não tem fonte e não há fonte padrão.")
    db = fontes.FonteSql(fonte, fontes.ler_senha(fonte["id"]))
    print(f"carga {nome} · fonte {fonte['nome']} · motor {db.motor}")

    # soma o tempo gasto gravando os lotes (adicionar), que hoje entra no tempo de extração
    original = qvd_fluxo.EscritorQvdFluxo.adicionar
    gravando = [0.0]

    def adicionar_medindo(self, lote):
        t = time.perf_counter()
        original(self, lote)
        gravando[0] += time.perf_counter() - t

    qvd_fluxo.EscritorQvdFluxo.adicionar = adicionar_medindo

    gerador = GeradorQvd(db=None, qlik=None, work_dir="tmp_qvd/medicao")
    resultados = []
    try:
        for modo in modos:
            gerador_qvd.LOTES_ANTECIPADOS = modo
            gravando[0] = 0.0
            local = gerador.work_dir / f"{carga.nome}_{uuid.uuid4().hex[:8]}.qvd"
            try:
                m = gerador._gerar(carga, db, local, lambda fase, **d: None, validar=True)
            finally:
                local.unlink(missing_ok=True)
            resultados.append((modo, m, gravando[0]))
            print(f"  antecipados={modo}: extração {m['seg_extracao']:.1f}s (gravando lotes {gravando[0]:.1f}s) · "
                  f"geração {m['seg_geracao']:.1f}s · {m['linhas'] / m['seg_extracao']:,.0f} linhas/s")
    finally:
        db.fechar()

    print("\nresumo (extração):")
    for modo, m, g in resultados:
        print(f"  antecipados={modo}: {m['seg_extracao']:8.1f}s   gravando lotes {g:7.1f}s")
    print("Sem antecipação, extração ≈ banco + gravação. Com ela, o ganho máximo é o tempo gravando lotes.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], [int(x) for x in sys.argv[2:]] or [0, 2])
