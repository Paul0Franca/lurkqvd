-- 001: schema inicial do LurkQVD (usuários, espaços, cargas, execuções, auditoria).

CREATE SCHEMA IF NOT EXISTS lurkqvd;

-- Usuários (login com Google)
CREATE TABLE lurkqvd.usuarios (
    id             serial PRIMARY KEY,
    google_sub     text NOT NULL UNIQUE,      -- ID estável do Google (o e-mail pode mudar)
    email          text NOT NULL UNIQUE,
    nome           text,
    papel          text NOT NULL DEFAULT 'leitor'
                   CHECK (papel IN ('admin', 'editor', 'leitor')),
    ativo          boolean NOT NULL DEFAULT true,
    criado_em      timestamptz NOT NULL DEFAULT now(),
    ultimo_login   timestamptz
);

-- Cache dos espaços da Qlik (vem do list_spaces)
CREATE TABLE lurkqvd.espacos (
    connection_id  uuid PRIMARY KEY,
    space_id       text UNIQUE,               -- NULL = espaço pessoal
    nome           text NOT NULL,
    tipo           text NOT NULL,             -- shared, managed, personal
    atualizado_em  timestamptz NOT NULL DEFAULT now()
);

-- Definição de cada carga (o CargaQvd)
CREATE TABLE lurkqvd.cargas (
    id             serial PRIMARY KEY,
    nome           text NOT NULL UNIQUE,
    query          text NOT NULL,
    params         jsonb NOT NULL DEFAULT '{}',
    connection_id  uuid REFERENCES lurkqvd.espacos (connection_id),
    qlik_path      text NOT NULL,
    file_id        uuid,                      -- preenchido após o 1º upload
    ativo          boolean NOT NULL DEFAULT true,
    criado_por     int REFERENCES lurkqvd.usuarios (id),
    atualizado_por int REFERENCES lurkqvd.usuarios (id),
    criado_em      timestamptz NOT NULL DEFAULT now(),
    atualizado_em  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (connection_id, qlik_path)
);

-- Cada rodada: histórico E fila do worker
CREATE TABLE lurkqvd.execucoes (
    id             bigserial PRIMARY KEY,
    carga_id       int NOT NULL REFERENCES lurkqvd.cargas (id),
    status         text NOT NULL DEFAULT 'pendente'
                   CHECK (status IN ('pendente', 'rodando', 'sucesso', 'erro')),
    origem         text NOT NULL DEFAULT 'manual',   -- manual, airflow, api
    solicitado_por int REFERENCES lurkqvd.usuarios (id),
    solicitado_em  timestamptz NOT NULL DEFAULT now(),
    iniciado_em    timestamptz,
    finalizado_em  timestamptz,
    linhas         int,
    colunas        int,
    tamanho_bytes  bigint,
    seg_extracao   numeric(10, 2),
    seg_geracao    numeric(10, 2),
    seg_upload     numeric(10, 2),
    erro           text
);

-- Worker pega o próximo pendente rápido
CREATE INDEX ix_execucoes_fila ON lurkqvd.execucoes (solicitado_em) WHERE status = 'pendente';
-- Histórico por carga (tela do front)
CREATE INDEX ix_execucoes_carga ON lurkqvd.execucoes (carga_id, solicitado_em DESC);
-- Impede a mesma carga pendente/rodando duas vezes ao mesmo tempo
CREATE UNIQUE INDEX ux_execucoes_ativa ON lurkqvd.execucoes (carga_id)
    WHERE status IN ('pendente', 'rodando');

-- Log de ações: quem fez o quê, quando
CREATE TABLE lurkqvd.auditoria (
    id             bigserial PRIMARY KEY,
    usuario_id     int REFERENCES lurkqvd.usuarios (id),   -- NULL = sistema (Airflow, worker)
    acao           text NOT NULL,             -- ex.: carga.criar, carga.executar, arquivo.apagar
    alvo_tipo      text,                      -- carga, arquivo, pasta
    alvo_id        text,
    detalhes       jsonb NOT NULL DEFAULT '{}',
    criado_em      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_auditoria_alvo ON lurkqvd.auditoria (alvo_tipo, alvo_id, criado_em DESC);
