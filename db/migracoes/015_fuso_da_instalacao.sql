-- 015: o fuso dos agendamentos passa a ser o da instalação (LURKQVD_FUSO)
--   Coluna fuso vazia = segue o fuso da instalação. Até aqui ela sempre recebia o padrão
--   'America/Sao_Paulo' (nenhuma tela escolhia outro), então esses valores viram vazios.
ALTER TABLE lurkqvd.cargas     ALTER COLUMN fuso DROP NOT NULL, ALTER COLUMN fuso DROP DEFAULT;
ALTER TABLE lurkqvd.aplicacoes ALTER COLUMN fuso DROP NOT NULL, ALTER COLUMN fuso DROP DEFAULT;

UPDATE lurkqvd.cargas     SET fuso = NULL WHERE fuso = 'America/Sao_Paulo';
UPDATE lurkqvd.aplicacoes SET fuso = NULL WHERE fuso = 'America/Sao_Paulo';
