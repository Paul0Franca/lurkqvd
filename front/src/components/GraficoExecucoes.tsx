// Gráfico das últimas execuções de uma carga: uma barra por execução, da mais
// antiga (esquerda) para a mais recente (direita). Em "Duração" a barra é dividida
// nas três etapas; em "Linhas" e "Tamanho", uma série só.

import { useState } from "react";
import { Ban, X } from "lucide-react";
import type { Execucao } from "../api";
import { ROTULO, dataHora, duracao, tamanho } from "../lib/formato";

type Medida = "duracao" | "linhas" | "tamanho";

// validada (scripts/validate_palette.js): banda de luminosidade, croma e daltonismo ok
const CORES_ETAPA = { extracao: "#0a7ca6", geracao: "#2cc3df", upload: "#7c83db" } as const;

const ETAPAS = [
  { chave: "seg_extracao", nome: "Extração", cor: CORES_ETAPA.extracao },
  { chave: "seg_geracao", nome: "Geração do QVD", cor: CORES_ETAPA.geracao },
  { chave: "seg_upload", nome: "Upload", cor: CORES_ETAPA.upload },
] as const;

const MEDIDAS: { id: Medida; rotulo: string }[] = [
  { id: "duracao", rotulo: "Duração" },
  { id: "linhas", rotulo: "Linhas" },
  { id: "tamanho", rotulo: "Tamanho" },
];

const ALTURA = 148; // px da área de plotagem

const linhas = (n: number) => n.toLocaleString("pt-BR");
const curtoData = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });

function total(e: Execucao): number {
  return ETAPAS.reduce((s, et) => s + Number(e[et.chave] ?? 0), 0);
}

function valor(e: Execucao, m: Medida): number {
  if (m === "duracao") return total(e);
  if (m === "linhas") return e.linhas ?? 0;
  return e.tamanho_bytes ?? 0;
}

function formatar(v: number, m: Medida): string {
  if (v === 0) return "0";
  if (m === "duracao") return duracao(v);
  if (m === "linhas") return linhas(Math.round(v));
  return tamanho(v);
}

/** Teto "redondo" para a escala: 1, 2, 2.5, 5 × 10^n. */
function teto(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return ([1, 2, 2.5, 5, 10].find((f) => f * p >= v) ?? 10) * p;
}

function quem(e: Execucao): string {
  if (e.usuario_nome) return e.usuario_nome.split(" ")[0];
  if (e.usuario_email) return e.usuario_email.split("@")[0];
  if (e.token_nome) return e.token_nome;
  return e.origem === "agendador" ? "Agendamento" : e.origem === "airflow" ? "Airflow" : e.origem === "aplicacao" ? "Aplicação" : "Sistema";
}

export default function GraficoExecucoes({ historico }: { historico: Execucao[] }) {
  const [medida, setMedida] = useState<Medida>("duracao");
  const [foco, setFoco] = useState<number | null>(null);

  const execs = [...historico].reverse(); // mais antiga primeiro
  const sucessos = execs.filter((e) => e.status === "sucesso");
  if (sucessos.length === 0) return null;

  const max = teto(Math.max(...sucessos.map((e) => valor(e, medida))));
  const media = sucessos.reduce((s, e) => s + valor(e, medida), 0) / sucessos.length;
  const ultima = sucessos.at(-1)!;
  const variacao = media > 0 ? (valor(ultima, medida) - media) / media : 0;
  const erros = execs.filter((e) => e.status === "erro").length;
  const atual = foco !== null ? execs[foco] : null;

  return (
    <section className="grafico-exec mt-8" aria-labelledby="titulo-grafico">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id="titulo-grafico" className="font-sora text-sm font-semibold">
            Últimas {execs.length} execuções
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Média {formatar(media, medida)}
            {sucessos.length > 1 && Math.abs(variacao) >= 0.01 && (
              <>
                , a última foi {Math.abs(Math.round(variacao * 100))}% {variacao > 0 ? "acima" : "abaixo"}
              </>
            )}
            {erros > 0 && `, ${erros} com erro`}
          </p>
        </div>
        <div className="segmentos" role="radiogroup" aria-label="Medida do gráfico">
          {MEDIDAS.map((m) => (
            <button key={m.id} type="button" role="radio" className="segmento" aria-checked={medida === m.id} onClick={() => setMedida(m.id)}>
              {m.rotulo}
            </button>
          ))}
        </div>
      </div>

      {medida === "duracao" && (
        <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legenda">
          {ETAPAS.map((et) => (
            <li key={et.chave} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: et.cor }} aria-hidden="true" />
              {et.nome}
              <span className="tabular-nums text-foreground">{duracao(Number(ultima[et.chave] ?? 0))}</span>
              <span className="sr-only">na última execução</span>
            </li>
          ))}
        </ul>
      )}

      {/* área do gráfico */}
      <div className="relative mt-4 pl-14" onMouseLeave={() => setFoco(null)}>
        {/* grade: 0, metade e teto */}
        {[1, 0.5, 0].map((f) => (
          <div key={f} className="grafico-grade" style={{ bottom: 22 + f * ALTURA }}>
            <span>{formatar(max * f, medida)}</span>
          </div>
        ))}
        {/* média */}
        <div className="grafico-media" style={{ bottom: 22 + (media / max) * ALTURA }} aria-hidden="true">
          <span>média</span>
        </div>

        <div className="relative flex items-end gap-[6px]" style={{ height: ALTURA + 22 }}>
          {execs.map((e, i) => {
            const v = valor(e, medida);
            const h = e.status === "sucesso" ? Math.max((v / max) * ALTURA, 3) : 0;
            const ativo = foco === i;
            return (
              <button
                key={e.id}
                type="button"
                className="grafico-coluna"
                data-ativo={ativo || undefined}
                data-apagado={foco !== null && !ativo ? true : undefined}
                onMouseEnter={() => setFoco(i)}
                onFocus={() => setFoco(i)}
                onBlur={() => setFoco(null)}
                aria-label={`${dataHora(e.solicitado_em)}: ${ROTULO[e.status]}${e.status === "sucesso" ? `, ${formatar(v, medida)}` : ""}`}
              >
                <span className="flex w-full max-w-[34px] flex-col-reverse items-stretch" style={{ height: ALTURA }}>
                  {e.status === "sucesso" ? (
                    medida === "duracao" ? (
                      <span className="grafico-pilha" style={{ height: h }}>
                        {[...ETAPAS].reverse().map((et) => {
                          const s = Number(e[et.chave] ?? 0);
                          return s > 0 ? <span key={et.chave} style={{ flexGrow: s, background: et.cor }} /> : null;
                        })}
                      </span>
                    ) : (
                      <span className="grafico-pilha" style={{ height: h }}>
                        <span style={{ flexGrow: 1, background: CORES_ETAPA.extracao }} />
                      </span>
                    )
                  ) : e.status === "erro" ? (
                    <span className="grafico-erro" title="Erro">
                      <X className="h-3 w-3" strokeWidth={3} aria-hidden="true" />
                    </span>
                  ) : e.status === "cancelado" ? (
                    <span className="grafico-cancelado" title="Cancelado">
                      <Ban className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" />
                    </span>
                  ) : (
                    <span className="grafico-andamento" />
                  )}
                </span>
                <span className="grafico-rotulo">{curtoData.format(new Date(e.solicitado_em))}</span>
              </button>
            );
          })}

          {atual && foco !== null && (
            <div
              className="grafico-dica"
              role="status"
              style={
                foco >= execs.length / 2
                  ? { right: `calc(${((execs.length - foco) / execs.length) * 100}% + 8px)` }
                  : { left: `calc(${((foco + 1) / execs.length) * 100}% + 8px)` }
              }
            >
              <p className="font-medium text-foreground">{dataHora(atual.solicitado_em)}</p>
              <p className={`mt-0.5 dica-status-${atual.status}`}>
                {ROTULO[atual.status]}, por {quem(atual)}
              </p>
              {atual.status === "sucesso" &&
                (medida === "duracao" ? (
                  <dl className="mt-2 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
                    {ETAPAS.map((et) => (
                      <div key={et.chave} className="contents">
                        <dt className="inline-flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-[2px]" style={{ background: et.cor }} aria-hidden="true" />
                          {et.nome}
                        </dt>
                        <dd className="text-right tabular-nums text-foreground">{duracao(Number(atual[et.chave] ?? 0))}</dd>
                      </div>
                    ))}
                    <dt className="mt-1 border-t border-border pt-1">Total</dt>
                    <dd className="mt-1 border-t border-border pt-1 text-right font-medium tabular-nums text-foreground">{duracao(total(atual))}</dd>
                  </dl>
                ) : (
                  <p className="mt-2 font-sora text-base font-semibold tabular-nums text-foreground">
                    {medida === "linhas" ? `${linhas(atual.linhas ?? 0)} linhas` : tamanho(atual.tamanho_bytes)}
                  </p>
                ))}
              {atual.erro && (
                <p className={`mt-1.5 line-clamp-3 max-w-[240px] ${atual.status === "cancelado" ? "text-muted-foreground" : "text-destructive"}`}>
                  {atual.erro}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* versão em tabela para leitor de tela */}
      <table className="sr-only">
        <caption>Últimas execuções</caption>
        <thead>
          <tr>
            <th>Quando</th>
            <th>Status</th>
            <th>Duração</th>
            <th>Linhas</th>
            <th>Tamanho</th>
          </tr>
        </thead>
        <tbody>
          {execs.map((e) => (
            <tr key={e.id}>
              <td>{dataHora(e.solicitado_em)}</td>
              <td>{ROTULO[e.status]}</td>
              <td>{e.status === "sucesso" ? duracao(total(e)) : "—"}</td>
              <td>{e.linhas != null ? linhas(e.linhas) : "—"}</td>
              <td>{e.tamanho_bytes != null ? tamanho(e.tamanho_bytes) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
