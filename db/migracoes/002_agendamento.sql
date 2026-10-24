-- Agendamento de cargas (executado pelo próprio worker).
-- Banco já existente:  docker exec -i lurkqvd-postgres psql -U lurkqvd -d lurkqvd < db/migracoes/002_agendamento.sql

ALTER TABLE lurkqvd.cargas
    ADD COLUMN IF NOT EXISTS agendamento      text,                                   -- expressão cron; NULL = só manual
    ADD COLUMN IF NOT EXISTS fuso             text NOT NULL DEFAULT 'America/Sao_Paulo',
    ADD COLUMN IF NOT EXISTS proxima_execucao timestamptz;                            -- calculada a partir do cron

-- o worker procura "o que já venceu" a cada poucos segundos
CREATE INDEX IF NOT EXISTS ix_cargas_agenda
    ON lurkqvd.cargas (proxima_execucao)
    WHERE ativo AND agendamento IS NOT NULL;
