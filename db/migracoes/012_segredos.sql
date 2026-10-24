-- 012: segredos no próprio Postgres
--   Cada linha é um segredo do LurkQVD (qlik_qvd, lurkqvd_fontes, lurkqvd_smtp): um JSON criptografado
--   com Fernet pela API/worker (chave em LURKQVD_FERNET_KEY, que nunca vem para o banco).
--   A última verificação da tela Segredos passa a ser a configuração 'segredos_status' (antes 'gcp_status').

CREATE TABLE IF NOT EXISTS lurkqvd.segredos (
    nome           text PRIMARY KEY,
    valor          text NOT NULL,                 -- token Fernet (base64)
    atualizado_em  timestamptz NOT NULL DEFAULT now()
);

DELETE FROM lurkqvd.configuracoes WHERE chave = 'gcp_status';
