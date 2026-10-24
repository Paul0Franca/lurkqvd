"""Publica um conteúdo temporário que já está na Qlik (para quando a carga falhou só no último passo).

O envio em pedaços guarda o arquivo numa área temporária da Qlik por 6 horas. Se a carga caiu
depois disso, dá para criar/substituir o data file com esse conteúdo, sem reler o banco.

Uso, na raiz do projeto:
    python -m scripts.publicar_temporario minha_carga <id-do-conteudo-temporario>

O ID aparece no log do worker: "conteúdo temporário <id>".
"""

import sys

from src.lurkqvd.clients.qlik import QlikCredentials, QlikQvd
from src.lurkqvd.config import qlik_conexao
from src.lurkqvd.repository.repositorio import Repositorio


def main(nome: str, temp_id: str) -> None:
    repo = Repositorio()
    achada = repo.buscar_carga_por_nome(nome)
    if not achada:
        sys.exit(f"Carga '{nome}' não encontrada.")
    _, carga = achada
    tenant = repo.config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
    qlik = QlikQvd(QlikCredentials(token=qlik_conexao.ler_token()), tenant, timeout=(10, 120))

    r = qlik._session.get(f"{qlik.base_url}/temp-contents/{temp_id}/details", timeout=qlik.timeout)
    if r.status_code in (404, 410):
        sys.exit("Esse conteúdo temporário não existe mais (expirou). Rode a carga de novo.")
    qlik._raise_for_status(r)
    det = r.json()
    tamanho = int(det.get("Size") or det.get("size") or 0)
    print(f"Conteúdo temporário {temp_id}: {tamanho / 1024**2:,.1f} MB, expira em {det.get('Expires') or det.get('expires')}")

    caminho = carga.qlik_path.strip("/")
    payload = {"name": caminho, "tempContentFileId": temp_id}
    if carga.connection_id:
        payload["connectionId"] = carga.connection_id
    existente = qlik._achar_por_caminho(carga.connection_id, caminho)
    if existente:
        print(f"Substituindo {caminho} (ID {existente['id']})...")
        resposta = qlik._pedido_final("PUT", f"{qlik.base_url}/data-files/{existente['id']}", payload, None)
    else:
        print(f"Criando {caminho}...")
        resposta = qlik._pedido_final("POST", f"{qlik.base_url}/data-files", payload, None,
                                      achar_criado=lambda: qlik._achar_por_caminho(carga.connection_id, caminho),
                                      tamanho=tamanho)
    info = resposta if isinstance(resposta, dict) else (qlik._raise_for_status(resposta) or resposta.json())
    if tamanho and int(info.get("size") or -1) != tamanho:
        sys.exit(f"ATENÇÃO: a Qlik ficou com {info.get('size')} bytes, o conteúdo tinha {tamanho}.")
    print(f"OK: {caminho} publicado na Qlik (ID {info['id']}, {int(info['size']) / 1024**2:,.1f} MB).")
    print("A execução continua marcada como erro no LurkQVD; a próxima execução da carga acha o arquivo pelo nome.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Uso: python -m scripts.publicar_temporario <carga> <id do conteúdo temporário>")
    main(sys.argv[1], sys.argv[2])
