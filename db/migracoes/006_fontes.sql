-- Fontes de dados: de onde cada carga lê. A senha fica no Secret Manager
-- (secret lurkqvd_fontes, JSON {"<id da fonte>": "<senha>"}), nunca aqui.

CREATE TABLE IF NOT EXISTS lurkqvd.fontes (
    id             serial PRIMARY KEY,
    nome           text NOT NULL UNIQUE,
    tipo           text NOT NULL CHECK (tipo IN ('mssql', 'postgres', 'mysql', 'oracle')),
    host           text NOT NULL,
    porta          int  NOT NULL CHECK (porta BETWEEN 1 AND 65535),
    banco          text NOT NULL,
    usuario        text NOT NULL,
    opcoes         jsonb NOT NULL DEFAULT '{}',     -- ex.: {"encrypt": true, "trust_cert": true}
    padrao         boolean NOT NULL DEFAULT false,  -- usada pelas cargas sem fonte definida
    ultimo_teste   jsonb,                           -- {ok, erro, versao, latencia_ms, testado_em}
    criado_por     int REFERENCES lurkqvd.usuarios (id),
    criado_em      timestamptz NOT NULL DEFAULT now(),
    atualizado_por int REFERENCES lurkqvd.usuarios (id),
    atualizado_em  timestamptz NOT NULL DEFAULT now()
);

-- no máximo uma fonte padrão
CREATE UNIQUE INDEX IF NOT EXISTS ux_fontes_padrao ON lurkqvd.fontes (padrao) WHERE padrao;

-- NULL = usa a fonte padrão (e, sem fonte padrão, a conexão configurada no servidor)
ALTER TABLE lurkqvd.cargas ADD COLUMN IF NOT EXISTS fonte_id int REFERENCES lurkqvd.fontes (id);
