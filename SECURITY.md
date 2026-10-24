# Segurança

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use o recurso *Report a vulnerability* (aba **Security** do repositório no
GitHub), que cria um aviso privado para os mantenedores. Descreva o problema, como reproduzir e o impacto.

Respondemos em até 5 dias úteis e combinamos com você a divulgação depois que a correção estiver publicada.

## Versões com correções de segurança

Só a versão mais recente (branch `main`) recebe correções.

## O que o LurkQVD faz para proteger os seus dados

- **Senhas de usuários:** hash `scrypt` com sal; a senha nunca é guardada nem registrada em log.
- **Sessões:** token aleatório de 256 bits; o banco guarda só o SHA-256 dele. Expira após 12 h sem uso e
  em no máximo 7 dias. Trocar a senha ou ser desativado derruba as sessões abertas.
- **Força bruta:** 5 erros de login em 15 minutos (por login e IP) bloqueiam novas tentativas.
- **Primeiro acesso:** toda senha gerada pelo sistema (admin da instalação, usuário novo, redefinição) é
  temporária, com troca obrigatória no primeiro login.
- **Credenciais externas** (API key da Qlik, senhas dos bancos de origem e do SMTP): criptografadas no
  Postgres com Fernet (AES-128-CBC + HMAC-SHA256). A chave fica só no servidor (`LURKQVD_FERNET_KEY`).
- **Tokens de API** (integrações como o Airflow): guardados só como hash, com validade e revogação;
  nunca têm permissão de administrador.
- **Permissões** por papel (leitor, editor, admin), checadas em todas as rotas; a suíte de testes
  confere que nenhuma rota responde sem login.
- **Front:** Content-Security-Policy sem scripts de terceiros nem inline, `X-Frame-Options: DENY`,
  `nosniff` e demais cabeçalhos de segurança no nginx.
- **Auditoria** de logins, cadastros, mudanças de acesso, de configuração e de cargas.

## Recomendações para produção

- Publique o LurkQVD **atrás de HTTPS** (proxy reverso ou balanceador com certificado).
- Use, nas fontes de dados, um **usuário de banco só de leitura**.
- Guarde uma cópia da `LURKQVD_FERNET_KEY` num cofre de senhas, fora do servidor.
- Não ative `LURKQVD_AUTH_DEV` fora de testes locais: ela libera tudo sem login.
- Faça backup do volume do Postgres.
