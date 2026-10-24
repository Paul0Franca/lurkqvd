-- 011: notificações por e-mail (SMTP)
--   configuracoes 'smtp':          servidor, porta, segurança, usuário e remetente (a senha fica no Secret
--                                  Manager, secret lurkqvd_smtp, JSON {"senha": "..."}; nunca aqui)
--   configuracoes 'notificacoes':  o que avisar e para quem
--   notificado_em:                 o worker já olhou essa execução para avisar (ou não) por e-mail;
--                                  as que já existiam entram como vistas, para não chover e-mail ao ligar
--   notificacoes_enviadas:         histórico dos envios (convites, avisos de erro, testes), com o erro se falhou

ALTER TABLE lurkqvd.execucoes ADD COLUMN IF NOT EXISTS notificado_em timestamptz;
UPDATE lurkqvd.execucoes SET notificado_em = COALESCE(finalizado_em, now())
 WHERE notificado_em IS NULL AND status IN ('sucesso', 'erro', 'cancelado');
CREATE INDEX IF NOT EXISTS ix_execucoes_notificar ON lurkqvd.execucoes (id) WHERE notificado_em IS NULL;

ALTER TABLE lurkqvd.execucoes_aplicacao ADD COLUMN IF NOT EXISTS notificado_em timestamptz;
UPDATE lurkqvd.execucoes_aplicacao SET notificado_em = COALESCE(finalizado_em, now())
 WHERE notificado_em IS NULL AND status IN ('sucesso', 'erro', 'cancelado');
CREATE INDEX IF NOT EXISTS ix_execucoes_aplicacao_notificar ON lurkqvd.execucoes_aplicacao (id) WHERE notificado_em IS NULL;

CREATE TABLE IF NOT EXISTS lurkqvd.notificacoes_enviadas (
    id             bigserial PRIMARY KEY,
    tipo           text NOT NULL,                 -- convite, falhas, qlik, teste
    assunto        text NOT NULL,
    destinatarios  text[] NOT NULL,
    ok             boolean NOT NULL,
    erro           text,
    detalhes       jsonb NOT NULL DEFAULT '{}',
    criado_em      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_notificacoes_enviadas_recentes ON lurkqvd.notificacoes_enviadas (criado_em DESC);

INSERT INTO lurkqvd.configuracoes (chave, valor) VALUES
    ('notificacoes', '{"convites": true, "erros_cargas": true, "erros_aplicacoes": true, "recuperacao": true,
                       "qlik": true, "so_mudanca": true, "para_admins": true, "extras": []}')
ON CONFLICT (chave) DO NOTHING;
