"""Repositório dos metadados do lurkqvd no Postgres (schema lurkqvd).

Concentra todo o SQL de cargas, execuções (que também são a fila do worker),
espaços e auditoria. Quem usa (worker, API, scripts) não escreve SQL.
"""

import hashlib
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.lurkqvd import fuso
from src.lurkqvd.pipeline import memoria
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd, ResultadoCarga
from src.lurkqvd.repository.acesso import AcessoMixin, LoginJaExiste  # noqa: F401
from src.lurkqvd.repository.aplicacoes import AplicacaoJaEmExecucao, AplicacoesMixin  # noqa: F401
from src.lurkqvd.repository.notificacoes import NotificacoesMixin

DSN_PADRAO = "postgresql://lurkqvd:lurkqvd_dev@127.0.0.1:5433/lurkqvd"  # Postgres de teste (docker)


FUSO_PADRAO = fuso.FUSO
_TRAVA_FILA = 4_272_012  # advisory lock da fila por máquina (o 4_272_011 é o das migrações)
_TRAVA_FUSO = 4_272_013  # dois workers subindo juntos não recalculam a agenda duas vezes


class OperacaoNaoPermitida(Exception):
    """Regra de negócio impediu a alteração (ex.: tirar o último admin)."""


class CargaJaEmExecucao(Exception):
    """A carga já tem uma execução pendente ou rodando."""


class AgendamentoInvalido(ValueError):
    """A expressão cron não é válida."""


def proximas_execucoes(cron: str, fuso: str | None = None, quantidade: int = 1, depois_de: datetime | None = None) -> list[datetime]:
    """Próximos horários de um cron, no fuso informado (None: o da instalação, LURKQVD_FUSO)."""
    from cronsim import CronSim, CronSimError

    zona = ZoneInfo(fuso or FUSO_PADRAO)
    inicio = (depois_de or datetime.now(zona)).astimezone(zona)
    try:
        it = CronSim(cron.strip(), inicio)
        return [next(it) for _ in range(quantidade)]
    except (CronSimError, StopIteration) as e:
        raise AgendamentoInvalido(f"Agendamento inválido: {e}") from e


class Repositorio(AcessoMixin, AplicacoesMixin, NotificacoesMixin):
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("LURKQVD_PG_DSN", DSN_PADRAO)

    @contextmanager
    def _conn(self) -> Iterator[psycopg.Connection]:
        """Uma conexão por operação, em transação: commit no fim, rollback se der erro."""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    # ------------------------------------------------------------------ #
    # Usuários
    # ------------------------------------------------------------------ #
    def listar_usuarios(self) -> list[dict]:
        sql = """
            SELECT u.id, u.email, u.nome, u.papel, u.ativo, u.criado_em, u.ultimo_login, u.foto_url,
                   u.trocar_senha, u.senha_hash IS NOT NULL AS tem_senha,
                   (SELECT count(*) FROM lurkqvd.cargas c WHERE c.criado_por = u.id) AS cargas_criadas
              FROM lurkqvd.usuarios u
             ORDER BY u.ativo DESC, lower(COALESCE(u.nome, u.email))
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchall()

    def alterar_usuario(self, alvo_id: int, usuario_id: int, *, papel: str | None = None,
                        ativo: bool | None = None) -> dict | None:
        """Muda papel e/ou ativo. Ninguém altera a si mesmo, e sempre sobra um admin ativo."""
        if alvo_id == usuario_id:
            raise OperacaoNaoPermitida("Você não pode alterar o próprio acesso.")
        with self._conn() as conn:
            atual = conn.execute(
                "SELECT * FROM lurkqvd.usuarios WHERE id = %s FOR UPDATE", (alvo_id,)
            ).fetchone()
            if not atual:
                return None
            novo_papel = papel if papel is not None else atual["papel"]
            novo_ativo = ativo if ativo is not None else atual["ativo"]
            if atual["papel"] == "admin" and atual["ativo"] and (novo_papel != "admin" or not novo_ativo):
                outros = conn.execute(
                    "SELECT count(*) AS n FROM lurkqvd.usuarios WHERE papel = 'admin' AND ativo AND id <> %s",
                    (alvo_id,),
                ).fetchone()["n"]
                if outros == 0:
                    raise OperacaoNaoPermitida("É preciso manter pelo menos um admin ativo.")

            mudancas = {}
            if novo_papel != atual["papel"]:
                mudancas["papel"] = {"de": atual["papel"], "para": novo_papel}
            if novo_ativo != atual["ativo"]:
                mudancas["ativo"] = {"de": atual["ativo"], "para": novo_ativo}
            if not mudancas:
                return atual
            novo = conn.execute(
                "UPDATE lurkqvd.usuarios SET papel = %s, ativo = %s WHERE id = %s RETURNING *",
                (novo_papel, novo_ativo, alvo_id),
            ).fetchone()
            if not novo_ativo:  # desativado: sai na hora de todos os navegadores
                conn.execute("UPDATE lurkqvd.sessoes SET revogada_em = now() WHERE usuario_id = %s AND revogada_em IS NULL",
                             (alvo_id,))
            self._auditar(conn, usuario_id, "usuario.alterar", "usuario", alvo_id,
                          {"email": atual["email"], **mudancas})
        return novo

    # ------------------------------------------------------------------ #
    # Espaços
    # ------------------------------------------------------------------ #
    def sincronizar_espacos(self, espacos: list[dict]) -> int:
        """Atualiza o cache de espaços com o retorno do QlikQvd.list_spaces()."""
        sql = """
            INSERT INTO lurkqvd.espacos (connection_id, space_id, nome, tipo, atualizado_em)
            VALUES (%(connection_id)s, %(space_id)s, %(space_name)s, %(space_type)s, now())
            ON CONFLICT (connection_id) DO UPDATE
               SET space_id = EXCLUDED.space_id,
                   nome = EXCLUDED.nome,
                   tipo = EXCLUDED.tipo,
                   atualizado_em = now()
        """
        with self._conn() as conn:
            conn.cursor().executemany(sql, espacos)
        return len(espacos)

    def resumo_espacos(self) -> list[dict]:
        """Cada espaço com quantas cargas tem, quanto já publicou e se alguma falhou.

        Cargas sem connection_id pertencem ao espaço pessoal.
        """
        sql = """
            SELECT esp.connection_id, esp.space_id, esp.nome, esp.tipo,
                   count(c.id)                                   AS qtd_cargas,
                   count(c.id) FILTER (WHERE ult.status = 'erro') AS com_erro,
                   count(c.id) FILTER (WHERE ult.status IN ('pendente', 'rodando')) AS em_andamento,
                   COALESCE(sum(suc.tamanho_bytes), 0)::bigint   AS bytes_publicados,
                   max(ult.finalizado_em)                         AS ultima_execucao
              FROM lurkqvd.espacos esp
              LEFT JOIN lurkqvd.cargas c
                     ON c.connection_id = esp.connection_id
                     OR (c.connection_id IS NULL AND esp.tipo = 'personal')
              LEFT JOIN LATERAL (
                    SELECT status, finalizado_em FROM lurkqvd.execucoes e
                     WHERE e.carga_id = c.id ORDER BY e.solicitado_em DESC LIMIT 1
              ) ult ON true
              LEFT JOIN LATERAL (
                    SELECT tamanho_bytes FROM lurkqvd.execucoes e
                     WHERE e.carga_id = c.id AND e.status = 'sucesso'
                     ORDER BY e.finalizado_em DESC LIMIT 1
              ) suc ON true
             GROUP BY esp.connection_id, esp.space_id, esp.nome, esp.tipo
             ORDER BY count(c.id) DESC, esp.nome
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchall()

    def buscar_espaco(self, connection_id: str) -> dict | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM lurkqvd.espacos WHERE connection_id = %s", (connection_id,)
            ).fetchone()

    def listar_espacos(self) -> list[dict]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM lurkqvd.espacos ORDER BY nome").fetchall()

    # ------------------------------------------------------------------ #
    # Cargas
    # ------------------------------------------------------------------ #
    def criar_carga(self, carga: CargaQvd, usuario_id: int | None = None, agendamento: str | None = None,
                    aplicacao_id: int | None = None) -> int:
        """aplicacao_id: já entra nessa aplicação (no fim da ordem), na mesma transação; None = carga solta."""
        proxima = proximas_execucoes(agendamento)[0] if agendamento else None
        sql = """
            INSERT INTO lurkqvd.cargas
                   (nome, query, params, connection_id, qlik_path, file_id, criado_por, atualizado_por,
                    agendamento, proxima_execucao, fonte_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn() as conn:
            row = conn.execute(
                sql,
                (carga.nome, carga.query, Jsonb(carga.params), carga.connection_id,
                 carga.qlik_path, carga.file_id, usuario_id, usuario_id, agendamento, proxima,
                 getattr(carga, "fonte_id", None)),
            ).fetchone()
            carga_id = row["id"]
            if aplicacao_id is not None:
                conn.execute(
                    """
                    INSERT INTO lurkqvd.aplicacao_cargas (aplicacao_id, carga_id, ordem)
                    SELECT %s, %s, COALESCE(MAX(ordem) + 1, 0) FROM lurkqvd.aplicacao_cargas WHERE aplicacao_id = %s
                    """,
                    (aplicacao_id, carga_id, aplicacao_id),
                )
            self._auditar(conn, usuario_id, "carga.criar", "carga", carga_id,
                          {"nome": carga.nome, "agendamento": agendamento, "aplicacao_id": aplicacao_id})
        return carga_id

    def atualizar_carga(self, carga_id: int, usuario_id: int | None, *, agendamento: str | None = ...,
                        ativo: bool | None = None, query: str | None = None,
                        fonte_id: int | None = ...) -> dict | None:
        """Altera agendamento, ativo, consulta e/ou fonte.

        agendamento=None remove; fonte_id=None volta a acompanhar a fonte padrão; omitido (...) mantém.
        """
        mudancas, valores = [], []
        if fonte_id is not ...:
            mudancas.append("fonte_id = %s")
            valores.append(fonte_id)
        if query is not None:
            mudancas.append("query = %s")
            valores.append(query)
        if agendamento is not ...:
            mudancas += ["agendamento = %s", "proxima_execucao = %s"]
            valores += [agendamento, proximas_execucoes(agendamento)[0] if agendamento else None]
        if ativo is not None:
            mudancas.append("ativo = %s")
            valores.append(ativo)
        if not mudancas:
            return self.buscar_carga_detalhe(carga_id)

        with self._conn() as conn:
            antes = conn.execute(
                "SELECT agendamento, ativo, query, fonte_id FROM lurkqvd.cargas WHERE id = %s FOR UPDATE", (carga_id,)
            ).fetchone()
            if not antes:
                return None
            conn.execute(
                f"UPDATE lurkqvd.cargas SET {', '.join(mudancas)}, atualizado_em = now(), atualizado_por = %s WHERE id = %s",
                (*valores, usuario_id, carga_id),
            )
            depois = {"agendamento": agendamento if agendamento is not ... else antes["agendamento"],
                      "ativo": ativo if ativo is not None else antes["ativo"],
                      "query": query if query is not None else antes["query"],
                      "fonte_id": fonte_id if fonte_id is not ... else antes["fonte_id"]}
            # na auditoria entram só os campos que mudaram (a consulta pode ser longa)
            alterados = {k for k in depois if depois[k] != antes[k]}
            self._auditar(conn, usuario_id, "carga.alterar", "carga", carga_id,
                          {"antes": {k: antes[k] for k in alterados}, "depois": {k: depois[k] for k in alterados}})
        return self.buscar_carga_detalhe(carga_id)

    def enfileirar_agendadas(self) -> list[int]:
        """Enfileira as cargas cujo horário chegou e calcula o próximo horário de cada uma.

        - SKIP LOCKED: vários workers podem chamar ao mesmo tempo sem duplicar.
        - Se a carga já está pendente/rodando, não cria outra execução (só avança o horário).
        - Horários perdidos (worker parado) não acumulam: roda uma vez e segue do horário atual.
        Retorna os ids das execuções criadas.
        """
        criadas: list[int] = []
        with self._conn() as conn:
            if self._config(conn, "agenda", {}).get("pausada"):
                return criadas
            vencidas = conn.execute(
                """
                SELECT id, agendamento, fuso FROM lurkqvd.cargas
                 WHERE ativo AND agendamento IS NOT NULL AND proxima_execucao <= now()
                 ORDER BY proxima_execucao
                   FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            for c in vencidas:
                row = conn.execute(
                    """
                    INSERT INTO lurkqvd.execucoes (carga_id, origem)
                    VALUES (%s, 'agendador')
                    ON CONFLICT (carga_id) WHERE status IN ('pendente', 'rodando') DO NOTHING
                    RETURNING id
                    """,
                    (c["id"],),
                ).fetchone()
                if row:
                    criadas.append(row["id"])
                    self._auditar(conn, None, "carga.executar", "carga", c["id"],
                                  {"execucao_id": row["id"], "origem": "agendador"})
                try:
                    proxima = proximas_execucoes(c["agendamento"], c["fuso"])[0]
                except AgendamentoInvalido:
                    proxima = None  # cron quebrado não trava o agendador: só para de agendar essa carga
                conn.execute("UPDATE lurkqvd.cargas SET proxima_execucao = %s WHERE id = %s", (proxima, c["id"]))
        return criadas

    def listar_cargas(self) -> list[dict]:
        """Cargas com o status da última execução (para a tela principal do front)."""
        sql = """
            SELECT c.id, c.nome, c.qlik_path, c.connection_id, c.file_id, c.ativo,
                   c.agendamento, c.proxima_execucao,
                   esp.nome AS espaco_nome,
                   ult.id AS ultima_execucao_id, ult.status AS ultimo_status,
                   ult.finalizado_em AS ultima_finalizacao,
                   suc.tamanho_bytes AS ultimo_tamanho_bytes,
                   c.criado_em, cri.nome AS criador_nome, cri.email AS criador_email,
                   cri.foto_url AS criador_foto,
                   c.fonte_id, COALESCE(f.nome, fp.nome) AS fonte_nome, (c.fonte_id IS NULL) AS fonte_padrao
              FROM lurkqvd.cargas c
              LEFT JOIN lurkqvd.fontes f  ON f.id = c.fonte_id
              LEFT JOIN lurkqvd.fontes fp ON fp.padrao AND c.fonte_id IS NULL
              LEFT JOIN lurkqvd.espacos esp ON esp.connection_id = c.connection_id
              LEFT JOIN lurkqvd.usuarios cri ON cri.id = c.criado_por
              LEFT JOIN LATERAL (
                    SELECT id, status, finalizado_em
                      FROM lurkqvd.execucoes e
                     WHERE e.carga_id = c.id
                     ORDER BY e.solicitado_em DESC
                     LIMIT 1
              ) ult ON true
              LEFT JOIN LATERAL (
                    SELECT tamanho_bytes FROM lurkqvd.execucoes e
                     WHERE e.carga_id = c.id AND e.status = 'sucesso'
                     ORDER BY e.finalizado_em DESC LIMIT 1
              ) suc ON true
             ORDER BY c.nome
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchall()

    def mudar_destino(self, carga_id: int, connection_id: str | None, qlik_path: str, usuario_id: int | None) -> dict | None:
        """Troca o espaço/caminho onde a carga publica. O ID do arquivo antigo é esquecido: a próxima execução
        publica no destino novo (o arquivo antigo fica na Qlik, sem ser mais atualizado).
        Recusa com execução na fila ou rodando, e se outra carga já publica nesse destino."""
        with self._conn() as conn:
            atual = conn.execute("SELECT id, nome, connection_id, qlik_path FROM lurkqvd.cargas WHERE id = %s FOR UPDATE",
                                 (carga_id,)).fetchone()
            if not atual:
                return None
            if conn.execute("SELECT 1 FROM lurkqvd.execucoes WHERE carga_id = %s AND status IN ('pendente', 'rodando')",
                            (carga_id,)).fetchone():
                raise OperacaoNaoPermitida("A carga está na fila ou rodando: mude o destino depois que ela terminar.")
            # o UNIQUE (connection_id, qlik_path) não pega o espaço pessoal (connection_id nulo): confere aqui
            outra = conn.execute(
                "SELECT nome FROM lurkqvd.cargas WHERE connection_id IS NOT DISTINCT FROM %s::uuid AND qlik_path = %s AND id <> %s",
                (connection_id, qlik_path, carga_id),
            ).fetchone()
            if outra:
                raise OperacaoNaoPermitida(f"A carga {outra['nome']} já publica nesse destino.")
            if str(atual["connection_id"] or "") == str(connection_id or "") and atual["qlik_path"] == qlik_path:
                return self.buscar_carga_detalhe(carga_id)
            conn.execute(
                """
                UPDATE lurkqvd.cargas
                   SET connection_id = %s, qlik_path = %s, file_id = NULL, atualizado_em = now(), atualizado_por = %s
                 WHERE id = %s
                """,
                (connection_id, qlik_path, usuario_id, carga_id),
            )
            self._auditar(conn, usuario_id, "carga.destino", "carga", carga_id, {
                "de": {"connection_id": str(atual["connection_id"]) if atual["connection_id"] else None,
                       "qlik_path": atual["qlik_path"]},
                "para": {"connection_id": connection_id, "qlik_path": qlik_path},
            })
        return self.buscar_carga_detalhe(carga_id)

    def buscar_carga_detalhe(self, carga_id: int) -> dict | None:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT c.*, COALESCE(f.nome, fp.nome) AS fonte_nome, (c.fonte_id IS NULL) AS fonte_padrao
                  FROM lurkqvd.cargas c
                  LEFT JOIN lurkqvd.fontes f  ON f.id = c.fonte_id
                  LEFT JOIN lurkqvd.fontes fp ON fp.padrao AND c.fonte_id IS NULL
                 WHERE c.id = %s
                """,
                (carga_id,),
            ).fetchone()

    def buscar_carga(self, carga_id: int) -> CargaQvd | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM lurkqvd.cargas WHERE id = %s", (carga_id,)).fetchone()
        return self._para_carga(row) if row else None

    def buscar_carga_por_nome(self, nome: str) -> tuple[int, CargaQvd] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM lurkqvd.cargas WHERE nome = %s", (nome,)).fetchone()
        return (row["id"], self._para_carga(row)) if row else None

    @staticmethod
    def _para_carga(row: dict) -> CargaQvd:
        return CargaQvd(
            nome=row["nome"],
            query=row["query"],
            qlik_path=row["qlik_path"],
            connection_id=str(row["connection_id"]) if row["connection_id"] else None,
            file_id=str(row["file_id"]) if row["file_id"] else None,
            params=row["params"] or {},
            fonte_id=row.get("fonte_id"),
        )

    # ------------------------------------------------------------------ #
    # Execuções (histórico + fila)
    # ------------------------------------------------------------------ #
    def enfileirar(self, carga_id: int, origem: str = "manual", usuario_id: int | None = None,
                   token_id: int | None = None) -> int:
        """Cria uma execução pendente. Falha se a carga já estiver pendente/rodando
        (a exceção traz o id da execução ativa, para quem chamou poder esperar por ela)."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    INSERT INTO lurkqvd.execucoes (carga_id, origem, solicitado_por, token_id)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
                    (carga_id, origem, usuario_id, token_id),
                ).fetchone()
                detalhes = {"execucao_id": row["id"]}
                if token_id:
                    nome = conn.execute("SELECT nome FROM lurkqvd.tokens_api WHERE id = %s", (token_id,)).fetchone()
                    detalhes.update(origem="token", token_id=token_id, token_nome=nome["nome"] if nome else None)
                self._auditar(conn, usuario_id, "carga.executar", "carga", carga_id, detalhes)
                return row["id"]
        except psycopg.errors.UniqueViolation as e:
            with self._conn() as conn:
                ativa = conn.execute(
                    "SELECT id FROM lurkqvd.execucoes WHERE carga_id = %s AND status IN ('pendente', 'rodando')",
                    (carga_id,),
                ).fetchone()
            erro = CargaJaEmExecucao(f"A carga {carga_id} já está pendente ou rodando.")
            erro.execucao_id = ativa["id"] if ativa else None
            raise erro from e

    def pegar_proxima(self, maquina: str | None = None, capacidade: int | None = None,
                      reserva_padrao: int = 0, espera_max_s: float = 900) -> tuple[int, int, CargaQvd] | None:
        """Pega a execução pendente mais antiga que cabe na memória da máquina e marca como 'rodando'.

        FOR UPDATE SKIP LOCKED: dois workers nunca pegam a mesma execução.
        Reserva: com `capacidade` (bytes), a execução reserva a estimativa de memória da carga (maior
        pico das últimas 3 com sucesso; sem histórico, `reserva_padrao`) e só é pega se couber no que
        os workers da mesma `maquina` ainda não reservaram (regras em memoria.escolher). Uma trava por
        máquina impede dois workers dela de decidirem ao mesmo tempo. Sem `capacidade`: ordem de chegada.
        Retorna (execucao_id, carga_id, carga) ou None se não houver o que pegar agora.
        """
        maquina = maquina or ""
        with self._conn() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_TRAVA_FILA, maquina))
            reservado = conn.execute(
                """
                SELECT COALESCE(sum(memoria_reservada_bytes), 0) AS total FROM lurkqvd.execucoes
                 WHERE status = 'rodando' AND maquina = %s
                """,
                (maquina,),
            ).fetchone()["total"]
            fila = [
                memoria.Pendente(r["id"], int(r["historico"] or reserva_padrao), float(r["espera_s"]))
                for r in conn.execute(
                    """
                    SELECT e.id, extract(epoch FROM now() - e.solicitado_em) AS espera_s,
                           (SELECT max(u.memoria_pico_bytes) FROM (
                                SELECT h.memoria_pico_bytes FROM lurkqvd.execucoes h
                                 WHERE h.carga_id = e.carga_id AND h.status = 'sucesso'
                                   AND h.memoria_pico_bytes IS NOT NULL
                                 ORDER BY h.finalizado_em DESC LIMIT 3) u) AS historico
                      FROM lurkqvd.execucoes e
                     WHERE e.status = 'pendente'
                     ORDER BY e.solicitado_em
                     LIMIT 100
                    """
                ).fetchall()
            ]
            while True:
                escolhida = memoria.escolher(fila, int(reservado), capacidade if capacidade is not None else 2**62,
                                             espera_max_s)
                if escolhida is None:
                    return None
                row = conn.execute(
                    """
                    UPDATE lurkqvd.execucoes e
                       SET status = 'rodando', iniciado_em = now(), maquina = %s, memoria_reservada_bytes = %s
                     WHERE e.id = (SELECT id FROM lurkqvd.execucoes
                                    WHERE id = %s AND status = 'pendente'
                                      FOR UPDATE SKIP LOCKED)
                 RETURNING e.id, e.carga_id
                    """,
                    (maquina, escolhida.estimativa if capacidade is not None else None, escolhida.id),
                ).fetchone()
                if row:
                    break
                fila.remove(escolhida)  # outra máquina pegou antes: decide de novo sem ela
            carga = conn.execute("SELECT * FROM lurkqvd.cargas WHERE id = %s", (row["carga_id"],)).fetchone()
        return row["id"], row["carga_id"], self._para_carga(carga)

    def registrar_memoria(self, execucao_id: int, pico_bytes: int | None) -> None:
        """Quanto a execução fez o worker crescer: base da reserva das próximas execuções da carga."""
        if pico_bytes is None:
            return
        with self._conn() as conn:
            conn.execute("UPDATE lurkqvd.execucoes SET memoria_pico_bytes = %s WHERE id = %s", (pico_bytes, execucao_id))

    def linhas_da_ultima(self, carga_id: int) -> int | None:
        """Linhas da última execução com sucesso, a previsão do percentual. None se a consulta ou a fonte
        da carga mudou depois dela (a contagem antiga seria de outra consulta)."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT e.linhas,
                       EXISTS (SELECT 1 FROM lurkqvd.auditoria a
                                WHERE a.alvo_tipo = 'carga' AND a.alvo_id = e.carga_id::text
                                  AND a.acao = 'carga.alterar' AND a.criado_em > e.iniciado_em
                                  AND a.detalhes -> 'antes' ?| array['query', 'fonte_id']) AS alterada
                  FROM lurkqvd.execucoes e
                 WHERE e.carga_id = %s AND e.status = 'sucesso' AND e.linhas IS NOT NULL
                 ORDER BY e.iniciado_em DESC LIMIT 1
                """,
                (carga_id,),
            ).fetchone()
        return int(row["linhas"]) if row and not row["alterada"] else None

    def finalizar_sucesso(self, execucao_id: int, carga_id: int, r: ResultadoCarga) -> None:
        """Grava as métricas e guarda o file_id na carga (primeiro upload ou recriação)."""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE lurkqvd.execucoes
                   SET status = 'sucesso', finalizado_em = now(),
                       linhas = %s, colunas = %s, tamanho_bytes = %s,
                       seg_extracao = %s, seg_geracao = %s, seg_upload = %s,
                       composicao = %s
                 WHERE id = %s
                """,
                (r.linhas, r.colunas, r.tamanho_bytes,
                 r.seg_extracao, r.seg_geracao, r.seg_upload,
                 Jsonb(r.composicao) if getattr(r, "composicao", None) else None, execucao_id),
            )
            conn.execute(
                """
                UPDATE lurkqvd.cargas SET file_id = %s, atualizado_em = now()
                 WHERE id = %s AND file_id IS DISTINCT FROM %s::uuid
                """,
                (r.file_id, carga_id, r.file_id),
            )

    # ------------------------------------------------------------------ #
    # Progresso e cancelamento
    # ------------------------------------------------------------------ #
    def registrar_progresso(self, execucao_id: int, progresso: dict) -> bool:
        """Grava o progresso da execução. Retorna True se alguém pediu para cancelar."""
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE lurkqvd.execucoes SET progresso = %s
                 WHERE id = %s AND status = 'rodando'
             RETURNING cancelar_em IS NOT NULL AS cancelar
                """,
                (Jsonb(progresso), execucao_id),
            ).fetchone()
        return bool(row and row["cancelar"])

    def pedir_cancelamento(self, execucao_id: int, usuario_id: int | None) -> dict | None:
        """Pede o cancelamento. Retorna a execução atualizada (None se não existe).

        - pendente: sai da fila na hora (status 'cancelado');
        - rodando com worker vivo: marca cancelar_em; o worker para no próximo ponto seguro;
        - rodando sem worker vivo (terminal fechado, máquina caiu): cancela na hora, sem esperar
          o limite de execução travada.
        """
        with self._conn() as conn:
            e = conn.execute(
                "SELECT id, carga_id, status FROM lurkqvd.execucoes WHERE id = %s FOR UPDATE", (execucao_id,)
            ).fetchone()
            if not e:
                return None
            if e["status"] not in ("pendente", "rodando"):
                raise OperacaoNaoPermitida("Essa execução já terminou.")
            vivo = conn.execute(
                """
                SELECT 1 FROM lurkqvd.workers
                 WHERE execucao_id = %s AND encerrado_em IS NULL
                   AND ultimo_sinal > now() - make_interval(secs => %s)
                """,
                (execucao_id, self.SEGUNDOS_SEM_SINAL),
            ).fetchone()
            if e["status"] == "pendente" or not vivo:
                motivo = ("Cancelada antes de começar." if e["status"] == "pendente"
                          else "Cancelada: o worker que rodava a carga parou de responder.")
                conn.execute(
                    """
                    UPDATE lurkqvd.execucoes
                       SET status = 'cancelado', finalizado_em = now(), erro = %s,
                           cancelar_em = now(), cancelado_por = %s
                     WHERE id = %s
                    """,
                    (motivo, usuario_id, execucao_id),
                )
                imediato = True
            else:
                conn.execute(
                    "UPDATE lurkqvd.execucoes SET cancelar_em = now(), cancelado_por = %s WHERE id = %s",
                    (usuario_id, execucao_id),
                )
                imediato = False
            self._auditar(conn, usuario_id, "execucao.cancelar", "carga", e["carga_id"],
                          {"execucao_id": execucao_id, "status_antes": e["status"], "imediato": imediato})
        return self.buscar_execucao(execucao_id)

    def finalizar_cancelada(self, execucao_id: int, progresso: dict | None = None) -> None:
        fase = (progresso or {}).get("fase")
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE lurkqvd.execucoes
                   SET status = 'cancelado', finalizado_em = now(), progresso = COALESCE(%s, progresso),
                       erro = %s
                 WHERE id = %s
                """,
                (Jsonb(progresso) if progresso else None,
                 f"Cancelada a pedido durante a fase “{fase}”." if fase else "Cancelada a pedido.", execucao_id),
            )

    def finalizar_erro(self, execucao_id: int, erro: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE lurkqvd.execucoes SET status = 'erro', finalizado_em = now(), erro = %s WHERE id = %s",
                (erro[:5000], execucao_id),
            )

    def recuperar_travadas(self, minutos: int | None = None) -> int:
        """Marca como erro execuções 'rodando' há mais de N minutos.

        Se o worker morrer no meio (queda, reinício da máquina), a execução ficaria
        'rodando' para sempre, e o índice único bloquearia novas execuções da carga.
        """
        with self._conn() as conn:
            if minutos is None:
                minutos = int(self._config(conn, "execucao", {}).get("limite_travada_min", 60))
            cur = conn.execute(
                """
                UPDATE lurkqvd.execucoes
                   SET status = CASE WHEN cancelar_em IS NOT NULL THEN 'cancelado' ELSE 'erro' END,
                       finalizado_em = now(),
                       erro = 'Execução interrompida (worker parou no meio); marcada pelo recuperar_travadas.'
                 WHERE status = 'rodando'
                   AND iniciado_em < now() - make_interval(mins => %s)
                """,
                (minutos,),
            )
            return cur.rowcount

    # ------------------------------------------------------------------ #
    # Tokens de API (só o hash fica guardado)
    # ------------------------------------------------------------------ #
    PREFIXO_TOKEN = "lqvd_"

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def criar_token_api(self, nome: str, permissao: str, validade_dias: int | None, usuario_id: int) -> tuple[dict, str]:
        """Cria o token e devolve (linha, token em texto). O texto só existe neste momento."""
        prefixo = f"{self.PREFIXO_TOKEN}{secrets.token_hex(3)}"
        token = f"{prefixo}_{secrets.token_urlsafe(32)}"
        expira = datetime.now(timezone.utc) + timedelta(days=validade_dias) if validade_dias else None
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO lurkqvd.tokens_api (nome, prefixo, hash, permissao, expira_em, criado_por)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (nome.strip(), prefixo, self._hash_token(token), permissao, expira, usuario_id),
            ).fetchone()
            self._auditar(conn, usuario_id, "token.criar", "token", row["id"],
                          {"nome": nome.strip(), "permissao": permissao, "prefixo": prefixo,
                           "validade_dias": validade_dias})
        return next(t for t in self.listar_tokens_api() if t["id"] == row["id"]), token

    def listar_tokens_api(self) -> list[dict]:
        sql = """
            SELECT t.id, t.nome, t.prefixo, t.permissao, t.expira_em, t.criado_em, t.ultimo_uso, t.ultimo_ip,
                   t.revogado_em, u.nome AS criado_por_nome, r.nome AS revogado_por_nome,
                   CASE WHEN t.revogado_em IS NOT NULL THEN 'revogado'
                        WHEN t.expira_em IS NOT NULL AND t.expira_em <= now() THEN 'vencido'
                        ELSE 'ativo' END AS estado,
                   (SELECT count(*) FROM lurkqvd.execucoes e WHERE e.token_id = t.id) AS execucoes
              FROM lurkqvd.tokens_api t
              LEFT JOIN lurkqvd.usuarios u ON u.id = t.criado_por
              LEFT JOIN lurkqvd.usuarios r ON r.id = t.revogado_por
             ORDER BY (t.revogado_em IS NULL) DESC, t.criado_em DESC
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchall()

    def revogar_token_api(self, token_id: int, usuario_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE lurkqvd.tokens_api SET revogado_em = now(), revogado_por = %s
                 WHERE id = %s AND revogado_em IS NULL RETURNING nome, prefixo
                """,
                (usuario_id, token_id),
            ).fetchone()
            if row:
                self._auditar(conn, usuario_id, "token.revogar", "token", token_id,
                              {"nome": row["nome"], "prefixo": row["prefixo"]})
        return row is not None

    def validar_token_api(self, token: str, ip: str | None = None) -> dict | None:
        """Token ativo (não revogado nem vencido) ou None. Registra o uso (no máximo 1 vez por minuto)."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, nome, prefixo, permissao FROM lurkqvd.tokens_api
                 WHERE hash = %s AND revogado_em IS NULL AND (expira_em IS NULL OR expira_em > now())
                """,
                (self._hash_token(token),),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE lurkqvd.tokens_api SET ultimo_uso = now(), ultimo_ip = %s
                     WHERE id = %s AND (ultimo_uso IS NULL OR ultimo_uso < now() - interval '1 minute')
                    """,
                    (ip, row["id"]),
                )
        return row

    # ------------------------------------------------------------------ #
    # Fontes de dados (a senha fica nos segredos)
    # ------------------------------------------------------------------ #
    _CAMPOS_FONTE = ("nome", "tipo", "host", "porta", "banco", "usuario", "opcoes")

    def listar_fontes(self) -> list[dict]:
        sql = """
            SELECT f.*, (SELECT count(*) FROM lurkqvd.cargas c
                          WHERE c.fonte_id = f.id OR (c.fonte_id IS NULL AND f.padrao)) AS qtd_cargas
              FROM lurkqvd.fontes f
             ORDER BY f.padrao DESC, lower(f.nome)
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchall()

    def buscar_fonte(self, fonte_id: int) -> dict | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM lurkqvd.fontes WHERE id = %s", (fonte_id,)).fetchone()

    def fonte_para_execucao(self, fonte_id: int | None) -> dict | None:
        """A fonte da carga; sem fonte definida, a padrão; sem padrão, None (conexão do servidor)."""
        with self._conn() as conn:
            if fonte_id is not None:
                return conn.execute("SELECT * FROM lurkqvd.fontes WHERE id = %s", (fonte_id,)).fetchone()
            return conn.execute("SELECT * FROM lurkqvd.fontes WHERE padrao").fetchone()

    def criar_fonte(self, dados: dict, usuario_id: int, ultimo_teste: dict | None) -> dict:
        with self._conn() as conn:
            if dados.get("padrao"):
                conn.execute("UPDATE lurkqvd.fontes SET padrao = false WHERE padrao")
            fonte = conn.execute(
                """
                INSERT INTO lurkqvd.fontes (nome, tipo, host, porta, banco, usuario, opcoes, padrao,
                                            ultimo_teste, criado_por, atualizado_por)
                VALUES (%(nome)s, %(tipo)s, %(host)s, %(porta)s, %(banco)s, %(usuario)s, %(opcoes)s,
                        %(padrao)s, %(teste)s, %(u)s, %(u)s)
                RETURNING *
                """,
                {**dados, "opcoes": Jsonb(dados.get("opcoes") or {}), "padrao": bool(dados.get("padrao")),
                 "teste": Jsonb(ultimo_teste) if ultimo_teste else None, "u": usuario_id},
            ).fetchone()
            self._auditar(conn, usuario_id, "fonte.criar", "fonte", fonte["id"],
                          {"nome": fonte["nome"], "tipo": fonte["tipo"], "host": fonte["host"],
                           "banco": fonte["banco"], "padrao": fonte["padrao"]})
        return fonte

    def alterar_fonte(self, fonte_id: int, dados: dict, usuario_id: int, *, ultimo_teste: dict | None,
                      senha_trocada: bool) -> dict | None:
        with self._conn() as conn:
            antes = conn.execute("SELECT * FROM lurkqvd.fontes WHERE id = %s FOR UPDATE", (fonte_id,)).fetchone()
            if not antes:
                return None
            novo = {c: dados.get(c, antes[c]) for c in self._CAMPOS_FONTE}
            fonte = conn.execute(
                """
                UPDATE lurkqvd.fontes
                   SET nome = %(nome)s, tipo = %(tipo)s, host = %(host)s, porta = %(porta)s, banco = %(banco)s,
                       usuario = %(usuario)s, opcoes = %(opcoes)s, ultimo_teste = COALESCE(%(teste)s, ultimo_teste),
                       atualizado_por = %(u)s, atualizado_em = now()
                 WHERE id = %(id)s
                RETURNING *
                """,
                {**novo, "opcoes": Jsonb(novo["opcoes"] or {}), "teste": Jsonb(ultimo_teste) if ultimo_teste else None,
                 "u": usuario_id, "id": fonte_id},
            ).fetchone()
            mudou = {c: {"de": antes[c], "para": novo[c]} for c in self._CAMPOS_FONTE if antes[c] != novo[c]}
            if senha_trocada:
                mudou["senha"] = "trocada"
            if mudou:
                self._auditar(conn, usuario_id, "fonte.alterar", "fonte", fonte_id, {"nome": fonte["nome"], **mudou})
        return fonte

    def definir_fonte_padrao(self, fonte_id: int, usuario_id: int) -> bool:
        with self._conn() as conn:
            if not conn.execute("SELECT 1 FROM lurkqvd.fontes WHERE id = %s", (fonte_id,)).fetchone():
                return False
            conn.execute("UPDATE lurkqvd.fontes SET padrao = false WHERE padrao AND id <> %s", (fonte_id,))
            fonte = conn.execute(
                "UPDATE lurkqvd.fontes SET padrao = true WHERE id = %s RETURNING nome", (fonte_id,)
            ).fetchone()
            self._auditar(conn, usuario_id, "fonte.padrao", "fonte", fonte_id, {"nome": fonte["nome"]})
        return True

    def remover_fonte(self, fonte_id: int, usuario_id: int) -> str | None:
        """Remove se nenhuma carga depende dela. Retorna o nome removido; None se não existir."""
        with self._conn() as conn:
            fonte = conn.execute("SELECT * FROM lurkqvd.fontes WHERE id = %s FOR UPDATE", (fonte_id,)).fetchone()
            if not fonte:
                return None
            em_uso = conn.execute(
                "SELECT count(*) AS n FROM lurkqvd.cargas WHERE fonte_id = %s OR (fonte_id IS NULL AND %s)",
                (fonte_id, fonte["padrao"]),
            ).fetchone()["n"]
            if em_uso:
                raise OperacaoNaoPermitida(
                    f"{em_uso} carga(s) usam essa fonte. Mude a fonte delas antes de remover."
                    + (" Ela também é a padrão." if fonte["padrao"] else "")
                )
            conn.execute("DELETE FROM lurkqvd.fontes WHERE id = %s", (fonte_id,))
            self._auditar(conn, usuario_id, "fonte.remover", "fonte", fonte_id, {"nome": fonte["nome"]})
        return fonte["nome"]

    def salvar_teste_fonte(self, fonte_id: int, teste: dict) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE lurkqvd.fontes SET ultimo_teste = %s WHERE id = %s", (Jsonb(teste), fonte_id))

    # ------------------------------------------------------------------ #
    # Workers (sinal de vida) e configurações gerais
    # ------------------------------------------------------------------ #
    SEGUNDOS_SEM_SINAL = 60  # worker sem sinal há mais que isso é considerado parado

    def registrar_worker(self, worker_id: str, host: str, pid: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO lurkqvd.workers (id, host, pid) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                   SET iniciado_em = now(), ultimo_sinal = now(), execucao_id = NULL, encerrado_em = NULL
                """,
                (worker_id, host, pid),
            )

    def sinal_worker(self, worker_id: str, execucao_id: int | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE lurkqvd.workers SET ultimo_sinal = now(), execucao_id = %s WHERE id = %s",
                (execucao_id, worker_id),
            )

    def encerrar_worker(self, worker_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE lurkqvd.workers SET encerrado_em = now(), execucao_id = NULL WHERE id = %s",
                (worker_id,),
            )

    def status_sistema(self) -> dict:
        """Workers vistos nas últimas 24h, fila e configurações (tela Worker e agenda + aviso do painel)."""
        with self._conn() as conn:
            workers = conn.execute(
                """
                SELECT w.id, w.host, w.pid, w.iniciado_em, w.ultimo_sinal, w.encerrado_em,
                       w.execucao_id, c.nome AS carga_nome,
                       CASE WHEN w.encerrado_em IS NOT NULL THEN 'encerrado'
                            WHEN w.ultimo_sinal > now() - make_interval(secs => %s) THEN 'ativo'
                            ELSE 'sem_sinal' END AS estado
                  FROM lurkqvd.workers w
                  LEFT JOIN lurkqvd.execucoes e ON e.id = w.execucao_id
                  LEFT JOIN lurkqvd.cargas c ON c.id = e.carga_id
                 WHERE w.ultimo_sinal > now() - interval '24 hours'
                 ORDER BY (w.encerrado_em IS NULL) DESC, w.ultimo_sinal DESC
                """,
                (self.SEGUNDOS_SEM_SINAL,),
            ).fetchall()
            fila = conn.execute(
                """
                SELECT count(*) FILTER (WHERE status = 'pendente') AS pendentes,
                       count(*) FILTER (WHERE status = 'rodando')  AS rodando,
                       min(solicitado_em) FILTER (WHERE status = 'pendente') AS pendente_desde
                  FROM lurkqvd.execucoes
                 WHERE status IN ('pendente', 'rodando')
                """
            ).fetchone()
            agendadas = conn.execute(
                "SELECT count(*) AS n FROM lurkqvd.cargas WHERE ativo AND agendamento IS NOT NULL"
            ).fetchone()["n"]
            agenda = conn.execute(
                """
                SELECT cf.valor, cf.atualizado_em, u.nome AS por_nome
                  FROM lurkqvd.configuracoes cf
                  LEFT JOIN lurkqvd.usuarios u ON u.id = cf.atualizado_por
                 WHERE cf.chave = 'agenda'
                """
            ).fetchone()
            execucao = self._config(conn, "execucao", {})
            qlik_status = self._config(conn, "qlik_status", {})
            ultimo_sinal = conn.execute("SELECT max(ultimo_sinal) AS t FROM lurkqvd.workers").fetchone()["t"]

        valor_agenda = (agenda or {}).get("valor") or {}
        return {
            "workers": workers,
            "workers_ativos": sum(1 for w in workers if w["estado"] == "ativo"),
            "ultimo_sinal": ultimo_sinal,
            "fila": {**fila, "agendadas": agendadas},
            "agenda": {
                "pausada": bool(valor_agenda.get("pausada")),
                "motivo": valor_agenda.get("motivo"),
                "desde": agenda["atualizado_em"] if agenda else None,
                "por_nome": agenda["por_nome"] if agenda else None,
            },
            "limite_travada_min": int(execucao.get("limite_travada_min", 60)),
            "fuso_padrao": FUSO_PADRAO,
            "qlik": {
                "ok": qlik_status.get("ok"),
                "expira_em": qlik_status.get("expira_em"),
                "verificado_em": qlik_status.get("verificado_em"),
            },
        }

    def pausar_agenda(self, pausada: bool, motivo: str | None, usuario_id: int) -> None:
        """Pausa/retoma todos os agendamentos.

        Ao retomar, recalcula o próximo horário de cada carga a partir de agora:
        o que venceu durante a pausa NÃO roda de uma vez ao liberar.
        """
        valor = {"pausada": pausada, "motivo": (motivo or "").strip() or None if pausada else None}
        with self._conn() as conn:
            self._salvar_config(conn, "agenda", valor, usuario_id)
            if not pausada:
                agora = datetime.now(timezone.utc)
                for c in conn.execute(
                    "SELECT id, agendamento, fuso FROM lurkqvd.cargas WHERE agendamento IS NOT NULL FOR UPDATE"
                ).fetchall():
                    prox = proximas_execucoes(c["agendamento"], c["fuso"], 1, agora)[0]
                    conn.execute("UPDATE lurkqvd.cargas SET proxima_execucao = %s WHERE id = %s", (prox, c["id"]))
            self._auditar(conn, usuario_id, "agenda.pausar" if pausada else "agenda.retomar", "sistema", "agenda",
                          {"motivo": valor["motivo"]} if pausada else {})

    def alterar_limite_travada(self, minutos: int, usuario_id: int) -> None:
        with self._conn() as conn:
            antes = self._config(conn, "execucao", {}).get("limite_travada_min")
            self._salvar_config(conn, "execucao", {"limite_travada_min": minutos}, usuario_id)
            self._auditar(conn, usuario_id, "config.alterar", "sistema", "execucao",
                          {"limite_travada_min": {"de": antes, "para": minutos}})

    # --- Qlik Cloud: tenant (config "qlik") e último teste da key (config "qlik_status") ---
    def config_qlik(self, tenant_padrao: str) -> dict:
        with self._conn() as conn:
            linhas = {
                r["chave"]: r
                for r in conn.execute(
                    """
                    SELECT cf.chave, cf.valor, cf.atualizado_em, u.nome AS por_nome
                      FROM lurkqvd.configuracoes cf
                      LEFT JOIN lurkqvd.usuarios u ON u.id = cf.atualizado_por
                     WHERE cf.chave IN ('qlik', 'qlik_status')
                    """
                ).fetchall()
            }
        qlik = linhas.get("qlik")
        return {
            "tenant": ((qlik or {}).get("valor") or {}).get("tenant") or tenant_padrao,
            "alterado_em": qlik["atualizado_em"] if qlik else None,
            "alterado_por": qlik["por_nome"] if qlik else None,
            "status": (linhas.get("qlik_status") or {}).get("valor"),
        }

    def versao_qlik(self):
        """Muda sempre que o tenant ou a key mudam: o worker usa para recriar o client da Qlik."""
        with self._conn() as conn:
            row = conn.execute("SELECT atualizado_em FROM lurkqvd.configuracoes WHERE chave = 'qlik'").fetchone()
        return row["atualizado_em"] if row else None

    def alterar_qlik(self, usuario_id: int, *, tenant: str, tenant_mudou: bool, token_mascara: str | None,
                     chave_id: str | None) -> None:
        """Registra a troca de tenant e/ou de key (a key em si fica só nos segredos)."""
        with self._conn() as conn:
            self._salvar_config(conn, "qlik", {"tenant": tenant}, usuario_id)
            detalhes = {}
            if tenant_mudou:
                detalhes["tenant"] = tenant
            if token_mascara:
                detalhes["api_key"] = {"mascara": token_mascara, "id": chave_id}
            self._auditar(conn, usuario_id, "config.qlik", "sistema", "qlik", detalhes)

    def salvar_status_qlik(self, status: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO lurkqvd.configuracoes (chave, valor) VALUES ('qlik_status', %s)
                ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado_em = now()
                """,
                (Jsonb(status),),
            )

    @staticmethod
    def _config(conn: psycopg.Connection, chave: str, padrao: dict) -> dict:
        row = conn.execute("SELECT valor FROM lurkqvd.configuracoes WHERE chave = %s", (chave,)).fetchone()
        return row["valor"] if row else padrao

    @staticmethod
    def _salvar_config(conn: psycopg.Connection, chave: str, valor: dict, usuario_id: int | None) -> None:
        conn.execute(
            """
            INSERT INTO lurkqvd.configuracoes (chave, valor, atualizado_por) VALUES (%s, %s, %s)
            ON CONFLICT (chave) DO UPDATE
               SET valor = EXCLUDED.valor, atualizado_em = now(), atualizado_por = EXCLUDED.atualizado_por
            """,
            (chave, Jsonb(valor), usuario_id),
        )

    def resumo(self) -> dict:
        """Números da tela inicial: estado das cargas e quanto foi publicado na Qlik."""
        sql = """
            SELECT count(*)                                                    AS total_cargas,
                   count(*) FILTER (WHERE c.ativo)                             AS cargas_ativas,
                   count(*) FILTER (WHERE ult.status = 'erro')                 AS com_erro,
                   count(*) FILTER (WHERE ult.status IN ('pendente','rodando')) AS em_andamento,
                   COALESCE(sum(suc.tamanho_bytes), 0)::bigint                 AS bytes_publicados,
                   (SELECT count(*) FROM lurkqvd.execucoes
                     WHERE solicitado_em > now() - interval '24 hours')        AS execucoes_24h
              FROM lurkqvd.cargas c
              LEFT JOIN LATERAL (
                    SELECT status FROM lurkqvd.execucoes e
                     WHERE e.carga_id = c.id ORDER BY e.solicitado_em DESC LIMIT 1
              ) ult ON true
              LEFT JOIN LATERAL (
                    SELECT tamanho_bytes FROM lurkqvd.execucoes e
                     WHERE e.carga_id = c.id AND e.status = 'sucesso'
                     ORDER BY e.finalizado_em DESC LIMIT 1
              ) suc ON true
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchone()

    def execucoes_recentes(self, limite: int = 10) -> list[dict]:
        """Últimas execuções de todas as cargas, com o nome da carga e de quem pediu."""
        sql = """
            SELECT e.id, e.carga_id, c.nome AS carga_nome, e.status, e.origem,
                   e.solicitado_em, e.iniciado_em, e.finalizado_em,
                   e.linhas, e.tamanho_bytes, e.erro,
                   (COALESCE(e.seg_extracao, 0) + COALESCE(e.seg_geracao, 0) + COALESCE(e.seg_upload, 0)) AS seg_total,
                   u.nome AS usuario_nome, u.email AS usuario_email, u.foto_url AS usuario_foto,
                   t.nome AS token_nome
              FROM lurkqvd.execucoes e
              JOIN lurkqvd.cargas c ON c.id = e.carga_id
              LEFT JOIN lurkqvd.usuarios u ON u.id = e.solicitado_por
              LEFT JOIN lurkqvd.tokens_api t ON t.id = e.token_id
             ORDER BY e.solicitado_em DESC
             LIMIT %s
        """
        with self._conn() as conn:
            return conn.execute(sql, (limite,)).fetchall()

    def alinhar_fuso(self) -> int:
        """Se LURKQVD_FUSO mudou desde a última subida, recalcula o próximo horário dos agendamentos
        que seguem o fuso da instalação (coluna fuso vazia). Devolve quantos foram recalculados."""
        with self._conn() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_TRAVA_FUSO,))
            # antes desta configuração existir, o fuso era sempre o de São Paulo
            anterior = self._config(conn, "fuso", {}).get("nome", "America/Sao_Paulo")
            if anterior == FUSO_PADRAO:
                return 0
            recalculados = 0
            agora = datetime.now(timezone.utc)
            for tabela in ("cargas", "aplicacoes"):
                for r in conn.execute(
                    f"SELECT id, agendamento FROM lurkqvd.{tabela}"
                    "  WHERE agendamento IS NOT NULL AND fuso IS NULL FOR UPDATE"
                ).fetchall():
                    try:
                        prox = proximas_execucoes(r["agendamento"], None, 1, agora)[0]
                    except AgendamentoInvalido:
                        continue
                    conn.execute(f"UPDATE lurkqvd.{tabela} SET proxima_execucao = %s WHERE id = %s", (prox, r["id"]))
                    recalculados += 1
            self._salvar_config(conn, "fuso", {"nome": FUSO_PADRAO}, None)
            return recalculados

    def execucoes_por_dia(self, dias: int = 14, fuso: str = FUSO_PADRAO) -> list[dict]:
        """Execuções por dia (no fuso local) nos últimos N dias, incluindo dias sem nenhuma."""
        sql = """
            WITH dias AS (
                SELECT generate_series(
                           (now() AT TIME ZONE %(fuso)s)::date - (%(dias)s - 1),
                           (now() AT TIME ZONE %(fuso)s)::date,
                           interval '1 day')::date AS dia
            )
            SELECT d.dia,
                   count(e.id) FILTER (WHERE e.status = 'sucesso')                 AS sucesso,
                   count(e.id) FILTER (WHERE e.status = 'erro')                    AS erro,
                   count(e.id) FILTER (WHERE e.status IN ('pendente', 'rodando'))  AS em_andamento,
                   COALESCE(array_agg(DISTINCT c.nome) FILTER (WHERE e.status = 'erro'), '{}') AS cargas_com_erro
              FROM dias d
              LEFT JOIN lurkqvd.execucoes e
                     ON e.solicitado_em >= d.dia::timestamp AT TIME ZONE %(fuso)s
                    AND e.solicitado_em <  (d.dia + 1)::timestamp AT TIME ZONE %(fuso)s
              LEFT JOIN lurkqvd.cargas c ON c.id = e.carga_id
             GROUP BY d.dia
             ORDER BY d.dia
        """
        with self._conn() as conn:
            return conn.execute(sql, {"dias": dias, "fuso": fuso}).fetchall()

    def ultima_composicao(self, carga_id: int) -> dict | None:
        """Composição da última execução com sucesso que a mediu."""
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT id AS execucao_id, finalizado_em, tamanho_bytes, linhas, composicao
                  FROM lurkqvd.execucoes
                 WHERE carga_id = %s AND status = 'sucesso' AND composicao IS NOT NULL
                 ORDER BY finalizado_em DESC LIMIT 1
                """,
                (carga_id,),
            ).fetchone()

    def buscar_execucao(self, execucao_id: int) -> dict | None:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT e.*, c.nome AS carga_nome, t.nome AS token_nome
                  FROM lurkqvd.execucoes e
                  JOIN lurkqvd.cargas c ON c.id = e.carga_id
                  LEFT JOIN lurkqvd.tokens_api t ON t.id = e.token_id
                 WHERE e.id = %s
                """,
                (execucao_id,),
            ).fetchone()

    def historico(self, carga_id: int, limite: int = 20) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT e.*, u.nome AS usuario_nome, u.email AS usuario_email, u.foto_url AS usuario_foto,
                       t.nome AS token_nome
                  FROM lurkqvd.execucoes e
                  LEFT JOIN lurkqvd.usuarios u ON u.id = e.solicitado_por
                  LEFT JOIN lurkqvd.tokens_api t ON t.id = e.token_id
                 WHERE e.carga_id = %s ORDER BY e.solicitado_em DESC LIMIT %s
                """,
                (carga_id, limite),
            ).fetchall()

    # ------------------------------------------------------------------ #
    # Auditoria
    # ------------------------------------------------------------------ #
    CATEGORIAS_AUDITORIA = {
        "cargas": ("carga.criar", "carga.alterar", "carga.destino", "pasta.criar"),
        "execucoes": ("carga.executar", "execucao.cancelar", "aplicacao.executar", "aplicacao.cancelar"),
        "aplicacoes": ("aplicacao.criar", "aplicacao.alterar", "aplicacao.remover", "aplicacao.mover_carga"),
        "acessos": ("usuario.criar", "usuario.alterar", "usuario.redefinir_senha", "usuario.trocar_senha",
                    "usuario.completar_conta", "convite.criar", "convite.remover", "token.criar", "token.revogar"),
        "sistema": ("agenda.pausar", "agenda.retomar", "config.alterar", "config.qlik",
                    "fonte.criar", "fonte.alterar", "fonte.padrao", "fonte.remover",
                    "config.smtp", "config.smtp_remover", "config.notificacoes"),
        "logins": ("usuario.login",),
    }

    def listar_auditoria(self, *, categoria: str | None = None, usuario_id: int | None = None,
                         incluir_logins: bool = False, antes_de: int | None = None, limite: int = 50) -> list[dict]:
        """Registros de auditoria, do mais novo para o mais antigo (paginação por id: antes_de)."""
        filtros, params = [], {"limite": limite}
        if categoria:
            filtros.append("a.acao = ANY(%(acoes)s)")
            params["acoes"] = list(self.CATEGORIAS_AUDITORIA.get(categoria, ()))
        elif not incluir_logins:
            filtros.append("a.acao <> 'usuario.login'")
        if usuario_id is not None:
            filtros.append("a.usuario_id = %(usuario_id)s")
            params["usuario_id"] = usuario_id
        if antes_de is not None:
            filtros.append("a.id < %(antes_de)s")
            params["antes_de"] = antes_de
        where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        sql = f"""
            SELECT a.id, a.acao, a.alvo_tipo, a.alvo_id, a.detalhes, a.criado_em,
                   a.usuario_id, u.nome AS usuario_nome, u.email AS usuario_email, u.foto_url AS usuario_foto,
                   CASE a.alvo_tipo
                        WHEN 'carga'   THEN c.nome
                        WHEN 'usuario' THEN COALESCE(ua.nome, ua.email)
                        WHEN 'fonte'   THEN COALESCE(fo.nome, a.detalhes->>'nome')
                        WHEN 'token'   THEN a.detalhes->>'nome'
                        ELSE a.alvo_id END AS alvo_nome
              FROM lurkqvd.auditoria a
              LEFT JOIN lurkqvd.usuarios u  ON u.id = a.usuario_id
              LEFT JOIN lurkqvd.cargas c    ON a.alvo_tipo = 'carga'   AND c.id::text  = a.alvo_id
              LEFT JOIN lurkqvd.usuarios ua ON a.alvo_tipo = 'usuario' AND ua.id::text = a.alvo_id
              LEFT JOIN lurkqvd.fontes fo   ON a.alvo_tipo = 'fonte'   AND fo.id::text = a.alvo_id
              {where}
             ORDER BY a.id DESC
             LIMIT %(limite)s
        """
        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()

    def auditar(self, usuario_id: int | None, acao: str, alvo_tipo: str, alvo_id, detalhes: dict | None = None) -> None:
        """Registra uma ação que não passa por outra escrita no banco (ex.: criar pasta na Qlik)."""
        with self._conn() as conn:
            self._auditar(conn, usuario_id, acao, alvo_tipo, alvo_id, detalhes)

    @staticmethod
    def _auditar(conn: psycopg.Connection, usuario_id: int | None, acao: str,
                 alvo_tipo: str, alvo_id, detalhes: dict | None = None) -> None:
        """Grava na MESMA transação da ação: se a ação falhar, o log também não fica."""
        conn.execute(
            """
            INSERT INTO lurkqvd.auditoria (usuario_id, acao, alvo_tipo, alvo_id, detalhes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (usuario_id, acao, alvo_tipo, str(alvo_id), Jsonb(detalhes or {})),
        )
