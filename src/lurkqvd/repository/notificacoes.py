"""Notificações por e-mail: configuração do SMTP, preferências, histórico de envios e a "fila" de avisos.

A fila não é uma tabela à parte: cada execução (de carga ou de aplicação) que termina fica com
notificado_em vazio até o worker olhar para ela. O worker "pega" as que terminaram com
UPDATE ... FOR UPDATE SKIP LOCKED (vários workers não avisam a mesma coisa duas vezes) e decide
se vale um e-mail, comparando com a execução anterior (para avisar só quando muda de estado).

Mixin do Repositorio: usa self._conn(), self._config(), self._salvar_config() e self._auditar().
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

PREFERENCIAS_PADRAO = {
    "erros_cargas": True,      # carga terminou com erro
    "erros_aplicacoes": True,  # aplicação terminou com erro (carga falhou ou reload falhou)
    "recuperacao": True,       # voltou a funcionar depois de falhar
    "qlik": True,              # API key da Qlik vencendo ou recusada
    "so_mudanca": True,        # avisar só a 1ª falha seguida (não a cada execução agendada que falhar de novo)
    "para_admins": True,       # todos os admins ativos recebem os avisos
    "extras": [],              # e-mails a mais (ex.: grupo do time)
}

# execução anterior da mesma carga/aplicação que terminou em sucesso ou erro (cancelada não conta)
_ANTERIOR = """
    (SELECT p.status FROM lurkqvd.{tabela} p
      WHERE p.{dono} = x.{dono} AND p.id <> x.id AND p.status IN ('sucesso', 'erro')
        AND p.finalizado_em <= x.finalizado_em
      ORDER BY p.finalizado_em DESC, p.id DESC LIMIT 1)
"""


class NotificacoesMixin:
    # ------------------------------------------------------------------ #
    # SMTP (a senha fica nos segredos)
    # ------------------------------------------------------------------ #
    def config_smtp(self) -> dict:
        with self._conn() as conn:
            linhas = {
                r["chave"]: r
                for r in conn.execute(
                    """
                    SELECT cf.chave, cf.valor, cf.atualizado_em, u.nome AS por_nome
                      FROM lurkqvd.configuracoes cf
                      LEFT JOIN lurkqvd.usuarios u ON u.id = cf.atualizado_por
                     WHERE cf.chave IN ('smtp', 'smtp_status')
                    """
                ).fetchall()
            }
        smtp = linhas.get("smtp")
        return {
            "smtp": (smtp or {}).get("valor") or None,
            "alterado_em": smtp["atualizado_em"] if smtp else None,
            "alterado_por": smtp["por_nome"] if smtp else None,
            "status": (linhas.get("smtp_status") or {}).get("valor"),
        }

    def salvar_smtp(self, usuario_id: int, cfg: dict, *, senha_trocada: bool, status: dict | None) -> None:
        with self._conn() as conn:
            antes = self._config(conn, "smtp", {})
            self._salvar_config(conn, "smtp", cfg, usuario_id)
            if status:
                self._salvar_config(conn, "smtp_status", status, usuario_id)
            mudou = {k: cfg.get(k) for k in ("host", "porta", "seguranca", "usuario", "remetente", "remetente_nome")
                     if cfg.get(k) != antes.get(k)}
            if senha_trocada:
                mudou["senha"] = True
            self._auditar(conn, usuario_id, "config.smtp", "sistema", "smtp", {"criado": not antes, **mudou})

    def salvar_status_smtp(self, status: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO lurkqvd.configuracoes (chave, valor) VALUES ('smtp_status', %s)
                ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado_em = now()
                """,
                (Jsonb(status),),
            )

    def remover_smtp(self, usuario_id: int) -> bool:
        with self._conn() as conn:
            apagou = conn.execute(
                "DELETE FROM lurkqvd.configuracoes WHERE chave IN ('smtp', 'smtp_status')"
            ).rowcount > 0
            if apagou:
                self._auditar(conn, usuario_id, "config.smtp_remover", "sistema", "smtp")
        return apagou

    # ------------------------------------------------------------------ #
    # Preferências (o que avisar e para quem)
    # ------------------------------------------------------------------ #
    def config_notificacoes(self) -> dict:
        with self._conn() as conn:
            return {**PREFERENCIAS_PADRAO, **self._config(conn, "notificacoes", {})}

    def alterar_notificacoes(self, usuario_id: int, valor: dict) -> dict:
        with self._conn() as conn:
            antes = {**PREFERENCIAS_PADRAO, **self._config(conn, "notificacoes", {})}
            novo = {**antes, **valor}
            self._salvar_config(conn, "notificacoes", novo, usuario_id)
            mudou = {k: {"de": antes.get(k), "para": v} for k, v in novo.items() if antes.get(k) != v}
            if mudou:
                self._auditar(conn, usuario_id, "config.notificacoes", "sistema", "notificacoes", mudou)
        return novo

    def emails_admins(self) -> list[str]:
        with self._conn() as conn:
            return [r["email"] for r in conn.execute(
                "SELECT email FROM lurkqvd.usuarios WHERE papel = 'admin' AND ativo AND email LIKE '%%@%%' ORDER BY email"
            ).fetchall()]

    # ------------------------------------------------------------------ #
    # Histórico de envios
    # ------------------------------------------------------------------ #
    def registrar_notificacao(self, tipo: str, assunto: str, para: list[str], ok: bool,
                              erro: str | None = None, detalhes: dict | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO lurkqvd.notificacoes_enviadas (tipo, assunto, destinatarios, ok, erro, detalhes)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (tipo, assunto[:300], para, ok, (erro or None) and erro[:2000], Jsonb(detalhes or {})),
            )

    def notificacoes_recentes(self, limite: int = 20) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT id, tipo, assunto, destinatarios, ok, erro, criado_em
                  FROM lurkqvd.notificacoes_enviadas ORDER BY id DESC LIMIT %s
                """,
                (limite,),
            ).fetchall()

    def marcar_aviso(self, chave: str, valor) -> bool:
        """Guarda o último aviso de um tipo (ex.: qual API key já teve o vencimento avisado).

        Retorna True só para quem mudou o valor: com vários workers, só um manda o e-mail.
        """
        with self._conn() as conn:
            return conn.execute(
                """
                INSERT INTO lurkqvd.configuracoes AS cf (chave, valor) VALUES ('notificacoes_estado', %s)
                ON CONFLICT (chave) DO UPDATE SET valor = cf.valor || EXCLUDED.valor, atualizado_em = now()
                 WHERE cf.valor -> %s IS DISTINCT FROM EXCLUDED.valor -> %s
             RETURNING 1
                """,
                (Jsonb({chave: valor}), chave, chave),
            ).fetchone() is not None

    # ------------------------------------------------------------------ #
    # Execuções que terminaram e ainda não foram avaliadas para aviso
    # ------------------------------------------------------------------ #
    def notif_pegar_execucoes(self, limite: int = 100) -> list[dict]:
        """Marca como vistas e devolve as execuções de carga que terminaram, com o status da anterior."""
        anterior = _ANTERIOR.format(tabela="execucoes", dono="carga_id")
        with self._conn() as conn:
            return conn.execute(
                f"""
                UPDATE lurkqvd.execucoes x SET notificado_em = now()
                 WHERE x.id IN (SELECT id FROM lurkqvd.execucoes
                                 WHERE notificado_em IS NULL AND status IN ('sucesso', 'erro', 'cancelado')
                                 ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)
             RETURNING x.id, x.carga_id, x.status, x.origem, x.erro, x.iniciado_em, x.finalizado_em,
                       (SELECT nome FROM lurkqvd.cargas c WHERE c.id = x.carga_id) AS nome,
                       {anterior} AS status_anterior
                """,
                (limite,),
            ).fetchall()

    def notif_pegar_execucoes_aplicacao(self, limite: int = 100) -> list[dict]:
        anterior = _ANTERIOR.format(tabela="execucoes_aplicacao", dono="aplicacao_id")
        with self._conn() as conn:
            return conn.execute(
                f"""
                UPDATE lurkqvd.execucoes_aplicacao x SET notificado_em = now()
                 WHERE x.id IN (SELECT id FROM lurkqvd.execucoes_aplicacao
                                 WHERE notificado_em IS NULL AND status IN ('sucesso', 'erro', 'cancelado')
                                 ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)
             RETURNING x.id, x.aplicacao_id, x.status, x.origem, x.erro, x.iniciado_em, x.finalizado_em,
                       (SELECT nome FROM lurkqvd.aplicacoes a WHERE a.id = x.aplicacao_id) AS nome,
                       {anterior} AS status_anterior
                """,
                (limite,),
            ).fetchall()
