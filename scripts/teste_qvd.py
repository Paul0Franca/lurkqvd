import logging

from src.lurkqvd.clients.qlik import QlikCredentials, QlikQvd
from src.lurkqvd.config import fontes, qlik_conexao
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, GeradorQvd


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

    gerador = GeradorQvd(
        db=_fonte_padrao(),
        qlik=QlikQvd(QlikCredentials(qlik_conexao.ler_token()), _tenant(), timeout=(10, 900)),
    )

    carga = CargaQvd(
        nome="fct_vendas_item",
        query="SELECT * FROM marts.fct_vendas_item",
        qlik_path="lurkqvd_teste/stage/fct_vendas_item.qvd",
        connection_id=None,  # espaço pessoal, por enquanto
    )

    r = gerador.executar(carga)
    print(r)
    print(f"total: {r.seg_total:.1f}s")


if __name__ == "__main__":
    main()