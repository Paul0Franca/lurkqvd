import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, KeyRound, Pause, ServerOff } from "lucide-react";
import type { Api, CargaResumo, ExecucaoRecente, ExecucoesDia, Resumo, StatusSistema, Usuario } from "../api";
import { relativo } from "../lib/formato";
import { DIAS_AVISO_PAINEL, diasAte, textoDias } from "../lib/vencimento";
import { link } from "../rotas";
import Atividade from "./Atividade";
import GraficoDiario from "./GraficoDiario";
import PainelHero from "./PainelHero";
import { StatusBadge } from "./comum";
import { SubLogoQVD } from "./Logo";

interface Props {
  api: Api;
  usuario: Usuario;
  /** abre as configurações (só admin) */
  aoAbrirConfig?: () => void;
}

const ATUALIZAR_MS = 15000;

export default function Painel({ api, usuario, aoAbrirConfig }: Props) {
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [recentes, setRecentes] = useState<ExecucaoRecente[] | null>(null);
  const [cargas, setCargas] = useState<CargaResumo[] | null>(null);
  const [diario, setDiario] = useState<ExecucoesDia[] | null>(null);
  const [sistema, setSistema] = useState<StatusSistema | null>(null);

  const atualizar = useCallback(() => {
    api.resumo().then(setResumo).catch(() => {});
    api.recentes().then(setRecentes).catch(() => {});
    api.listarCargas().then(setCargas).catch(() => {});
    api.resumoDiario().then(setDiario).catch(() => {});
    api.statusSistema().then(setSistema).catch(() => {});
  }, [api]);

  // o painel é de acompanhamento: se atualiza sozinho enquanto a aba está aberta
  useEffect(() => {
    atualizar();
    const t = setInterval(() => document.visibilityState === "visible" && atualizar(), ATUALIZAR_MS);
    return () => clearInterval(t);
  }, [atualizar]);

  const atencao = (cargas ?? []).filter((c) => c.ultimo_status === "erro" || c.ultimo_status === "rodando" || c.ultimo_status === "pendente");
  const primeiroNome = (usuario.nome ?? usuario.email).split(/[ @]/)[0];

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <PainelHero nome={primeiroNome} resumo={resumo} sistema={sistema} cargas={cargas} diario={diario} />

      {sistema && <AvisosSistema st={sistema} aoAbrirConfig={aoAbrirConfig} />}

      <GraficoDiario dias={diario} />

      <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_380px]">
        {/* ---------- precisa de atenção ---------- */}
        <section aria-labelledby="titulo-atencao" className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="titulo-atencao" className="font-sora text-sm font-semibold">
              Precisa de atenção
            </h2>
            <a href={link({ tela: "cargas" })} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              Ver todas as cargas
              <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
          </div>

          {!cargas ? (
            <p className="vazio">Carregando…</p>
          ) : atencao.length === 0 ? (
            <div className="tudo-em-dia flex items-center gap-5 rounded-2xl border border-border bg-card px-6 py-8">
              <SubLogoQVD tamanho={56} corForma="currentColor" corOlhos="var(--lq-surface)" pisca className="shrink-0 text-foreground" />
              <div>
                <p className="font-sora font-semibold">Nada pede atenção agora.</p>
                <p className="mt-1 text-sm text-muted-foreground">Cargas com erro ou em execução aparecem aqui.</p>
              </div>
            </div>
          ) : (
            <ul className="lista-repo overflow-hidden rounded-2xl border border-border bg-card">
              {atencao.map((c) => (
                <li key={c.id}>
                  <a href={link({ tela: "carga", id: c.id })} className="linha-repo">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-[13px] font-semibold">{c.nome}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {c.espaco_nome ?? "Pessoal"}, {c.qlik_path}
                      </span>
                    </span>
                    {c.ultima_finalizacao && <span className="hidden text-sm text-muted-foreground sm:block">{relativo(c.ultima_finalizacao)}</span>}
                    <StatusBadge status={c.ultimo_status} />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>

        <Atividade execucoes={recentes} />
      </div>
    </div>
  );
}

/** Faixas de aviso no topo do painel: worker parado e agenda pausada. */
function AvisosSistema({ st, aoAbrirConfig }: { st: StatusSistema; aoAbrirConfig?: () => void }) {
  const parado = st.workers_ativos === 0 && (st.fila.pendentes > 0 || st.fila.agendadas > 0);
  const dias = st.qlik?.expira_em ? diasAte(st.qlik.expira_em) : null;
  const keyVencendo = dias !== null && dias <= DIAS_AVISO_PAINEL;
  const keyRecusada = st.qlik?.ok === false;
  if (!parado && !st.agenda.pausada && !keyVencendo && !keyRecusada) return null;
  const detalhes = aoAbrirConfig && (
    <button type="button" className="aviso-acao" onClick={aoAbrirConfig}>
      Ver detalhes
    </button>
  );
  return (
    <div className="mt-6 flex flex-col gap-3">
      {parado && (
        <div className="aviso aviso-erro" role="alert">
          <ServerOff className="h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="min-w-0 flex-1">
            <strong>O worker não está rodando.</strong>{" "}
            {st.fila.pendentes > 0
              ? `${st.fila.pendentes === 1 ? "1 execução está" : `${st.fila.pendentes} execuções estão`} esperando na fila.`
              : "Os agendamentos não vão rodar até ele voltar."}
            {st.ultimo_sinal && ` Último sinal ${relativo(st.ultimo_sinal)}.`}
          </p>
          {detalhes}
        </div>
      )}
      {(keyRecusada || keyVencendo) && (
        <div className={`aviso ${keyRecusada || (dias !== null && dias <= 7) ? "aviso-erro" : "aviso-pausa"}`} role="alert">
          <KeyRound className="h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="min-w-0 flex-1">
            {keyRecusada ? (
              <>
                <strong>A Qlik recusou a API key.</strong> Nenhuma carga consegue publicar até ela ser substituída.
              </>
            ) : (
              <>
                <strong>A API key da Qlik {textoDias(dias!)}.</strong> Quando vencer, as cargas param de publicar. Gere uma nova na Qlik Cloud e substitua nas configurações.
              </>
            )}
          </p>
          {detalhes}
        </div>
      )}
      {st.agenda.pausada && (
        <div className="aviso aviso-pausa" role="status">
          <Pause className="h-4 w-4 shrink-0" aria-hidden="true" />
          <p className="min-w-0 flex-1">
            <strong>Agendamentos pausados</strong>
            {st.agenda.por_nome && ` por ${st.agenda.por_nome.split(" ")[0]}`}
            {st.agenda.desde && ` ${relativo(st.agenda.desde)}`}.{st.agenda.motivo && ` Motivo: ${st.agenda.motivo}.`} Execuções manuais continuam funcionando.
          </p>
          {detalhes}
        </div>
      )}
    </div>
  );
}
