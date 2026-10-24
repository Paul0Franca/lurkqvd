// Painel: execuções por dia nos últimos 14 dias, empilhando sucesso e erro.
// Reaproveita o visual do gráfico da carga (classes grafico-*).

import { useState } from "react";
import type { ExecucoesDia } from "../api";

// validada (scripts/validate_palette.js): contraste, croma e daltonismo ok
const COR = { sucesso: "#0a7ca6", erro: "#d1503c" } as const;
const ALTURA = 132;

const fmtDiaCurto = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" });
const fmtDiaLongo = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
const semana = new Intl.DateTimeFormat("pt-BR", { weekday: "short", timeZone: "UTC" });
const diaSemana = (d: Date) => semana.format(d).replace(".", "");
const maiuscula = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

// "2026-10-18" vira data em UTC para o dia não escorregar com o fuso
const paraData = (dia: string) => new Date(`${dia}T00:00:00Z`);

/** Teto da escala: o dobro de um passo "redondo" e inteiro, para a linha do meio cair num número exato. */
function teto(v: number): number {
  if (v <= 4) return 4;
  const passo = v / 2;
  const p = 10 ** Math.floor(Math.log10(passo));
  const f = [1, 2, 2.5, 5, 10].find((x) => x * p >= passo) ?? 10;
  return Math.ceil(f * p) * 2;
}

const plural = (n: number, um: string, varios: string) => `${n.toLocaleString("pt-BR")} ${n === 1 ? um : varios}`;

export default function GraficoDiario({ dias }: { dias: ExecucoesDia[] | null }) {
  const [foco, setFoco] = useState<number | null>(null);

  const totalSuc = (dias ?? []).reduce((s, d) => s + d.sucesso, 0);
  const totalErr = (dias ?? []).reduce((s, d) => s + d.erro, 0);
  const total = totalSuc + totalErr;
  const max = teto(Math.max(1, ...(dias ?? []).map((d) => d.sucesso + d.erro)));
  const atual = foco !== null && dias ? dias[foco] : null;
  const hoje = dias?.at(-1)?.dia;

  return (
    <section className="grafico-exec mt-8" aria-labelledby="titulo-diario">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id="titulo-diario" className="font-sora text-sm font-semibold">
            Execuções por dia
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {!dias
              ? "Carregando…"
              : total === 0
                ? `Nenhuma execução nos últimos ${dias.length} dias.`
                : `Últimos ${dias.length} dias: ${plural(total, "execução", "execuções")}, ${Math.round((totalSuc / total) * 100)}% com sucesso`}
          </p>
        </div>
        {dias && total > 0 && (
          <ul className="flex gap-4 text-xs text-muted-foreground" aria-label="Legenda">
            <li className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: COR.sucesso }} aria-hidden="true" />
              Sucesso <span className="tabular-nums text-foreground">{totalSuc.toLocaleString("pt-BR")}</span>
            </li>
            <li className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: COR.erro }} aria-hidden="true" />
              Erro <span className="tabular-nums text-foreground">{totalErr.toLocaleString("pt-BR")}</span>
            </li>
          </ul>
        )}
      </div>

      {dias && (
        <div className="relative mt-5 pl-10" onMouseLeave={() => setFoco(null)}>
          {[1, 0.5, 0].map((f) => (
            <div key={f} className="grafico-grade" style={{ bottom: 22 + f * ALTURA }}>
              <span>{Math.round(max * f)}</span>
            </div>
          ))}

          <div className="relative flex items-end gap-[6px]" style={{ height: ALTURA + 22 }}>
            {dias.map((d, i) => {
              const soma = d.sucesso + d.erro;
              const ativo = foco === i;
              const data = paraData(d.dia);
              return (
                <button
                  key={d.dia}
                  type="button"
                  className="grafico-coluna"
                  data-ativo={ativo || undefined}
                  data-apagado={foco !== null && !ativo ? true : undefined}
                  onMouseEnter={() => setFoco(i)}
                  onFocus={() => setFoco(i)}
                  onBlur={() => setFoco(null)}
                  aria-label={`${fmtDiaLongo.format(data)}: ${plural(d.sucesso, "sucesso", "sucessos")}, ${plural(d.erro, "erro", "erros")}`}
                >
                  <span className="flex w-full max-w-[40px] flex-col-reverse" style={{ height: ALTURA }}>
                    {soma > 0 ? (
                      <span className="grafico-pilha" style={{ height: Math.max((soma / max) * ALTURA, 3) }}>
                        {d.erro > 0 && <span style={{ flexGrow: d.erro, background: COR.erro }} />}
                        {d.sucesso > 0 && <span style={{ flexGrow: d.sucesso, background: COR.sucesso }} />}
                      </span>
                    ) : (
                      <span className="grafico-vazio" aria-hidden="true" />
                    )}
                  </span>
                  <span className="grafico-rotulo" data-hoje={d.dia === hoje || undefined}>
                    {d.dia === hoje ? "hoje" : `${diaSemana(data)} ${fmtDiaCurto.format(data).slice(0, 2)}`}
                  </span>
                </button>
              );
            })}

            {atual && foco !== null && (
              <div
                className="grafico-dica"
                role="status"
                style={
                  foco >= dias.length / 2
                    ? { right: `calc(${((dias.length - foco) / dias.length) * 100}% + 8px)` }
                    : { left: `calc(${((foco + 1) / dias.length) * 100}% + 8px)` }
                }
              >
                <p className="font-medium text-foreground">{maiuscula(fmtDiaLongo.format(paraData(atual.dia)))}</p>
                <dl className="mt-2 grid grid-cols-[auto_auto] gap-x-6 gap-y-0.5">
                  <dt className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-[2px]" style={{ background: COR.sucesso }} aria-hidden="true" />
                    Sucesso
                  </dt>
                  <dd className="text-right tabular-nums text-foreground">{atual.sucesso}</dd>
                  <dt className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-[2px]" style={{ background: COR.erro }} aria-hidden="true" />
                    Erro
                  </dt>
                  <dd className="text-right tabular-nums text-foreground">{atual.erro}</dd>
                  {atual.em_andamento > 0 && (
                    <>
                      <dt>Em andamento</dt>
                      <dd className="text-right tabular-nums text-foreground">{atual.em_andamento}</dd>
                    </>
                  )}
                </dl>
                {atual.cargas_com_erro.length > 0 && (
                  <div className="mt-2 border-t border-border pt-2">
                    <p>Falharam:</p>
                    <ul className="mt-0.5 font-mono text-[12px] text-foreground">
                      {atual.cargas_com_erro.slice(0, 4).map((n) => (
                        <li key={n} className="truncate">
                          {n}
                        </li>
                      ))}
                    </ul>
                    {atual.cargas_com_erro.length > 4 && <p className="mt-0.5">e mais {atual.cargas_com_erro.length - 4}</p>}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {dias && (
        <table className="sr-only">
          <caption>Execuções por dia</caption>
          <thead>
            <tr>
              <th>Dia</th>
              <th>Sucesso</th>
              <th>Erro</th>
              <th>Cargas com erro</th>
            </tr>
          </thead>
          <tbody>
            {dias.map((d) => (
              <tr key={d.dia}>
                <td>{fmtDiaLongo.format(paraData(d.dia))}</td>
                <td>{d.sucesso}</td>
                <td>{d.erro}</td>
                <td>{d.cargas_com_erro.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
