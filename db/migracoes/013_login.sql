-- 013: login próprio (e-mail + senha), sem Google
--   usuarios.senha_hash:    scrypt (formato em src/lurkqvd/senhas.py); NULL = ainda sem senha (só entra depois
--                           que um admin redefinir, ou pelo comando definir-senha)
--   usuarios.trocar_senha:  senha temporária (gerada pelo sistema): no próximo login a pessoa é obrigada a trocar
--   usuarios.google_sub:    resto do login com Google; deixa de ser obrigatório
--   sessoes:                um login = uma sessão; só o hash do token fica aqui
--   convites:               sai: o admin cadastra a pessoa e ela recebe a senha temporária por e-mail

ALTER TABLE lurkqvd.usuarios ALTER COLUMN google_sub DROP NOT NULL;
ALTER TABLE lurkqvd.usuarios ADD COLUMN IF NOT EXISTS senha_hash text;
ALTER TABLE lurkqvd.usuarios ADD COLUMN IF NOT EXISTS trocar_senha boolean NOT NULL DEFAULT false;
ALTER TABLE lurkqvd.usuarios ADD COLUMN IF NOT EXISTS senha_alterada_em timestamptz;

CREATE TABLE IF NOT EXISTS lurkqvd.sessoes (
    id             bigserial PRIMARY KEY,
    usuario_id     int NOT NULL REFERENCES lurkqvd.usuarios (id) ON DELETE CASCADE,
    hash           text NOT NULL UNIQUE,          -- sha256 do token
    criado_em      timestamptz NOT NULL DEFAULT now(),
    ultimo_uso     timestamptz NOT NULL DEFAULT now(),
    expira_em      timestamptz NOT NULL,          -- limite absoluto; inatividade é conferida pelo ultimo_uso
    ip             text,
    navegador      text,
    revogada_em    timestamptz
);
CREATE INDEX IF NOT EXISTS ix_sessoes_usuario ON lurkqvd.sessoes (usuario_id) WHERE revogada_em IS NULL;

DROP TABLE IF EXISTS lurkqvd.convites;
