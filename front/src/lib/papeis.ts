import type { Papel } from "../api";

export const PAPEIS: Papel[] = ["leitor", "editor", "admin"];

export const NOME_PAPEL: Record<Papel, string> = { leitor: "Leitor", editor: "Editor", admin: "Admin" };

export const DESCRICAO_PAPEL: Record<Papel, string> = {
  leitor: "Acompanha cargas e execuções",
  editor: "Também executa cargas",
  admin: "Cria cargas, pastas e gerencia acessos",
};
