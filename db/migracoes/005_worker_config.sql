-- Sinal de vida dos workers (heartbeat) e configurações gerais.

CREATE TABLE IF NOT EXISTS lurkqvd.workers (
    id             text PRIMARY KEY,              -- host:pid
    host           text NOT NULL,
    pid            int  NOT NULL,
    iniciado_em    timestamptz NOT NULL DEFAULT now(),
    ultimo_sinal   timestamptz NOT NULL DEFAULT now(),
    execucao_id    int REFERENCES lurkqvd.execucoes (id) ON DELETE SET NULL,  -- o que está rodando agora
    encerrado_em   timestamptz                    -- preenchido na parada suave
);

CREATE TABLE IF NOT EXISTS lurkqvd.configuracoes (
    chave          text PRIMARY KEY,
    valor          jsonb NOT NULL,
    atualizado_em  timestamptz NOT NULL DEFAULT now(),
    atualizado_por int REFERENCES lurkqvd.usuarios (id)
);

INSERT INTO lurkqvd.configuracoes (chave, valor) VALUES
    ('agenda',   '{"pausada": false}'),
    ('execucao', '{"limite_travada_min": 60}')
ON CONFLICT (chave) DO NOTHING;
