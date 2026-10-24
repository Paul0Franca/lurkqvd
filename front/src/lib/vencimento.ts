// Vencimento da API key da Qlik: quantos dias faltam e o tom do aviso.

export type Nivel = "ok" | "atencao" | "critico" | "vencida";

/** Dias inteiros até a data (negativo = já passou). */
export function diasAte(iso: string): number {
  return Math.floor((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

export function nivel(dias: number): Nivel {
  if (dias < 0) return "vencida";
  if (dias <= 7) return "critico";
  if (dias <= 30) return "atencao";
  return "ok";
}

export function textoDias(dias: number): string {
  if (dias < 0) return dias === -1 ? "venceu ontem" : `venceu há ${-dias} dias`;
  if (dias === 0) return "vence hoje";
  if (dias === 1) return "vence amanhã";
  return `vence em ${dias} dias`;
}

/** Faixa do painel aparece com 15 dias ou menos. */
export const DIAS_AVISO_PAINEL = 15;
