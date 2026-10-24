// Dispara e acompanha a execução de UMA carga até terminar. Usado na lista e na página da carga.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Api, Execucao, StatusExecucao } from "../api";

const INTERVALO_MS = 2000; // o worker grava o progresso a cada ~2s
const FINAIS: StatusExecucao[] = ["sucesso", "erro", "cancelado"];

interface Opcoes {
  api: Api;
  cargaId: number;
  /** status/ID da execução mais recente vindos da tela (atualizam quando ela recarrega o histórico) */
  statusInicial: StatusExecucao | null;
  execucaoInicial: number | null;
  /** chamado a cada mudança de status (fila → rodando → fim), para a tela recarregar o histórico */
  aoMudar?: (e?: Execucao) => void;
}

export function useExecucao({ api, cargaId, statusInicial, execucaoInicial, aoMudar }: Opcoes) {
  // execução que este hook está acompanhando
  const [acompanhada, setAcompanhada] = useState<{ id: number; status: StatusExecucao; dados?: Execucao } | null>(null);
  const [cancelando, setCancelando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const geracao = useRef(0); // cada acompanhamento novo invalida o anterior
  const idAtual = useRef<number | null>(null);
  const aoMudarRef = useRef(aoMudar);

  useEffect(() => {
    aoMudarRef.current = aoMudar;
  }, [aoMudar]);

  const parar = useCallback(() => {
    geracao.current += 1;
    idAtual.current = null;
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const acompanhar = useCallback(
    (execucaoId: number, statusConhecido: StatusExecucao) => {
      if (idAtual.current === execucaoId) return; // já acompanhando esta
      parar();
      const minha = geracao.current;
      idAtual.current = execucaoId;
      let anterior = statusConhecido;

      const tick = async () => {
        if (geracao.current !== minha) return;
        try {
          const e = await api.execucao(execucaoId);
          if (geracao.current !== minha) return;
          setAcompanhada({ id: execucaoId, status: e.status, dados: e });
          if (e.status !== anterior) {
            anterior = e.status;
            aoMudarRef.current?.(e);
          }
          if (FINAIS.includes(e.status)) {
            idAtual.current = null;
            return;
          }
        } catch {
          /* falha pontual de rede: tenta de novo */
        }
        if (geracao.current === minha) timer.current = setTimeout(tick, INTERVALO_MS);
      };
      tick();
    },
    [api, parar],
  );

  // acompanha qualquer execução em andamento que a tela descobrir
  // (ao abrir, ou uma iniciada pelo agendador/por outra pessoa enquanto a tela está aberta)
  useEffect(() => {
    if (execucaoInicial && (statusInicial === "pendente" || statusInicial === "rodando")) {
      acompanhar(execucaoInicial, statusInicial);
    }
  }, [execucaoInicial, statusInicial, acompanhar]);

  useEffect(() => parar, [parar]);

  const executar = useCallback(async () => {
    setErro(null);
    try {
      const { execucao_id } = await api.executar(cargaId);
      setAcompanhada({ id: execucao_id, status: "pendente" });
      aoMudarRef.current?.();
      acompanhar(execucao_id, "pendente");
    } catch (e) {
      setErro((e as Error).message);
    }
  }, [api, cargaId, acompanhar]);

  // pede o cancelamento da execução acompanhada; o acompanhamento segue até ela virar "cancelado"
  const cancelar = useCallback(async () => {
    const id = idAtual.current ?? acompanhada?.id ?? execucaoInicial;
    if (!id) return;
    setErro(null);
    setCancelando(true);
    try {
      const e = await api.cancelarExecucao(id);
      setAcompanhada({ id, status: e.status, dados: e });
      if (FINAIS.includes(e.status)) aoMudarRef.current?.(e);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setCancelando(false);
    }
  }, [api, acompanhada?.id, execucaoInicial]);

  // vale o que for mais novo: a execução acompanhada ou a que veio da tela
  const atual = acompanhada && (execucaoInicial === null || acompanhada.id >= execucaoInicial) ? acompanhada : null;
  const status = atual ? atual.status : statusInicial;
  const emAndamento = status === "pendente" || status === "rodando";
  /** dados ao vivo da execução em andamento (progresso, cancelamento pedido) */
  const execucao = emAndamento ? (atual?.dados ?? null) : null;
  return { status, emAndamento, executar, erro, execucao, cancelar, cancelando };
}
