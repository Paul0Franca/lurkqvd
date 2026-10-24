"""Teste de ponta a ponta com o Postgres: cadastra, enfileira, executa e grava o histórico.

Simula o que o worker vai fazer, só que uma vez e no próprio script.
"""

import logging

from src.lurkqvd.clients.qlik import QlikCredentials, QlikQvd
from src.lurkqvd.config import fontes, qlik_conexao
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, GeradorQvd
from src.lurkqvd.repository.repositorio import Repositorio


def _tenant() -> str:
    from src.lurkqvd.repository.repositorio import Repositorio

    return Repositorio().config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]


def _fonte_padrao():
    """Conexão da fonte padrão (Configurações › Fontes de dados)."""
    from src.lurkqvd.repository.repositorio import Repositorio

    fonte = Repositorio().fonte_para_execucao(None)
    if not fonte:
        raise SystemExit("Cadastre uma fonte de dados padrão antes.")
    return fontes.FonteSql(fonte, fontes.ler_senha(fonte["id"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    repo = Repositorio()
    qlik = QlikQvd(QlikCredentials(qlik_conexao.ler_token()), _tenant(), timeout=(10, 900))

    # 1) cache de espaços
    print("espaços sincronizados:", repo.sincronizar_espacos(qlik.list_spaces()))

    # 2) cadastra a carga (só na 1ª vez)
    existente = repo.buscar_carga_por_nome("fct_vendas_item")
    if existente:
        carga_id = existente[0]
    else:
        carga_id = repo.criar_carga(
            CargaQvd(
                nome="fct_vendas_item",
                query="SELECT * FROM marts.fct_vendas_item",
                qlik_path="lurkqvd_teste/stage/fct_vendas_item.qvd",
                connection_id=None,  # espaço pessoal, por enquanto
            )
        )
    print("carga_id:", carga_id)

    # 3) enfileira (como a API vai fazer)
    print("execução enfileirada:", repo.enfileirar(carga_id, origem="manual"))

    # 4) pega da fila e executa (como o worker vai fazer)
    proxima = repo.pegar_proxima()
    assert proxima, "fila vazia?"
    execucao_id, carga_id, carga = proxima

    gerador = GeradorQvd(db=_fonte_padrao(), qlik=qlik)
    try:
        resultado = gerador.executar(carga)
        repo.finalizar_sucesso(execucao_id, carga_id, resultado)
    except Exception as e:
        repo.finalizar_erro(execucao_id, f"{type(e).__name__}: {e}")
        raise

    # 5) histórico
    for h in repo.historico(carga_id, limite=5):
        print(h["id"], h["status"], h["linhas"], h["tamanho_bytes"], h["seg_extracao"], h["erro"])


if __name__ == "__main__":
    main()