-- Tokens de API para sistemas (ex.: Airflow) acionarem cargas.
-- Só o hash SHA-256 do token é guardado: ele aparece uma única vez, na criação.

CREATE TABLE IF NOT EXISTS lurkqvd.tokens_api (
    id             serial PRIMARY KEY,
    nome           text NOT NULL,
    prefixo        text NOT NULL UNIQUE,             -- início visível, ex.: lqvd_7f3a9c
    hash           text NOT NULL UNIQUE,             -- sha256 do token inteiro
    permissao      text NOT NULL CHECK (permissao IN ('executar', 'leitura')),
    expira_em      timestamptz,                      -- NULL = sem validade
    criado_por     int REFERENCES lurkqvd.usuarios (id),
    criado_em      timestamptz NOT NULL DEFAULT now(),
    ultimo_uso     timestamptz,
    ultimo_ip      text,
    revogado_em    timestamptz,
    revogado_por   int REFERENCES lurkqvd.usuarios (id)
);

-- de qual token veio a execução (quando não foi uma pessoa)
ALTER TABLE lurkqvd.execucoes ADD COLUMN IF NOT EXISTS token_id int REFERENCES lurkqvd.tokens_api (id);
