// Peças pequenas reaproveitadas pelas telas.

import { useState } from "react";
import { Check, ChevronRight, Copy, Loader2, Play } from "lucide-react";
import type { StatusExecucao } from "../api";
import { ROTULO } from "../lib/formato";

export function StatusBadge({ status }: { status: StatusExecucao | null }) {
  if (!status) return <span className="status status-nunca">Nunca rodou</span>;
  return (
    <span className={`status status-${status} inline-flex items-center gap-1.5`}>
      {status === "rodando" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
      {ROTULO[status]}
    </span>
  );
}

export interface Migalha {
  rotulo: string;
  href?: string;
}

/** Caminho no topo da página: Espaços / SH DWH / qvd / vendas */
export function Migalhas({ itens }: { itens: Migalha[] }) {
  return (
    <nav aria-label="Você está em" className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
      {itens.map((m, i) => (
        <span key={`${m.rotulo}-${i}`} className="inline-flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />}
          {m.href && i < itens.length - 1 ? (
            <a href={m.href} className="rounded px-1 py-0.5 hover:bg-secondary hover:text-foreground">
              {m.rotulo}
            </a>
          ) : (
            <span className="px-1 py-0.5 text-foreground" aria-current={i === itens.length - 1 ? "page" : undefined}>
              {m.rotulo}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}

export function BotaoExecutar({
  emAndamento,
  desativado,
  aoClicar,
  tamanho = "normal",
}: {
  emAndamento: boolean;
  desativado?: boolean;
  aoClicar: () => void;
  tamanho?: "normal" | "grande";
}) {
  return (
    <button
      className={tamanho === "grande" ? "btn-primario inline-flex items-center gap-2" : "btn-executar inline-flex items-center gap-1.5"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        aoClicar();
      }}
      disabled={emAndamento || desativado}
    >
      {emAndamento ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <Play className="h-3.5 w-3.5" aria-hidden="true" fill="currentColor" />
      )}
      {emAndamento ? "Executando" : "Executar"}
    </button>
  );
}

/** Ícone de "repositório": as três linhas de dados do sub-logo, em escala de ícone. */
export function IconeEspaco({ ativo, className = "" }: { ativo: boolean; className?: string }) {
  const cor = ativo ? "var(--lq-accent)" : "var(--lq-muted)";
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="3" y="6" width="18" height="2.6" rx="1.3" fill={cor} />
      <rect x="3" y="11" width="13.5" height="2.6" rx="1.3" fill={cor} opacity="0.6" />
      <rect x="3" y="16" width="9" height="2.6" rx="1.3" fill={cor} opacity="0.32" />
    </svg>
  );
}

/** Comando de terminal em bloco escuro, com botão de copiar. */
export function Comando({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="comando">
      <code>{texto}</code>
      <button
        type="button"
        aria-label="Copiar comando"
        onClick={() =>
          navigator.clipboard
            .writeText(texto)
            .then(() => {
              setCopiado(true);
              setTimeout(() => setCopiado(false), 1500);
            })
            .catch(() => {})
        }
      >
        {copiado ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

/** Trecho de código com várias linhas e botão de copiar. */
export function BlocoExemplo({ codigo, linguagem }: { codigo: string; linguagem?: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="bloco-exemplo">
      <div className="bloco-exemplo-topo">
        <span>{linguagem}</span>
        <button
          type="button"
          onClick={() =>
            navigator.clipboard
              .writeText(codigo)
              .then(() => {
                setCopiado(true);
                setTimeout(() => setCopiado(false), 1500);
              })
              .catch(() => {})
          }
        >
          {copiado ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copiado ? "Copiado" : "Copiar"}
        </button>
      </div>
      <pre>
        <code>{codigo}</code>
      </pre>
    </div>
  );
}
