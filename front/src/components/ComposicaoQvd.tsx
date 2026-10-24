// Painel "o que pesa no QVD": usado na estimativa (antes de gerar) e na composição medida (depois).

import { useEffect, useState } from "react";
import { Lightbulb } from "lucide-react";
import type { Api, Estimativa } from "../api";
import { relativo, tamanho } from "../lib/formato";

const CATEGORIA: Record<string, string> = {
  inteiro: "inteiro",
  decimal: "decimal",
  texto: "texto",
  data: "data",
  data_hora: "data e hora",
  hora: "hora",
};

const ORIGEM: Record<string, { rotulo: string; dica: string }> = {
  medido: { rotulo: "medido", dica: "Contado nos dados da última execução" },
  exato: { rotulo: "exato", dica: "A consulta inteira coube na amostra" },
  "estatística": { rotulo: "estatística", dica: "Estatísticas do próprio banco para essa coluna" },
  amostra: { rotulo: "amostra", dica: "Extrapolado da amostra; precisão menor" },
};

const num = (n: number) => n.toLocaleString("pt-BR");

interface Props {
  r: Estimativa;
  titulo: string;
  /** tamanho real do QVD publicado, quando existir */
  realBytes?: number | null;
  /** texto pequeno de rodapé (de onde vieram os números) */
  rodape?: string;
  desatualizada?: boolean;
}

export default function PainelComposicao({ r, titulo, realBytes, rodape, desatualizada }: Props) {
  const maiorPct = Math.max(...r.colunas.map((c) => c.pct), 1); // barras relativas à maior coluna
  const mostrarOrigem = r.colunas.some((c) => c.origem && c.origem !== "medido");

  return (
    <div className={`estimativa ${desatualizada ? "opacity-60" : ""}`} aria-live="polite">
      {desatualizada && <p className="mb-3 text-xs text-muted-foreground">A consulta mudou desde esta estimativa.</p>}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs text-muted-foreground">{titulo}</p>
          <p className="mt-0.5 font-sora text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums">
            {realBytes != null ? tamanho(realBytes) : `≈ ${tamanho(r.tamanho_bytes)}`}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {num(r.linhas)} linhas{r.origem_linhas === "plano" && " (pelo plano do banco)"} · {r.bytes_por_linha} bytes por linha no índice · {r.colunas.length} colunas
          </p>
        </div>
        <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 text-right text-xs">
          <dt className="text-muted-foreground">da cota de {num(r.cota_gb)} GB</dt>
          <dd className="font-medium tabular-nums">{r.pct_cota < 0.01 ? "< 0,01" : r.pct_cota.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%</dd>
          <dt className="text-muted-foreground">calculado em</dt>
          <dd className="tabular-nums">
            {r.segundos.toLocaleString("pt-BR")} s{r.fonte_nome && <span className="text-muted-foreground"> · {r.fonte_nome}</span>}
          </dd>
        </dl>
      </div>

      <div className="mt-5">
        <p className="mb-2 text-xs font-medium">O que pesa no arquivo</p>
        <ol className="flex flex-col gap-1.5">
          {r.colunas.map((c) => (
            <li key={c.nome} className="coluna-peso" title={`${num(c.distintos)} valores distintos · ${c.bits} bits por linha no índice · símbolos ${tamanho(c.bytes_simbolos)} + índice ${tamanho(c.bytes_indice)}`}>
              <span className="min-w-0 truncate font-mono text-[12.5px]">{c.nome}</span>
              <span className="hidden items-center gap-1.5 text-[11px] text-muted-foreground sm:flex">
                <span className="truncate">
                  {CATEGORIA[c.categoria] ?? c.categoria} · {num(c.distintos)} distintos
                </span>
                {mostrarOrigem && c.origem && (
                  <span className={`selo-origem selo-origem-${c.origem === "amostra" ? "fraca" : "forte"}`} title={ORIGEM[c.origem]?.dica}>
                    {ORIGEM[c.origem]?.rotulo ?? c.origem}
                  </span>
                )}
              </span>
              <span className="barra-peso" aria-hidden="true">
                <span style={{ width: `${Math.max((100 * c.pct) / maiorPct, 1)}%` }} />
              </span>
              <span className="text-right text-xs tabular-nums">
                {c.pct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%<span className="ml-1.5 text-muted-foreground">{tamanho(c.bytes_total)}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      {(r.sugestoes.length > 0 || (r.avisos?.length ?? 0) > 0) && (
        <ul className="mt-5 flex flex-col gap-2">
          {r.sugestoes.map((s) => (
            <li key={s} className="dica-estimativa">
              <Lightbulb className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {s}
            </li>
          ))}
          {r.avisos?.map((a) => (
            <li key={a} className="text-xs text-muted-foreground">
              {a}
            </li>
          ))}
        </ul>
      )}

      {rodape && <p className="mt-4 text-[11px] text-muted-foreground">{rodape}</p>}
    </div>
  );
}

/** Página da carga: composição medida na última execução (não consulta o banco de origem). */
export function ComposicaoCarga({ api, cargaId, versao }: { api: Api; cargaId: number; versao?: number | null }) {
  const [dados, setDados] = useState<Awaited<ReturnType<Api["composicao"]>> | null>(null);
  const [vazio, setVazio] = useState(false);

  // recarrega quando chega uma execução nova (versao = id da última com sucesso)
  useEffect(() => {
    let vivo = true;
    api
      .composicao(cargaId)
      .then((d) => {
        if (!vivo) return;
        setDados(d);
        setVazio(false);
      })
      .catch(() => vivo && setVazio(true));
    return () => {
      vivo = false;
    };
  }, [api, cargaId, versao]);

  if (vazio || !dados) {
    return vazio ? (
      <p className="mt-3 rounded-xl border border-dashed border-border px-4 py-3 text-xs text-muted-foreground">
        A composição do QVD (o que pesa em cada coluna) aparece aqui depois da próxima execução, medida sem custo extra no banco.
      </p>
    ) : null;
  }

  return (
    <PainelComposicao
      r={dados.composicao}
      titulo={`QVD publicado${dados.finalizado_em ? ` ${relativo(dados.finalizado_em)}` : ""}`}
      realBytes={dados.tamanho_bytes}
      rodape="Medido nos dados da última execução, enquanto o QVD era gerado: nenhuma consulta extra no banco."
    />
  );
}
