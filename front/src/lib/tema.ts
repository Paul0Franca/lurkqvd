// Tema claro/escuro. A preferência fica no navegador (localStorage); "sistema" acompanha o sistema operacional.
// O index.html aplica o tema salvo antes da 1ª pintura (sem piscar); daqui em diante, quem troca é este módulo.
// A troca "pinta" a tela num círculo que cresce a partir do botão (View Transitions), quando o navegador suporta.

import { useSyncExternalStore } from "react";
import { flushSync } from "react-dom";

export type PreferenciaTema = "claro" | "escuro" | "sistema";
export type Tema = "claro" | "escuro";

const CHAVE = "lurkqvd.tema"; // a mesma do script do index.html
const midia = window.matchMedia("(prefers-color-scheme: dark)");
const ouvintes = new Set<() => void>();

function lerPreferencia(): PreferenciaTema {
  try {
    const v = localStorage.getItem(CHAVE);
    if (v === "claro" || v === "escuro") return v;
  } catch {
    /* navegação privada / armazenamento bloqueado: segue o sistema */
  }
  return "sistema";
}

let preferencia = lerPreferencia();

function resolver(p: PreferenciaTema): Tema {
  return p === "sistema" ? (midia.matches ? "escuro" : "claro") : p;
}

function aplicar() {
  document.documentElement.dataset.tema = resolver(preferencia);
  ouvintes.forEach((f) => f());
}

midia.addEventListener("change", () => preferencia === "sistema" && aplicar());

/** Troca o tema. `origem`: ponto (na tela) de onde a transição se espalha, normalmente o botão clicado. */
export function definirTema(p: PreferenciaTema, origem?: { x: number; y: number }) {
  if (p === preferencia) return;
  const antes = resolver(preferencia);
  preferencia = p;
  try {
    if (p === "sistema") localStorage.removeItem(CHAVE);
    else localStorage.setItem(CHAVE, p);
  } catch {
    /* vale só para esta aba */
  }

  const semAnimacao = resolver(p) === antes || !document.startViewTransition || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (semAnimacao) {
    aplicar();
    return;
  }

  const x = origem?.x ?? window.innerWidth - 40;
  const y = origem?.y ?? 32;
  const raio = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const transicao = document.startViewTransition(() => flushSync(aplicar));
  transicao.ready
    .then(() =>
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${raio}px at ${x}px ${y}px)`] },
        { duration: 560, easing: "cubic-bezier(.65, 0, .35, 1)", pseudoElement: "::view-transition-new(root)" },
      ),
    )
    .catch(() => {});
}

/** Centro de um elemento, para usar como origem da transição. */
export function centro(el: Element): { x: number; y: number } {
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

function assinar(f: () => void) {
  ouvintes.add(f);
  return () => ouvintes.delete(f);
}

const foto = () => `${preferencia}|${resolver(preferencia)}`;

export function useTema(): { preferencia: PreferenciaTema; tema: Tema } {
  const [p, t] = useSyncExternalStore(assinar, foto).split("|") as [PreferenciaTema, Tema];
  return { preferencia: p, tema: t };
}
