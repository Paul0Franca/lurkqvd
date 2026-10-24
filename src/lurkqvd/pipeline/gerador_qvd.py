"""Componente de geração de QVD: extrai do SQL Server, gera o QVD e sobe na Qlik Cloud.

É o núcleo reaproveitado por quem dispara cargas (script, Airflow, worker, API):
quem chama monta uma CargaQvd e recebe um ResultadoCarga com as métricas.
"""

import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from src.lurkqvd.clients.qlik import QlikQvd
from src.lurkqvd.pipeline import memoria
from src.lurkqvd.pipeline.qvd_fluxo import EscritorQvdFluxo, conferir_arquivo

logger = logging.getLogger(__name__)

# por quanto tempo um QVD guardado (envio que falhou) pode ser reenviado em vez de reler o banco
VALIDADE_PENDENTE_H = int(os.getenv("LURKQVD_VALIDADE_PENDENTE_H", "12"))
# lotes lidos à frente enquanto o anterior vira QVD (0 = lê e grava em sequência, sem thread)
LOTES_ANTECIPADOS = int(os.getenv("LURKQVD_LOTES_ANTECIPADOS", "2"))


@dataclass
class CargaQvd:
    """Definição de uma carga. No futuro, vem da tabela de metadados no Postgres."""

    nome: str                       # identificador legível, ex.: "fct_vendas_item"
    query: str                      # SELECT de origem no SQL Server
    qlik_path: str                  # caminho na Qlik, ex.: "dwh/vendas/fct_vendas_item.qvd"
    connection_id: str | None       # conexão DataFiles do espaço (None = pessoal)
    file_id: str | None = None      # ID do data file na Qlik, se já existir
    params: dict = field(default_factory=dict)  # parâmetros da query
    fonte_id: int | None = None     # fonte de dados (None = a padrão)


@dataclass
class ResultadoCarga:
    nome: str
    file_id: str
    criado: bool                    # True = upload novo, False = substituição
    linhas: int
    colunas: int
    tamanho_bytes: int
    seg_extracao: float
    seg_geracao: float
    seg_upload: float
    composicao: dict | None = None  # peso de cada coluna no QVD (medido nesta execução)

    @property
    def seg_total(self) -> float:
        return self.seg_extracao + self.seg_geracao + self.seg_upload


class GeradorQvd:
    def __init__(self, db, qlik: QlikQvd, work_dir: str | Path = "tmp_qvd") -> None:
        """db: conexão padrão (FonteSql) para quando executar() não recebe uma; None = sempre informar."""
        self.db = db
        self.qlik = qlik
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def executar(self, carga: CargaQvd, *, validar: bool = True, db=None, progresso=None) -> ResultadoCarga:
        """Roda o ciclo completo de uma carga. Levanta exceção se qualquer etapa falhar.

        O QVD é gerado EM FLUXO (qvd_fluxo): cada lote lido vai direto para o gerador e sai da
        memória; o que fica guardado são só os valores distintos de cada coluna. Assim a memória
        não cresce com o número de linhas.

        Se o ENVIO falhar de vez (rede, Qlik fora do ar), o QVD gerado fica guardado em
        <work_dir>/pendentes: a próxima execução da mesma carga, se a consulta não mudou e o
        arquivo tem menos de VALIDADE_PENDENTE_H horas, pula a leitura e só reenvia.

        db: conexão da fonte da carga (com iter_lotes ou, ao menos, query_pl). Sem ela, a do gerador.
        progresso(fase, **dados): avisado a cada etapa e durante leitura/montagem/envio. Se levantar
        exceção (ex.: cancelamento), a carga para ali; o QVD na Qlik só muda no último passo.
        """
        db = db or self.db
        if db is None:
            raise RuntimeError("Nenhuma fonte de dados para esta carga. Cadastre uma em Configurações › Fontes de dados.")
        avisar = progresso or (lambda fase, **dados: None)
        logger.info("[%s] iniciando", carga.nome)

        guardado = self._pendente(carga)
        if guardado:
            local, gerado = guardado
            logger.info("[%s] reaproveitando o QVD gerado em %s (o envio anterior falhou); só reenvia",
                        carga.nome, gerado["gerado_em"])
            return self._publicar(carga, local, gerado, avisar, reaproveitado=True)

        local = self.work_dir / f"{carga.nome}_{uuid.uuid4().hex[:8]}.qvd"
        try:
            gerado = self._gerar(carga, db, local, avisar, validar)
            return self._publicar(carga, local, gerado, avisar, reaproveitado=False)
        finally:
            local.unlink(missing_ok=True)  # não deixa QVD temporário no disco (o guardado já foi movido)

    def _gerar(self, carga: CargaQvd, db, local: Path, avisar, validar: bool) -> dict:
        """Lê a consulta em lotes e escreve o QVD em `local`. Devolve as métricas da geração."""
        escritor = EscritorQvdFluxo(local, carga.nome, dir_temp=self.work_dir)
        try:
            t0 = time.perf_counter()
            avisar("lendo", linhas=0, linhas_previstas=self._linhas_previstas(db, carga))
            lidas, colunas, bytes_lidos = 0, 0, 0
            with closing(self._lotes_antecipados(db, carga)) as lotes:
                for lote in lotes:
                    bytes_lidos += lote.estimated_size()  # dados já decodificados (≈ o que veio do banco)
                    escritor.adicionar(lote)
                    lidas += lote.height
                    colunas = lote.width
                    seg = time.perf_counter() - t0
                    avisar("lendo", linhas=lidas, linhas_por_seg=round(lidas / seg) if seg > 0 else None,
                           bytes_lidos=bytes_lidos, mb_por_seg=round(bytes_lidos / seg / 1024**2, 1) if seg > 0 else None)
                    memoria.conferir(carga.nome)
                    del lote
            t1 = time.perf_counter()
            logger.info("[%s] extração (%s): (%s, %s) em %.1fs · %.0f MB · %.1f MB/s", carga.nome,
                        getattr(db, "ultimo_motor", None) or "odbc", lidas, colunas, t1 - t0,
                        bytes_lidos / 1024**2, bytes_lidos / max(t1 - t0, 1e-9) / 1024**2)

            if lidas == 0:
                raise ValueError(f"[{carga.nome}] a query não retornou linhas; QVD não gerado.")

            avisar("gerando", linhas=lidas, montagem_pct=0)

            def ao_montar(feito: int, total: int) -> None:
                avisar("gerando", linhas=lidas, montagem_pct=round(100 * feito / total) if total else None)
                memoria.conferir(carga.nome)

            info = escritor.finalizar(ao_progredir=ao_montar)
            if validar:
                conferir_arquivo(local, lidas)
            t2 = time.perf_counter()
            total = local.stat().st_size
            logger.info("[%s] QVD: %.1f MB em %.1fs", carga.nome, total / 1024**2, t2 - t1)
            return {
                "linhas": lidas,
                "colunas": info["colunas"],
                "seg_extracao": t1 - t0,
                "seg_geracao": t2 - t1,
                "composicao": self._medir_composicao(carga, info, total),
            }
        finally:
            escritor.descartar()  # apaga os temporários do gerador

    def _publicar(self, carga: CargaQvd, local: Path, gerado: dict, avisar, *, reaproveitado: bool) -> ResultadoCarga:
        """Envia o QVD à Qlik. Se o envio falhar (e não for um cancelamento), guarda o arquivo."""
        linhas = gerado["linhas"]
        total = local.stat().st_size
        interrompido = False  # o próprio aviso de progresso levantou (cancelamento): não guarda

        def ao_enviar(feito: int, tot: int) -> None:
            nonlocal interrompido
            try:
                avisar("enviando", linhas=linhas, bytes_enviados=feito, bytes_total=tot,
                       reaproveitado=reaproveitado or None,
                       gerado_em=gerado.get("gerado_em") if reaproveitado else None)
            except Exception:
                interrompido = True
                raise

        t2 = time.perf_counter()
        try:
            ao_enviar(0, total)
            info_qlik, criado = self._subir(carga, local, ao_enviar=ao_enviar)
        except Exception as e:
            if interrompido:
                if reaproveitado:
                    self._descartar_pendente(carga)
                raise
            if not reaproveitado:
                self._guardar_pendente(carga, local, gerado)
            validade = time.strftime("%H:%M", time.localtime(time.time() + VALIDADE_PENDENTE_H * 3600))
            raise RuntimeError(
                f"O envio à Qlik falhou ({type(e).__name__}: {str(e)[:300]}). O QVD ficou guardado: "
                f"a próxima execução desta carga só reenvia, sem reler o banco (vale até ~{validade})."
            ) from e
        t3 = time.perf_counter()
        logger.info("[%s] upload (%s) em %.1fs", carga.nome, "novo" if criado else "substituição", t3 - t2)
        if reaproveitado:
            self._descartar_pendente(carga)

        return ResultadoCarga(
            nome=carga.nome,
            file_id=info_qlik["id"],
            criado=criado,
            linhas=linhas,
            colunas=gerado["colunas"],
            tamanho_bytes=info_qlik["size"],
            seg_extracao=gerado["seg_extracao"],
            seg_geracao=gerado["seg_geracao"],
            seg_upload=t3 - t2,
            composicao=gerado.get("composicao"),
        )

    # ------------------------------------------------------------------ #
    # QVD guardado quando o envio falha
    # ------------------------------------------------------------------ #
    def _caminhos_pendente(self, carga: CargaQvd) -> tuple[Path, Path]:
        pasta = self.work_dir / "pendentes"
        nome = re.sub(r"[^A-Za-z0-9_.-]", "_", carga.nome)
        return pasta / f"{nome}.qvd", pasta / f"{nome}.json"

    @staticmethod
    def _assinatura(carga: CargaQvd) -> str:
        """Muda se a consulta, os parâmetros ou a fonte mudarem: aí o guardado não serve. O destino fica de fora:
        o conteúdo do QVD não depende de onde ele é publicado (mover o destino aproveita o guardado)."""
        base = json.dumps([carga.query, carga.params or {}, carga.fonte_id], sort_keys=True, default=str)
        return hashlib.sha256(base.encode()).hexdigest()

    def _guardar_pendente(self, carga: CargaQvd, local: Path, gerado: dict) -> None:
        try:
            qvd_p, meta_p = self._caminhos_pendente(carga)
            qvd_p.parent.mkdir(parents=True, exist_ok=True)
            os.replace(local, qvd_p)
            meta_p.write_text(json.dumps({
                **gerado,
                "assinatura": self._assinatura(carga),
                "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gerado_ts": time.time(),
                "bytes": qvd_p.stat().st_size,
            }, default=str), encoding="utf-8")
            logger.warning("[%s] envio falhou; QVD guardado em %s para a próxima execução", carga.nome, qvd_p)
        except Exception:
            logger.warning("[%s] não consegui guardar o QVD para reenvio", carga.nome, exc_info=True)

    def _pendente(self, carga: CargaQvd) -> tuple[Path, dict] | None:
        """O QVD guardado desta carga, se ainda servir; senão apaga o que estiver lá."""
        qvd_p, meta_p = self._caminhos_pendente(carga)
        if not qvd_p.exists() or not meta_p.exists():
            return None
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            idade_h = (time.time() - float(meta["gerado_ts"])) / 3600
            motivo = None
            if meta.get("assinatura") != self._assinatura(carga):
                motivo = "a consulta (ou fonte/destino) mudou"
            elif idade_h > VALIDADE_PENDENTE_H:
                motivo = f"tem {idade_h:.0f}h (limite {VALIDADE_PENDENTE_H}h)"
            elif qvd_p.stat().st_size != int(meta.get("bytes", -1)):
                motivo = "o arquivo mudou de tamanho"
            if motivo:
                logger.info("[%s] QVD guardado descartado: %s; gerando de novo", carga.nome, motivo)
                self._descartar_pendente(carga)
                return None
            conferir_arquivo(qvd_p, int(meta["linhas"]))
            return qvd_p, meta
        except Exception:
            logger.warning("[%s] QVD guardado inválido; gerando de novo", carga.nome, exc_info=True)
            self._descartar_pendente(carga)
            return None

    def _descartar_pendente(self, carga: CargaQvd) -> None:
        for p in self._caminhos_pendente(carga):
            p.unlink(missing_ok=True)

    def _lotes_antecipados(self, db, carga: CargaQvd):
        """Os lotes da consulta já preparados para o QVD, lidos por uma thread à parte até
        LOTES_ANTECIPADOS à frente: o banco manda o próximo enquanto o atual vira QVD, e o tempo
        da extração fica perto do maior dos dois, não da soma. O driver e o Polars soltam o GIL.

        Uma falha na leitura sobe aqui, no lote em que aconteceu. Se quem consome parar antes
        (cancelamento, erro ao gravar), a leitura para no lote em andamento e a conexão é fechada
        antes de sair daqui.
        """
        if LOTES_ANTECIPADOS <= 0:
            for lote in self._lotes(db, carga):
                yield self.preparar_para_qvd(lote)
            return

        fila: queue.Queue = queue.Queue(maxsize=LOTES_ANTECIPADOS)
        parar = threading.Event()

        def entregar(item) -> bool:
            while not parar.is_set():
                try:
                    fila.put(item, timeout=0.5)
                    return True
                except queue.Full:
                    pass
            return False

        def ler() -> None:
            try:
                with closing(self._lotes(db, carga)) as lotes:
                    for lote in lotes:
                        if not entregar(("lote", self.preparar_para_qvd(lote))):
                            return
                entregar(("fim", None))
            except BaseException as e:  # sobe na thread de quem consome
                entregar(("erro", e))

        leitora = threading.Thread(target=ler, name=f"leitura-{carga.nome}", daemon=True)
        leitora.start()
        try:
            while True:
                tipo, valor = fila.get()
                if tipo == "fim":
                    return
                if tipo == "erro":
                    raise valor
                yield valor
        finally:
            parar.set()
            leitora.join()

    def _lotes(self, db, carga: CargaQvd):
        """Lotes da consulta. Conexões sem leitura em lotes entregam tudo de uma vez e são fatiadas."""
        if hasattr(db, "iter_lotes"):
            yield from db.iter_lotes(carga.query, carga.params)
            return
        df = db.query_pl(carga.query, carga.params)
        for i in range(0, df.height, 100_000):
            yield df.slice(i, 100_000)

    @staticmethod
    def _linhas_previstas(db, carga: CargaQvd) -> int | None:
        """Linhas que o banco espera devolver (plano estimado, não executa). Só para o percentual."""
        prever = getattr(db, "linhas_previstas", None)
        if prever is None:
            return None
        try:
            return prever(carga.query, carga.params)
        except Exception:
            logger.debug("[%s] sem estimativa de linhas pelo plano", carga.nome, exc_info=True)
            return None

    @staticmethod
    def _medir_composicao(carga: CargaQvd, info: dict, tamanho: int) -> dict | None:
        """Peso de cada coluna no QVD, exato (vem do próprio gerador). Nunca derruba a carga."""
        try:
            from src.lurkqvd.pipeline.estimativa import composicao_medida

            return composicao_medida(info, tamanho)
        except Exception:
            logger.warning("[%s] não consegui medir a composição do QVD", carga.nome, exc_info=True)
            return None

    @staticmethod
    def preparar_para_qvd(df: pl.DataFrame) -> pl.DataFrame:
        """Ajusta tipos que o QVD não preserva bem.

        - Decimal -> Float64: senão o qvdrs grava como texto e o Sum() no Qlik quebra.
        - Boolean -> Int8 (1/0): o Qlik não tem booleano; deixamos explícito.
        """
        return df.with_columns(
            pl.col(pl.Decimal).cast(pl.Float64),
            pl.col(pl.Boolean).cast(pl.Int8),
        )

    # ------------------------------------------------------------------ #
    # Etapas internas
    # ------------------------------------------------------------------ #
    def _subir(self, carga: CargaQvd, local: Path, ao_enviar=None) -> tuple[dict, bool]:
        """Substitui se já houver arquivo; senão cria. Retorna (info do arquivo, criado?).

        O destino que vale é o da carga (espaço + caminho). Se o arquivo do ID guardado sumiu (404) ou ficou
        inacessível (403: alguém o moveu na Qlik para um espaço onde a API key não tem acesso), procura pelo
        caminho de destino e, se não houver nada lá, cria de novo. O ID novo é gravado na carga ao final.
        """
        file_id = carga.file_id or self._buscar_file_id(carga)

        if file_id:
            try:
                return self._substituir(carga, file_id, local, ao_enviar), False
            except FileNotFoundError:
                logger.warning("[%s] file_id %s não existe mais na Qlik; publicando de novo no destino", carga.nome, file_id)
            except Exception as e:
                if getattr(getattr(e, "response", None), "status_code", None) != 403:
                    raise
                logger.warning("[%s] sem acesso ao file_id %s (movido para outro espaço na Qlik?); publicando de novo "
                               "no destino da carga: %s", carga.nome, file_id, carga.qlik_path)
            # o ID guardado não serve mais: pode já existir um arquivo no destino (ex.: criado à mão)
            no_destino = self._buscar_file_id(carga) if carga.file_id else None
            if no_destino and no_destino != file_id:
                return self._substituir(carga, no_destino, local, ao_enviar), False

        info = self.qlik.upload_file(carga.connection_id, carga.qlik_path, str(local), ao_enviar=ao_enviar)
        return info, True

    def _substituir(self, carga: CargaQvd, file_id: str, local: Path, ao_enviar) -> dict:
        return self.qlik.replace_file(file_id, carga.connection_id, str(local), path=carga.qlik_path, ao_enviar=ao_enviar)

    def _buscar_file_id(self, carga: CargaQvd) -> str | None:
        """Procura o arquivo pelo caminho, para quando o ID ainda não está nos metadados."""
        pasta, _, nome = carga.qlik_path.strip("/").rpartition("/")
        for item in self.qlik.list_files(carga.connection_id, pasta or None):
            if not item["is_folder"] and item["base_name"] == nome:
                return item["id"]
        return None
