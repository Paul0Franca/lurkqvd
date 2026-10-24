-- Foto do perfil Google (claim "picture" do ID token), atualizada a cada login.
ALTER TABLE lurkqvd.usuarios ADD COLUMN IF NOT EXISTS foto_url text;
