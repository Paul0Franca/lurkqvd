import { useEffect, useState } from "react";
import type { Api } from "../api";
import { DIAS, type Agenda, type ModoAgenda, paraCron } from "../lib/agenda";

const MODOS: { modo: ModoAgenda; rotulo: string }[] = [
  { modo: "manual", rotulo: "Manual" },
  { modo: "horas", rotulo: "A cada X horas" },
  { modo: "diario", rotulo: "Diário" },
  { modo: "uteis", rotulo: "Dias úteis" },
  { modo: "semanal", rotulo: "Semanal" },
  { modo: "cron", rotulo: "Cron" },
];

interface Props {
  api: Api;
  valor: Agenda;
  aoMudar: (a: Agenda) => void;
  /** recebe os próximos horários válidos (ou null se o cron for inválido) */
  aoValidar?: (proximas: string[] | null) => void;
}

const FORMATO = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export default function AgendamentoEditor({ api, valor, aoMudar, aoValidar }: Props) {
  const cron = paraCron(valor);
  const [proximas, setProximas] = useState<string[]>([]);
  const [fuso, setFuso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // pede ao backend os próximos horários: a mesma conta que o worker vai fazer
  useEffect(() => {
    if (!cron) {
      aoValidar?.([]);
      return;
    }
    let cancelado = false;
    const t = setTimeout(() => {
      api
        .previaAgendamento(cron)
        .then((r) => {
          if (cancelado) return;
          setProximas(r.proximas);
          setFuso(r.fuso);
          setErro(null);
          aoValidar?.(r.proximas);
        })
        .catch((e: Error) => {
          if (cancelado) return;
          setProximas([]);
          setErro(e.message);
          aoValidar?.(null);
        });
    }, 350);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
    // aoValidar fica fora: é callback do pai e não deve refazer a consulta
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cron, api]);

  const muda = (parcial: Partial<Agenda>) => aoMudar({ ...valor, ...parcial });

  return (
    <div className="flex flex-col gap-4">
      <div role="radiogroup" aria-label="Frequência" className="segmentos">
        {MODOS.map((m) => (
          <button
            key={m.modo}
            type="button"
            role="radio"
            aria-checked={valor.modo === m.modo}
            className="segmento"
            onClick={() => muda({ modo: m.modo })}
          >
            {m.rotulo}
          </button>
        ))}
      </div>

      {valor.modo === "manual" && (
        <p className="text-sm text-muted-foreground">A carga só roda quando alguém clicar em Executar ou o Airflow chamar a API.</p>
      )}

      {valor.modo === "horas" && (
        <label className="flex items-center gap-3 text-sm">
          A cada
          <input
            type="number"
            min={1}
            max={23}
            value={valor.horas}
            onChange={(e) => muda({ horas: Number(e.target.value) })}
            className="campo w-20 text-center tabular-nums"
          />
          horas, na hora cheia
        </label>
      )}

      {(valor.modo === "diario" || valor.modo === "uteis" || valor.modo === "semanal") && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {valor.modo === "semanal" && (
            <label className="flex items-center gap-3">
              Toda
              <select value={valor.dia} onChange={(e) => muda({ dia: Number(e.target.value) })} className="campo w-auto">
                {DIAS.map((d, i) => (
                  <option key={d} value={i}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex items-center gap-3">
            {valor.modo === "semanal" ? "às" : valor.modo === "uteis" ? "De segunda a sexta, às" : "Todo dia, às"}
            <input type="time" value={valor.hora} onChange={(e) => muda({ hora: e.target.value })} className="campo w-auto tabular-nums" />
          </label>
        </div>
      )}

      {valor.modo === "cron" && (
        <div className="flex flex-col gap-1.5">
          <input
            value={valor.cron}
            onChange={(e) => muda({ cron: e.target.value })}
            placeholder="0 6 * * 1-5"
            className="campo font-mono"
            aria-label="Expressão cron"
            aria-invalid={Boolean(erro)}
            spellCheck={false}
          />
          <span className="text-xs text-muted-foreground">minuto, hora, dia do mês, mês, dia da semana. Fuso: {fuso ?? "o da instalação"}.</span>
        </div>
      )}

      {cron && (
        <div className="proximas" aria-live="polite">
          {erro ? (
            <p className="text-sm text-destructive">{erro}</p>
          ) : proximas.length > 0 ? (
            <>
              <span className="text-xs text-muted-foreground">Próximas execuções</span>
              <ol className="mt-2 flex flex-wrap gap-2">
                {proximas.map((p, i) => (
                  <li key={p} className={`proxima ${i === 0 ? "proxima-primeira" : ""}`}>
                    {FORMATO.format(new Date(p))}
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Calculando…</p>
          )}
        </div>
      )}
    </div>
  );
}
