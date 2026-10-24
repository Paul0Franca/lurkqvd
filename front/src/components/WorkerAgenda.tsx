// Configurações > Worker e agenda: o worker está vivo? a fila está andando? e o botão de pausa geral.

import { useCallback, useEffect, useState } from "react";
import { Pause, Play, X } from "lucide-react";
import type { Api, StatusSistema, WorkerStatus } from "../api";
import { dataHora, relativo } from "../lib/formato";
import { Comando } from "./comum";

const ATUALIZAR_MS = 5000;
const COMANDO = "python -m src.lurkqvd.worker";

const ESTADO: Record<WorkerStatus["estado"], string> = { ativo: "ativo", sem_sinal: "sem sinal", encerrado: "encerrado" };

export default function WorkerAgenda({ api }: { api: Api }) {
  const [st, setSt] = useState<StatusSistema | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api
      .statusSistema()
      .then((s) => {
        setSt(s);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(() => {
    carregar();
    const t = setInterval(carregar, ATUALIZAR_MS);
    return () => clearInterval(t);
  }, [carregar]);

  if (!st) return <p className="vazio">{erro ?? "Carregando…"}</p>;

  const ativo = st.workers.find((w) => w.estado === "ativo");
  const vivo = st.workers_ativos > 0;

  return (
    <div className="flex flex-col gap-8">
      {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}

      {/* ---------- o worker está vivo? ---------- */}
      <section className={`cartao-worker ${vivo ? "" : "cartao-worker-parado"}`} aria-live="polite">
        <div className="flex items-start gap-4">
          <span className={`pulso ${vivo ? "pulso-ok" : "pulso-parado"}`} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h3 className="font-sora text-base font-semibold">{vivo ? "Worker rodando" : "Nenhum worker rodando"}</h3>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {vivo
                ? ativo?.carga_nome
                  ? <>Executando <span className="font-mono text-foreground">{ativo.carga_nome}</span> agora</>
                  : "Esperando a próxima carga da fila"
                : st.ultimo_sinal
                  ? `Último sinal ${relativo(st.ultimo_sinal)}. Cargas manuais e agendadas ficam “Na fila” até ele voltar.`
                  : "Ele nunca rodou com esta versão. Cargas manuais e agendadas ficam “Na fila” até ele subir."}
            </p>
          </div>
        </div>

        {!vivo && (
          <div className="mt-4">
            <p className="mb-1.5 text-xs text-muted-foreground">Na raiz do projeto, rode:</p>
            <Comando texto={COMANDO} />
          </div>
        )}

        {st.workers.length > 0 && (
          <ul className="mt-5 divide-y divide-border border-t border-border">
            {st.workers.map((w) => (
              <li key={w.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-xs">
                <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground" title={w.id}>
                  {w.host}
                  <span className="text-muted-foreground">:{w.pid}</span>
                </span>
                <span className={`estado-worker estado-${w.estado}`}>{ESTADO[w.estado]}</span>
                <span className="w-40 text-muted-foreground" title={dataHora(w.iniciado_em)}>
                  iniciado {relativo(w.iniciado_em)}
                </span>
                <span className="w-36 text-muted-foreground" title={dataHora(w.encerrado_em ?? w.ultimo_sinal)}>
                  {w.encerrado_em ? `parou ${relativo(w.encerrado_em)}` : `sinal ${relativo(w.ultimo_sinal)}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ---------- fila ---------- */}
      <section aria-labelledby="titulo-fila">
        <h3 id="titulo-fila" className="mb-3 text-sm font-semibold">
          Fila
        </h3>
        <dl className="grid grid-cols-3 overflow-hidden rounded-2xl border border-border">
          <Numero rotulo="Na fila" valor={st.fila.pendentes} alerta={st.fila.pendentes > 0 && !vivo} />
          <Numero rotulo="Rodando" valor={st.fila.rodando} />
          <Numero rotulo="Cargas agendadas" valor={st.fila.agendadas} />
        </dl>
        {st.fila.pendente_desde && (
          <p className="mt-2 text-xs text-muted-foreground">A mais antiga entrou na fila {relativo(st.fila.pendente_desde)}.</p>
        )}
      </section>

      {/* ---------- pausa geral ---------- */}
      <PausaAgenda api={api} st={st} aoMudar={setSt} />

      {/* ---------- execução travada ---------- */}
      <LimiteTravada key={st.limite_travada_min} api={api} atual={st.limite_travada_min} aoMudar={setSt} />

      <section className="flex items-center justify-between gap-4 border-t border-border pt-6 text-sm">
        <div>
          <h3 className="font-semibold">Fuso dos agendamentos</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Horários como “todo dia às 06:00” valem neste fuso.</p>
        </div>
        <span className="font-mono text-[13px]">{st.fuso_padrao}</span>
      </section>
    </div>
  );
}

function Numero({ rotulo, valor, alerta }: { rotulo: string; valor: number; alerta?: boolean }) {
  return (
    <div className="metrica border-border p-4">
      <dt className="text-xs text-muted-foreground">{rotulo}</dt>
      <dd className={`mt-1 font-sora text-[22px] font-semibold tabular-nums ${alerta ? "text-destructive" : ""}`}>{valor}</dd>
    </div>
  );
}

function PausaAgenda({ api, st, aoMudar }: { api: Api; st: StatusSistema; aoMudar: (s: StatusSistema) => void }) {
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const { agenda } = st;

  async function salvar(pausada: boolean) {
    setSalvando(true);
    setErro(null);
    try {
      aoMudar(await api.alterarAgenda(pausada, motivo));
      setConfirmando(false);
      setMotivo("");
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section aria-labelledby="titulo-pausa" className={`cartao-pausa ${agenda.pausada ? "cartao-pausa-ativa" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 id="titulo-pausa" className="flex items-center gap-2 text-sm font-semibold">
            {agenda.pausada ? <Pause className="h-4 w-4" aria-hidden="true" /> : <Play className="h-4 w-4 text-primary" aria-hidden="true" />}
            {agenda.pausada ? "Agendamentos pausados" : "Agendamentos ativos"}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {agenda.pausada ? (
              <>
                Desde {agenda.desde ? dataHora(agenda.desde) : "—"}
                {agenda.por_nome && `, por ${agenda.por_nome.split(" ")[0]}`}.{agenda.motivo && <> Motivo: “{agenda.motivo}”.</>} Execuções manuais continuam funcionando.
              </>
            ) : (
              "Pause tudo de uma vez numa manutenção do banco de origem ou da Qlik. Quem clicar em Executar ainda consegue rodar."
            )}
          </p>
        </div>
        {agenda.pausada ? (
          <button type="button" className="btn-primario inline-flex items-center gap-2" disabled={salvando} onClick={() => salvar(false)}>
            <Play className="h-4 w-4" aria-hidden="true" />
            {salvando ? "Retomando…" : "Retomar agendamentos"}
          </button>
        ) : (
          !confirmando && (
            <button type="button" className="btn-secundario inline-flex items-center gap-2" onClick={() => setConfirmando(true)}>
              <Pause className="h-4 w-4" aria-hidden="true" />
              Pausar todos
            </button>
          )
        )}
      </div>

      {agenda.pausada && (
        <p className="mt-3 text-xs text-muted-foreground">Ao retomar, os horários perdidos durante a pausa não rodam: cada carga volta no próximo horário dela.</p>
      )}

      {!agenda.pausada && confirmando && (
        <form
          className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            salvar(true);
          }}
        >
          <label htmlFor="motivo-pausa" className="sr-only">
            Motivo
          </label>
          <input
            id="motivo-pausa"
            className="campo campo-pequeno min-w-[220px] flex-1"
            placeholder="Motivo (opcional), ex.: manutenção do banco de origem"
            maxLength={200}
            value={motivo}
            autoFocus
            onChange={(e) => setMotivo(e.target.value)}
          />
          <button type="button" className="btn-secundario" onClick={() => setConfirmando(false)}>
            Cancelar
          </button>
          <button type="submit" className="btn-perigo inline-flex items-center gap-2" disabled={salvando}>
            <Pause className="h-4 w-4" aria-hidden="true" />
            {salvando ? "Pausando…" : "Pausar agendamentos"}
          </button>
        </form>
      )}
      {erro && (
        <p className="mt-2 flex items-center gap-2 text-sm text-destructive">
          <X className="h-4 w-4" />
          {erro}
        </p>
      )}
    </section>
  );
}

function LimiteTravada({ api, atual, aoMudar }: { api: Api; atual: number; aoMudar: (s: StatusSistema) => void }) {
  const [valor, setValor] = useState(String(atual));
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const n = Number(valor);
  const valido = Number.isInteger(n) && n >= 10 && n <= 720;

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setErro(null);
    try {
      aoMudar(await api.alterarLimiteTravada(n));
    } catch (err) {
      setErro((err as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section aria-labelledby="titulo-travada" className="border-t border-border pt-6">
      <form onSubmit={salvar} className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 id="titulo-travada" className="text-sm font-semibold">
            Execução travada
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Se o worker cair no meio de uma carga, ela fica “Rodando” para sempre. Ao subir, o worker marca como erro as que passaram deste tempo. Deixe acima da carga mais demorada.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="limite-travada" className="sr-only">
            Minutos
          </label>
          <input
            id="limite-travada"
            type="number"
            min={10}
            max={720}
            className="campo campo-pequeno w-[84px] text-right tabular-nums"
            aria-invalid={!valido || undefined}
            value={valor}
            onChange={(e) => setValor(e.target.value)}
          />
          <span className="text-sm text-muted-foreground">min</span>
          <button type="submit" className="btn-secundario" disabled={!valido || n === atual || salvando}>
            {salvando ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </form>
      {!valido && <p className="mt-2 text-xs text-destructive">Entre 10 e 720 minutos.</p>}
      {erro && <p className="mt-2 text-sm text-destructive">{erro}</p>}
    </section>
  );
}
