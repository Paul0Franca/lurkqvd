# Como contribuir

Obrigado pelo interesse no LurkQVD! Correções, melhorias na documentação, relatos de bug e ideias são bem-vindos.

## Antes de começar

- **Bug ou ideia:** abra uma [issue](../../issues/new/choose) antes de escrever código grande. Assim combinamos o
  caminho e ninguém perde trabalho.
- **Falha de segurança:** **não** abra issue pública. Siga o [SECURITY.md](SECURITY.md).
- Mudanças pequenas (erro de digitação, ajuste de texto, correção óbvia) podem ir direto num pull request.

Ao participar, você concorda com o [Código de Conduta](CODE_OF_CONDUCT.md).

## Ambiente de desenvolvimento

Requisitos: Python 3.12, Node 22, Docker e o
[ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
O passo a passo para subir banco, API, worker e front está na seção
[Desenvolvimento do README](README.md#desenvolvimento).

Tudo roda a partir da **raiz do projeto**: os imports são absolutos a partir de `src.`
(ex.: `from src.lurkqvd.repository.repositorio import Repositorio`).

## Fluxo

1. Faça um fork e crie um branch a partir do `main` (ex.: `corrige-estimativa-postgres`).
2. Faça a mudança, com testes quando fizer sentido.
3. Rode as verificações (abaixo) e abra o pull request para o `main`, explicando o que muda e por quê.
4. O CI roda os testes, o lint e o build do front e das imagens Docker. O PR só entra com tudo verde.

Prefira PRs pequenos e com um assunto só: são revisados mais rápido.

## Verificações antes do PR

```bash
.venv/bin/python -m pytest                 # Windows: .venv\Scripts\python -m pytest
cd front && npm run lint && npm run build  # o build é a checagem de tipos
```

Os testes de banco criam um Postgres descartável no servidor do `docker-compose.dev.yml` e são pulados se ele não
estiver no ar. No CI eles rodam sempre, então suba o banco de desenvolvimento para não ter surpresa.

## Padrões do projeto

- **Português** em tudo: código, nomes, comentários, mensagens, UI, commits e documentação.
- **Todo SQL fica no `Repositorio`** (`src/lurkqvd/repository/`). API, worker e scripts não escrevem SQL.
- **A API não executa cargas, só enfileira.** O trabalho pesado é do worker, e a fila
  (`lurkqvd.execucoes`, com `FOR UPDATE SKIP LOCKED`) precisa continuar aceitando vários workers juntos.
- **Migrações:** mudança de schema é um **arquivo novo** em `db/migracoes/` com o próximo número
  (`NNN_descricao.sql`). Nunca edite um arquivo já publicado.
- **Formato QVD:** o escritor em `pipeline/qvd_fluxo.py` precisa gerar arquivo idêntico ao da biblioteca `qvdrs`.
  Leia o docstring dele antes de mexer; os testes em `tests/test_qvd_fluxo.py` conferem isso.
- **Segredos** (API key da Qlik, senhas das fontes e do SMTP) nunca vão para a configuração nem para o log:
  passam sempre por `config/segredos.py`.
- **Configuração** por variáveis `LURKQVD_*`, lidas com `os.getenv` no topo do módulo e documentadas no
  docstring dele. Variável nova também entra no `.env.example` e na tabela de configuração do README.
- **Fuso:** use `src/lurkqvd/fuso.py`; não escreva `America/Sao_Paulo` no código.
- **Sem serviços externos obrigatórios:** a ideia é instalar e usar com o mínimo de configuração.
- **Dependências** ficam com versão fixa em `requirements.txt` / `requirements-dev.txt`. Dependência nova
  precisa de um bom motivo e de licença compatível com a Apache 2.0.

O [CLAUDE.md](CLAUDE.md) descreve a arquitetura com mais detalhe e serve de referência para pessoas e para
assistentes de código.

## Changelog

Mudança que o usuário percebe (recurso, correção, variável nova, algo que exige ação na atualização) ganha uma
linha na seção **[Não lançado]** do [CHANGELOG.md](CHANGELOG.md).

## Licença

Ao enviar uma contribuição, você concorda que ela seja distribuída sob a [Apache License 2.0](LICENSE), a mesma
do projeto.
