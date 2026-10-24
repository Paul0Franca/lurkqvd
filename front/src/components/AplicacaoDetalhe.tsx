// Página da aplicação: o fluxo cargas → app da Qlik ao vivo, a última rodada e o histórico.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { AppWindow, Ban, CalendarClock, Pencil, Play, Trash2 } from "lucide-react";
import type { Api, Aplicacao, CargaNaRodada, CargaResumo, ExecucaoAplicacao, Usuario } from "../api";
import { descrever } from "../lib/agenda";
import { dataHora, relativo, tamanho } from "../lib/formato";
import { link, navegar } from "../rotas";
import AplicacaoForm from "./AplicacaoForm";
import {
  etapaDaCarga,
  etapaDoReload,
  segundosEntre,
  StatusAplicacaoBadge,
  tempo,
  useRodadaAplicacao,
  type Etapa,
} from "./AplicacoesComum";
import { Migalhas } from "./comum";

interface Props {
  api: Api;
  usuario: Usuario;
  id: number;
}

export default function AplicacaoDetalhe({ api, usuario, id }: Props) {
  const [aplicacao, setAplicacao] = useState<Aplicacao | null>(null);
  const [historico, setHistorico] = useState<ExecucaoAplicacao[]>([]);
  const [cargas, setCargas] = useState<CargaResumo[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api.aplicacao(id).then(setAplicacao).catch((e: Error) => setErro(e.message));
    api.historicoAplicacao(id).then(setHistorico).catch(() => {});
  }, [api, id]);

  useEffect(() => {
    carregar();
    api.listarCargas().then(setCargas).catch(() => {});
    const t = setInterval(carregar, 20_000);
    return () => clearInterval(t);
  }, [api, carregar]);

  if (erro) {
    return (
      <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
        <p className="alerta alerta-erro">{erro}</p>
        <a href={link({ tela: "cargas" })} className="text-sm text-primary hover:underline">
          Voltar para as aplicações
        </a>
      </div>
    );
  }
  if (!aplicacao) return <p className="vazio mx-auto max-w-[1100px] px-6 py-8">Carregando…</p>;
  return <Conteudo api={api} usuario={usuario} aplicacao={aplicacao} historico={historico} cargas={cargas} aoMudar={carregar} aoAlterar={setAplicacao} />;
}

function Conteudo({
  api,
  usuario,
  aplicacao: a,
  historico,
  cargas,
  aoMudar,
  aoAlterar,
}: {
  api: Api;
  usuario: Usuario;
  aplicacao: Aplicacao;
  historico: ExecucaoAplicacao[];
  cargas: CargaResumo[];
  aoMudar: () => void;
  aoAlterar: (a: Aplicacao) => void;
}) {
  const { rodada, emAndamento, executar, cancelar, ocupado, erro } = useRodadaAplicacao(api, a, aoMudar);
  const [editando, setEditando] = useState(false);
  const [confirmarRemocao, setConfirmarRemocao] = useState(false);
  const [erroRemocao, setErroRemocao] = useState<string | null>(null);
  const admin = usuario.papel === "admin";
  const podeExecutar = admin || usuario.papel === "editor";
  const ultimaTerminada = historico.find((h) => h.terminou) ?? null;

  useEffect(() => {
    if (!confirmarRemocao) return;
    const t = setTimeout(() => setConfirmarRemocao(false), 4000);
    return () => clearTimeout(t);
  }, [confirmarRemocao]);

  async function remover() {
    try {
      await api.removerAplicacao(a.id);
      navegar({ tela: "cargas" });
    } catch (e) {
      setErroRemocao((e as Error).message);
      setConfirmarRemocao(false);
    }
  }

  // o que o fluxo mostra: a rodada ao vivo ou, sem rodada, o último estado de cada carga.
  // Rodada recém-criada (pendente) ainda não tem cargas: o worker as liga ao pegá-la, segundos depois.
  const aoVivo = rodada && (!rodada.terminou || rodada.id === a.ultima_execucao_id);
  const nos: NoCarga[] =
    aoVivo && rodada.cargas?.length
      ? rodada.cargas.map((c) => ({ id: c.carga_id, nome: c.nome, etapa: etapaDaCarga(c.status), rodada: c }))
      : aoVivo && !rodada.terminou
        ? a.cargas.map((c) => ({ id: c.id, nome: c.nome, etapa: "espera", resumo: c.ativo ? "Aguardando o worker" : "Inativa: fica de fora", inativa: !c.ativo }))
        : a.cargas.map((c) => ({
          id: c.id,
          nome: c.nome,
          etapa: etapaDaCarga(c.ultimo_status),
          resumo: c.ultimo_status === "sucesso" ? [tamanho(c.ultimo_tamanho_bytes), tempo(c.ultima_duracao)].join(" · ") : c.ultimo_status === "erro" ? "Erro na última execução" : c.ultimo_status ? undefined : "Nunca rodou",
          inativa: !c.ativo,
        }));

  const xReload = rodada ?? (a.ultima_execucao_id ? { status: a.ultimo_status!, reload_status: a.ultimo_reload_status } : null);

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <Migalhas itens={[{ rotulo: "Aplicações", href: link({ tela: "cargas" }) }, { rotulo: a.nome }]} />

      <header className="mt-5 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="truncate font-sora text-[26px] font-semibold tracking-[-0.02em]">{a.nome}</h1>
            <StatusAplicacaoBadge status={rodada && !rodada.terminou ? rodada.status : (rodada?.status ?? a.ultimo_status)} />
            {!a.ativo && <span className="tag">inativa</span>}
          </div>
          {a.descricao && <p className="mt-1.5 max-w-[68ch] text-sm text-muted-foreground">{a.descricao}</p>}
          <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>
              {a.cargas.length} {a.cargas.length === 1 ? "carga" : "cargas"}
              {a.qlik_app_id ? (
                <>
                  {" "}
                  alimentando <span className="text-foreground">{a.qlik_app_nome}</span>
                </>
              ) : (
                ", sem app da Qlik vinculado"
              )}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
              {a.agendamento ? descrever(a.agendamento) : "Só manual ou pela API"}
            </span>
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-2">
            {admin && (
              <>
                <button type="button" className="btn-secundario inline-flex items-center gap-1.5" onClick={() => setEditando(true)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Editar
                </button>
                <button
                  type="button"
                  className={confirmarRemocao ? "btn-perigo inline-flex items-center gap-1.5" : "icone-btn"}
                  onClick={() => (confirmarRemocao ? remover() : setConfirmarRemocao(true))}
                  aria-label="Remover aplicação"
                  title="Remover aplicação (as cargas continuam existindo)"
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  {confirmarRemocao && "Confirmar remoção"}
                </button>
              </>
            )}
            {podeExecutar &&
              (emAndamento ? (
                <button type="button" className="btn-secundario inline-flex items-center gap-2" onClick={cancelar} disabled={ocupado || !rodada}>
                  <Ban className="h-4 w-4" aria-hidden="true" /> Cancelar
                </button>
              ) : (
                <button type="button" className="btn-primario inline-flex items-center gap-2" onClick={executar} disabled={ocupado || !a.ativo || (!a.cargas.length && !a.qlik_app_id)}>
                  <Play className="h-4 w-4" fill="currentColor" aria-hidden="true" /> Executar tudo
                </button>
              ))}
          </div>
          {(erro || erroRemocao) && <span className="text-xs text-destructive">{erro ?? erroRemocao}</span>}
        </div>
      </header>

      <Fluxo
        nos={nos}
        app={{
          nome: a.qlik_app_nome,
          temApp: Boolean(a.qlik_app_id),
          etapa: etapaDoReload(xReload as ExecucaoAplicacao | null, Boolean(a.qlik_app_id)),
          rodada: rodada ?? null,
          ultima: ultimaTerminada,
        }}
        cancelando={Boolean(rodada?.cancelar_em && !rodada.terminou)}
      />

      {rodada?.terminou && rodada.erro && rodada.status !== "sucesso" && (
        <p className={`alerta mt-4 whitespace-pre-line ${rodada.status === "erro" ? "alerta-erro" : "alerta-aviso"}`}>{rodada.erro}</p>
      )}

      <section className="mt-10" aria-labelledby="titulo-historico-app">
        <h2 id="titulo-historico-app" className="font-sora text-sm font-semibold">
          Execuções
        </h2>
        {!historico.length ? (
          <p className="vazio mt-2">Ainda não rodou. “Executar tudo” atualiza as cargas e recarrega o app.</p>
        ) : (
          <ul className="mt-3 overflow-hidden rounded-2xl border border-border bg-card">
            {historico.map((h) => (
              <LinhaHistorico key={h.id} h={h} temApp={Boolean(a.qlik_app_id)} />
            ))}
          </ul>
        )}
      </section>

      {editando && (
        <AplicacaoForm
          api={api}
          aplicacao={a}
          cargas={cargas}
          aoFechar={() => setEditando(false)}
          aoSalvar={(nova) => {
            setEditando(false);
            aoAlterar(nova);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- //
// Fluxo: cargas à esquerda convergindo para o app da Qlik à direita
// ---------------------------------------------------------------------- //
interface NoCarga {
  id: number;
  nome: string;
  etapa: Etapa;
  rodada?: CargaNaRodada;
  resumo?: string;
  inativa?: boolean;
}

interface NoApp {
  nome: string | null;
  temApp: boolean;
  etapa: Etapa;
  rodada: ExecucaoAplicacao | null;
  ultima: ExecucaoAplicacao | null;
}

function Fluxo({ nos, app, cancelando }: { nos: NoCarga[]; app: NoApp; cancelando: boolean }) {
  const area = useRef<HTMLDivElement>(null);
  const alvo = useRef<HTMLDivElement>(null);
  const origens = useRef<(HTMLLIElement | null)[]>([]);
  const [linhas, setLinhas] = useState<{ d: string; etapa: Etapa }[]>([]);
  const [caixa, setCaixa] = useState({ w: 0, h: 0 });

  const desenhar = useCallback(() => {
    const base = area.current?.getBoundingClientRect();
    const destino = alvo.current?.getBoundingClientRect();
    if (!base || !destino) return;
    const n = nos.length;
    const ex = destino.left - base.left;
    const cy = destino.top - base.top + destino.height / 2;
    const novas = nos.map((no, i) => {
      const r = origens.current[i]?.getBoundingClientRect();
      if (!r) return { d: "", etapa: no.etapa };
      const sx = r.right - base.left;
      const sy = r.top - base.top + r.height / 2;
      const ey = cy + (n > 1 ? (i - (n - 1) / 2) * Math.min(9, 60 / n) : 0);
      const dx = Math.max(24, (ex - sx) * 0.55);
      return { d: `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`, etapa: no.etapa };
    });
    setLinhas(novas);
    setCaixa({ w: base.width, h: base.height });
  }, [nos]);

  useLayoutEffect(() => {
    desenhar();
    const ro = new ResizeObserver(desenhar);
    if (area.current) ro.observe(area.current);
    return () => ro.disconnect();
  }, [desenhar]);

  return (
    <section className="fluxo mt-8" aria-label="Fluxo da aplicação">
      <div ref={area} className="fluxo-area">
        <svg className="fluxo-linhas" width={caixa.w} height={caixa.h} aria-hidden="true">
          {linhas.map((l, i) => l.d && <path key={i} d={l.d} className={`linha linha-${l.etapa}`} />)}
        </svg>

        <ol className="fluxo-cargas">
          {nos.map((no, i) => (
            <li key={no.id} ref={(el) => { origens.current[i] = el; }} className={`no-carga no-${no.etapa}${no.inativa ? " opacity-60" : ""}`}>
              <a href={link({ tela: "carga", id: no.id })} className="no-carga-nome" title={no.nome}>
                {no.nome}
              </a>
              <DetalheCarga no={no} />
            </li>
          ))}
          {!nos.length && <li className="no-carga no-espera text-[13px] text-muted-foreground">Nenhuma carga. Arraste cargas para esta aplicação na aba Cargas.</li>}
        </ol>

        <div ref={alvo} className={`no-app no-${app.etapa}${cancelando ? " no-cancelando" : ""}`}>
          <span className="no-app-icone" aria-hidden="true">
            <AppWindow className="h-6 w-6" />
          </span>
          <p className="no-app-nome">{app.temApp ? app.nome : "Só QVDs"}</p>
          <p className="no-app-estado">
            <EstadoApp app={app} cancelando={cancelando} />
          </p>
        </div>
      </div>
    </section>
  );
}

function DetalheCarga({ no }: { no: NoCarga }) {
  const r = no.rodada;
  const p = r?.progresso;
  if (r?.status === "rodando" && p) {
    const fase =
      p.fase === "lendo"
        ? `${(p.linhas ?? 0).toLocaleString("pt-BR")} linhas${p.mb_por_seg != null ? ` · ${p.mb_por_seg.toLocaleString("pt-BR")} MB/s` : ""}`
        : p.fase === "gerando"
          ? "Gerando o QVD"
          : p.fase === "enviando" && p.bytes_total
            ? `Enviando ${Math.round((100 * (p.bytes_enviados ?? 0)) / p.bytes_total)}%`
            : "Preparando";
    const fracao =
      p.fase === "lendo" && p.linhas_previstas ? Math.min((p.linhas ?? 0) / p.linhas_previstas, 0.99) : p.fase === "enviando" && p.bytes_total ? (p.bytes_enviados ?? 0) / p.bytes_total : null;
    return (
      <>
        <span className="no-carga-info">{fase}</span>
        <span className="no-carga-barra">
          <span style={{ width: fracao != null ? `${Math.max(fracao * 100, 2)}%` : "35%" }} className={fracao == null ? "indeterminada" : ""} />
        </span>
      </>
    );
  }
  if (r) {
    const texto =
      r.status === "sucesso"
        ? [tamanho(r.tamanho_bytes), tempo(r.duracao)].join(" · ")
        : r.status === "pendente"
          ? r.disparada_aqui
            ? "Na fila do worker"
            : "Na fila (já estava agendada)"
          : r.status === "erro"
            ? "Falhou"
            : r.status === "cancelado"
              ? "Cancelada"
              : "";
    return (
      <span className="no-carga-info" title={r.erro ?? undefined}>
        {texto}
        {!r.disparada_aqui && r.status !== "pendente" && <span className="tag !ml-1.5">reaproveitada</span>}
      </span>
    );
  }
  return <span className="no-carga-info">{no.resumo ?? ""}</span>;
}

function EstadoApp({ app, cancelando }: { app: NoApp; cancelando: boolean }) {
  const x = app.rodada && !app.rodada.terminou ? app.rodada : null;
  if (!app.temApp) return <>Vincule um app em Editar para recarregá-lo no fim</>;
  if (cancelando) return <>Cancelando o reload…</>;
  if (x?.status === "pendente" || x?.status === "cargas") return <>Espera as cargas terminarem</>;
  if (x?.status === "recarregando")
    return <>{x.reload_status === "QUEUED" || x.reload_status === "DISPARANDO" ? "Na fila da Qlik" : `Recarregando · ${tempo(segundosEntre(x.reload_iniciado_em))}`}</>;
  const u = app.rodada?.terminou ? app.rodada : app.ultima;
  if (!u) return <>Ainda não recarregado pelo LurkQVD</>;
  if (u.reload_status === "SUCCEEDED") return <>Recarregado {relativo(u.reload_finalizado_em ?? u.finalizado_em ?? "")} em {tempo(segundosEntre(u.reload_iniciado_em, u.reload_finalizado_em))}</>;
  if (u.status === "erro" && !u.reload_status) return <>Não recarregado: houve falha nas cargas</>;
  if (u.status === "cancelado") return <>Cancelado</>;
  return <>O reload falhou na Qlik</>;
}

function LinhaHistorico({ h, temApp }: { h: ExecucaoAplicacao; temApp: boolean }) {
  const quem = h.usuario_nome ?? h.usuario_email ?? h.token_nome ?? (h.origem === "agendador" ? "Agendamento" : "API");
  const total = segundosEntre(h.iniciado_em ?? h.solicitado_em, h.finalizado_em);
  const reload = h.reload_iniciado_em ? segundosEntre(h.reload_iniciado_em, h.reload_finalizado_em) : null;
  return (
    <li className="linha-hist-app">
      <StatusAplicacaoBadge status={h.status} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm">
          {dataHora(h.solicitado_em)} <span className="text-muted-foreground">· {quem}</span>
        </span>
        {h.erro && h.status !== "sucesso" && <span className="block truncate text-[12px] text-muted-foreground" title={h.erro}>{h.erro.split("\n")[0]}</span>}
      </span>
      <span className="hidden text-right text-[12.5px] text-muted-foreground sm:block">
        {h.terminou ? `total ${tempo(total)}` : "em andamento"}
        {temApp && reload != null && h.terminou && <span className="block">reload {tempo(reload)}</span>}
      </span>
    </li>
  );
}
