"""Aplicações: grupos de cargas que alimentam um app da Qlik.

Uma rodada da aplicação ("executar tudo"):
  pendente     -> o worker dispara as cargas (reaproveitando as que já estão em andamento)
  cargas       -> esperando as cargas terminarem
  recarregando -> todas deram certo e a aplicação tem app da Qlik: reload disparado e acompanhado
  sucesso / erro / cancelado
Se alguma carga falhar, o app NÃO é recarregado (não atualiza o app com dados pela metade).

Mixin do Repositorio: usa self._conn() e self._auditar(). As etapas da orquestração "pegam" cada
rodada com UPDATE ... RETURNING / FOR UPDATE SKIP LOCKED, então vários workers podem rodar juntos.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

STATUS_ATIVOS = ("pendente", "cargas", "recarregando")
RELOAD_FIM = ("SUCCEEDED", "FAILED", "CANCELED", "EXCEEDED_LIMIT")


class AplicacaoJaEmExecucao(Exception):
    """A aplicação já tem uma rodada pendente ou em andamento."""

    execucao_id: int | None = None


class AplicacoesMixin:
    # ------------------------------------------------------------------ #
    # Cadastro
    # ------------------------------------------------------------------ #
    _SQL_APLICACOES = """
        SELECT a.*,
               cri.nome AS criador_nome, cri.email AS criador_email, cri.foto_url AS criador_foto,
               COALESCE((SELECT json_agg(json_build_object(
                           'id', c.id, 'nome', c.nome, 'ativo', c.ativo, 'ordem', ac.ordem,
                           'ultimo_status', ult.status, 'ultima_execucao_id', ult.id,
                           'ultima_finalizacao', ult.finalizado_em, 'ultimo_tamanho_bytes', suc.tamanho_bytes,
                           'ultima_duracao', suc.duracao)
                         ORDER BY ac.ordem, c.nome)
                  FROM lurkqvd.aplicacao_cargas ac
                  JOIN lurkqvd.cargas c ON c.id = ac.carga_id
                  LEFT JOIN LATERAL (SELECT id, status, finalizado_em FROM lurkqvd.execucoes e
                                      WHERE e.carga_id = c.id ORDER BY e.solicitado_em DESC LIMIT 1) ult ON true
                  LEFT JOIN LATERAL (SELECT tamanho_bytes,
                                            COALESCE(seg_extracao, 0) + COALESCE(seg_geracao, 0) + COALESCE(seg_upload, 0) AS duracao
                                       FROM lurkqvd.execucoes e
                                      WHERE e.carga_id = c.id AND e.status = 'sucesso'
                                      ORDER BY e.finalizado_em DESC LIMIT 1) suc ON true
                 WHERE ac.aplicacao_id = a.id), '[]'::json) AS cargas,
               ult.id AS ultima_execucao_id, ult.status AS ultimo_status, ult.solicitado_em AS ultima_solicitacao,
               ult.iniciado_em AS ultimo_inicio, ult.finalizado_em AS ultima_finalizacao,
               ult.reload_status AS ultimo_reload_status, ult.erro AS ultimo_erro,
               suc.finalizado_em AS ultimo_sucesso_em,
               EXTRACT(EPOCH FROM (suc.finalizado_em - suc.iniciado_em)) AS ultimo_sucesso_seg,
               EXTRACT(EPOCH FROM (suc.reload_finalizado_em - suc.reload_iniciado_em)) AS ultimo_reload_seg
          FROM lurkqvd.aplicacoes a
          LEFT JOIN lurkqvd.usuarios cri ON cri.id = a.criado_por
          LEFT JOIN LATERAL (SELECT * FROM lurkqvd.execucoes_aplicacao x
                              WHERE x.aplicacao_id = a.id ORDER BY x.solicitado_em DESC LIMIT 1) ult ON true
          LEFT JOIN LATERAL (SELECT * FROM lurkqvd.execucoes_aplicacao x
                              WHERE x.aplicacao_id = a.id AND x.status = 'sucesso'
                              ORDER BY x.finalizado_em DESC LIMIT 1) suc ON true
    """

    def listar_aplicacoes(self) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(self._SQL_APLICACOES + " ORDER BY a.nome").fetchall()

    def buscar_aplicacao(self, aplicacao_id: int) -> dict | None:
        with self._conn() as conn:
            return conn.execute(self._SQL_APLICACOES + " WHERE a.id = %s", (aplicacao_id,)).fetchone()

    def buscar_aplicacao_por_nome(self, nome: str) -> dict | None:
        with self._conn() as conn:
            return conn.execute(self._SQL_APLICACOES + " WHERE a.nome = %s", (nome,)).fetchone()

    def criar_aplicacao(self, dados: dict, usuario_id: int | None) -> int:
        from src.lurkqvd.repository.repositorio import proximas_execucoes

        agendamento = (dados.get("agendamento") or "").strip() or None
        proxima = proximas_execucoes(agendamento)[0] if agendamento else None  # valida o cron
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO lurkqvd.aplicacoes (nome, descricao, qlik_app_id, qlik_app_nome, agendamento,
                                                proxima_execucao, criado_por, atualizado_por)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (dados["nome"].strip(), dados.get("descricao"), dados.get("qlik_app_id"), dados.get("qlik_app_nome"),
                 agendamento, proxima, usuario_id, usuario_id),
            ).fetchone()
            for ordem, carga_id in enumerate(dados.get("carga_ids") or []):
                conn.execute(
                    "INSERT INTO lurkqvd.aplicacao_cargas (aplicacao_id, carga_id, ordem) VALUES (%s, %s, %s)"
                    " ON CONFLICT DO NOTHING", (row["id"], carga_id, ordem))
            self._auditar(conn, usuario_id, "aplicacao.criar", "aplicacao", row["id"],
                          {"nome": dados["nome"], "qlik_app_id": dados.get("qlik_app_id"),
                           "cargas": list(dados.get("carga_ids") or [])})
            return row["id"]

    _CAMPOS_EDITAVEIS = ("nome", "descricao", "qlik_app_id", "qlik_app_nome", "agendamento", "ativo")

    def alterar_aplicacao(self, aplicacao_id: int, campos: dict, usuario_id: int | None) -> dict | None:
        from src.lurkqvd.repository.repositorio import proximas_execucoes

        campos = {k: v for k, v in campos.items() if k in self._CAMPOS_EDITAVEIS}
        if "agendamento" in campos:
            campos["agendamento"] = (campos["agendamento"] or "").strip() or None
            campos["proxima_execucao"] = proximas_execucoes(campos["agendamento"])[0] if campos["agendamento"] else None
        if "qlik_app_id" in campos and not campos["qlik_app_id"]:
            campos["qlik_app_id"], campos["qlik_app_nome"] = None, None
        if not campos:
            return self.buscar_aplicacao(aplicacao_id)
        with self._conn() as conn:
            antes = conn.execute("SELECT * FROM lurkqvd.aplicacoes WHERE id = %s FOR UPDATE", (aplicacao_id,)).fetchone()
            if not antes:
                return None
            sets = ", ".join(f"{k} = %s" for k in campos)
            conn.execute(f"UPDATE lurkqvd.aplicacoes SET {sets}, atualizado_em = now(), atualizado_por = %s WHERE id = %s",
                         (*campos.values(), usuario_id, aplicacao_id))
            mudou = {k: {"de": antes[k], "para": v} for k, v in campos.items()
                     if k != "proxima_execucao" and antes.get(k) != v}
            if mudou:
                self._auditar(conn, usuario_id, "aplicacao.alterar", "aplicacao", aplicacao_id, mudou)
        return self.buscar_aplicacao(aplicacao_id)

    def remover_aplicacao(self, aplicacao_id: int, usuario_id: int | None) -> str | None:
        """Remove a aplicação (as cargas continuam existindo). Bloqueia se houver rodada ativa."""
        from src.lurkqvd.repository.repositorio import OperacaoNaoPermitida

        with self._conn() as conn:
            app = conn.execute("SELECT nome FROM lurkqvd.aplicacoes WHERE id = %s FOR UPDATE", (aplicacao_id,)).fetchone()
            if not app:
                return None
            ativa = conn.execute("SELECT 1 FROM lurkqvd.execucoes_aplicacao WHERE aplicacao_id = %s AND status = ANY(%s)",
                                 (aplicacao_id, list(STATUS_ATIVOS))).fetchone()
            if ativa:
                raise OperacaoNaoPermitida("A aplicação está executando agora. Cancele ou espere terminar.")
            conn.execute("DELETE FROM lurkqvd.aplicacoes WHERE id = %s", (aplicacao_id,))
            self._auditar(conn, usuario_id, "aplicacao.remover", "aplicacao", aplicacao_id, {"nome": app["nome"]})
            return app["nome"]

    def mover_carga(self, carga_id: int, origem_id: int | None, destino_id: int | None, *,
                    copiar: bool, posicao: int | None, usuario_id: int | None) -> None:
        """Arrastar e soltar: tira a carga da origem (a menos que copiar) e põe no destino, na posição.
        origem None = vinha de "sem aplicação"; destino None = só tirar da origem."""
        with self._conn() as conn:
            if origem_id is not None and not copiar and origem_id != destino_id:
                conn.execute("DELETE FROM lurkqvd.aplicacao_cargas WHERE aplicacao_id = %s AND carga_id = %s",
                             (origem_id, carga_id))
            if destino_id is not None:
                ids = [r["carga_id"] for r in conn.execute(
                    "SELECT carga_id FROM lurkqvd.aplicacao_cargas WHERE aplicacao_id = %s ORDER BY ordem, carga_id",
                    (destino_id,)).fetchall() if r["carga_id"] != carga_id]
                pos = len(ids) if posicao is None else max(0, min(posicao, len(ids)))
                ids.insert(pos, carga_id)
                conn.execute("DELETE FROM lurkqvd.aplicacao_cargas WHERE aplicacao_id = %s", (destino_id,))
                for ordem, cid in enumerate(ids):
                    conn.execute("INSERT INTO lurkqvd.aplicacao_cargas (aplicacao_id, carga_id, ordem) VALUES (%s, %s, %s)",
                                 (destino_id, cid, ordem))
            self._auditar(conn, usuario_id, "aplicacao.mover_carga", "carga", carga_id,
                          {"de": origem_id, "para": destino_id, "copiar": copiar})

    # ------------------------------------------------------------------ #
    # Rodadas
    # ------------------------------------------------------------------ #
    def enfileirar_aplicacao(self, aplicacao_id: int, origem: str = "manual", usuario_id: int | None = None,
                             token_id: int | None = None) -> int:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    INSERT INTO lurkqvd.execucoes_aplicacao (aplicacao_id, origem, solicitado_por, token_id)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
                    (aplicacao_id, origem, usuario_id, token_id),
                ).fetchone()
                self._auditar(conn, usuario_id, "aplicacao.executar", "aplicacao", aplicacao_id,
                              {"execucao_aplicacao_id": row["id"], "origem": origem, "token_id": token_id})
                return row["id"]
        except psycopg.errors.UniqueViolation as e:
            with self._conn() as conn:
                ativa = conn.execute("SELECT id FROM lurkqvd.execucoes_aplicacao WHERE aplicacao_id = %s AND status = ANY(%s)",
                                     (aplicacao_id, list(STATUS_ATIVOS))).fetchone()
            erro = AplicacaoJaEmExecucao("A aplicação já está executando.")
            erro.execucao_id = ativa["id"] if ativa else None
            raise erro from e

    def execucao_aplicacao(self, execucao_aplicacao_id: int) -> dict | None:
        """A rodada com o status de cada carga (inclui o progresso ao vivo de quem está rodando)."""
        with self._conn() as conn:
            x = conn.execute(
                """
                SELECT x.*, a.nome AS aplicacao_nome, a.qlik_app_nome,
                       u.nome AS usuario_nome, u.email AS usuario_email, u.foto_url AS usuario_foto,
                       t.nome AS token_nome
                  FROM lurkqvd.execucoes_aplicacao x
                  JOIN lurkqvd.aplicacoes a ON a.id = x.aplicacao_id
                  LEFT JOIN lurkqvd.usuarios u ON u.id = x.solicitado_por
                  LEFT JOIN lurkqvd.tokens_api t ON t.id = x.token_id
                 WHERE x.id = %s
                """,
                (execucao_aplicacao_id,),
            ).fetchone()
            if not x:
                return None
            x["cargas"] = conn.execute(
                """
                SELECT c.id AS carga_id, c.nome, l.disparada_aqui,
                       e.id AS execucao_id, e.status, e.progresso, e.iniciado_em, e.finalizado_em,
                       e.linhas, e.tamanho_bytes, e.erro, e.cancelar_em,
                       COALESCE(e.seg_extracao, 0) + COALESCE(e.seg_geracao, 0) + COALESCE(e.seg_upload, 0) AS duracao
                  FROM lurkqvd.execucao_aplicacao_cargas l
                  JOIN lurkqvd.cargas c ON c.id = l.carga_id
                  LEFT JOIN lurkqvd.execucoes e ON e.id = l.execucao_id
                  LEFT JOIN lurkqvd.aplicacao_cargas ac ON ac.aplicacao_id = %s AND ac.carga_id = c.id
                 WHERE l.execucao_aplicacao_id = %s
                 ORDER BY ac.ordem NULLS LAST, c.nome
                """,
                (x["aplicacao_id"], execucao_aplicacao_id),
            ).fetchall()
            return x

    def historico_aplicacao(self, aplicacao_id: int, limite: int = 20) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT x.id, x.status, x.origem, x.solicitado_em, x.iniciado_em, x.finalizado_em,
                       x.reload_status, x.reload_iniciado_em, x.reload_finalizado_em, x.erro,
                       u.nome AS usuario_nome, u.email AS usuario_email, t.nome AS token_nome,
                       (SELECT count(*) FROM lurkqvd.execucao_aplicacao_cargas l WHERE l.execucao_aplicacao_id = x.id) AS qtd_cargas
                  FROM lurkqvd.execucoes_aplicacao x
                  LEFT JOIN lurkqvd.usuarios u ON u.id = x.solicitado_por
                  LEFT JOIN lurkqvd.tokens_api t ON t.id = x.token_id
                 WHERE x.aplicacao_id = %s
                 ORDER BY x.solicitado_em DESC LIMIT %s
                """,
                (aplicacao_id, limite),
            ).fetchall()

    def pedir_cancelamento_aplicacao(self, execucao_aplicacao_id: int, usuario_id: int | None) -> dict | None:
        """pendente: cancela na hora. cargas: cancela as cargas que ESTA rodada disparou (as reaproveitadas
        seguem, pois servem a outra rodada/agenda) e encerra. recarregando: o worker cancela o reload na Qlik."""
        from src.lurkqvd.repository.repositorio import OperacaoNaoPermitida

        cancelar_cargas: list[int] = []
        with self._conn() as conn:
            x = conn.execute("SELECT id, aplicacao_id, status FROM lurkqvd.execucoes_aplicacao WHERE id = %s FOR UPDATE",
                             (execucao_aplicacao_id,)).fetchone()
            if not x:
                return None
            if x["status"] not in STATUS_ATIVOS:
                raise OperacaoNaoPermitida("Essa execução já terminou.")
            if x["status"] == "recarregando":
                conn.execute("UPDATE lurkqvd.execucoes_aplicacao SET cancelar_em = now(), cancelado_por = %s WHERE id = %s",
                             (usuario_id, execucao_aplicacao_id))
            else:
                if x["status"] == "cargas":
                    cancelar_cargas = [r["execucao_id"] for r in conn.execute(
                        """
                        SELECT l.execucao_id FROM lurkqvd.execucao_aplicacao_cargas l
                          JOIN lurkqvd.execucoes e ON e.id = l.execucao_id
                         WHERE l.execucao_aplicacao_id = %s AND l.disparada_aqui
                           AND e.status IN ('pendente', 'rodando')
                           AND NOT EXISTS (   -- não cancela carga que outra rodada ativa também espera
                                SELECT 1 FROM lurkqvd.execucao_aplicacao_cargas o
                                  JOIN lurkqvd.execucoes_aplicacao ox ON ox.id = o.execucao_aplicacao_id
                                 WHERE o.execucao_id = l.execucao_id AND ox.id <> l.execucao_aplicacao_id
                                   AND ox.status IN ('pendente', 'cargas', 'recarregando'))
                        """,
                        (execucao_aplicacao_id,)).fetchall()]
                conn.execute(
                    """
                    UPDATE lurkqvd.execucoes_aplicacao
                       SET status = 'cancelado', finalizado_em = now(), cancelar_em = now(), cancelado_por = %s,
                           erro = %s
                     WHERE id = %s
                    """,
                    (usuario_id, "Cancelada antes de começar." if x["status"] == "pendente"
                     else "Cancelada durante as cargas; o app da Qlik não foi recarregado.", execucao_aplicacao_id),
                )
            self._auditar(conn, usuario_id, "aplicacao.cancelar", "aplicacao", x["aplicacao_id"],
                          {"execucao_aplicacao_id": execucao_aplicacao_id, "status_antes": x["status"],
                           "cargas_canceladas": cancelar_cargas})
        for execucao_id in cancelar_cargas:
            try:
                self.pedir_cancelamento(execucao_id, usuario_id)
            except Exception:
                pass  # já terminou nesse meio-tempo
        return self.execucao_aplicacao(execucao_aplicacao_id)

    # ------------------------------------------------------------------ #
    # Orquestração (chamada pelo worker a cada poucos segundos)
    # ------------------------------------------------------------------ #
    def orq_iniciar_pendentes(self) -> list[int]:
        """Rodadas pendentes: dispara as cargas ativas da aplicação. Carga que já está na fila ou
        rodando (agenda, outra aplicação, alguém na tela) é reaproveitada, não roda duas vezes."""
        iniciadas = []
        with self._conn() as conn:
            pendentes = conn.execute(
                """
                SELECT x.id, x.aplicacao_id, x.solicitado_por, a.qlik_app_id
                  FROM lurkqvd.execucoes_aplicacao x JOIN lurkqvd.aplicacoes a ON a.id = x.aplicacao_id
                 WHERE x.status = 'pendente'
                 ORDER BY x.solicitado_em
                   FOR UPDATE OF x SKIP LOCKED
                """
            ).fetchall()
            for x in pendentes:
                cargas = conn.execute(
                    """
                    SELECT c.id FROM lurkqvd.aplicacao_cargas ac JOIN lurkqvd.cargas c ON c.id = ac.carga_id
                     WHERE ac.aplicacao_id = %s AND c.ativo ORDER BY ac.ordem, c.nome
                    """,
                    (x["aplicacao_id"],),
                ).fetchall()
                for c in cargas:
                    nova = conn.execute(
                        """
                        INSERT INTO lurkqvd.execucoes (carga_id, origem, solicitado_por)
                        VALUES (%s, 'aplicacao', %s)
                        ON CONFLICT (carga_id) WHERE status IN ('pendente', 'rodando') DO NOTHING
                        RETURNING id
                        """,
                        (c["id"], x["solicitado_por"]),
                    ).fetchone()
                    if nova:
                        execucao_id, aqui = nova["id"], True
                    else:
                        execucao_id = conn.execute(
                            "SELECT id FROM lurkqvd.execucoes WHERE carga_id = %s AND status IN ('pendente', 'rodando')",
                            (c["id"],)).fetchone()["id"]
                        aqui = False
                    conn.execute(
                        """
                        INSERT INTO lurkqvd.execucao_aplicacao_cargas (execucao_aplicacao_id, carga_id, execucao_id, disparada_aqui)
                        VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                        """,
                        (x["id"], c["id"], execucao_id, aqui),
                    )
                conn.execute(
                    "UPDATE lurkqvd.execucoes_aplicacao SET status = 'cargas', iniciado_em = now(), qlik_app_id = %s WHERE id = %s",
                    (x["qlik_app_id"], x["id"]),
                )
                iniciadas.append(x["id"])
        return iniciadas

    def orq_concluir_cargas(self) -> list[dict]:
        """Rodadas cujas cargas terminaram todas. Com erro: encerra (sem reload). Sem app da Qlik:
        sucesso. Com app: marca 'recarregando' e devolve para o worker disparar o reload."""
        para_recarregar = []
        with self._conn() as conn:
            prontas = conn.execute(
                """
                SELECT x.id, x.aplicacao_id, x.qlik_app_id,
                       count(l.carga_id) FILTER (WHERE e.status IN ('erro', 'cancelado')) AS falhas,
                       string_agg(c.nome, ', ') FILTER (WHERE e.status IN ('erro', 'cancelado')) AS nomes_falhas
                  FROM lurkqvd.execucoes_aplicacao x
                  LEFT JOIN lurkqvd.execucao_aplicacao_cargas l ON l.execucao_aplicacao_id = x.id
                  LEFT JOIN lurkqvd.execucoes e ON e.id = l.execucao_id
                  LEFT JOIN lurkqvd.cargas c ON c.id = l.carga_id
                 WHERE x.status = 'cargas'
                 GROUP BY x.id
                HAVING count(l.carga_id) FILTER (WHERE e.status IN ('pendente', 'rodando')) = 0
                """
            ).fetchall()
            for x in prontas:
                travada = conn.execute("SELECT id FROM lurkqvd.execucoes_aplicacao WHERE id = %s AND status = 'cargas' "
                                       "FOR UPDATE SKIP LOCKED", (x["id"],)).fetchone()
                if not travada:
                    continue
                if x["falhas"]:
                    conn.execute(
                        "UPDATE lurkqvd.execucoes_aplicacao SET status = 'erro', finalizado_em = now(), erro = %s WHERE id = %s",
                        (f"{x['falhas']} carga(s) falharam ({x['nomes_falhas']}); o app da Qlik não foi recarregado.", x["id"]))
                elif not x["qlik_app_id"]:
                    conn.execute("UPDATE lurkqvd.execucoes_aplicacao SET status = 'sucesso', finalizado_em = now() WHERE id = %s",
                                 (x["id"],))
                else:
                    conn.execute(
                        "UPDATE lurkqvd.execucoes_aplicacao SET status = 'recarregando', reload_status = 'DISPARANDO', "
                        "reload_iniciado_em = now() WHERE id = %s", (x["id"],))
                    para_recarregar.append({"id": x["id"], "qlik_app_id": x["qlik_app_id"]})
        return para_recarregar

    def orq_registrar_reload(self, execucao_aplicacao_id: int, reload: dict | None, erro: str | None = None) -> None:
        with self._conn() as conn:
            if erro:
                conn.execute(
                    "UPDATE lurkqvd.execucoes_aplicacao SET status = 'erro', finalizado_em = now(), reload_status = 'FAILED', "
                    "reload_finalizado_em = now(), erro = %s WHERE id = %s", (erro[:2000], execucao_aplicacao_id))
            else:
                conn.execute(
                    "UPDATE lurkqvd.execucoes_aplicacao SET reload_id = %s, reload_status = %s, reload_consultado_em = now() "
                    "WHERE id = %s", (reload.get("id"), reload.get("status") or "QUEUED", execucao_aplicacao_id))

    def orq_reloads_para_consultar(self, intervalo_seg: int = 8) -> list[dict]:
        """Reloads em andamento para o worker consultar (no máximo a cada intervalo_seg cada um).
        Também devolve os que pediram cancelamento e os que ficaram sem ID (worker caiu ao disparar)."""
        with self._conn() as conn:
            return conn.execute(
                """
                UPDATE lurkqvd.execucoes_aplicacao x
                   SET reload_consultado_em = now()
                 WHERE x.id IN (
                        SELECT id FROM lurkqvd.execucoes_aplicacao
                         WHERE status = 'recarregando'
                           AND (reload_id IS NOT NULL OR reload_iniciado_em < now() - interval '10 minutes')
                           AND (reload_consultado_em IS NULL
                                OR reload_consultado_em < now() - make_interval(secs => %s)
                                OR cancelar_em IS NOT NULL)
                         FOR UPDATE SKIP LOCKED)
             RETURNING x.id, x.reload_id, x.cancelar_em
                """,
                (intervalo_seg,),
            ).fetchall()

    def orq_atualizar_reload(self, execucao_aplicacao_id: int, reload: dict | None, *, cancelado: bool = False,
                             erro: str | None = None) -> None:
        """Grava o status do reload; nos status finais, encerra a rodada."""
        with self._conn() as conn:
            if erro or reload is None:
                conn.execute(
                    "UPDATE lurkqvd.execucoes_aplicacao SET status = %s, finalizado_em = now(), reload_finalizado_em = now(), "
                    "erro = %s WHERE id = %s",
                    ("cancelado" if cancelado else "erro", erro or "Reload sem ID (o worker caiu ao disparar).",
                     execucao_aplicacao_id))
                return
            status = reload.get("status") or "QUEUED"
            if status not in RELOAD_FIM:
                conn.execute("UPDATE lurkqvd.execucoes_aplicacao SET reload_status = %s WHERE id = %s",
                             (status, execucao_aplicacao_id))
                return
            final = "sucesso" if status == "SUCCEEDED" else "cancelado" if status == "CANCELED" else "erro"
            mensagem = None
            if final == "erro":
                mensagem = (reload.get("errorMessage") or "").strip() or (
                    "O reload passou do limite da Qlik (EXCEEDED_LIMIT)." if status == "EXCEEDED_LIMIT" else "O reload falhou na Qlik.")
                trecho = (reload.get("log") or "").strip().splitlines()[-8:]
                if trecho:
                    mensagem += "\n" + "\n".join(trecho)
            conn.execute(
                """
                UPDATE lurkqvd.execucoes_aplicacao
                   SET status = %s, reload_status = %s, finalizado_em = now(),
                       reload_iniciado_em = COALESCE(%s::timestamptz, reload_iniciado_em),
                       reload_finalizado_em = COALESCE(%s::timestamptz, now()), erro = %s
                 WHERE id = %s
                """,
                (final, status, reload.get("startTime") or None, reload.get("endTime") or None,
                 mensagem[:4000] if mensagem else None, execucao_aplicacao_id),
            )

    def enfileirar_aplicacoes_agendadas(self) -> list[int]:
        from src.lurkqvd.repository.repositorio import AgendamentoInvalido, proximas_execucoes

        criadas: list[int] = []
        with self._conn() as conn:
            if self._config(conn, "agenda", {}).get("pausada"):
                return criadas
            vencidas = conn.execute(
                """
                SELECT id, agendamento, fuso FROM lurkqvd.aplicacoes
                 WHERE ativo AND agendamento IS NOT NULL AND proxima_execucao <= now()
                 ORDER BY proxima_execucao FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            for a in vencidas:
                row = conn.execute(
                    """
                    INSERT INTO lurkqvd.execucoes_aplicacao (aplicacao_id, origem) VALUES (%s, 'agendador')
                    ON CONFLICT (aplicacao_id) WHERE status IN ('pendente', 'cargas', 'recarregando') DO NOTHING
                    RETURNING id
                    """,
                    (a["id"],),
                ).fetchone()
                if row:
                    criadas.append(row["id"])
                    self._auditar(conn, None, "aplicacao.executar", "aplicacao", a["id"],
                                  {"execucao_aplicacao_id": row["id"], "origem": "agendador"})
                try:
                    proxima = proximas_execucoes(a["agendamento"], a["fuso"])[0]
                except AgendamentoInvalido:
                    proxima = None
                conn.execute("UPDATE lurkqvd.aplicacoes SET proxima_execucao = %s WHERE id = %s", (proxima, a["id"]))
        return criadas
