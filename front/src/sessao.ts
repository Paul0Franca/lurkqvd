// Guarda o token da sessão no navegador (localStorage: sobrevive a fechar a aba, até a sessão vencer).
// A validade real é conferida pela API; aqui só evita usar um token que já se sabe vencido.

const CHAVE = "lurkqvd.sessao";

export function tokenSalvo(): string | null {
  try {
    const salvo = JSON.parse(localStorage.getItem(CHAVE) ?? "null") as { token?: string; expira_em?: string } | null;
    if (salvo?.token && salvo.expira_em && new Date(salvo.expira_em).getTime() > Date.now() + 60_000) return salvo.token;
    localStorage.removeItem(CHAVE);
  } catch {
    /* storage indisponível ou conteúdo antigo: segue sem sessão salva */
  }
  return null;
}

export function salvarToken(token: string, expiraEm: string): void {
  try {
    localStorage.setItem(CHAVE, JSON.stringify({ token, expira_em: expiraEm }));
  } catch {
    /* ignora: a sessão vale só enquanto a página estiver aberta */
  }
}

export function limparToken(): void {
  try {
    localStorage.removeItem(CHAVE);
    sessionStorage.removeItem("lurkqvd.token"); // do login com o Google
  } catch {
    /* ignora */
  }
}
