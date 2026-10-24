"""Segredos do LurkQVD (API key da Qlik, senhas das fontes, senha do SMTP): guardados no próprio Postgres,
na tabela lurkqvd.segredos, criptografados com Fernet. Nada sai para serviços externos.

Todo acesso a segredo passa por aqui. Cada segredo é um JSON (ex.: {"qvd_token": "..."}) com um nome
(ex.: qlik_qvd); a configuração em si (servidor SMTP, fontes...) fica nas outras tabelas, sem a senha.

Variáveis de ambiente:
  LURKQVD_FERNET_KEY   chave(s), separadas por vírgula. A 1ª criptografa; as outras só leem (para trocar
                       de chave sem perder nada: veja o comando "rotacionar").
                       Perder a chave = perder os segredos: guarde uma cópia fora do servidor.

Comandos, na raiz do projeto:
  python -m src.lurkqvd.config.segredos gerar-chave   imprime uma chave nova
  python -m src.lurkqvd.config.segredos rotacionar    recriptografa tudo com a 1ª chave
"""

import json
import os
import sys
from datetime import datetime, timezone

import psycopg

DSN_PADRAO = "postgresql://lurkqvd:lurkqvd_dev@127.0.0.1:5433/lurkqvd"  # o mesmo do Repositorio


class SemChave(RuntimeError):
    """LURKQVD_FERNET_KEY não definida (ou inválida)."""


class ChaveErrada(RuntimeError):
    """O segredo foi criptografado com uma chave que não está mais em LURKQVD_FERNET_KEY."""


def lurkqvd() -> list[dict]:
    """Os segredos que o LurkQVD usa."""
    from src.lurkqvd.config import fontes, qlik_conexao, smtp

    return [
        {"nome": qlik_conexao.nome_secret(), "finalidade": "API key da Qlik Cloud"},
        {"nome": fontes.nome_secret(), "finalidade": "Senhas das fontes de dados"},
        {"nome": smtp.nome_secret(), "finalidade": "Senha do servidor de e-mail (SMTP)"},
    ]


# ---------------------------------------------------------------------- #
# Interface usada pelo resto do LurkQVD
# ---------------------------------------------------------------------- #
def ler_json(nome: str, *, vazio_se_sem_versao: bool = False) -> dict:
    """Conteúdo do segredo. vazio_se_sem_versao: segredo ainda não gravado vira {} em vez de erro."""
    fernet = _fernet()
    with psycopg.connect(_dsn()) as conn:
        row = conn.execute("SELECT valor FROM lurkqvd.segredos WHERE nome = %s", (nome,)).fetchone()
    if row:
        return _abrir(fernet, nome, row[0])
    if vazio_se_sem_versao:
        return {}
    raise RuntimeError(f"O segredo '{nome}' ainda não foi configurado.")


def gravar_json(nome: str, dados: dict) -> None:
    valor = _fernet().encrypt(json.dumps(dados).encode()).decode()
    with psycopg.connect(_dsn()) as conn:
        conn.execute(
            """
            INSERT INTO lurkqvd.segredos (nome, valor) VALUES (%s, %s)
            ON CONFLICT (nome) DO UPDATE SET valor = EXCLUDED.valor, atualizado_em = now()
            """,
            (nome, valor),
        )


def alterar_chave(nome: str, chave: str, valor: str | None, *, vazio_se_sem_versao: bool = False) -> None:
    """Troca (ou remove, com valor=None) uma chave do JSON do segredo, mantendo as outras. O segredo é criado
    na 1ª gravação. Lê, altera e grava na mesma transação, com a linha travada: duas telas salvando juntas
    não se perdem. (vazio_se_sem_versao: aceito por compatibilidade; não muda nada aqui.)"""
    fernet = _fernet()
    with psycopg.connect(_dsn()) as conn:
        conn.execute(
            "INSERT INTO lurkqvd.segredos (nome, valor) VALUES (%s, %s) ON CONFLICT (nome) DO NOTHING",
            (nome, fernet.encrypt(b"{}").decode()),
        )
        atual = conn.execute("SELECT valor FROM lurkqvd.segredos WHERE nome = %s FOR UPDATE", (nome,)).fetchone()[0]
        dados = _abrir(fernet, nome, atual)
        if valor is None:
            if chave not in dados:
                return
            dados.pop(chave)
        else:
            dados[chave] = valor
        conn.execute(
            "UPDATE lurkqvd.segredos SET valor = %s, atualizado_em = now() WHERE nome = %s",
            (fernet.encrypt(json.dumps(dados).encode()).decode(), nome),
        )


def mensagem_erro(e: Exception, nome: str) -> tuple[int, str]:
    """(status HTTP, mensagem amigável) para falhas ao ler/gravar um segredo."""
    if isinstance(e, (SemChave, ChaveErrada)):
        return 503, str(e)
    if isinstance(e, psycopg.Error):
        return 503, f"Não consegui acessar os segredos no Postgres: {e}"
    return 502, f"Falha ao acessar o segredo '{nome}': {e}"


def diagnostico_lurkqvd() -> dict:
    """Estado de cada segredo do LurkQVD (tela Configurações › Segredos). Não levanta exceção."""
    resultado = {"erro": None, "chaves_fernet": len(_chaves()), "secrets": [],
                 "verificado_em": datetime.now(timezone.utc).isoformat()}
    try:
        fernet = _fernet()
        with psycopg.connect(_dsn()) as conn:
            linhas = {r[0]: r[1:] for r in conn.execute("SELECT nome, valor, atualizado_em FROM lurkqvd.segredos")}
    except Exception as e:
        resultado["erro"] = str(e)
        return resultado

    for s in lurkqvd():
        item = {**s, "existe": s["nome"] in linhas, "legivel": True, "erro": None, "atualizado_em": None, "chaves": 0}
        if item["existe"]:
            valor, atualizado_em = linhas[s["nome"]]
            item["atualizado_em"] = atualizado_em.isoformat()
            try:
                item["chaves"] = len(_abrir(fernet, s["nome"], valor))
            except ChaveErrada as e:
                item["legivel"] = False
                item["erro"] = str(e)
        resultado["secrets"].append(item)
    return resultado


# ---------------------------------------------------------------------- #
# Criptografia e banco
# ---------------------------------------------------------------------- #
def _chaves() -> list[str]:
    return [c.strip() for c in os.getenv("LURKQVD_FERNET_KEY", "").split(",") if c.strip()]


def _fernet():
    from cryptography.fernet import Fernet, MultiFernet

    chaves = _chaves()
    if not chaves:
        raise SemChave(
            "LURKQVD_FERNET_KEY não está definida no servidor: sem ela não dá para ler nem gravar senhas. Gere uma com "
            "'python -m src.lurkqvd.config.segredos gerar-chave', coloque no .env da API e do worker e reinicie."
        )
    try:
        return MultiFernet([Fernet(c) for c in chaves])
    except ValueError as e:
        raise SemChave(f"LURKQVD_FERNET_KEY inválida ({e}). Gere uma com 'python -m src.lurkqvd.config.segredos gerar-chave'.") from e


def _abrir(fernet, nome: str, valor: str) -> dict:
    from cryptography.fernet import InvalidToken

    try:
        return json.loads(fernet.decrypt(valor.encode()))
    except InvalidToken as e:
        raise ChaveErrada(
            f"Não consegui abrir o segredo '{nome}': ele foi gravado com outra chave. Coloque a chave antiga em "
            "LURKQVD_FERNET_KEY (depois da nova, separada por vírgula) ou grave o segredo de novo pela tela."
        ) from e


def _dsn() -> str:
    return os.getenv("LURKQVD_PG_DSN", DSN_PADRAO)


# ---------------------------------------------------------------------- #
# Comandos
# ---------------------------------------------------------------------- #
def _rotacionar() -> None:
    fernet = _fernet()
    with psycopg.connect(_dsn()) as conn:
        linhas = conn.execute("SELECT nome, valor FROM lurkqvd.segredos FOR UPDATE").fetchall()
        for nome, valor in linhas:
            conn.execute("UPDATE lurkqvd.segredos SET valor = %s WHERE nome = %s",
                         (fernet.rotate(valor.encode()).decode(), nome))
    print(f"{len(linhas)} segredo(s) recriptografado(s) com a 1ª chave. As outras já podem sair de LURKQVD_FERNET_KEY.")


def main() -> None:
    args = sys.argv[1:]
    if args == ["gerar-chave"]:
        from cryptography.fernet import Fernet

        print(Fernet.generate_key().decode())
    elif args == ["rotacionar"]:
        _rotacionar()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
