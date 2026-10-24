## O que muda

<!-- O que este PR faz e por quê. Se resolve uma issue: "Resolve #123". -->

## Como testar

<!-- Passos para conferir a mudança (tela, comando, carga de exemplo). -->

## Checklist

- [ ] `pytest` passa (com o Postgres de desenvolvimento no ar)
- [ ] `npm run lint` e `npm run build` passam, se mexeu no front
- [ ] Mudança de schema é uma migração **nova** em `db/migracoes/`, sem editar as já publicadas
- [ ] Variável `LURKQVD_*` nova está no `.env.example` e na tabela do README
- [ ] Linha no `CHANGELOG.md` em **[Não lançado]**, se o usuário percebe a mudança
- [ ] Nada de senha, token ou dado real em código, testes ou prints
