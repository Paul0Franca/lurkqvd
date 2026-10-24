-- Convites: e-mail pré-cadastrado com um papel. No 1º login a pessoa já entra
-- com esse papel e o convite é apagado.
CREATE TABLE IF NOT EXISTS lurkqvd.convites (
    email          text PRIMARY KEY,           -- sempre em minúsculas
    papel          text NOT NULL CHECK (papel IN ('admin', 'editor', 'leitor')),
    convidado_por  int REFERENCES lurkqvd.usuarios (id),
    criado_em      timestamptz NOT NULL DEFAULT now()
);
