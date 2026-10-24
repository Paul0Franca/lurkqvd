"""Comandos de administração do LurkQVD, para rodar no servidor.

Uso, na raiz do projeto:
    python -m src.lurkqvd.cli migrar                     aplica as migrações pendentes do banco (db/migracoes)
    python -m src.lurkqvd.cli definir-senha <login>      sorteia uma senha temporária (troca obrigatória no login)
    python -m src.lurkqvd.cli definir-senha <login> --senha "..."   usa a senha informada (também temporária)

definir-senha serve para entrar quando ninguém consegue mais (ex.: o único admin esqueceu a senha) e para dar a
primeira senha a usuários que vieram do antigo login com o Google.
"""

import argparse
import logging
import sys

from src.lurkqvd import senhas
from src.lurkqvd.repository.repositorio import Repositorio


def definir_senha(login: str, senha: str | None) -> None:
    repo = Repositorio()
    usuario = repo.usuario_para_login(login)
    if not usuario:
        sys.exit(f"Usuário '{login}' não encontrado.")
    if senha:
        motivo = senhas.problema(senha, login=usuario["email"])
        if motivo:
            sys.exit(motivo)
    senha = senha or senhas.temporaria()
    repo.definir_senha(usuario["id"], senhas.gerar_hash(senha), trocar_senha=True, por=None)
    if not usuario["ativo"]:
        print("Atenção: esse usuário está desativado; reative em Configurações › Usuários e acesso.")
    print(f"Login: {usuario['email']}\nSenha temporária: {senha}\nNo próximo login será pedida uma senha nova.")


def migrar() -> None:
    from src.lurkqvd import migracoes

    feitas = migracoes.migrar(Repositorio().dsn)
    print(f"{len(feitas)} migração(ões) aplicada(s): {', '.join(feitas)}" if feitas else "Banco em dia: nenhuma migração pendente.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m src.lurkqvd.cli", description="Administração do LurkQVD")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("migrar", help="aplica as migrações pendentes do banco")
    p = comandos.add_parser("definir-senha", help="define uma senha temporária para um usuário")
    p.add_argument("login", help="e-mail do usuário (ou admin)")
    p.add_argument("--senha", help="senha a usar (padrão: sorteada)")
    args = parser.parse_args()
    if args.comando == "migrar":
        migrar()
    elif args.comando == "definir-senha":
        definir_senha(args.login, args.senha)


if __name__ == "__main__":
    main()
