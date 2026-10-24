"""Login: contas com senha e sessões.

Mixin do Repositorio: usa self._conn() e self._auditar().
O token de sessão só existe no navegador; aqui fica o sha256 dele.
"""

from __future__ import annotations

import hashlib
import os
import secrets

PREFIXO_SESSAO = "lqs_"
SESSAO_INATIVA_H = int(os.getenv("LURKQVD_SESSAO_INATIVA_H", "12"))   # sem uso por mais que isso, cai
SESSAO_MAX_DIAS = int(os.getenv("LURKQVD_SESSAO_MAX_DIAS", "7"))      # limite absoluto de uma sessão

# o que as rotas recebem como "usuário atual" (sem o hash da senha)
_CAMPOS_USUARIO = "u.id, u.email, u.nome, u.papel, u.ativo, u.ultimo_login, u.foto_url, u.trocar_senha"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginJaExiste(Exception):
    """Já existe um usuário com esse e-mail/login."""


class AcessoMixin:
    # ------------------------------------------------------------------ #
    # Contas
    # ------------------------------------------------------------------ #
    def usuario_para_login(self, login: str) -> dict | None:
        """Usuário pelo e-mail (ou "admin"), com o hash da senha, para conferir no login."""
        with self._conn() as conn:
            return conn.execute(
                f"SELECT {_CAMPOS_USUARIO}, u.senha_hash FROM lurkqvd.usuarios u WHERE u.email = %s",
                (login.strip().lower(),),
            ).fetchone()

    def usuario_por_id(self, usuario_id: int) -> dict | None:
        with self._conn() as conn:
            return conn.execute(f"SELECT {_CAMPOS_USUARIO}, u.senha_hash FROM lurkqvd.usuarios u WHERE u.id = %s",
                                (usuario_id,)).fetchone()

    def criar_usuario(self, email: str, nome: str | None, papel: str, senha_hash: str, *,
                      trocar_senha: bool = True, criado_por: int | None = None) -> dict:
        email = email.strip().lower()
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM lurkqvd.usuarios WHERE email = %s", (email,)).fetchone():
                raise LoginJaExiste("Já existe um usuário com esse e-mail.")
            u = conn.execute(
                f"""
                INSERT INTO lurkqvd.usuarios AS u (email, nome, papel, senha_hash, trocar_senha, senha_alterada_em)
                VALUES (%s, %s, %s, %s, %s, now())
                RETURNING {_CAMPOS_USUARIO}
                """,
                (email, (nome or "").strip() or None, papel, senha_hash, trocar_senha),
            ).fetchone()
            self._auditar(conn, criado_por, "usuario.criar", "usuario", u["id"], {"email": email, "papel": papel})
        return u

    def garantir_admin_padrao(self, login: str, senha_hash: str) -> bool:
        """Cria o admin padrão se o banco não tem nenhum usuário. True = criou agora."""
        with self._conn() as conn:
            conn.execute("LOCK TABLE lurkqvd.usuarios IN SHARE ROW EXCLUSIVE MODE")  # duas APIs subindo juntas
            if conn.execute("SELECT 1 FROM lurkqvd.usuarios LIMIT 1").fetchone():
                return False
            u = conn.execute(
                """
                INSERT INTO lurkqvd.usuarios (email, nome, papel, senha_hash, trocar_senha, senha_alterada_em)
                VALUES (%s, 'Administrador', 'admin', %s, true, now()) RETURNING id
                """,
                (login, senha_hash),
            ).fetchone()
            self._auditar(conn, None, "usuario.criar", "usuario", u["id"], {"email": login, "papel": "admin",
                                                                            "admin_padrao": True})
        return True

    def definir_senha(self, usuario_id: int, senha_hash: str, *, trocar_senha: bool, por: int | None,
                      manter_sessao: str | None = None) -> None:
        """Grava a senha e derruba as outras sessões da pessoa (mantém só a do token informado)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE lurkqvd.usuarios SET senha_hash = %s, trocar_senha = %s, senha_alterada_em = now() WHERE id = %s",
                (senha_hash, trocar_senha, usuario_id),
            )
            conn.execute(
                "UPDATE lurkqvd.sessoes SET revogada_em = now() WHERE usuario_id = %s AND revogada_em IS NULL AND hash <> %s",
                (usuario_id, _hash(manter_sessao) if manter_sessao else ""),
            )
            acao = "usuario.trocar_senha" if por == usuario_id else "usuario.redefinir_senha"
            self._auditar(conn, por, acao, "usuario", usuario_id)

    def completar_conta(self, usuario_id: int, email: str, nome: str) -> None:
        """Admin padrão: troca o login "admin" pelo e-mail real (no primeiro acesso)."""
        email = email.strip().lower()
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM lurkqvd.usuarios WHERE email = %s AND id <> %s", (email, usuario_id)).fetchone():
                raise LoginJaExiste("Já existe um usuário com esse e-mail.")
            conn.execute("UPDATE lurkqvd.usuarios SET email = %s, nome = %s WHERE id = %s",
                         (email, nome.strip(), usuario_id))
            self._auditar(conn, usuario_id, "usuario.completar_conta", "usuario", usuario_id, {"email": email})

    # ------------------------------------------------------------------ #
    # Sessões
    # ------------------------------------------------------------------ #
    def criar_sessao(self, usuario_id: int, ip: str | None, navegador: str | None) -> tuple[str, dict]:
        """(token, sessão). O token só existe neste momento; registra o login."""
        token = PREFIXO_SESSAO + secrets.token_urlsafe(32)
        with self._conn() as conn:
            sessao = conn.execute(
                """
                INSERT INTO lurkqvd.sessoes (usuario_id, hash, expira_em, ip, navegador)
                VALUES (%s, %s, now() + make_interval(days => %s), %s, %s)
                RETURNING id, criado_em, expira_em
                """,
                (usuario_id, _hash(token), SESSAO_MAX_DIAS, ip, (navegador or "")[:300] or None),
            ).fetchone()
            conn.execute("UPDATE lurkqvd.usuarios SET ultimo_login = now() WHERE id = %s", (usuario_id,))
            self._auditar(conn, usuario_id, "usuario.login", "usuario", usuario_id, {"ip": ip})
        return token, sessao

    def usuario_da_sessao(self, token: str) -> dict | None:
        """Usuário de uma sessão válida (não revogada, dentro do prazo e usada nas últimas horas), ou None.
        Renova o "último uso" no máximo uma vez por minuto."""
        with self._conn() as conn:
            return conn.execute(
                f"""
                WITH s AS (
                    UPDATE lurkqvd.sessoes
                       SET ultimo_uso = CASE WHEN ultimo_uso < now() - interval '1 minute' THEN now() ELSE ultimo_uso END
                     WHERE hash = %s AND revogada_em IS NULL AND expira_em > now()
                       AND ultimo_uso > now() - make_interval(hours => %s)
                    RETURNING usuario_id
                )
                SELECT {_CAMPOS_USUARIO} FROM s JOIN lurkqvd.usuarios u ON u.id = s.usuario_id
                """,
                (_hash(token), SESSAO_INATIVA_H),
            ).fetchone()

    def encerrar_sessao(self, token: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE lurkqvd.sessoes SET revogada_em = now() WHERE hash = %s AND revogada_em IS NULL",
                         (_hash(token),))

    def encerrar_sessoes_do_usuario(self, usuario_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE lurkqvd.sessoes SET revogada_em = now() WHERE usuario_id = %s AND revogada_em IS NULL",
                         (usuario_id,))
