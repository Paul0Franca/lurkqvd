"""Worker do lurkqvd: fica rodando, enfileira as cargas agendadas e executa a fila (lurkqvd.execucoes).

Uso, na raiz do projeto:
    python -m src.lurkqvd.worker              # fica rodando (Ctrl+C para parar)
    python -m src.lurkqvd.worker --uma-vez    # esvazia a fila e sai (bom para testar)

Vários workers podem rodar juntos: o FOR UPDATE SKIP LOCKED garante que
cada execução é pega por um só. Os da mesma máquina (LURKQVD_MAQUINA; padrão: o nome do host) dividem a
mesma RAM: cada um só pega uma carga se a memória estimada dela couber no que sobra (pipeline/memoria.py).
"""

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time

from typing import Callable

from src.lurkqvd.clients.qlik import QlikCredentials, QlikQvd
from src.lurkqvd import fuso, migracoes
from src.lurkqvd.config import fontes, qlik_conexao
from src.lurkqvd.notificacoes import Notificador
from src.lurkqvd.pipeline import memoria
from src.lurkqvd.pipeline.gerador_qvd import GeradorQvd
from src.lurkqvd.repository.repositorio import Repositorio

logger = logging.getLogger("lurkqvd.worker")
# workers com o mesmo nome de máquina dividem a mesma RAM (no Docker, cada container tem um host próprio:
# o docker-compose.yml dá o mesmo nome a todos os workers da instalação)
MAQUINA = os.getenv("LURKQVD_MAQUINA") or socket.gethostname()


class Cancelada(Exception):
    """Alguém pediu para cancelar a execução (botão Cancelar)."""


class Progresso:
    """Recebe os avisos do gerador e grava o progresso no Postgres, no máximo a cada `intervalo` s
    (sempre na troca de fase). A cada gravação descobre se pediram para cancelar e, se sim,
    levanta Cancelada: o gerador para no ponto em que está (lote lido, pedaço enviado...)."""

    def __init__(self, repo: Repositorio, execucao_id: int, intervalo: float = 2.0,
                 linhas_previstas: int | None = None, medidor: memoria.Medidor | None = None) -> None:
        self.repo = repo
        self.medidor = medidor  # recebe a fase atual: pico de memória por fase
        self.execucao_id = execucao_id
        self.intervalo = intervalo
        # linhas da última execução com sucesso: previsão melhor que a do plano do SQL Server
        self._previstas_fixas = linhas_previstas
        self.estado: dict = {"linhas_previstas": linhas_previstas} if linhas_previstas else {}
        self._ultima_gravacao = 0.0
        self._ultimo_log = 0.0

    def __call__(self, fase: str, **dados) -> None:
        agora = time.monotonic()
        nova_fase = fase != self.estado.get("fase")
        if nova_fase:
            self.estado = {"fase": fase, "fase_desde": _agora_iso(),
                           **({"linhas_previstas": self.estado["linhas_previstas"]}
                              if self.estado.get("linhas_previstas") else {})}
            if self.medidor:
                self.medidor.fase = fase
        if self._previstas_fixas:
            dados.pop("linhas_previstas", None)
        self.estado.update({k: v for k, v in dados.items() if v is not None})
        if fase == "lendo" and agora - self._ultimo_log >= 30 and self.estado.get("linhas"):
            self._ultimo_log = agora
            logger.info("execução %s: lendo %s linhas (%s/s · %s MB/s)", self.execucao_id,
                        f"{self.estado['linhas']:,}".replace(",", "."),
                        f"{self.estado.get('linhas_por_seg') or 0:,}".replace(",", "."),
                        f"{self.estado.get('mb_por_seg') or 0:.1f}".replace(".", ","))
        if not nova_fase and agora - self._ultima_gravacao < self.intervalo:
            return
        self._ultima_gravacao = agora
        self.estado["atualizado_em"] = _agora_iso()
        try:
            cancelar = self.repo.registrar_progresso(self.execucao_id, self.estado)
        except Exception:  # Postgres instável: o progresso é só informativo, a carga segue
            logger.warning("não consegui gravar o progresso", exc_info=True)
            return
        if cancelar:
            raise Cancelada(f"cancelamento pedido durante a fase “{fase}”")


def _agora_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class Worker:
    INTERVALO_VERSAO_QLIK = 30.0       # de quanto em quanto tempo confere se a key/tenant mudou
    INTERVALO_STATUS_QLIK = 6 * 3600.0  # de quanto em quanto tempo testa a key (vencimento no painel)

    def __init__(self, repo: Repositorio, gerador: GeradorQvd | None = None, intervalo: float = 5.0,
                 intervalo_agenda: float = 20.0, fabrica_gerador: Callable[[], GeradorQvd] | None = None,
                 fabrica_qlik: Callable[[], QlikQvd] | None = None, intervalo_orquestracao: float = 3.0,
                 notificador: Notificador | None = None, intervalo_notificacoes: float = 20.0) -> None:
        self.repo = repo
        # e-mails de aviso: thread à parte (um SMTP lento não atrasa a fila nem as aplicações)
        self.notificador = notificador
        self.intervalo_notificacoes = intervalo_notificacoes
        # aplicações: uma thread à parte dispara as cargas, espera e recarrega o app na Qlik,
        # mesmo enquanto o laço principal roda uma carga longa. Client da Qlik próprio (o requests
        # não deve ser compartilhado entre threads).
        self.fabrica_qlik = fabrica_qlik
        self._qlik_orq: QlikQvd | None = None
        self._versao_qlik_orq = None
        self.intervalo_orquestracao = intervalo_orquestracao
        self.fabrica_gerador = fabrica_gerador
        # criado na 1ª carga (e recriado quando a Qlik muda): numa instalação nova ainda não há key nem tenant
        self.gerador = gerador
        self._versao_qlik = repo.versao_qlik() if fabrica_gerador else None
        self._proxima_versao_qlik = 0.0
        self._proximo_status_qlik = 0.0
        self._conexoes: dict[int, tuple] = {}  # fonte_id -> (atualizado_em, FonteSql)
        self.intervalo = intervalo  # segundos de espera quando a fila está vazia
        self.intervalo_agenda = intervalo_agenda  # de quanto em quanto tempo olha os agendamentos
        self._proxima_agenda = 0.0
        self._parar = False
        # sinal de vida: uma thread à parte, para continuar batendo durante uma carga longa
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self.maquina = MAQUINA
        self.execucao_atual: int | None = None
        self._fim_sinal = threading.Event()

    def _bater_sinal(self, intervalo: float = 15.0) -> None:
        while not self._fim_sinal.wait(intervalo):
            try:
                self.repo.sinal_worker(self.id, self.execucao_atual)
            except Exception:  # Postgres fora do ar: tenta de novo no próximo ciclo
                logger.warning("não consegui registrar o sinal de vida", exc_info=True)

    def pedir_parada(self, *_args) -> None:
        """Parada suave: termina a carga em andamento e só então sai."""
        if not self._parar:
            logger.info("parada solicitada; terminando a carga atual (se houver)...")
        self._parar = True

    def verificar_agenda(self) -> None:
        """Enfileira as cargas agendadas que venceram (no máximo a cada intervalo_agenda)."""
        agora = time.monotonic()
        if agora < self._proxima_agenda:
            return
        self._proxima_agenda = agora + self.intervalo_agenda
        criadas = self.repo.enfileirar_agendadas()
        if criadas:
            logger.info("agendador: %s execução(ões) enfileirada(s): %s", len(criadas), criadas)
        apps = self.repo.enfileirar_aplicacoes_agendadas()
        if apps:
            logger.info("agendador: %s aplicação(ões) disparada(s): %s", len(apps), apps)

    def verificar_qlik(self) -> None:
        """Key ou tenant trocados pela tela: recria o client da Qlik. E, de tempos em tempos, testa a key."""
        if not self.fabrica_gerador:
            return
        agora = time.monotonic()
        if agora >= self._proxima_versao_qlik:
            self._proxima_versao_qlik = agora + self.INTERVALO_VERSAO_QLIK
            versao = self.repo.versao_qlik()
            if versao != self._versao_qlik:
                self.gerador = None  # recriado na próxima carga, com a key/tenant novos
                self._versao_qlik = versao
                logger.info("configuração da Qlik mudou: client recriado")
        if agora >= self._proximo_status_qlik:
            self._proximo_status_qlik = agora + self.INTERVALO_STATUS_QLIK
            try:
                tenant = self.repo.config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
                if not tenant or not qlik_conexao.tem_token():
                    return  # Qlik ainda não configurada: nada a testar
                resultado = qlik_conexao.testar(tenant, qlik_conexao.ler_token())
                self.repo.salvar_status_qlik(qlik_conexao.para_cache(resultado))
                if not resultado["ok"]:
                    logger.warning("teste da API key da Qlik falhou: %s", resultado["erro"])
            except Exception:
                logger.warning("não consegui testar a API key da Qlik", exc_info=True)

    def conexao_para(self, fonte_id: int | None):
        """Conexão da fonte da carga (ou da padrão). None = nenhuma fonte cadastrada (a carga falha com o aviso).

        Reaproveita a conexão enquanto a fonte não muda; se alguém editar a fonte, recria.
        """
        fonte = self.repo.fonte_para_execucao(fonte_id)
        if fonte is None:
            if fonte_id is not None:
                raise RuntimeError(f"A fonte {fonte_id} da carga não existe mais.")
            return None
        em_cache = self._conexoes.get(fonte["id"])
        if em_cache and em_cache[0] == fonte["atualizado_em"]:
            return em_cache[1]
        if em_cache:
            em_cache[1].fechar()
        conexao = fontes.FonteSql(fonte, fontes.ler_senha(fonte["id"]))
        self._conexoes[fonte["id"]] = (fonte["atualizado_em"], conexao)
        return conexao

    def processar_uma(self) -> bool:
        """Executa a próxima da fila. Retorna False se a fila estava vazia."""
        proxima = self.repo.pegar_proxima(
            maquina=self.maquina, capacidade=memoria.capacidade(),
            reserva_padrao=memoria.RESERVA_PADRAO_MB * 1024 * 1024, espera_max_s=memoria.ESPERA_MAX_MIN * 60,
        )
        if not proxima:
            return False

        execucao_id, carga_id, carga = proxima
        self.execucao_atual = execucao_id
        self._sinal_agora()
        logger.info("execução %s: carga '%s' (id %s)", execucao_id, carga.nome, carga_id)
        medidor = memoria.Medidor()
        progresso = Progresso(self.repo, execucao_id, linhas_previstas=self._linhas_da_ultima(carga_id),
                              medidor=medidor)
        try:
            progresso("preparando")
            if self.gerador is None:
                if not self.fabrica_gerador:
                    raise RuntimeError("worker sem gerador configurado")
                self.gerador = self.fabrica_gerador()
            with medidor:
                resultado = self.gerador.executar(carga, db=self.conexao_para(carga.fonte_id), progresso=progresso)
            self._registrar_memoria(execucao_id, medidor)
            self.repo.finalizar_sucesso(execucao_id, carga_id, resultado)
            logger.info("execução %s: sucesso em %.1fs", execucao_id, resultado.seg_total)
        except Cancelada as e:
            logger.info("execução %s: %s; parada sem publicar", execucao_id, e)
            self._registrar_memoria(execucao_id, medidor)
            self.repo.finalizar_cancelada(execucao_id, progresso.estado)
        except Exception as e:  # uma carga com erro não derruba o worker
            logger.exception("execução %s: erro", execucao_id)
            self._registrar_memoria(execucao_id, medidor)
            self.repo.finalizar_erro(execucao_id, f"{type(e).__name__}: {e}")
        finally:
            self.execucao_atual = None
            self._sinal_agora()
            memoria.devolver()  # o worker parado não fica com o pico da carga
        return True

    # ------------------------------------------------------------------ #
    # Aplicações (thread de orquestração)
    # ------------------------------------------------------------------ #
    def _laco_orquestracao(self) -> None:
        while not self._fim_sinal.wait(self.intervalo_orquestracao):
            try:
                self.orquestrar()
            except Exception:  # Postgres/Qlik fora do ar: tenta de novo no próximo ciclo
                logger.warning("falha na orquestração das aplicações", exc_info=True)

    def orquestrar(self) -> None:
        """Um ciclo: dispara cargas das rodadas novas, conclui as que terminaram, dispara e acompanha reloads."""
        for x in self.repo.orq_iniciar_pendentes():
            logger.info("aplicação: rodada %s iniciada (cargas disparadas)", x)
        for x in self.repo.orq_concluir_cargas():
            self._disparar_reload(x)
        for x in self.repo.orq_reloads_para_consultar():
            self._acompanhar_reload(x)

    def _qlik(self) -> QlikQvd:
        if self.fabrica_qlik is None:
            raise RuntimeError("worker sem client da Qlik para recarregar apps")
        versao = self.repo.versao_qlik()
        if self._qlik_orq is None or versao != self._versao_qlik_orq:
            self._qlik_orq, self._versao_qlik_orq = self.fabrica_qlik(), versao
        return self._qlik_orq

    def _disparar_reload(self, x: dict) -> None:
        try:
            reload = self._qlik().recarregar_app(x["qlik_app_id"])
            self.repo.orq_registrar_reload(x["id"], reload)
            logger.info("aplicação: rodada %s, reload %s disparado na Qlik", x["id"], reload.get("id"))
        except Exception as e:
            logger.warning("aplicação: rodada %s, não consegui disparar o reload", x["id"], exc_info=True)
            self.repo.orq_registrar_reload(x["id"], None, erro=f"Não consegui disparar o reload na Qlik: {e}")

    def _acompanhar_reload(self, x: dict) -> None:
        if not x["reload_id"]:
            self.repo.orq_atualizar_reload(x["id"], None)
            return
        qlik = self._qlik()
        if x["cancelar_em"]:
            try:
                qlik.cancelar_reload(x["reload_id"])
            except Exception:
                logger.warning("aplicação: não consegui pedir o cancelamento do reload %s", x["reload_id"], exc_info=True)
        try:
            reload = qlik.status_reload(x["reload_id"])
        except Exception:
            logger.warning("aplicação: não consegui consultar o reload %s; tento de novo", x["reload_id"], exc_info=True)
            return
        self.repo.orq_atualizar_reload(x["id"], reload)
        if reload.get("status") in ("SUCCEEDED", "FAILED", "CANCELED", "EXCEEDED_LIMIT"):
            logger.info("aplicação: rodada %s, reload %s terminou: %s", x["id"], x["reload_id"], reload.get("status"))

    # ------------------------------------------------------------------ #
    # Notificações por e-mail (thread à parte)
    # ------------------------------------------------------------------ #
    def _laco_notificacoes(self) -> None:
        while not self._fim_sinal.wait(self.intervalo_notificacoes):
            try:
                enviados = self.notificador.ciclo()
                if enviados:
                    logger.info("notificações: %s e-mail(s) enviado(s)", enviados)
            except Exception:  # Postgres/SMTP fora do ar: tenta de novo no próximo ciclo
                logger.warning("falha ao processar as notificações", exc_info=True)

    def _registrar_memoria(self, execucao_id: int, medidor: memoria.Medidor) -> None:
        """Grava o pico antes do status final: quando a execução sai de 'rodando', a estimativa já está lá."""
        try:
            self.repo.registrar_memoria(execucao_id, medidor.incremento)
            if medidor.incremento is not None:
                fases = " · ".join(f"{f} {b / 1024**2:.0f}" for f, b in medidor.picos.items())
                logger.info("execução %s: memória +%.0f MB (pico do worker %.0f MB; por fase, MB: %s)",
                            execucao_id, medidor.incremento / 1024**2, medidor.pico / 1024**2, fases)
        except Exception:  # só informativo: não pode mudar o resultado da carga
            logger.warning("não consegui gravar a memória da execução %s", execucao_id, exc_info=True)

    def _linhas_da_ultima(self, carga_id: int) -> int | None:
        try:
            return self.repo.linhas_da_ultima(carga_id)
        except Exception:
            return None

    def _sinal_agora(self) -> None:
        try:
            self.repo.sinal_worker(self.id, self.execucao_atual)
        except Exception:
            logger.warning("não consegui registrar o sinal de vida", exc_info=True)

    def rodar(self, uma_vez: bool = False) -> None:
        travadas = self.repo.recuperar_travadas()
        if travadas:
            logger.warning("%s execução(ões) travada(s) marcada(s) como erro", travadas)
        if recalculados := self.repo.alinhar_fuso():
            logger.info("fuso mudou para %s: próximo horário de %s agendamento(s) recalculado", fuso.FUSO, recalculados)

        self.repo.registrar_worker(self.id, socket.gethostname(), os.getpid())
        threading.Thread(target=self._bater_sinal, name="sinal-de-vida", daemon=True).start()
        if not uma_vez:
            threading.Thread(target=self._laco_orquestracao, name="aplicacoes", daemon=True).start()
            if self.notificador:
                threading.Thread(target=self._laco_notificacoes, name="notificacoes", daemon=True).start()
        cap = memoria.capacidade()
        logger.info("worker %s iniciado na máquina %s (intervalo %.0fs; fuso %s; memória para as cargas da máquina: %s)",
                    self.id, self.maquina, self.intervalo, fuso.FUSO, f"{cap / 1024**3:.1f} GB" if cap else "sem controle")
        try:
            self._laco(uma_vez)
        finally:
            self._fim_sinal.set()
            try:
                self.repo.encerrar_worker(self.id)
            except Exception:
                logger.warning("não consegui registrar o encerramento", exc_info=True)
        logger.info("worker encerrado")

    def _laco(self, uma_vez: bool) -> None:
        while not self._parar:
            try:
                self.verificar_qlik()
                if not uma_vez:
                    self.verificar_agenda()
                tinha_trabalho = self.processar_uma()
            except Exception:  # ex.: Postgres fora do ar; espera e tenta de novo
                logger.exception("falha ao consultar a fila")
                tinha_trabalho = False

            if not tinha_trabalho:
                if uma_vez:
                    break
                self._dormir()

    def _dormir(self) -> None:
        """Espera em passos curtos para responder rápido a um Ctrl+C."""
        fim = time.monotonic() + self.intervalo
        while not self._parar and time.monotonic() < fim:
            time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker de cargas QVD")
    parser.add_argument("--uma-vez", action="store_true", help="esvazia a fila e sai")
    parser.add_argument("--intervalo", type=float, default=5.0, help="segundos entre consultas à fila vazia")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    repo = Repositorio()
    try:
        migracoes.exigir_em_dia(repo.dsn)
    except migracoes.BancoDesatualizado as e:
        logger.error("%s", e)
        sys.exit(1)

    def criar_gerador() -> GeradorQvd:
        # key sempre a mais recente dos segredos; tenant das configurações (tela Qlik Cloud)
        tenant = repo.config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
        qlik = QlikQvd(QlikCredentials(token=qlik_conexao.ler_token()), tenant, timeout=(10, 900))
        return GeradorQvd(db=None, qlik=qlik)  # a conexão vem da fonte de cada carga (conexao_para)

    def criar_qlik() -> QlikQvd:
        tenant = repo.config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
        return QlikQvd(QlikCredentials(token=qlik_conexao.ler_token()), tenant, timeout=(10, 60))

    worker = Worker(repo=repo, fabrica_gerador=criar_gerador, fabrica_qlik=criar_qlik, intervalo=args.intervalo,
                    notificador=Notificador(repo))
    signal.signal(signal.SIGINT, worker.pedir_parada)   # Ctrl+C
    signal.signal(signal.SIGTERM, worker.pedir_parada)  # docker stop / systemd
    worker.rodar(uma_vez=args.uma_vez)


if __name__ == "__main__":
    main()
