-- 009: progresso ao vivo e cancelamento de execuções
--   progresso:    fase atual, linhas lidas, bytes enviados... (o worker atualiza a cada ~2s)
--   cancelar_em:  alguém pediu para cancelar; o worker para no próximo ponto seguro
--   status novo:  'cancelado'
ALTER TABLE lurkqvd.execucoes
    ADD COLUMN IF NOT EXISTS progresso     jsonb,
    ADD COLUMN IF NOT EXISTS cancelar_em   timestamptz,
    ADD COLUMN IF NOT EXISTS cancelado_por int REFERENCES lurkqvd.usuarios (id);

ALTER TABLE lurkqvd.execucoes DROP CONSTRAINT IF EXISTS execucoes_status_check;
ALTER TABLE lurkqvd.execucoes
    ADD CONSTRAINT execucoes_status_check
    CHECK (status IN ('pendente', 'rodando', 'sucesso', 'erro', 'cancelado'));
