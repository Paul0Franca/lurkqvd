"""Migrações do banco do LurkQVD: aplica, em ordem, os arquivos de db/migracoes que ainda não rodaram.

Uso, na raiz do projeto (o Docker já roda isto antes de subir a API e o worker):
    python -m src.lurkqvd.cli migrar

Regras:
  - cada arquivo é NNN_descricao.sql e roda uma única vez, numa transação (falhou = nada dele fica);
  - o que já rodou fica em lurkqvd.migracoes;
  - uma trava no Postgres (advisory lock) impede duas migrações ao mesmo tempo (API e worker subindo juntos);
  - mudança de schema = arquivo novo com o próximo número. Nunca edite um arquivo que já foi publicado;
  - a API e o worker não migram sozinhos (o Docker roda o migrar antes deles): se faltar migração, eles se
    recusam a subir e dizem o comando (exigir_em_dia).

Bancos criados antes deste controle (pelos scripts de init do docker) são reconhecidos pelo que cada
migração cria (tabela ou coluna) e entram na lista como já aplicados.
"""

import logging
import re
from pathlib import Path

import psycopg

logger = logging.getLogger("lurkqvd.migracoes")

PASTA = Path(__file__).resolve().parents[2] / "db" / "migracoes"
_TRAVA = 4_272_011  # número qualquer, fixo: identifica a trava de migração do LurkQVD

# o que cada migração antiga criou, para reconhecer bancos anteriores ao controle de versão
_MARCAS = {
    "001": "SELECT to_regclass('lurkqvd.usuarios') IS NOT NULL",
    "002": "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'lurkqvd' AND table_name = 'cargas' AND column_name = 'agendamento')",
    "003": "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'lurkqvd' AND table_name = 'usuarios' AND column_name = 'foto_url')",
    # 004 criou convites, que a 013 apagou
    "004": "SELECT to_regclass('lurkqvd.convites') IS NOT NULL OR to_regclass('lurkqvd.sessoes') IS NOT NULL",
    "005": "SELECT to_regclass('lurkqvd.configuracoes') IS NOT NULL",
    "006": "SELECT to_regclass('lurkqvd.fontes') IS NOT NULL",
    "007": "SELECT to_regclass('lurkqvd.tokens_api') IS NOT NULL",
    "008": "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'lurkqvd' AND table_name = 'execucoes' AND column_name = 'composicao')",
    "009": "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'lurkqvd' AND table_name = 'execucoes' AND column_name = 'progresso')",
    "010": "SELECT to_regclass('lurkqvd.aplicacoes') IS NOT NULL",
    "011": "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'lurkqvd' AND table_name = 'execucoes' AND column_name = 'notificado_em')",
    "012": "SELECT to_regclass('lurkqvd.segredos') IS NOT NULL",
    "013": "SELECT to_regclass('lurkqvd.sessoes') IS NOT NULL",
}


def arquivos() -> list[tuple[str, Path]]:
    """[(versão, arquivo)] em ordem."""
    itens = []
    for p in sorted(PASTA.glob("*.sql")):
        m = re.match(r"^(\d{3})_[\w-]+\.sql$", p.name)
        if not m:
            raise RuntimeError(f"Nome de migração fora do padrão NNN_descricao.sql: {p.name}")
        itens.append((m.group(1), p))
    versoes = [v for v, _ in itens]
    if len(set(versoes)) != len(versoes):
        raise RuntimeError("Há duas migrações com o mesmo número em db/migracoes.")
    return itens


class BancoDesatualizado(RuntimeError):
    """O banco não tem todas as migrações deste código."""


def pendentes(dsn: str) -> list[str]:
    """Arquivos de migração que ainda não rodaram neste banco. Só consulta: não aplica nada."""
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        if conn.execute("SELECT to_regclass('lurkqvd.migracoes')").fetchone()[0] is None:
            return [arquivo.name for _, arquivo in arquivos()]
        feitas = {r[0] for r in conn.execute("SELECT versao FROM lurkqvd.migracoes")}
    return [arquivo.name for versao, arquivo in arquivos() if versao not in feitas]


def exigir_em_dia(dsn: str) -> None:
    """Levanta BancoDesatualizado, com o comando para resolver, se faltar alguma migração."""
    falta = pendentes(dsn)
    if falta:
        raise BancoDesatualizado(
            f"O banco está sem {len(falta)} migração(ões) deste código ({', '.join(falta)}). "
            "Aplique antes de subir: python -m src.lurkqvd.cli migrar"
        )


def migrar(dsn: str) -> list[str]:
    """Aplica as pendentes. Devolve os nomes dos arquivos aplicados agora."""
    aplicadas_agora = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_TRAVA,))
        try:
            conn.execute("CREATE SCHEMA IF NOT EXISTS lurkqvd")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lurkqvd.migracoes (
                    versao      text PRIMARY KEY,
                    arquivo     text NOT NULL,
                    aplicada_em timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            feitas = {r[0] for r in conn.execute("SELECT versao FROM lurkqvd.migracoes")}
            if not feitas:
                _reconhecer_banco_antigo(conn, feitas)

            for versao, arquivo in arquivos():
                if versao in feitas:
                    continue
                logger.info("aplicando migração %s", arquivo.name)
                with conn.transaction():
                    conn.execute(arquivo.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO lurkqvd.migracoes (versao, arquivo) VALUES (%s, %s)", (versao, arquivo.name))
                aplicadas_agora.append(arquivo.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_TRAVA,))
    return aplicadas_agora


def _reconhecer_banco_antigo(conn: psycopg.Connection, feitas: set[str]) -> None:
    """Banco criado antes do controle de versão: registra como aplicadas as migrações cujo resultado já existe."""
    for versao, arquivo in arquivos():
        marca = _MARCAS.get(versao)
        if marca and conn.execute(marca).fetchone()[0]:
            conn.execute("INSERT INTO lurkqvd.migracoes (versao, arquivo) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (versao, arquivo.name))
            feitas.add(versao)
    if feitas:
        logger.info("banco existente reconhecido: %s migração(ões) já estavam aplicadas", len(feitas))
