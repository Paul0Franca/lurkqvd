# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral

LurkQVD: plataforma que extrai dados do SQL Server, gera arquivos **QVD** e publica como data files na **Qlik Cloud**, com agendamento (cron), fila de execuções, "aplicações" (grupos de cargas + reload de app Qlik), notificações por e-mail e auditoria. Código, nomes, comentários, mensagens e UI são em **português** — mantenha o padrão.

Projeto open source (Apache 2.0). Dependências Python fixas em `requirements.txt` (dev/testes: `requirements-dev.txt`), Python 3.12.

## Comandos

Tudo roda a partir da **raiz do projeto**: os imports são absolutos a partir de `src.` (ex.: `from src.lurkqvd.repository.repositorio import Repositorio`). O `.env` da raiz é carregado em `src/lurkqvd/__init__.py`.

```bash
# Instalação completa (Postgres + API + worker + web na porta 8080)
docker compose up -d --build

# Desenvolvimento: só o Postgres (127.0.0.1:5433), o resto roda local
docker compose -f docker-compose.dev.yml up -d
.venv/Scripts/python -m src.lurkqvd.cli migrar                 # aplica as migrações pendentes
.venv/Scripts/uvicorn src.lurkqvd.api.main:app --reload        # API, docs em http://localhost:8000/docs
.venv/Scripts/python -m src.lurkqvd.worker                     # worker (--uma-vez: esvazia a fila e sai)
cd front && npm run dev                                        # http://localhost:5173
npm run build                                                  # tsc -b && vite build (é a checagem de tipos)
npm run lint                                                   # oxlint

# Testes (pytest; os de banco criam um Postgres descartável e são pulados sem Postgres)
.venv/Scripts/python -m pytest
.venv/Scripts/python -m pytest tests/test_acesso.py -k bloqueio   # um teste só

# Administração
.venv/Scripts/python -m src.lurkqvd.cli definir-senha <login>      # senha temporária (emergência)
.venv/Scripts/python -m src.lurkqvd.config.segredos gerar-chave    # LURKQVD_FERNET_KEY nova
```

`scripts/` são ferramentas de diagnóstico/medição (não testes), rodadas como módulo contra bancos e Qlik reais; cada uma documenta o uso no docstring (`python -m scripts.comparar_motores <carga>`, `scripts.medir_leitura`, `scripts.medir_paralelo`, `scripts.enfileirar`, `scripts.publicar_temporario`).

### Migrações de banco

Uma pasta só: `db/migracoes/NNN_descricao.sql`, aplicadas em ordem por `src/lurkqvd/migracoes.py` (`cli migrar`; no Docker roda antes da API e do worker, com advisory lock). O que já rodou fica em `lurkqvd.migracoes`. Mudança de schema = **arquivo novo com o próximo número**; nunca edite um arquivo já publicado. Tudo fica no schema `lurkqvd`. Bancos anteriores ao controle são reconhecidos pelas marcas em `_MARCAS`: ao criar uma migração nova, não precisa adicionar marca.

### Docker

`Dockerfile` (raiz): imagem única da API e do worker (Python 3.12 + ODBC Driver 18), usuário sem root, entrypoint `docker/entrypoint.sh` (`api` | `worker` | `cli ...` | `chave`). `front/Dockerfile`: build Vite com `VITE_API_URL=/api` servido por nginx (`front/nginx/`), que repassa `/api/` para a API e aplica a CSP (sem scripts inline nem de terceiros: o tema inicial está em `front/public/tema.js` e a fonte Sora vem de `@fontsource/sora`). O Postgres não expõe porta no compose de produção.

## Arquitetura

```
front (React) ──Bearer token──> API (FastAPI)  ──> Postgres (lurkqvd.*)  <── Worker(s)
                                 só enfileira        fila = lurkqvd.execucoes    executam
                                                                                    │
                                              SQL Server ──> GeradorQvd ──> Qlik Cloud
```

- **API não executa cargas, só enfileira.** `src/lurkqvd/api/main.py` é a maior parte das rotas; `api/acesso.py`, `api/aplicacoes.py` e `api/notificacoes.py` são `APIRouter`s incluídos no fim de `main.py` (nesta versão do FastAPI eles aparecem em `app.routes` encapsulados; as rotas estão em `.original_router.routes`).
- **Todo SQL fica no `Repositorio`** (`repository/repositorio.py`), composto por mixins (`AcessoMixin`, `AplicacoesMixin`, `NotificacoesMixin`, que usam `self._conn()` e `self._auditar()`). API, worker e scripts não escrevem SQL. DSN: `LURKQVD_PG_DSN`, padrão o Postgres do `docker-compose.dev.yml` (use `127.0.0.1`, não `localhost`: no Windows o `localhost` tenta IPv6 antes e demora).
- **Fila no Postgres**: `lurkqvd.execucoes` é ao mesmo tempo histórico e fila; o worker pega trabalho com `FOR UPDATE SKIP LOCKED`, então vários workers podem rodar juntos. Qualquer etapa nova de orquestração deve manter essa propriedade. Reserva de memória: `pegar_proxima` só entrega uma carga se o pico das últimas execuções dela (`memoria_pico_bytes`, medido pelo `memoria.Medidor`) couber no que os workers da mesma `LURKQVD_MAQUINA` não reservaram; a regra é a função pura `memoria.escolher`, e uma advisory lock por máquina serializa a decisão.
- **Worker** (`worker.py`): o client da Qlik/gerador é criado só na 1ª carga (instalação nova sobe sem key). Laço principal (verifica a key da Qlik, enfileira o que o cron mandou, processa uma execução) + threads daemon para sinal de vida, orquestração de aplicações (`pendente → cargas → recarregando → sucesso/erro/cancelado`; com carga falhando, o app **não** é recarregado) e notificações. Progresso e cancelamento: a classe `Progresso` grava no Postgres a cada ~2s e, ao gravar, levanta `Cancelada` se pediram cancelamento.
- **Pipeline** (`pipeline/`):
  - `gerador_qvd.py` — `GeradorQvd.executar(CargaQvd) -> ResultadoCarga`, o núcleo reutilizável. Lê em lotes, gera, valida e sobe. Se o envio falha, o QVD fica em `tmp_qvd/pendentes` e a próxima execução da mesma carga (query igual, dentro de `LURKQVD_VALIDADE_PENDENTE_H`) reenvia sem reler o banco.
  - `qvd_fluxo.py` — escritor de QVD em streaming (memória ~ valores distintos, índice em arquivo temporário). Precisa gerar arquivo **idêntico ao da lib `qvdrs`** (pacote `qvd`): o docstring lista as regras de formato seguidas; leia antes de mexer.
  - `estimativa.py` — estima tamanho do QVD sem varrer a tabela (SHOWPLAN + estatísticas + amostra).
  - `memoria.py` — trava de memória do processo (`LURKQVD_LIMITE_MEMORIA_PCT`, precisa de `psutil`).
- **Qlik** (`clients/qlik.py`): REST da Qlik Cloud. Acima de `LURKQVD_LIMITE_ENVIO_DIRETO_MB` o envio é retomável (tus) em pedaços via `/temp-contents`, que ficam ~6h na Qlik.
- **Fontes de dados** (`config/fontes.py`): drivers por tipo de banco. SQL Server com motores `odbc` (padrão/fallback), `arrow-odbc` e `connectorx`; PostgreSQL (beta) com `psycopg` (cursor no servidor; tipos sem equivalente no QVD viram texto em `_normalizar_postgres`). O 1º motor de cada tipo é o fallback. A estimativa (`pipeline/estimativa.py`) escolhe o dialeto por `engine.dialect.name`.
- **Conexão com o banco de origem** vem sempre de uma fonte cadastrada (`config/fontes.py`, senha nos segredos): a da carga ou a padrão. Sem fonte, a carga falha com aviso; não existe mais conexão "do servidor" (o antigo `src/core` foi removido).

### Segredos e configuração

- Segredos (API key da Qlik, senhas das fontes e do SMTP) **nunca** ficam na configuração: ficam na tabela `lurkqvd.segredos`, criptografados com Fernet (chave em `LURKQVD_FERNET_KEY`; várias separadas por vírgula = rotação, a 1ª criptografa). Todo acesso passa por `config/segredos.py` (`ler_json`, `alterar_chave`, `mensagem_erro`). Cada segredo é um JSON com nome: `qlik_qvd` (`{"qvd_token": ...}`), `lurkqvd_fontes` (`{"<id fonte>": "<senha>"}`), `lurkqvd_smtp` (`{"senha": ...}`). Sem a chave, API/worker sobem, mas ler/gravar segredo dá 503 com a instrução.
- Comandos: `python -m src.lurkqvd.config.segredos gerar-chave | rotacionar`. Tela: Configurações › Segredos (`GET /config/segredos`, só leitura).
- **Qlik Cloud**: tenant salvo pela tela (sem padrão fixo); numa instalação nova o tenant é gravado antes da key, sem teste.
- **Sem dependência de GCP/Google**: nada no código importa bibliotecas do Google; não reintroduzir serviços externos obrigatórios (a ideia é instalar e usar com o mínimo de configuração).
- **Fuso**: `src/lurkqvd/fuso.py` (`LURKQVD_FUSO`) é a única fonte do fuso; não escreva `America/Sao_Paulo` no código. A coluna `fuso` de cargas/aplicações vazia = fuso da instalação.
- Variáveis de ambiente usam o prefixo `LURKQVD_*` e são lidas com `os.getenv` no topo de cada módulo (documentadas no docstring do módulo). `.env` na raiz é carregado em `src/lurkqvd/__init__.py`, antes de qualquer módulo (variáveis já definidas no ambiente têm precedência).

### Autenticação

Login próprio, sem Google: `POST /auth/entrar` (e-mail + senha, hash `scrypt` em `senhas.py`) devolve um token de sessão `lqs_...` (só o sha256 fica em `lurkqvd.sessoes`; 12h de inatividade, 7 dias no máximo); o front manda `Authorization: Bearer <token>`. Tokens de API têm prefixo `lqvd_` (Airflow/integrações). Papéis: `leitor < editor < admin`, com `exigir_papel(...)`. Rotas em `api/auth.py` (dependências) e `api/acesso.py` (entrar/sair/senha/cadastro).
- **Instalação:** com o banco sem usuários, a API cria o login `admin` na subida; senha de `LURKQVD_ADMIN_SENHA` ou sorteada (no log e em `admin_senha_inicial.txt`, apagado após a troca). No 1º login ele troca a senha e informa nome/e-mail reais.
- **Senha temporária** (`usuarios.trocar_senha`): só libera `/auth/me`, `/auth/senha` e `/auth/sair` até trocar. O admin cadastra usuários e redefine senhas; a temporária vai **por e-mail**, então sem SMTP configurado o cadastro é recusado (não grava senha que ninguém recebe).
- Emergência: `python -m src.lurkqvd.cli definir-senha <login>`. 5 erros de login em 15 min por login+IP bloqueiam (em memória). `LURKQVD_AUTH_DEV=1` libera tudo como admin fictício (só local).

### Front

`front/src/api.ts` concentra o cliente HTTP e os tipos espelhando a API; componentes em `front/src/components/`, helpers em `front/src/lib/`. Config em `front/.env.local` (`VITE_API_URL`; variáveis `VITE_*` são públicas). Tema claro/escuro em `lib/tema.ts` (atributo `data-tema` no `<html>`). Fora do CORS, um 500 vira "Failed to fetch" no navegador: por isso `main.py` tem um handler de exceção registrado antes do middleware de CORS (`LURKQVD_CORS` lista as origens).
