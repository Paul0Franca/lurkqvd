"""Memória do worker: trava por carga, medição do pico e reserva na fila.

Trava: se a memória do processo passar do limite, a carga para com um erro claro, em vez de o sistema
operacional (ou o Rust, numa alocação que falha) derrubar o worker inteiro no meio.

Reserva: workers da mesma máquina dividem a mesma RAM. Cada execução grava quanto fez o processo crescer
(Medidor) e, na próxima vez, o worker só pega aquela carga se a estimativa couber no que sobra da
capacidade da máquina (escolher). Sem histórico, a carga reserva RESERVA_PADRAO_MB.

Variáveis:
  LURKQVD_LIMITE_MEMORIA_PCT     % da RAM usada como limite (padrão 75): da carga sozinha e da máquina toda
  LURKQVD_MEMORIA_SEM_HISTORICO_MB  reserva de uma carga que ainda não rodou (padrão 1024)
  LURKQVD_ESPERA_MAX_MIN         depois disso esperando por memória, nenhuma carga passa na frente (padrão 15)

A RAM considerada é a menor entre a da máquina e o limite do container (cgroup), se houver.
Precisa do psutil (pip install psutil); sem ele, trava e reserva ficam desligadas e o worker avisa no log.
"""

import ctypes
import gc
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("lurkqvd.memoria")

LIMITE_PCT = float(os.getenv("LURKQVD_LIMITE_MEMORIA_PCT", "75"))
RESERVA_PADRAO_MB = int(os.getenv("LURKQVD_MEMORIA_SEM_HISTORICO_MB", "1024"))
ESPERA_MAX_MIN = float(os.getenv("LURKQVD_ESPERA_MAX_MIN", "15"))
_INTERVALO = 1.0  # medir a memória custa pouco, mas não precisa ser a cada lote

# limite de memória do container: cgroup v2 e v1 ("max" ou um número enorme = sem limite)
_CGROUP = (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))


def _ram_total(total_maquina: int, arquivos=_CGROUP) -> int:
    """RAM que o processo pode usar: a da máquina ou o limite do container, o que for menor."""
    for arquivo in arquivos:
        try:
            valor = arquivo.read_text().strip()
        except OSError:
            continue
        if valor.isdigit() and 0 < int(valor) < total_maquina:
            return int(valor)
    return total_maquina


try:
    import psutil

    _processo = psutil.Process()
    _total = _ram_total(psutil.virtual_memory().total)
except ImportError:  # trava desligada
    psutil = None
    _processo = None
    _total = 0
    logger.warning("psutil não instalado: a trava de memória está desligada (pip install psutil)")

_ultima = 0.0


class MemoriaInsuficiente(RuntimeError):
    """A carga passou do limite de memória do worker."""


def uso() -> tuple[int, int] | None:
    """(bytes em uso pelo processo, bytes de RAM disponíveis), ou None sem psutil."""
    if _processo is None:
        return None
    return _processo.memory_info().rss, _total


def capacidade() -> int | None:
    """Bytes que as cargas de uma máquina podem usar juntas, ou None sem psutil (sem reserva)."""
    return int(_total * LIMITE_PCT / 100) if _processo is not None else None


def conferir(carga: str, *, forcar: bool = False) -> None:
    """Levanta MemoriaInsuficiente se o processo passou do limite. Barato: mede no máximo 1x/s."""
    global _ultima
    if _processo is None:
        return
    agora = time.monotonic()
    if not forcar and agora - _ultima < _INTERVALO:
        return
    _ultima = agora
    usado = _processo.memory_info().rss
    limite = _total * LIMITE_PCT / 100
    if usado > limite:
        raise MemoriaInsuficiente(
            f"A carga {carga} passou do limite de memória do worker ({usado / 1024**3:.1f} GB de "
            f"{limite / 1024**3:.1f} GB permitidos, {LIMITE_PCT:.0f}% da RAM). Provavelmente uma coluna "
            "tem valores distintos demais (ex.: um ID único por linha que os apps não usam): "
            "veja a composição do QVD e tire do SELECT o que não for necessário."
        )


def devolver() -> None:
    """Devolve ao sistema a memória que ficou livre no fim de uma carga. Os alocadores (o do Python, o
    do Arrow e o malloc da glibc) guardam o que foi liberado para reusar, e o worker parado ficaria com
    o pico da última carga. No Linux (glibc); nos outros sistemas, só o que o Python e o Arrow soltam."""
    gc.collect()
    try:
        import pyarrow as pa

        pa.default_memory_pool().release_unused()
    except ImportError:
        pass
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


class Medidor:
    """Mede, numa thread à parte, quanto o processo cresceu durante um trecho (pico − início).

        with Medidor() as m:
            ...carga...
        m.incremento  # bytes, ou None sem psutil
    """

    def __init__(self, intervalo: float = 0.5) -> None:
        self.intervalo = intervalo
        self.inicio = self.pico = 0
        self._fim = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Medidor":
        if _processo is not None:
            self.inicio = self.pico = _processo.memory_info().rss
            self._thread = threading.Thread(target=self._amostrar, name="medidor-memoria", daemon=True)
            self._thread.start()
        return self

    def _amostrar(self) -> None:
        while not self._fim.wait(self.intervalo):
            self.pico = max(self.pico, _processo.memory_info().rss)

    def __exit__(self, *_exc) -> None:
        if self._thread:
            self._fim.set()
            self._thread.join()
            self.pico = max(self.pico, _processo.memory_info().rss)

    @property
    def incremento(self) -> int | None:
        return max(self.pico - self.inicio, 0) if self._thread else None


@dataclass
class Pendente:
    id: int
    estimativa: int      # bytes que a carga deve usar (histórico ou RESERVA_PADRAO_MB)
    espera_s: float      # há quanto tempo está na fila


def escolher(pendentes: list[Pendente], reservado: int, capacidade: int, espera_max_s: float) -> Pendente | None:
    """Qual execução pendente (em ordem de chegada) esta máquina pode pegar agora, ou None.

    - a primeira que couber no que sobra (capacidade − reservado) é a escolhida;
    - com nada rodando na máquina, a primeira da fila roda mesmo que seja maior que a capacidade
      (senão nunca rodaria; a trava de memória continua valendo);
    - uma que não cabe deixa as de trás passarem na frente, até esperar espera_max_s: daí em diante
      ninguém passa, e a máquina espera esvaziar para ela.
    """
    livre = capacidade - reservado
    for p in pendentes:
        if p.estimativa <= livre or reservado <= 0:
            return p
        if p.espera_s >= espera_max_s:
            return None
    return None
