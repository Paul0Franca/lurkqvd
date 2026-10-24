-- Composição do QVD medida na própria execução (peso de cada coluna), sem custo extra no banco.
ALTER TABLE lurkqvd.execucoes ADD COLUMN IF NOT EXISTS composicao jsonb;
