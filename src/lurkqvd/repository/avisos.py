"""Avisos dentro da ferramenta: o sino do topo e o balão que abre ao entrar.

Cada aviso tem um público (papel mínimo de quem vê) e pode expirar. A leitura é por pessoa
(lurkqvd.avisos_lidos): o balão abre enquanto houver aviso com abrir_ao_entrar que ela não leu.

Mixin do Repositorio: usa self._conn() e self._auditar().
"""

from __future__ import annotations

# quem vê o quê: um papel enxerga os avisos do próprio nível para baixo
_PUBLICOS = {"leitor": ["leitor"], "editor": ["leitor", "editor"], "admin": ["leitor", "editor", "admin"]}

_CAMPOS = """a.id, a.titulo, a.texto, a.link_url, a.link_rotulo, a.publico, a.abrir_ao_entrar, a.origem,
             a.publicado_em, a.expira_em"""


class AvisosMixin:
    def avisos_do_usuario(self, usuario_id: int, papel: str, limite: int = 30) -> list[dict]:
        """Avisos em vigor que a pessoa pode ver, do mais novo para o mais antigo, com 'lido'."""
        sql = f"""
            SELECT {_CAMPOS}, l.lido_em IS NOT NULL AS lido
              FROM lurkqvd.avisos a
              LEFT JOIN lurkqvd.avisos_lidos l ON l.aviso_id = a.id AND l.usuario_id = %(u)s
             WHERE a.publico = ANY(%(publicos)s)
               AND a.publicado_em <= now()
               AND (a.expira_em IS NULL OR a.expira_em > now())
             ORDER BY a.publicado_em DESC, a.id DESC
             LIMIT %(limite)s
        """
        with self._conn() as conn:
            return conn.execute(sql, {"u": usuario_id, "publicos": _PUBLICOS.get(papel, ["leitor"]),
                                      "limite": limite}).fetchall()

    def marcar_avisos_lidos(self, usuario_id: int, papel: str, ids: list[int] | None = None) -> int:
        """Marca como lidos os avisos indicados (None = todos os que a pessoa vê). Devolve quantos eram novos."""
        sql = """
            INSERT INTO lurkqvd.avisos_lidos (aviso_id, usuario_id)
            SELECT a.id, %(u)s FROM lurkqvd.avisos a
             WHERE a.publico = ANY(%(publicos)s)
               AND (%(ids)s::int[] IS NULL OR a.id = ANY(%(ids)s::int[]))
            ON CONFLICT DO NOTHING
        """
        with self._conn() as conn:
            cur = conn.execute(sql, {"u": usuario_id, "publicos": _PUBLICOS.get(papel, ["leitor"]), "ids": ids})
            return cur.rowcount

    def listar_avisos_admin(self) -> list[dict]:
        """Todos os avisos (inclusive os vencidos), com quantas pessoas do público já leram."""
        sql = f"""
            SELECT {_CAMPOS}, a.criado_por, u.nome AS criado_por_nome,
                   (a.expira_em IS NOT NULL AND a.expira_em <= now()) AS expirado,
                   (SELECT count(*) FROM lurkqvd.avisos_lidos l
                      JOIN lurkqvd.usuarios lu ON lu.id = l.usuario_id AND lu.ativo
                     WHERE l.aviso_id = a.id) AS leituras,
                   (SELECT count(*) FROM lurkqvd.usuarios p
                     WHERE p.ativo AND p.papel = ANY(CASE a.publico WHEN 'admin' THEN ARRAY['admin']
                                                                    WHEN 'editor' THEN ARRAY['editor', 'admin']
                                                                    ELSE ARRAY['leitor', 'editor', 'admin'] END)
                   ) AS publico_total
              FROM lurkqvd.avisos a
              LEFT JOIN lurkqvd.usuarios u ON u.id = a.criado_por
             ORDER BY a.publicado_em DESC, a.id DESC
        """
        with self._conn() as conn:
            return conn.execute(sql).fetchall()

    def publicar_aviso(self, usuario_id: int, *, titulo: str, texto: str, link_url: str | None = None,
                       link_rotulo: str | None = None, publico: str = "leitor", abrir_ao_entrar: bool = True,
                       expira_em=None) -> dict:
        with self._conn() as conn:
            aviso = conn.execute(
                f"""
                INSERT INTO lurkqvd.avisos AS a (titulo, texto, link_url, link_rotulo, publico, abrir_ao_entrar,
                                                 expira_em, criado_por)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_CAMPOS}
                """,
                (titulo, texto, link_url, link_rotulo, publico, abrir_ao_entrar, expira_em, usuario_id),
            ).fetchone()
            # quem publica não precisa ver o próprio aviso abrir na tela
            conn.execute("INSERT INTO lurkqvd.avisos_lidos (aviso_id, usuario_id) VALUES (%s, %s)",
                         (aviso["id"], usuario_id))
            self._auditar(conn, usuario_id, "aviso.publicar", "aviso", aviso["id"],
                          {"titulo": titulo, "publico": publico, "abrir_ao_entrar": abrir_ao_entrar})
        return aviso

    def remover_aviso(self, usuario_id: int, aviso_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute("DELETE FROM lurkqvd.avisos WHERE id = %s RETURNING titulo", (aviso_id,)).fetchone()
            if not row:
                return False
            self._auditar(conn, usuario_id, "aviso.remover", "aviso", aviso_id, {"titulo": row["titulo"]})
        return True
