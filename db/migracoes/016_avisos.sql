-- 016: avisos dentro do LurkQVD (o sino do topo e o balão que abre ao entrar)
--   avisos:        o que aparece para quem usa a ferramenta. origem 'admin' = publicado em Configurações › Avisos;
--                  'sistema' = vem com o próprio LurkQVD (novidades da versão).
--                  publico = papel mínimo de quem vê (leitor = todo mundo).
--                  abrir_ao_entrar = abre o balão na tela enquanto a pessoa não marcar como lido.
--                  expira_em vazio = não expira.
--   avisos_lidos:  quem já leu o quê (uma linha por pessoa e aviso).

CREATE TABLE IF NOT EXISTS lurkqvd.avisos (
    id               serial PRIMARY KEY,
    titulo           text NOT NULL,
    texto            text NOT NULL,
    link_url         text,
    link_rotulo      text,
    publico          text NOT NULL DEFAULT 'leitor' CHECK (publico IN ('leitor', 'editor', 'admin')),
    abrir_ao_entrar  boolean NOT NULL DEFAULT true,
    origem           text NOT NULL DEFAULT 'admin' CHECK (origem IN ('admin', 'sistema')),
    publicado_em     timestamptz NOT NULL DEFAULT now(),
    expira_em        timestamptz,
    criado_por       int REFERENCES lurkqvd.usuarios (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_avisos_publicado ON lurkqvd.avisos (publicado_em DESC);

CREATE TABLE IF NOT EXISTS lurkqvd.avisos_lidos (
    aviso_id    int NOT NULL REFERENCES lurkqvd.avisos (id) ON DELETE CASCADE,
    usuario_id  int NOT NULL REFERENCES lurkqvd.usuarios (id) ON DELETE CASCADE,
    lido_em     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (aviso_id, usuario_id)
);

-- primeira novidade: a página do produto no site da DataLurk (some sozinha em 60 dias)
INSERT INTO lurkqvd.avisos (titulo, texto, link_url, link_rotulo, origem, expira_em)
VALUES (
    'O LurkQVD agora tem página própria',
    E'Conheça tudo o que o LurkQVD faz, veja as telas e acompanhe as novidades no site da DataLurk.\n\nOs avisos como este aparecem no sino do topo da tela.',
    'https://datalurk.com.br/lurkqvd',
    'Abrir datalurk.com.br/lurkqvd',
    'sistema',
    now() + interval '60 days'
);
