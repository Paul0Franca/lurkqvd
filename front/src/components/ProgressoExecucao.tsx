// Painel ao vivo da execução em andamento: fase, linhas lidas, velocidade, previsão e botão Cancelar.
import { useEffect, useState } from "react";
import { Ban, Check, Loader2, TriangleAlert } from "lucide-react";
import type { Execucao, StatusExecucao } from "../api";
import { tamanho } from "../lib/formato";

const FASES = [
  { chave: "preparando", rotulo: "Preparando" },
  { chave: "lendo", rotulo: "Lendo do banco" },
  { chave: "gerando", rotulo: "Gerando QVD" },
  { chave: "enviando", rotulo: "Enviando à Qlik" },
] as const;

/** Sem atualização há mais que isso numa fase que avisa sozinha = provavelmente parado no banco/rede. */
const SEM_AVANCO_SEG = 90;

const num = (n: number) => Math.round(n).toLocaleString("pt-BR");

/** "2026-10-20 15:07:40" (hora do worker) -> "20/10 15:07" */
function dataHoraCurta(texto: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(texto);
  return m ? `${m[3]}/${m[2]} ${m[4]}:${m[5]}` : texto;
}

/** 0s, 42s, 3min 05s, 1h 12min */
function tempo(seg: number): string {
  const s = Math.max(0, Math.round(seg));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}min ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}min`;
}

function segDesde(iso: string | undefined, agora: number): number | null {
  return iso ? Math.max(0, (agora - new Date(iso).getTime()) / 1000) : null;
}

export default function ProgressoExecucao({
  status,
  execucao,
  podeCancelar,
  cancelando,
  aoCancelar,
}: {
  status: StatusExecucao | null;
  execucao: Execucao | null;
  podeCancelar: boolean;
  cancelando: boolean;
  aoCancelar: () => void;
}) {
  const [agora, setAgora] = useState(() => Date.now());
  const [confirmando, setConfirmando] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setAgora(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // o "Confirmar cancelamento" volta a ser "Cancelar" se a pessoa não confirmar em alguns segundos
  useEffect(() => {
    if (!confirmando) return;
    const t = setTimeout(() => setConfirmando(false), 4000);
    return () => clearTimeout(t);
  }, [confirmando]);

  const p = execucao?.progresso ?? null;
  const pedidoCancelar = Boolean(execucao?.cancelar_em);
  const fase = status === "pendente" ? null : (p?.fase ?? "preparando");
  const iFase = FASES.findIndex((f) => f.chave === fase);
  const naFase = segDesde(p?.fase_desde, agora);
  const total = segDesde(execucao?.iniciado_em ?? undefined, agora);
  const parado = segDesde(p?.atualizado_em, agora);
  const semAvanco = (fase === "lendo" || fase === "enviando") && parado !== null && parado > SEM_AVANCO_SEG;

  // barra: linhas lidas sobre as previstas (lendo) ou bytes enviados sobre o total (enviando)
  const reenvio = fase === "enviando" && p?.reaproveitado;
  let fracao: number | null = null;
  let detalhe: React.ReactNode = null;
  let previsao: string | null = null;
  if (fase === "lendo") {
    const lidas = p?.linhas ?? 0;
    const previstas = p?.linhas_previstas;
    const ritmo = p?.linhas_por_seg;
    if (previstas && previstas > 0) fracao = Math.min(lidas / previstas, 0.99);
    if (previstas && ritmo && previstas > lidas) previsao = `termina de ler em ~${tempo((previstas - lidas) / ritmo)}`;
    detalhe = (
      <>
        <strong className="font-semibold text-foreground">{num(lidas)}</strong>
        {previstas ? ` de ~${num(previstas)}` : ""} linhas
        {ritmo ? ` · ${num(ritmo)}/s` : ""}
        {p?.mb_por_seg != null && (
          <>
            {" · "}
            <strong className="font-semibold text-foreground">{p.mb_por_seg.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB/s</strong>
          </>
        )}
        {p?.bytes_lidos ? ` · ${tamanho(p.bytes_lidos)} lidos` : ""}
      </>
    );
  } else if (fase === "enviando" && p?.bytes_total) {
    const enviados = p.bytes_enviados ?? 0;
    fracao = Math.min(enviados / p.bytes_total, 1);
    detalhe = (
      <>
        <strong className="font-semibold text-foreground">{tamanho(enviados)}</strong> de {tamanho(p.bytes_total)}
        {reenvio && p.gerado_em && <> · sem reler o banco: o QVD foi gerado em {dataHoraCurta(p.gerado_em)} e o envio anterior falhou</>}
      </>
    );
  } else if (fase === "gerando" && p?.linhas) {
    if (p.montagem_pct != null) fracao = Math.min(p.montagem_pct / 100, 0.99);
    detalhe = <>{num(p.linhas)} linhas lidas · montando o arquivo</>;
  }

  const titulo =
    status === "pendente"
      ? "Na fila, aguardando o worker"
      : reenvio
        ? "Reenviando QVD guardado"
        : (FASES[iFase]?.rotulo ?? "Rodando");

  return (
    <section className="progresso-exec mt-6" aria-live="polite" aria-label="Execução em andamento">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold">
            {pedidoCancelar ? (
              <Ban className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            ) : (
              <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
            )}
            {pedidoCancelar ? "Cancelando…" : titulo}
            {!pedidoCancelar && naFase !== null && fase && (
              <span className="font-normal text-muted-foreground">· há {tempo(naFase)}</span>
            )}
          </p>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {pedidoCancelar
              ? "O worker para no próximo lote lido ou pedaço enviado. O QVD na Qlik continua como estava."
              : (detalhe ?? (status === "pendente" ? "Começa assim que o worker pegar a fila." : " "))}
          </p>
        </div>
        {podeCancelar && !pedidoCancelar && (
          <button
            type="button"
            className={confirmando ? "btn-perigo inline-flex items-center gap-1.5" : "btn-secundario inline-flex items-center gap-1.5"}
            disabled={cancelando}
            onClick={() => (confirmando ? (setConfirmando(false), aoCancelar()) : setConfirmando(true))}
          >
            {cancelando ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Ban className="h-3.5 w-3.5" aria-hidden="true" />}
            {confirmando ? "Confirmar cancelamento" : "Cancelar"}
          </button>
        )}
      </div>

      {fase && !pedidoCancelar && (
        <>
          <div
            className="progresso-barra mt-3"
            role="progressbar"
            aria-label={titulo}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={fracao !== null ? Math.round(fracao * 100) : undefined}
          >
            <span
              className={fracao === null ? "progresso-indeterminado" : ""}
              style={fracao !== null ? { width: `${Math.max(fracao * 100, 1.5)}%` } : undefined}
            />
          </div>
          <div className="mt-1.5 flex flex-wrap justify-between gap-x-4 text-[11.5px] text-muted-foreground">
            <span>
              {fracao !== null ? `${Math.round(fracao * 100)}%` : ""}
              {previsao ? `${fracao !== null ? " · " : ""}${previsao}` : ""}
            </span>
            {total !== null && <span>rodando há {tempo(total)}</span>}
          </div>
        </>
      )}

      {semAvanco && !pedidoCancelar && (
        <p className="alerta alerta-aviso mt-3 flex items-start gap-2 text-[13px]">
          <TriangleAlert className="mt-0.5 h-4 w-4 flex-none" aria-hidden="true" />
          <span>
            Sem avanço há {tempo(parado!)}. O banco de origem pode estar ocupado ou com a consulta bloqueada
            {fase === "enviando" ? ", ou a conexão com a Qlik caiu" : ""}. Se não voltar, dá para cancelar.
          </span>
        </p>
      )}

      {fase && (
        <ol className="progresso-fases mt-4" aria-label="Etapas">
          {FASES.map((f, i) => {
            const estado = i < iFase ? "feita" : i === iFase ? "atual" : "proxima";
            return (
              <li key={f.chave} className={`fase-${estado}`}>
                <span className="progresso-ponto" aria-hidden="true">
                  {estado === "feita" && <Check className="h-2.5 w-2.5" strokeWidth={3.5} />}
                </span>
                {f.rotulo}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
