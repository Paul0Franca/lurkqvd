import { useState } from "react";
import { cn } from "@/lib/utils";

interface Props {
  nome?: string | null;
  email?: string | null;
  foto?: string | null;
  tamanho?: number;
  className?: string;
}

function iniciais(nome?: string | null, email?: string | null): string {
  const base = (nome || email?.split("@")[0] || "?").trim();
  const partes = base.split(/[\s._-]+/).filter(Boolean);
  const letras = partes.length > 1 ? partes[0][0] + partes.at(-1)![0] : base.slice(0, 2);
  return letras.toUpperCase();
}

/** Foto do perfil Google; sem foto (ou se ela falhar), mostra as iniciais. */
export default function Avatar({ nome, email, foto, tamanho = 28, className }: Props) {
  const [falhou, setFalhou] = useState(false);
  const estilo = { width: tamanho, height: tamanho, fontSize: Math.round(tamanho * 0.38) };

  if (foto && !falhou) {
    return (
      <img
        src={foto}
        alt=""
        // as fotos do Google (lh3.googleusercontent.com) recusam pedidos com Referer de outro site
        referrerPolicy="no-referrer"
        onError={() => setFalhou(true)}
        className={cn("avatar", className)}
        style={estilo}
      />
    );
  }
  return (
    <span className={cn("avatar avatar-iniciais", className)} style={estilo} aria-hidden="true">
      {iniciais(nome, email)}
    </span>
  );
}
