// Rotas por hash (#/espacos/...): simples, sem dependência e funciona em qualquer hospedagem estática.
import { useEffect, useState } from "react";

export type Rota =
  | { tela: "painel" }
  | { tela: "espacos" }
  | { tela: "espaco"; connectionId: string; pasta: string }
  | { tela: "cargas"; connectionId?: string; pasta?: string; visao?: "lista" | "aplicacoes" }
  | { tela: "aplicacao"; id: number }
  | { tela: "nova-carga"; connectionId?: string; pasta?: string }
  | { tela: "carga"; id: number };

export function lerRota(hash = window.location.hash): Rota {
  const [caminho, busca = ""] = hash.replace(/^#\/?/, "").split("?");
  const partes = caminho.split("/").filter(Boolean).map(decodeURIComponent);
  const q = new URLSearchParams(busca);
  const filtro = { connectionId: q.get("espaco") ?? undefined, pasta: q.get("pasta") ?? undefined };
  // a aba Cargas abre por aplicação; a lista vem com ?visao=lista ou com filtro de espaço/pasta (só a lista filtra)
  const visao = q.get("visao") === "lista" || (q.get("visao") !== "aplicacoes" && (filtro.connectionId || filtro.pasta)) ? ("lista" as const) : ("aplicacoes" as const);

  if (partes[0] === "espacos" && partes[1]) return { tela: "espaco", connectionId: partes[1], pasta: partes.slice(2).join("/") };
  if (partes[0] === "espacos") return { tela: "espacos" };
  if (partes[0] === "cargas" && partes[1] === "nova") return { tela: "nova-carga", ...filtro };
  if (partes[0] === "cargas" && Number(partes[1])) return { tela: "carga", id: Number(partes[1]) };
  if (partes[0] === "cargas") return { tela: "cargas", ...filtro, visao };
  if (partes[0] === "aplicacoes" && Number(partes[1])) return { tela: "aplicacao", id: Number(partes[1]) };
  if (partes[0] === "aplicacoes") return { tela: "cargas", visao: "aplicacoes" };
  return { tela: "painel" };
}

function consulta(connectionId?: string, pasta?: string, visao?: string): string {
  const q = new URLSearchParams();
  if (visao === "lista") q.set("visao", visao);
  if (connectionId) q.set("espaco", connectionId);
  if (pasta) q.set("pasta", pasta);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function link(rota: Rota): string {
  switch (rota.tela) {
    case "painel":
      return "#/";
    case "espacos":
      return "#/espacos";
    case "espaco":
      return `#/espacos/${encodeURIComponent(rota.connectionId)}${rota.pasta ? "/" + rota.pasta.split("/").map(encodeURIComponent).join("/") : ""}`;
    case "cargas":
      return `#/cargas${consulta(rota.connectionId, rota.pasta, rota.visao)}`;
    case "aplicacao":
      return `#/aplicacoes/${rota.id}`;
    case "nova-carga":
      return `#/cargas/nova${consulta(rota.connectionId, rota.pasta)}`;
    case "carga":
      return `#/cargas/${rota.id}`;
  }
}

export function navegar(rota: Rota): void {
  window.location.hash = link(rota).slice(1);
}

export function useRota(): Rota {
  const [rota, setRota] = useState<Rota>(() => lerRota());
  useEffect(() => {
    const mudou = () => {
      setRota(lerRota());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", mudou);
    return () => window.removeEventListener("hashchange", mudou);
  }, []);
  return rota;
}
