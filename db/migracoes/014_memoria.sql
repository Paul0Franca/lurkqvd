-- 014: memória por execução e reserva de memória na fila
--   memoria_pico_bytes:       quanto a carga fez o processo do worker crescer (pico − início); vira a estimativa
--                             das próximas execuções da mesma carga
--   memoria_reservada_bytes:  o que o worker reservou ao pegar a execução; a soma das que estão rodando
--                             numa máquina não passa da capacidade dela
--   maquina:                  onde rodou; workers da mesma máquina dividem a mesma RAM
ALTER TABLE lurkqvd.execucoes
    ADD COLUMN IF NOT EXISTS memoria_pico_bytes      bigint,
    ADD COLUMN IF NOT EXISTS memoria_reservada_bytes bigint,
    ADD COLUMN IF NOT EXISTS maquina                 text;

-- quanto já está reservado em cada máquina (consultado a cada execução pega)
CREATE INDEX IF NOT EXISTS ix_execucoes_rodando_maquina ON lurkqvd.execucoes (maquina) WHERE status = 'rodando';
