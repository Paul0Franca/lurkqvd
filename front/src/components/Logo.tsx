// Identidade DataLurk.
//
// - Bichinho "espiando": meia-lua com dois olhos que surge por trás de uma linha.
// - Sub-logo do LurkQVD: o mesmo bichinho espiando por cima de três linhas de dados
//   (as linhas de uma tabela que vira QVD). Mesma família, leitura própria.

import { useEffect, useId, useRef } from "react";

const GRAFITE = "#121417";
const OFFWHITE = "#F2F1EC";
const CIANO = "#22D3EE";

/* ------------------------------------------------------------------ */
/* Olhos que seguem o cursor (só quando há mouse e animação liberada)  */
/* ------------------------------------------------------------------ */
function useOlharCursor(ativo: boolean) {
  const ref = useRef<SVGGElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!ativo || !el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!window.matchMedia("(pointer: fine)").matches) return;

    let frame = 0;
    const mover = (e: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const r = el.ownerSVGElement?.getBoundingClientRect();
        if (!r) return;
        const dx = (e.clientX - (r.left + r.width / 2)) / (window.innerWidth / 2);
        const dy = (e.clientY - (r.top + r.height / 2)) / (window.innerHeight / 2);
        const x = Math.max(-1, Math.min(1, dx)) * 7;
        const y = Math.max(-1, Math.min(1, dy)) * 3;
        el.style.transform = `translate(${x}px, ${y}px)`;
      });
    };
    window.addEventListener("pointermove", mover);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", mover);
    };
  }, [ativo]);

  return ref;
}

/* ------------------------------------------------------------------ */
/* Sub-logo do LurkQVD                                                 */
/* ------------------------------------------------------------------ */
interface SubLogoProps {
  tamanho?: number;
  /** cor do bichinho; os olhos usam corOlhos */
  corForma?: string;
  corOlhos?: string;
  pisca?: boolean;
  className?: string;
}

export function SubLogoQVD({
  tamanho = 40,
  corForma = OFFWHITE,
  corOlhos = GRAFITE,
  pisca = false,
  className,
}: SubLogoProps) {
  const olho = pisca ? "lurk-pisca" : undefined;
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 200 200" className={className} aria-hidden="true">
      {/* bichinho, um pouco mais alto que no logo-mãe para dar espaço às linhas */}
      <path d="M50 112 A50 50 0 0 1 150 112 Z" fill={corForma} />
      <circle className={olho} cx="110" cy="84" r="10" fill={corOlhos} />
      <circle className={olho} cx="136" cy="84" r="10" fill={corOlhos} />
      {/* três linhas de dados, decrescentes: a "tabela" que vira QVD */}
      <rect x="22" y="110" width="156" height="12" rx="6" fill={CIANO} />
      <rect x="22" y="134" width="118" height="12" rx="6" fill={CIANO} opacity="0.55" />
      <rect x="22" y="158" width="78" height="12" rx="6" fill={CIANO} opacity="0.28" />
    </svg>
  );
}

/** Assinatura do produto: "Lurk" + "QVD", no padrão da família (LurkBI, LurkReach). */
export function Assinatura({ className = "" }: { className?: string }) {
  return (
    <span className={`font-sora tracking-tight ${className}`}>
      <span className="font-bold">Lurk</span>
      <span className="font-light">QVD</span>
    </span>
  );
}

/** Marca-mãe em texto, para a linha "por DataLurk". */
export function DataLurk({ className = "" }: { className?: string }) {
  return (
    <span className={`font-sora tracking-tight ${className}`}>
      <span className="font-bold">Data</span>
      <span className="font-light">Lurk</span>
    </span>
  );
}

// [x, y, raio, opacidade, cintila (1..3 ou 0)]
const ESTRELAS: [number, number, number, number, number][] = [
  [96, 58, 1.4, 0.35, 1], [182, 132, 1, 0.22, 0], [254, 36, 1.2, 0.3, 0], [318, 108, 0.9, 0.18, 2],
  [452, 30, 1.3, 0.32, 0], [531, 92, 1, 0.2, 3], [606, 44, 1.5, 0.38, 0], [688, 128, 1, 0.22, 1],
  [744, 66, 1.2, 0.28, 0], [140, 196, 0.9, 0.15, 0], [660, 200, 0.9, 0.15, 2], [392, 164, 0.8, 0.12, 0],
];

/* ------------------------------------------------------------------ */
/* Cena do painel: o bichinho da DataLurk espiando por cima do         */
/* horizonte, com o campo de dados embaixo.                            */
/* ------------------------------------------------------------------ */
export function CenaEspiando({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  const olhos = useOlharCursor(true);

  // horizonte em y=250 (centro da linha). Bichinho original (viewBox 200) escalado 2x.
  return (
    <svg viewBox="0 0 800 440" className={className} aria-hidden="true" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id={`hz-${id}`} x1="0" x2="1">
          <stop offset="0" stopColor={CIANO} stopOpacity="0" />
          <stop offset="0.25" stopColor={CIANO} stopOpacity="0.9" />
          <stop offset="0.5" stopColor={CIANO} />
          <stop offset="0.75" stopColor={CIANO} stopOpacity="0.9" />
          <stop offset="1" stopColor={CIANO} stopOpacity="0" />
        </linearGradient>

        {/* brilho do horizonte */}
        <filter id={`gl-${id}`} x="-20%" y="-400%" width="140%" height="900%">
          <feGaussianBlur stdDeviation="9" />
        </filter>

        {/* campo de dados: grade de pontos que some com a distância */}
        <pattern id={`pt-${id}`} width="22" height="22" patternUnits="userSpaceOnUse">
          <circle cx="11" cy="11" r="1.6" fill={OFFWHITE} />
        </pattern>
        <radialGradient id={`fd-${id}`} cx="0.5" cy="0" r="0.75">
          <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id={`mk-${id}`}>
          <rect x="0" y="262" width="800" height="178" fill={`url(#fd-${id})`} />
        </mask>

        {/* tudo abaixo do horizonte some: o bichinho sai de trás da linha */}
        <clipPath id={`cl-${id}`}>
          <rect x="0" y="0" width="800" height="251" />
        </clipPath>
      </defs>

      {/* céu: poucas estrelas, bem apagadas, algumas cintilam */}
      <g fill={OFFWHITE}>
        {ESTRELAS.map(([x, y, r, o, c], i) => (
          <circle key={i} cx={x} cy={y} r={r} opacity={o} className={c ? `lurk-estrela lurk-estrela-${c}` : undefined} />
        ))}
      </g>

      {/* campo de dados */}
      <rect x="0" y="262" width="800" height="178" fill={`url(#pt-${id})`} mask={`url(#mk-${id})`} opacity="0.35" />
      {/* ligações entre os pontos acesos: as associações que ele enxerga */}
      <polyline
        className="lurk-ligacao"
        points="297,407 341,341 407,385 473,363 539,341"
        fill="none"
        stroke={CIANO}
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.35"
      />
      {/* alguns pontos acesos: o que o bichinho está vendo */}
      <g fill={CIANO}>
        <circle className="lurk-ponto" cx="341" cy="341" r="2.4" />
        <circle className="lurk-ponto lurk-ponto-2" cx="473" cy="363" r="2.4" />
        <circle className="lurk-ponto lurk-ponto-3" cx="407" cy="385" r="2.4" />
        <circle className="lurk-ponto lurk-ponto-4" cx="297" cy="407" r="2.4" />
        <circle className="lurk-ponto lurk-ponto-5" cx="539" cy="341" r="2.4" />
      </g>

      {/* bichinho */}
      <g clipPath={`url(#cl-${id})`}>
        <g transform="translate(200 -14) scale(2)">
          <g className="lurk-sobe">
            <path d="M50 132 A50 50 0 0 1 150 132 Z" fill={OFFWHITE} />
            <g className="lurk-olha">
              <g ref={olhos} className="lurk-segue">
                <circle className="lurk-pisca" cx="110" cy="104" r="10" fill={GRAFITE} />
                <circle className="lurk-pisca" cx="136" cy="104" r="10" fill={GRAFITE} />
              </g>
            </g>
          </g>
        </g>
      </g>

      {/* horizonte: brilho + linha */}
      <rect x="40" y="244" width="720" height="12" rx="6" fill={`url(#hz-${id})`} filter={`url(#gl-${id})`} opacity="0.7" />
      <rect x="40" y="244" width="720" height="12" rx="6" fill={`url(#hz-${id})`} />
    </svg>
  );
}
