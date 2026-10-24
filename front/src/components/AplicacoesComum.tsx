// Peças compartilhadas das aplicações: status, barra da rodada e acompanhamento ao vivo.
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { Api, Aplicacao, CargaNaRodada, ExecucaoAplicacao, StatusAplicacao, StatusExecucao } from "../api";

export const ROTULO_APLICACAO: Record<StatusAplicacao, string> = {
  pendente: "Na fila",
  cargas: "Atualizando cargas",
  recarregando: "Recarregando app",
  sucesso: "Sucesso",
  erro: "Erro",
  cancelado: "Cancelado",
};

const CLASSE_STATUS: Record<StatusAplicacao, string> = {
  pendente: "status-pendente",
  cargas: "status-rodando",
  recarregando: "status-rodando",
  sucesso: "status-sucesso",
  erro: "status-erro",
  cancelado: "status-cancelado",
};

export const ATIVOS: StatusAplicacao[] = ["pendente", "cargas", "recarregando"];

export function StatusAplicacaoBadge({ status }: { status: StatusAplicacao | null }) {
  if (!status) return <span className="status status-nunca">Nunca rodou</span>;
  return (
    <span className={`status ${CLASSE_STATUS[status]} inline-flex items-center gap-1.5`}>
      {(status === "cargas" || status === "recarregando") && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
      {ROTULO_APLICACAO[status]}
    </span>
  );
}

/** 42s, 3min 05s, 1h 12min */
export function tempo(seg: number | null | undefined): string {
  if (seg == null || !Number.isFinite(seg)) return "—";
  const s = Math.max(0, Math.round(seg));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}min ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}min`;
}

export function segundosEntre(ini?: string | null, fim?: string | null): number | null {
  if (!ini) return null;
  const a = new Date(ini).getTime();
  const b = fim ? new Date(fim).getTime() : Date.now();
  return (b - a) / 1000;
}

/** Estado visual de um trecho do fluxo (carga ou reload). */
export type Etapa = "espera" | "andamento" | "feita" | "falha" | "cancelada";

export function etapaDaCarga(s: StatusExecucao | null | undefined): Etapa {
  if (s === "rodando") return "andamento";
  if (s === "sucesso") return "feita";
  if (s === "erro") return "falha";
  if (s === "cancelado") return "cancelada";
  return "espera";
}

export function etapaDoReload(x: Pick<ExecucaoAplicacao, "status" | "reload_status"> | null, temApp: boolean): Etapa {
  if (!x || !temApp) return "espera";
  if (x.status === "recarregando") return "andamento";
  if (x.reload_status === "SUCCEEDED") return "feita";
  if (x.reload_status === "CANCELED" || (x.status === "cancelado" && x.reload_status)) return "cancelada";
  if (x.reload_status && ["FAILED", "EXCEEDED_LIMIT"].includes(x.reload_status)) return "falha";
  return "espera";
}

/** Uma barra fina dividida: um trecho por carga e, no fim, o reload do app (se houver). */
export function BarraRodada({ cargas, reload, rotulo }: { cargas: Etapa[]; reload: Etapa | null; rotulo: string }) {
  const trechos = reload ? [...cargas, reload] : cargas;
  if (!trechos.length) return null;
  return (
    <div className="barra-rodada" role="img" aria-label={rotulo}>
      {trechos.map((e, i) => (
        <span key={i} className={`trecho trecho-${e}${reload && i === trechos.length - 1 ? " trecho-app" : ""}`} />
      ))}
    </div>
  );
}

export function resumoRodada(x: ExecucaoAplicacao | null): string {
  if (!x?.cargas) return "";
  const prontas = x.cargas.filter((c) => c.status === "sucesso").length;
  if (x.status === "pendente") return "Esperando o worker começar";
  if (x.status === "cargas") return `${prontas} de ${x.cargas.length} cargas prontas`;
  if (x.status === "recarregando") return x.reload_status === "QUEUED" ? "App na fila da Qlik" : "Recarregando o app na Qlik";
  return "";
}

/**
 * Acompanha a rodada em andamento de uma aplicação (a cada 2s) até terminar.
 * Devolve a rodada ao vivo, executar() e cancelar().
 */
export function useRodadaAplicacao(api: Api, aplicacao: Aplicacao | null, aoTerminar?: () => void) {
  const [rodada, setRodada] = useState<ExecucaoAplicacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const acompanhando = useRef<number | null>(null);
  const aoTerminarRef = useRef(aoTerminar);
  useEffect(() => {
    aoTerminarRef.current = aoTerminar;
  }, [aoTerminar]);

  const acompanhar = useCallback(
    (id: number) => {
      acompanhando.current = id;
      let timer: ReturnType<typeof setTimeout>;
      const tick = async () => {
        if (acompanhando.current !== id) return;
        try {
          const x = await api.execucaoAplicacao(id);
          if (acompanhando.current !== id) return;
          setRodada(x);
          if (x.terminou) {
            acompanhando.current = null;
            aoTerminarRef.current?.();
            return;
          }
        } catch {
          /* falha de rede pontual: tenta de novo */
        }
        timer = setTimeout(tick, 2000);
      };
      tick();
      return () => clearTimeout(timer);
    },
    [api],
  );

  // a tela descobriu uma rodada ativa (aberta agora, ou disparada pelo agendador/outra pessoa)
  const ativaId = aplicacao && aplicacao.ultimo_status && ATIVOS.includes(aplicacao.ultimo_status) ? aplicacao.ultima_execucao_id : null;
  useEffect(() => {
    if (ativaId && acompanhando.current !== ativaId) return acompanhar(ativaId);
  }, [ativaId, acompanhar]);
  useEffect(() => () => {
    acompanhando.current = null;
  }, []);

  const executar = useCallback(async () => {
    if (!aplicacao) return;
    setErro(null);
    setOcupado(true);
    try {
      const { execucao_aplicacao_id } = await api.executarAplicacao(aplicacao.id);
      acompanhar(execucao_aplicacao_id);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(false);
    }
  }, [api, aplicacao, acompanhar]);

  const cancelar = useCallback(async () => {
    if (!rodada) return;
    setOcupado(true);
    try {
      setRodada(await api.cancelarExecucaoAplicacao(rodada.id));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(false);
    }
  }, [api, rodada]);

  const emAndamento = Boolean(rodada && !rodada.terminou) || Boolean(ativaId && !rodada);
  return { rodada, emAndamento, executar, cancelar, ocupado, erro };
}

export function etapasDaRodada(x: ExecucaoAplicacao | null, aplicacao: Aplicacao): { cargas: Etapa[]; reload: Etapa | null } {
  const temApp = Boolean(aplicacao.qlik_app_id);
  if (x?.cargas?.length && !x.terminou) {
    return { cargas: x.cargas.map((c: CargaNaRodada) => etapaDaCarga(c.status)), reload: temApp ? etapaDoReload(x, temApp) : null };
  }
  if (x && !x.terminou) {
    // recém-criada: o worker ainda não ligou as cargas à rodada
    return { cargas: aplicacao.cargas.map((): Etapa => "espera"), reload: temApp ? etapaDoReload(x, temApp) : null };
  }
  return {
    cargas: aplicacao.cargas.map((c) => etapaDaCarga(c.ultimo_status)),
    reload: temApp ? (aplicacao.ultimo_reload_status === "SUCCEEDED" ? "feita" : aplicacao.ultimo_reload_status ? "falha" : "espera") : null,
  };
}
