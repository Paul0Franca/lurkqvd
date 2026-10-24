-- 010: aplicações (apps da Qlik) que agrupam cargas
--   aplicacoes:                    nome, app da Qlik (opcional) e agenda próprios
--   aplicacao_cargas:              quais cargas alimentam cada aplicação (uma carga pode estar em várias)
--   execucoes_aplicacao:           cada "executar tudo": dispara as cargas, espera, recarrega o app na Qlik
--   execucao_aplicacao_cargas:     qual execução de cada carga serviu a essa rodada (pode ser uma que
--                                  já estava em andamento, disparada por outra aplicação ou pelo agendador)
CREATE TABLE IF NOT EXISTS lurkqvd.aplicacoes (
    id                serial PRIMARY KEY,
    nome              text NOT NULL UNIQUE,
    descricao         text,
    qlik_app_id       text,                    -- NULL = só atualiza os QVDs, não recarrega app
    qlik_app_nome     text,                    -- nome do app na Qlik (guardado ao vincular, para exibir)
    agendamento       text,                    -- cron; NULL = só manual/API
    fuso              text NOT NULL DEFAULT 'America/Sao_Paulo',
    proxima_execucao  timestamptz,
    ativo             boolean NOT NULL DEFAULT true,
    criado_por        int REFERENCES lurkqvd.usuarios (id),
    atualizado_por    int REFERENCES lurkqvd.usuarios (id),
    criado_em         timestamptz NOT NULL DEFAULT now(),
    atualizado_em     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_aplicacoes_agenda
    ON lurkqvd.aplicacoes (proxima_execucao) WHERE ativo AND agendamento IS NOT NULL;

CREATE TABLE IF NOT EXISTS lurkqvd.aplicacao_cargas (
    aplicacao_id  int NOT NULL REFERENCES lurkqvd.aplicacoes (id) ON DELETE CASCADE,
    carga_id      int NOT NULL REFERENCES lurkqvd.cargas (id) ON DELETE CASCADE,
    ordem         int NOT NULL DEFAULT 0,
    PRIMARY KEY (aplicacao_id, carga_id)
);
CREATE INDEX IF NOT EXISTS ix_aplicacao_cargas_carga ON lurkqvd.aplicacao_cargas (carga_id);

CREATE TABLE IF NOT EXISTS lurkqvd.execucoes_aplicacao (
    id                  bigserial PRIMARY KEY,
    aplicacao_id        int NOT NULL REFERENCES lurkqvd.aplicacoes (id) ON DELETE CASCADE,
    status              text NOT NULL DEFAULT 'pendente'
                        CHECK (status IN ('pendente', 'cargas', 'recarregando', 'sucesso', 'erro', 'cancelado')),
    origem              text NOT NULL DEFAULT 'manual',     -- manual, agendador, api
    solicitado_por      int REFERENCES lurkqvd.usuarios (id),
    token_id            int REFERENCES lurkqvd.tokens_api (id),
    solicitado_em       timestamptz NOT NULL DEFAULT now(),
    iniciado_em         timestamptz,
    finalizado_em       timestamptz,
    qlik_app_id         text,                               -- o app no momento da execução
    reload_id           text,                               -- ID do reload na Qlik
    reload_status       text,                               -- QUEUED, RELOADING, SUCCEEDED, FAILED...
    reload_iniciado_em  timestamptz,
    reload_finalizado_em timestamptz,
    reload_consultado_em timestamptz,                       -- última consulta do status (para espaçar)
    erro                text,
    cancelar_em         timestamptz,
    cancelado_por       int REFERENCES lurkqvd.usuarios (id)
);
CREATE INDEX IF NOT EXISTS ix_execucoes_aplicacao_hist ON lurkqvd.execucoes_aplicacao (aplicacao_id, solicitado_em DESC);
-- uma rodada ativa por aplicação
CREATE UNIQUE INDEX IF NOT EXISTS ux_execucoes_aplicacao_ativa ON lurkqvd.execucoes_aplicacao (aplicacao_id)
    WHERE status IN ('pendente', 'cargas', 'recarregando');

CREATE TABLE IF NOT EXISTS lurkqvd.execucao_aplicacao_cargas (
    execucao_aplicacao_id  bigint NOT NULL REFERENCES lurkqvd.execucoes_aplicacao (id) ON DELETE CASCADE,
    carga_id               int NOT NULL REFERENCES lurkqvd.cargas (id) ON DELETE CASCADE,
    execucao_id            bigint REFERENCES lurkqvd.execucoes (id),
    disparada_aqui         boolean NOT NULL DEFAULT true,   -- false = reaproveitou uma que já estava rodando
    PRIMARY KEY (execucao_aplicacao_id, carga_id)
);
