import type { ArquivosQlikRemovidos } from "../api";

/** Texto do aviso quando o QVD não saiu da Qlik (a carga já saiu do LurkQVD). null = nada a avisar. */
export function avisoQlik(qlik: ArquivosQlikRemovidos | null | undefined): string | null {
  if (!qlik?.erros.length) return null;
  return (
    "Excluído do LurkQVD, mas não foi possível apagar na Qlik o arquivo de:\n" +
    qlik.erros.map((e) => `• ${e.nome}: ${e.erro}`).join("\n") +
    "\nApague-o direto na Qlik Cloud se ninguém mais usar."
  );
}
