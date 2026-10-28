# Changelog

As mudanças de cada versão do LurkQVD. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e as versões seguem o [Versionamento Semântico](https://semver.org/lang/pt-BR/): uma versão nova no primeiro
número pode exigir alguma ação na atualização, e isso fica descrito aqui.

Para lançar uma versão: troque `__version__` em `src/lurkqvd/__init__.py` e `version` em `front/package.json`,
mova o que estiver em "Não lançado" para uma seção `## [X.Y.Z] - AAAA-MM-DD` e empurre a tag `vX.Y.Z`.

## [Não lançado]

### Mudado
- Gerador de QVD: a memória não cresce mais com os valores distintos. As colunas com muitos valores vão
  para o disco espalhadas por hash e são resolvidas no fim em grupos de tamanho fixo. Numa tabela de
  6 milhões de linhas e 74 colunas, o pico caiu de ~3 GB para ~850 MB, com o mesmo arquivo.
- `LURKQVD_DISTINTOS_PYTHON` agora é o total de distintos na memória somando todas as colunas (padrão
  500000); antes era por coluna (250000).
- O worker devolve ao sistema a memória livre no fim de cada carga (antes ficava com o pico da última).
- Símbolos de texto do QVD montados sem laço em Python.
- Percentual da leitura: a contagem da última execução só vale como previsão se a consulta e a fonte não
  mudaram depois dela; senão volta para a estimativa do banco (antes a barra parava no meio).
- O log do worker mostra o pico de memória de cada fase da carga (lendo, gerando, enviando).
- Leitura com arrow-odbc: `LURKQVD_PACKET_SIZE` passa a valer 32767 por padrão (o maior que o SQL Server
  aceita). Na tabela de 16,9 milhões de linhas, a leitura foi de 628 s para 548 s, com o mesmo uso de CPU.
  `LURKQVD_PACKET_SIZE=0` volta ao padrão do driver.
- `scripts/medir_paralelo.py` lê com o mesmo buffer e o mesmo pacote de rede da carga.

### Adicionado
- `scripts/medir_escritor.py`: tempo e memória do gerador de QVD com uma tabela sintética.

## [0.1.0] - 2026-10-24

Primeira versão pública.

### Adicionado
- Cargas: consulta no SQL Server → QVD → data file na Qlik Cloud, com agendamento (cron), fila de execuções,
  progresso ao vivo e cancelamento.
- Gerador de QVD em fluxo: memória proporcional aos valores distintos, não ao número de linhas; arquivo
  idêntico ao da biblioteca `qvdrs`.
- Leitura antecipada: o banco manda o próximo lote enquanto o atual vira QVD (`LURKQVD_LOTES_ANTECIPADOS`).
- Reserva de memória na fila: cada execução grava o pico de memória, e os workers da mesma máquina
  (`LURKQVD_MAQUINA`) só pegam uma carga se a estimativa dela couber no que sobra. A trava de memória
  respeita o limite do container.
- Buffer do `arrow-odbc` limitado a 128 MB (`LURKQVD_BUFFER_LEITURA_MB`): ~1 GB a menos por carga, no mesmo ritmo.
- Motores de leitura `odbc`, `arrow-odbc` e `connectorx`, com volta automática para o ODBC.
- Envio retomável para a Qlik acima de `LURKQVD_LIMITE_ENVIO_DIRETO_MB`; se o envio falha, o QVD fica guardado
  e a próxima execução só reenvia.
- Aplicações: grupos de cargas que, juntas com sucesso, recarregam um app da Qlik.
- Estimativa do tamanho do QVD antes de rodar e composição (peso de cada coluna) depois.
- Login próprio com papéis (leitor, editor, admin), tokens de API para Airflow e integrações, auditoria.
- Notificações por e-mail.
- Segredos (API key da Qlik, senhas das fontes e do SMTP) criptografados no banco.
- Instalação com Docker Compose; imagens publicadas no GitHub Container Registry a cada versão.
- Versão do servidor no `/health` e no menu do usuário.
- PostgreSQL como fonte de dados (beta): leitura em lotes com cursor no servidor, teste de conexão com mensagens
  claras, estimativa pelo `EXPLAIN` e `pg_stats`. Tipos sem equivalente no QVD (uuid, json, arrays, bytea, interval)
  viram texto, e `timestamptz` vira a hora local do fuso da instalação.
- Fuso da instalação configurável (`LURKQVD_FUSO`, padrão `America/Sao_Paulo`): agendamentos, horários dos
  e-mails e gráfico por dia. Ao trocar, o worker recalcula o próximo horário dos agendamentos.
- A API e o worker se recusam a subir num banco com migração faltando, e dizem o comando para aplicar.
