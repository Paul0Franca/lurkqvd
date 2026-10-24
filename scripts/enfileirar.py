"""Enfileira uma carga pelo nome (faz o papel que a API vai ter).

Uso, na raiz do projeto:
    python -m scripts.enfileirar fct_vendas_item
"""

import sys

from src.lurkqvd.repository.repositorio import CargaJaEmExecucao, Repositorio


def main() -> None:
    nome = sys.argv[1] if len(sys.argv) > 1 else "fct_vendas_item"
    repo = Repositorio()

    encontrada = repo.buscar_carga_por_nome(nome)
    if not encontrada:
        sys.exit(f"Carga '{nome}' não cadastrada.")

    try:
        execucao_id = repo.enfileirar(encontrada[0], origem="manual")
        print(f"Enfileirada: execução {execucao_id} da carga '{nome}'")
    except CargaJaEmExecucao as e:
        print(e)


if __name__ == "__main__":
    main()