import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from base64 import b64encode
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger("lurkqvd.qlik")

# Acima disso a Qlik não aceita o envio direto (multipart numa requisição só): o arquivo sobe
# em pedaços para /temp-contents e o data file é criado/substituído apontando para ele.
LIMITE_ENVIO_DIRETO = int(os.getenv("LURKQVD_LIMITE_ENVIO_DIRETO_MB", "500")) * 1024 * 1024
TAMANHO_PEDACO = 8 * 1024 * 1024  # envio simples: leitura do arquivo em blocos de 8 MB

# Envio retomável (tus): cada PATCH leva um pedaço; se cair, só esse pedaço é reenviado.
PEDACO_RETOMAVEL = int(os.getenv("LURKQVD_PEDACO_UPLOAD_MB", "64")) * 1024 * 1024
TTL_TEMPORARIO = 6 * 3600  # validade do conteúdo temporário (padrão da Qlik: 1h, contada do início)
TUS_VERSAO = "1.0.0"
# quanto tempo o envio aguenta sem avançar nada (queda de rede, Qlik instável) antes de desistir
PACIENCIA_UPLOAD = int(os.getenv("LURKQVD_PACIENCIA_UPLOAD_MIN", "15")) * 60


@dataclass
class QlikCredentials:
    token: str


class QlikQvd:
    """Client da API REST da Qlik Cloud para gestão de data files (QVDs)."""

    def __init__(
        self,
        credentials: QlikCredentials,
        tenant: str,
        *,
        tentativas: int = 3,
        timeout: tuple[float, float] = (5, 30),
    ) -> None:
        if not tenant:
            raise RuntimeError("Qlik Cloud não configurada: informe o tenant em Configurações › Qlik Cloud.")
        self.base_url = f"https://{tenant}.qlikcloud.com/api/v1"
        self.timeout = timeout
        self._session = self._build_session(credentials.token, tentativas)

    # ------------------------------------------------------------------ #
    # Infra
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_session(token: str, tentativas: int) -> requests.Session:
        retry = Retry(
            total=tentativas,
            backoff_factor=1,  # 1s, 2s, 4s...
            status_forcelist=(429, 500, 502, 503, 504),
            # POST fica fora: repetir um upload pode duplicar o arquivo
            allowed_methods=frozenset({"GET", "PUT", "DELETE"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers.update({"Authorization": f"Bearer {token}"})
        return session

    def _get_paginated(self, url: str, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        while url:
            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()

            items.extend(body.get("data", []))
            url = body.get("links", {}).get("next", {}).get("href")
            params = None  # o href do next já traz os parâmetros
        return items

    # ------------------------------------------------------------------ #
    # Navegação
    # ------------------------------------------------------------------ #
    def list_spaces(self) -> list[dict]:
        """Lista os espaços com o connectionId da conexão DataFiles de cada um."""
        connections = self._get_paginated(f"{self.base_url}/data-files/connections")
        spaces = self._get_paginated(f"{self.base_url}/spaces", params={"limit": 100})
        spaces_by_id = {s["id"]: s for s in spaces}

        result = []
        for conn in connections:
            space = spaces_by_id.get(conn.get("spaceId"), {})
            result.append(
                {
                    "connection_id": conn["id"],
                    "space_id": conn.get("spaceId"),
                    "space_name": space.get("name", "Pessoal"),
                    "space_type": space.get("type", "personal"),
                }
            )
        return result

    def list_files(
        self,
        connection_id: str | None = None,
        folder_path: str | None = None,
    ) -> list[dict]:
        """Lista arquivos e pastas filhos diretos de uma pasta (ou da raiz) de um espaço.

        connection_id=None -> espaço pessoal.
        folder_path=None   -> raiz do espaço. Ex.: "stage/vendas".
        """
        params: dict = {
            "includeFolders": "true",
            "includeFolderStats": "true",
            "excludeSubFolders": "true",  # só filhos diretos, ideal para navegar no front
            "limit": 1000,
        }
        if connection_id:
            params["connectionId"] = connection_id
        if folder_path:
            params["folderPath"] = folder_path.strip("/")

        items = self._get_paginated(f"{self.base_url}/data-files", params=params)

        return [
            {
                "id": item["id"],
                "name": item["name"],              # caminho completo
                "base_name": item.get("baseName"),  # só o nome
                "is_folder": item.get("folder", False),
                "size": item.get("size", 0),
                "folder_path": item.get("folderPath"),
                "modified_date": item.get("modifiedDate"),
                "folder_size": (item.get("folderStats") or {}).get("aggregateFileSize"),
            }
            for item in items
        ]

    # ------------------------------------------------------------------ #
    # Pastas
    # ------------------------------------------------------------------ #
    def create_folder(self, connection_id: str | None, path: str) -> dict:
        """Cria uma pasta (e as intermediárias, se faltarem). Ex.: path="stage/vendas"."""
        payload = {"name": path.strip("/"), "folder": True}
        if connection_id:
            payload["connectionId"] = connection_id

        # multipart/form-data só com a parte "Json" (pasta não tem arquivo)
        response = self._session.post(
            f"{self.base_url}/data-files",
            files={"Json": (None, json.dumps(payload), "application/json")},
            timeout=self.timeout,
        )
        if response.status_code == 409:
            raise FileExistsError(f"Já existe um item com o nome '{path}' nesse espaço.")
        self._raise_for_status(response)
        return response.json()

    # ------------------------------------------------------------------ #
    # Arquivos grandes: envio em pedaços para /temp-contents
    # ------------------------------------------------------------------ #
    @staticmethod
    def _conferir_tamanho(arquivo: dict, local_file: str) -> dict:
        """Garante que a Qlik ficou com o arquivo inteiro: o tamanho lá tem que bater com o local."""
        local, remoto = os.path.getsize(local_file), arquivo.get("size")
        if remoto is not None and int(remoto) != local:
            raise RuntimeError(
                f"Upload incompleto: a Qlik ficou com {int(remoto):,} bytes, o QVD local tem {local:,}. "
                "Rode a carga de novo."
            )
        return arquivo

    @staticmethod
    def _grande(local_file: str) -> bool:
        return os.path.getsize(local_file) > LIMITE_ENVIO_DIRETO

    def _pedacos(self, local_file: str, ao_enviar=None):
        """Lê o arquivo de 8 em 8 MB (só um pedaço na memória por vez) e registra o progresso."""
        total = os.path.getsize(local_file)
        enviado, proximo_log = 0, 0.25
        with open(local_file, "rb") as fh:
            while bloco := fh.read(TAMANHO_PEDACO):
                enviado += len(bloco)
                if enviado / total >= proximo_log:
                    logger.info("upload %s: %d%% de %.0f MB", Path(local_file).name,
                                100 * enviado // total, total / 1024**2)
                    proximo_log += 0.25
                if ao_enviar:
                    ao_enviar(enviado, total)
                yield bloco

    # ------------------------------------------------------------------ #
    # Envio retomável (protocolo tus): /temp-contents/files
    # ------------------------------------------------------------------ #
    class _TusIndisponivel(Exception):
        """O tenant não aceitou o envio retomável; usa o envio simples."""

    def _enviar_temporario(self, local_file: str, ao_enviar=None) -> str:
        """Sobe o arquivo para a área temporária da Qlik e devolve o ID para criar/substituir o data file.

        ao_enviar(bytes_enviados, total): chamado a cada pedaço (progresso; se levantar exceção, para).
        """
        try:
            return self._enviar_retomavel(local_file, ao_enviar=ao_enviar)
        except self._TusIndisponivel as e:
            logger.warning("upload %s: envio retomável indisponível (%s); usando o envio simples",
                           Path(local_file).name, e)
            return self._enviar_temporario_simples(local_file, ao_enviar=ao_enviar)

    def _sessao_upload(self) -> requests.Session:
        """Sessão sem retry do urllib3: as repetições aqui são feitas por nós, sabendo a posição."""
        sessao = requests.Session()
        sessao.mount("https://", HTTPAdapter(max_retries=0))
        sessao.headers.update({"Authorization": self._session.headers["Authorization"],
                               "Tus-Resumable": TUS_VERSAO})
        return sessao

    def _enviar_retomavel(self, local_file: str, ao_enviar=None) -> str:
        """Envio em pedaços de 64 MB (PATCH com Upload-Offset).

        Se um pedaço falhar (conexão, timeout, 5xx, 409, 423, 429), pergunta à Qlik até onde ela
        recebeu (HEAD -> Upload-Offset) e continua dali. A Qlik recusa pedaço fora de posição,
        então não tem como pular parte do arquivo. Desiste depois de PACIENCIA_UPLOAD (15 min)
        sem nenhum avanço; cada avanço, mesmo parcial, zera a contagem.
        """
        nome = Path(local_file).name
        tamanho = os.path.getsize(local_file)
        metadados = ",".join(f"{k} {b64encode(str(v).encode()).decode()}"
                             for k, v in {"filename": nome, "ttl": TTL_TEMPORARIO}.items())
        # cada pedaço tem até 64 MB: tempo de leitura para ~0,5 MB/s no pior caso
        timeout_pedaco = (self.timeout[0], max(self.timeout[1], PEDACO_RETOMAVEL / (512 * 1024)))

        sessao = self._sessao_upload()
        try:
            try:
                r = sessao.post(f"{self.base_url}/temp-contents/files",
                                headers={"Upload-Length": str(tamanho), "Upload-Metadata": metadados},
                                timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                raise self._TusIndisponivel(f"falha ao abrir: {type(e).__name__}") from e
            if r.status_code in (404, 405, 501):
                raise self._TusIndisponivel(f"HTTP {r.status_code}")
            self._raise_for_status(r)
            local = r.headers.get("location") or r.headers.get("Location")
            if not local:
                raise self._TusIndisponivel("a Qlik não devolveu o endereço do envio")
            url = urljoin(f"{self.base_url}/temp-contents/files/", local)
            temp_id = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]

            offset, falhas, proximo_log = 0, 0, 0.25
            sem_avanco_desde = time.monotonic()
            with open(local_file, "rb") as fh:
                while offset < tamanho:
                    fh.seek(offset)
                    pedaco = fh.read(PEDACO_RETOMAVEL)
                    motivo, espera = None, 2 ** min(falhas + 1, 6)  # 4, 8, ... até 60s
                    try:
                        r = sessao.patch(url, data=pedaco, timeout=timeout_pedaco, headers={
                            "Upload-Offset": str(offset),
                            "Content-Type": "application/offset+octet-stream",
                        })
                        if r.status_code in (200, 204):
                            novo = int(r.headers.get("Upload-Offset", offset + len(pedaco)))
                            if novo <= offset:
                                raise RuntimeError(f"A Qlik não avançou o envio (offset {offset}).")
                            offset, falhas = novo, 0
                            sem_avanco_desde = time.monotonic()
                            if ao_enviar:
                                ao_enviar(offset, tamanho)
                            if offset / tamanho >= proximo_log:
                                logger.info("upload %s: %d%% de %.0f MB", nome, 100 * offset // tamanho,
                                            tamanho / 1024**2)
                                while offset / tamanho >= proximo_log:
                                    proximo_log += 0.25
                            continue
                        if r.status_code in (404, 410):
                            raise RuntimeError("O envio expirou ou sumiu na Qlik (HTTP %d). Rode a carga de novo."
                                               % r.status_code)
                        if r.status_code not in (409, 423, 429, 500, 502, 503, 504):
                            self._raise_for_status(r)
                        motivo = f"HTTP {r.status_code}"
                        if r.status_code == 429:
                            espera = int(r.headers.get("Retry-After") or espera)
                    except (requests.ConnectionError, requests.Timeout) as e:
                        motivo = type(e).__name__
                        sessao.close()
                        sessao = self._sessao_upload()  # conexão nova, sem a que caiu

                    falhas += 1
                    parado = time.monotonic() - sem_avanco_desde
                    if parado > PACIENCIA_UPLOAD:
                        raise RuntimeError(f"Upload de {nome} sem avanço há {parado / 60:.0f} min em "
                                           f"{offset / 1024**2:.0f} de {tamanho / 1024**2:.0f} MB ({motivo}).")
                    time.sleep(min(espera, 60))
                    antes, offset = offset, self._offset_na_qlik(sessao, url, offset)
                    if offset > antes:
                        falhas = 0  # a Qlik guardou parte do pedaço: houve avanço
                        sem_avanco_desde = time.monotonic()
                    logger.warning("upload %s: %s; retomando de %.0f MB (tentativa %d; desiste se ficar "
                                   "%d min sem avançar)", nome, motivo, offset / 1024**2, falhas + 1,
                                   PACIENCIA_UPLOAD // 60)
        finally:
            sessao.close()
        logger.info("upload %s: conteúdo temporário %s", nome, temp_id)
        return temp_id

    def _offset_na_qlik(self, sessao: requests.Session, url: str, atual: int) -> int:
        """Até onde a Qlik recebeu (HEAD). Se não der para perguntar agora, mantém a posição atual:
        o próximo PATCH vai confirmar (a Qlik responde 409 se a posição estiver errada)."""
        try:
            r = sessao.head(url, timeout=self.timeout)
            if r.status_code in (404, 410):
                raise RuntimeError("O envio expirou ou sumiu na Qlik. Rode a carga de novo.")
            if r.ok and r.headers.get("Upload-Offset") is not None:
                return int(r.headers["Upload-Offset"])
        except (requests.ConnectionError, requests.Timeout):
            pass
        return atual

    def _enviar_temporario_simples(self, local_file: str, tentativas: int = 3, ao_enviar=None) -> str:
        """Plano B: sobe o arquivo para /temp-contents numa requisição só (Transfer-Encoding: chunked).

        A repetição automática do urllib3 NÃO pode ser usada aqui: o gerador de pedaços não volta
        ao início, então uma repetição no meio mandaria o arquivo sem os primeiros pedaços. Por isso:
          - cada tentativa usa uma sessão nova, sem retry (e sem conexão parada que a Qlik já fechou);
          - se cair, a próxima tentativa recomeça o arquivo do byte zero, com um gerador novo.
        Repetir é seguro: um conteúdo temporário que sobrou expira sozinho na Qlik.
        """
        tamanho = os.path.getsize(local_file)
        # tempo de leitura generoso: ~1 MB/s no pior caso, nunca menos que o timeout normal
        timeout = (self.timeout[0], max(self.timeout[1], tamanho / (1024 * 1024)))
        for tentativa in range(1, tentativas + 1):
            with requests.Session() as sessao:
                sessao.mount("https://", HTTPAdapter(max_retries=0))
                sessao.headers["Authorization"] = self._session.headers["Authorization"]
                try:
                    response = sessao.post(
                        f"{self.base_url}/temp-contents",
                        params={"filename": Path(local_file).name, "ttl": TTL_TEMPORARIO},
                        data=self._pedacos(local_file, ao_enviar),
                        headers={"Content-Type": "application/octet-stream"},
                        timeout=timeout,
                    )
                except (requests.ConnectionError, requests.Timeout) as e:
                    if tentativa == tentativas:
                        raise
                    logger.warning("upload %s: conexão caiu (%s); recomeçando do início (tentativa %d de %d)",
                                   Path(local_file).name, type(e).__name__, tentativa + 1, tentativas)
                    time.sleep(2 ** tentativa)
                    continue
            if response.status_code in (429, 500, 502, 503, 504) and tentativa < tentativas:
                espera = int(response.headers.get("Retry-After") or 2 ** tentativa)
                logger.warning("upload %s: Qlik respondeu %d; recomeçando em %ds (tentativa %d de %d)",
                               Path(local_file).name, response.status_code, espera, tentativa + 1, tentativas)
                time.sleep(min(espera, 60))
                continue
            break
        self._raise_for_status(response)
        local = response.headers.get("location") or response.headers.get("Location") or ""
        temp_id = urlparse(local).path.rstrip("/").rsplit("/", 1)[-1] if local else None
        if not temp_id:  # algumas versões devolvem o ID no corpo
            temp_id = (response.json() if response.content else {}).get("id")
        if not temp_id:
            raise RuntimeError("A Qlik não devolveu o ID do conteúdo temporário.")
        logger.info("upload %s: conteúdo temporário %s", Path(local_file).name, temp_id)
        return temp_id

    # ------------------------------------------------------------------ #
    # Arquivos
    # ------------------------------------------------------------------ #
    def upload_file(self, connection_id: str | None, path: str, local_file: str, ao_enviar=None) -> dict:
        """Cria um novo data file. path = caminho na Qlik, ex.: "stage/vendas/fato_vendas.qvd".

        Até 500 MB vai numa requisição só; acima disso, em pedaços via /temp-contents.
        Se a conexão cair, repete com segurança: se a tentativa anterior já tinha criado o arquivo
        (409), confere pelo caminho e pelo tamanho em vez de duplicar.
        Se já existir, use replace_file com o ID guardado no Postgres.
        """
        payload = {"name": path.strip("/")}
        if connection_id:
            payload["connectionId"] = connection_id

        if self._grande(local_file):
            payload["tempContentFileId"] = self._enviar_temporario(local_file, ao_enviar)
        resposta = self._pedido_final(
            "POST", f"{self.base_url}/data-files", payload,
            None if "tempContentFileId" in payload else local_file,
            achar_criado=lambda: self._achar_por_caminho(connection_id, path),
            tamanho=os.path.getsize(local_file),
        )
        if isinstance(resposta, dict):  # a tentativa anterior criou; só a resposta tinha se perdido
            return resposta
        if resposta.status_code == 409:
            raise FileExistsError(f"Já existe '{path}' nesse espaço. Use replace_file.")
        self._raise_for_status(resposta)
        return self._conferir_tamanho(resposta.json(), local_file)

    def _pedido_final(self, metodo: str, url: str, payload: dict, arquivo: str | None, *,
                      achar_criado=None, tamanho: int | None = None, tentativas: int = 6):
        """Pedido que cria/substitui o data file (com o arquivo junto, ou só o JSON apontando para o
        conteúdo temporário).

        - Conexão nova a cada tentativa: a do client pode ter ficado parada durante a extração ou o
          envio em pedaços, e a Qlik fecha conexões paradas (foi o que derrubou uma carga de 4 GB
          com o conteúdo já todo enviado).
        - Se a conexão cair, tenta de novo. Num POST repetido, 409 pode ser o arquivo que a tentativa
          anterior criou (a resposta é que se perdeu): confere pelo caminho e pelo tamanho.
        Retorna a resposta ou, nesse último caso, o dict do arquivo já criado.
        """
        for tentativa in range(1, tentativas + 1):
            self._session.close()  # descarta conexões paradas do pool: a próxima abre uma nova
            fh = open(arquivo, "rb") if arquivo else None
            try:
                files = {"Json": (None, json.dumps(payload), "application/json")}
                if fh:
                    files = {"File": (Path(arquivo).name, fh, "application/octet-stream"), **files}
                resposta = self._session.request(metodo, url, files=files, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                if tentativa == tentativas:
                    raise
                logger.warning("%s %s: conexão caiu (%s); tentando de novo (%d de %d)",
                               metodo, url.rsplit("/api/v1", 1)[-1], type(e).__name__, tentativa + 1, tentativas)
                time.sleep(min(2 ** tentativa, 30))
                continue
            finally:
                if fh:
                    fh.close()
            if resposta.status_code == 409 and tentativa > 1 and achar_criado:
                criado = achar_criado()
                if criado and tamanho is not None and int(criado.get("size") or -1) == tamanho:
                    logger.info("%s: o arquivo já tinha sido criado pela tentativa anterior", criado.get("name"))
                    return criado
            if resposta.status_code in (429, 500, 502, 503, 504) and tentativa < tentativas:
                time.sleep(min(int(resposta.headers.get("Retry-After") or 2 ** tentativa), 60))
                continue
            return resposta
        return resposta

    def _achar_por_caminho(self, connection_id: str | None, path: str) -> dict | None:
        pasta, _, nome = path.strip("/").rpartition("/")
        for item in self.list_files(connection_id, pasta or None):
            if not item["is_folder"] and item["base_name"] == nome:
                return item
        return None

    def get_file(self, file_id: str) -> dict:
        response = self._session.get(f"{self.base_url}/data-files/{file_id}", timeout=self.timeout)
        if response.status_code == 404:
            raise FileNotFoundError(f"Data file {file_id} não existe mais na Qlik.")
        self._raise_for_status(response)
        return response.json()

    def replace_file(
        self,
        file_id: str,
        connection_id: str | None,
        local_file: str,
        path: str | None = None,
        ao_enviar=None,
    ) -> dict:
        """Substitui o conteúdo de um data file existente, mantendo o mesmo ID.

        Cuidados do PUT da Qlik:
        - sem "name", ela usa o nome do arquivo enviado e RENOMEIA/move para a raiz;
        - sem "connectionId", ela entende espaço pessoal e MOVE o arquivo para lá.
        Por isso sempre reenviamos os dois. path=None mantém o caminho atual.
        """
        name = path.strip("/") if path else self.get_file(file_id)["name"]
        payload = {"name": name}
        if connection_id:
            payload["connectionId"] = connection_id

        if self._grande(local_file):
            # acima de 500 MB: conteúdo em pedaços; o PUT leva só o JSON (pequeno, pode repetir)
            payload["tempContentFileId"] = self._enviar_temporario(local_file, ao_enviar)
        resposta = self._pedido_final(
            "PUT", f"{self.base_url}/data-files/{file_id}", payload,
            None if "tempContentFileId" in payload else local_file,
        )
        if resposta.status_code == 404:
            raise FileNotFoundError(f"Data file {file_id} não existe mais na Qlik.")
        self._raise_for_status(resposta)
        return self._conferir_tamanho(resposta.json(), local_file)

    # ------------------------------------------------------------------ #
    # Apps: busca e reload
    # ------------------------------------------------------------------ #
    @staticmethod
    def _app(item: dict) -> dict:
        abrir = ((item.get("links") or {}).get("open") or {}).get("href")
        return {
            "id": item.get("resourceId"),          # ID do app (o que vai no reload)
            "nome": item.get("name"),
            "espaco_id": item.get("spaceId"),
            "link": abrir,
            "atualizado_em": item.get("updatedAt"),
        }

    def buscar_apps(self, busca: str | None = None, limite: int = 30) -> list[dict]:
        """Apps que a API key enxerga, por nome (para o seletor da tela)."""
        params = {"resourceType": "app", "limit": max(1, min(limite, 100))}
        if busca:
            params["query"] = busca
        r = self._session.get(f"{self.base_url}/items", params=params, timeout=self.timeout)
        self._raise_for_status(r)
        return [self._app(i) for i in r.json().get("data", [])]

    def obter_app(self, app_id: str) -> dict | None:
        """O app pelo ID, ou None se não existir ou a API key não tiver acesso."""
        r = self._session.get(f"{self.base_url}/items",
                              params={"resourceType": "app", "resourceId": app_id, "limit": 1}, timeout=self.timeout)
        if r.status_code in (403, 404):
            return None
        self._raise_for_status(r)
        dados = r.json().get("data", [])
        return self._app(dados[0]) if dados else None

    def recarregar_app(self, app_id: str) -> dict:
        """Dispara o reload do app (POST /reloads). Devolve o registro do reload (id, status...).

        Sem repetição automática (é POST): um 429 da Qlik aqui significa que já existe um reload
        pendente desse app, e isso sobe como erro para quem chamou decidir.
        """
        r = self._pedido_json("POST", f"{self.base_url}/reloads", {"appId": app_id, "partial": False})
        if r.status_code == 429:
            raise RuntimeError("A Qlik já tem um reload pendente para esse app.")
        if r.status_code == 403:
            raise PermissionError("A API key não tem permissão para recarregar esse app (ou a cota de reloads acabou).")
        self._raise_for_status(r)
        return r.json()

    def status_reload(self, reload_id: str) -> dict:
        r = self._session.get(f"{self.base_url}/reloads/{reload_id}", timeout=self.timeout)
        self._raise_for_status(r)
        return r.json()

    def cancelar_reload(self, reload_id: str) -> bool:
        """True se a Qlik aceitou cancelar; False se o reload já não podia ser cancelado (409/404)."""
        r = self._pedido_json("POST", f"{self.base_url}/reloads/{reload_id}/actions/cancel", None)
        if r.status_code in (404, 409):
            return False
        self._raise_for_status(r)
        return True

    def _pedido_json(self, metodo: str, url: str, corpo: dict | None, tentativas: int = 3):
        """Pedido JSON pequeno com conexão nova e repetição só quando a conexão cai ANTES de a Qlik
        responder (ConnectTimeout/ConnectionError ao abrir)."""
        for tentativa in range(1, tentativas + 1):
            self._session.close()
            try:
                return self._session.request(metodo, url, json=corpo, timeout=self.timeout)
            except requests.ConnectTimeout:
                if tentativa == tentativas:
                    raise
                time.sleep(2 ** tentativa)

    def delete_file(self, file_id: str) -> bool:
        """Apaga um data file ou pasta.

        ATENÇÃO: apagar uma pasta apaga tudo dentro dela, recursivamente.
        Retorna False se o item já não existia (útil porque o DELETE tem retry:
        se a 1ª tentativa apagou e a resposta se perdeu, a 2ª devolve 404).
        """
        response = self._session.delete(f"{self.base_url}/data-files/{file_id}", timeout=self.timeout)
        if response.status_code == 404:
            return False
        self._raise_for_status(response)
        return True

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        """Igual ao raise_for_status, mas inclui o erro detalhado da Qlik (códigos DF-xxx)."""
        if response.ok:
            return
        try:
            detail = response.json().get("errors", response.text)
        except ValueError:
            detail = response.text
        raise requests.HTTPError(
            f"{response.status_code} em {response.request.method} {response.url}: {detail}",
            response=response,
        )
