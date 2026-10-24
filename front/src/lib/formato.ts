import type { StatusExecucao } from "../api";

// Formatação compartilhada entre as telas.

export function dataHora(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

export function tamanho(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes === 0) return "0 KB";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
  return `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("pt-BR")} KB`;
}

export function duracao(segundos: number | string | null | undefined): string {
  const s = Number(segundos ?? 0);
  if (!s) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}min ${Math.round(s % 60)}s`;
}

const RELATIVO = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });

/** "há 5 minutos", "ontem"... */
export function relativo(iso: string): string {
  const seg = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(seg);
  if (abs < 45) return "agora";
  if (abs < 3600) return RELATIVO.format(Math.round(seg / 60), "minute");
  if (abs < 86400) return RELATIVO.format(Math.round(seg / 3600), "hour");
  return RELATIVO.format(Math.round(seg / 86400), "day");
}

export const ROTULO: Record<StatusExecucao, string> = {
  pendente: "Na fila",
  rodando: "Rodando",
  sucesso: "Sucesso",
  erro: "Erro",
  cancelado: "Cancelado",
};

export const TIPO_ESPACO: Record<string, string> = {
  managed: "Gerenciado",
  shared: "Compartilhado",
  personal: "Pessoal",
  data: "Dados",
};
