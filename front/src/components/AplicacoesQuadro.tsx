// Visão "Por aplicação" da aba Cargas: um quadro por app, com as cargas que o alimentam.
// Admin arrasta cargas entre aplicações (Alt/Option ao soltar = copiar); cada carga também tem um
// menu com as mesmas ações, para quem usa teclado.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppWindow, Ban, CalendarClock, Copy, ExternalLink, GripVertical, Inbox, MoreHorizontal, Play, Plus, Undo2, X } from "lucide-react";
import type { Api, Aplicacao, CargaResumo, StatusExecucao, Usuario } from "../api";
import { descrever } from "../lib/agenda";
import { relativo, tamanho } from "../lib/formato";
import { link } from "../rotas";
import AplicacaoForm from "./AplicacaoForm";
import {
  BarraRodada,
  etapasDaRodada,
  resumoRodada,
  StatusAplicacaoBadge,
  tempo,
  useRodadaAplicacao,
} from "./AplicacoesComum";

interface Props {
  api: Api;
  usuario: Usuario;
  cargas: CargaResumo[];
  busca: string;
  aoMudarCargas?: () => void;
}

interface Arrasto {
  cargaId: number;
  origemId: number | null;
}
interface Alvo {
  appId: number | null;
  indice: number;
  copiar: boolean;
}
interface Aviso {
  texto: string;
  desfazer?: () => void;
  erro?: boolean;
}

const SEM_APP = "sem-app";

export default function AplicacoesQuadro({ api, usuario, cargas, busca }: Props) {
  const [apps, setApps] = useState<Aplicacao[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [arrasto, setArrasto] = useState<Arrasto | null>(null);
  const [alvo, setAlvo] = useState<Alvo | null>(null);
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const [criando, setCriando] = useState(false);
  const admin = usuario.papel === "admin";

  const carregar = useCallback(() => {
    api
      .aplicacoes()
      .then((a) => {
        setApps(a);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(() => {
    carregar();
    const t = setInterval(carregar, 20_000); // pega rodadas do agendador e mudanças de outras pessoas
    return () => clearInterval(t);
  }, [carregar]);

  useEffect(() => {
    if (!aviso) return;
    const t = setTimeout(() => setAviso(null), 6000);
    return () => clearTimeout(t);
  }, [aviso]);

  const porId = useMemo(() => new Map(cargas.map((c) => [c.id, c])), [cargas]);
  const semApp = useMemo(() => {
    const usadas = new Set((apps ?? []).flatMap((a) => a.cargas.map((c) => c.id)));
    return cargas.filter((c) => !usadas.has(c.id));
  }, [apps, cargas]);

  const termo = busca.trim().toLowerCase();
  const casa = (nome: string) => !termo || nome.toLowerCase().includes(termo);
  const visiveis = (apps ?? []).filter((a) => !termo || casa(a.nome) || a.cargas.some((c) => casa(c.nome)));

  const mover = useCallback(
    async (cargaId: number, origemId: number | null, destinoId: number | null, copiar: boolean, posicao: number | null, silencioso = false) => {
      const antes = apps;
      const nome = porId.get(cargaId)?.nome ?? "Carga";
      const posAnterior = origemId != null ? (apps?.find((a) => a.id === origemId)?.cargas.findIndex((c) => c.id === cargaId) ?? null) : null;
      // otimista: a tela muda na hora; se a API recusar, volta
      setApps((lista) => (lista ? moverLocal(lista, cargaId, origemId, destinoId, copiar, posicao, porId) : lista));
      try {
        setApps(await api.moverCarga({ carga_id: cargaId, origem_id: origemId, destino_id: destinoId, copiar, posicao }));
        if (silencioso) return;
        const destinoNome = apps?.find((a) => a.id === destinoId)?.nome;
        const texto =
          destinoId == null
            ? `${nome} saiu de ${apps?.find((a) => a.id === origemId)?.nome}`
            : copiar
              ? `${nome} também está em ${destinoNome}`
              : origemId === destinoId
                ? `${nome} mudou de posição`
                : `${nome} movida para ${destinoNome}`;
        setAviso({
          texto,
          desfazer: () =>
            copiar || origemId == null
              ? mover(cargaId, destinoId, null, false, null, true)
              : mover(cargaId, destinoId, origemId, false, posAnterior, true),
        });
      } catch (e) {
        setApps(antes);
        setAviso({ texto: (e as Error).message, erro: true });
      }
    },
    [api, apps, porId],
  );

  function soltar() {
    if (!arrasto || !alvo) return;
    const { cargaId, origemId } = arrasto;
    const destinoId = alvo.appId;
    setArrasto(null);
    setAlvo(null);
    if (destinoId === null && origemId === null) return; // de "sem aplicação" para lá mesmo
    const jaEsta = destinoId != null && apps?.find((a) => a.id === destinoId)?.cargas.some((c) => c.id === cargaId);
    if (jaEsta && origemId !== destinoId) {
      setAviso({ texto: `${porId.get(cargaId)?.nome} já está nessa aplicação.` });
      return;
    }
    let indice = alvo.indice;
    if (origemId === destinoId) {
      // reordenar no mesmo quadro: o índice veio contando o próprio chip, que sai antes de entrar
      const atual = apps?.find((a) => a.id === destinoId)?.cargas.findIndex((c) => c.id === cargaId) ?? -1;
      if (atual >= 0 && indice > atual) indice -= 1;
      if (indice === atual) return;
    }
    mover(cargaId, origemId, destinoId, alvo.copiar && origemId != null, destinoId == null ? null : indice);
  }

  const ctx: Ctx = { admin, arrasto, alvo, setArrasto, setAlvo, soltar, casa, apps: apps ?? [], mover, porId };

  return (
    <div className="mt-6">
      {erro && <p className="alerta alerta-erro">{erro}</p>}
      {!apps ? (
        <p className="vazio">Carregando aplicações…</p>
      ) : (
        <>
          {apps.length === 0 && (
            <div className="vazio-grande mb-5">
              <p className="vazio-titulo">Nenhuma aplicação ainda.</p>
              <p className="vazio">
                Agrupe as cargas de cada app da Qlik: executar a aplicação atualiza todas e, no fim, recarrega o app.
              </p>
            </div>
          )}
          <div className="quadro-apps">
            {visiveis.map((a) => (
              <CartaoAplicacao key={a.id} api={api} usuario={usuario} aplicacao={a} ctx={ctx} aoTerminar={carregar} />
            ))}
            {admin && !termo && (
              <button type="button" className="app-nova" onClick={() => setCriando(true)}>
                <Plus className="h-5 w-5" aria-hidden="true" />
                <span className="font-medium">Nova aplicação</span>
                <span className="text-[12.5px] text-muted-foreground">Agrupe as cargas de um app da Qlik</span>
              </button>
            )}
          </div>

          <SemAplicacao cargas={semApp.filter((c) => casa(c.nome) || !termo)} ctx={ctx} />
        </>
      )}

      {arrasto && admin && (
        <p className="dica-arrasto" role="status">
          Solte numa aplicação para mover · segure <kbd>Alt</kbd> para copiar
        </p>
      )}

      {aviso && (
        <div className={`aviso-flutuante${aviso.erro ? " aviso-erro" : ""}`} role="status">
          <span>{aviso.texto}</span>
          {aviso.desfazer && (
            <button
              type="button"
              className="aviso-acao"
              onClick={() => {
                aviso.desfazer?.();
                setAviso(null);
              }}
            >
              <Undo2 className="h-3.5 w-3.5" /> Desfazer
            </button>
          )}
          <button type="button" className="aviso-fechar" onClick={() => setAviso(null)} aria-label="Fechar aviso">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {criando && (
        <AplicacaoForm
          api={api}
          cargas={cargas}
          aoFechar={() => setCriando(false)}
          aoSalvar={() => {
            setCriando(false);
            carregar();
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- //

interface Ctx {
  admin: boolean;
  arrasto: Arrasto | null;
  alvo: Alvo | null;
  setArrasto: (a: Arrasto | null) => void;
  setAlvo: (a: Alvo | null) => void;
  soltar: () => void;
  casa: (nome: string) => boolean;
  apps: Aplicacao[];
  mover: (cargaId: number, origemId: number | null, destinoId: number | null, copiar: boolean, posicao: number | null) => void;
  porId: Map<number, CargaResumo>;
}

/** Recebe cargas arrastadas: calcula a posição de inserção pela posição do ponteiro sobre os chips. */
function useAreaSoltar(appId: number | null, ctx: Ctx) {
  const lista = useRef<HTMLUListElement>(null);
  const ativo = ctx.admin && ctx.arrasto !== null;

  function indicePara(e: React.DragEvent): number {
    const chips = Array.from(lista.current?.querySelectorAll<HTMLElement>("[data-chip]") ?? []);
    for (let i = 0; i < chips.length; i++) {
      const r = chips[i].getBoundingClientRect();
      if (e.clientY < r.top || (e.clientY <= r.bottom && e.clientX < r.left + r.width / 2)) return i;
    }
    return chips.length;
  }

  const props = ativo
    ? {
        onDragOver: (e: React.DragEvent) => {
          e.preventDefault();
          const copiar = e.altKey && ctx.arrasto?.origemId != null && appId != null;
          e.dataTransfer.dropEffect = copiar ? "copy" : "move";
          const indice = appId == null ? 0 : indicePara(e);
          if (ctx.alvo?.appId !== appId || ctx.alvo?.indice !== indice || ctx.alvo?.copiar !== copiar) ctx.setAlvo({ appId, indice, copiar });
        },
        onDragLeave: (e: React.DragEvent) => {
          if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) ctx.setAlvo(null);
        },
        onDrop: (e: React.DragEvent) => {
          e.preventDefault();
          ctx.soltar();
        },
      }
    : {};
  const ehAlvo = ativo && ctx.alvo?.appId === appId;
  return { lista, props, ehAlvo, indice: ehAlvo ? ctx.alvo!.indice : -1, copiar: ehAlvo && ctx.alvo!.copiar };
}

function CartaoAplicacao({ api, usuario, aplicacao: a, ctx, aoTerminar }: { api: Api; usuario: Usuario; aplicacao: Aplicacao; ctx: Ctx; aoTerminar: () => void }) {
  const { rodada, emAndamento, executar, cancelar, ocupado, erro } = useRodadaAplicacao(api, a, aoTerminar);
  const area = useAreaSoltar(a.id, ctx);
  const podeExecutar = usuario.papel === "admin" || usuario.papel === "editor";
  const status = rodada && !rodada.terminou ? rodada.status : (rodada?.status ?? a.ultimo_status);
  const etapas = etapasDaRodada(rodada, a);
  const chips = a.cargas;

  return (
    <article className={`app-card${area.ehAlvo ? " app-card-alvo" : ""}${!a.ativo ? " opacity-70" : ""}`} {...area.props}>
      <header className="flex items-center gap-3">
        <span className="app-icone" aria-hidden="true">
          <AppWindow className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <a href={link({ tela: "aplicacao", id: a.id })} className="app-nome">
              {a.nome}
            </a>
            {status && status !== "sucesso" && <StatusAplicacaoBadge status={status} />}
            {!a.ativo && <span className="tag">inativa</span>}
          </div>
        </div>
        {podeExecutar &&
          (emAndamento ? (
            <button type="button" className="btn-executar inline-flex items-center gap-1.5" onClick={cancelar} disabled={ocupado || !rodada}>
              <Ban className="h-3.5 w-3.5" aria-hidden="true" />
              Cancelar
            </button>
          ) : (
            <button
              type="button"
              className="btn-executar inline-flex items-center gap-1.5"
              onClick={executar}
              disabled={ocupado || !a.ativo || (!a.cargas.length && !a.qlik_app_id)}
            >
              <Play className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true" />
              Executar tudo
            </button>
          ))}
      </header>
      <p className="app-meta flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted-foreground">
        {a.qlik_app_id ? (
          <span className="inline-flex items-center gap-1">
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
            {a.qlik_app_nome}
          </span>
        ) : (
          <span>Só QVDs, sem app</span>
        )}
        {a.agendamento && (
          <span className="inline-flex items-center gap-1">
            <CalendarClock className="h-3 w-3" aria-hidden="true" />
            {descrever(a.agendamento)}
          </span>
        )}
        {a.ultimo_sucesso_em && !emAndamento && (
          <span title="Da primeira carga ao fim do reload">
            {relativo(a.ultimo_sucesso_em)} em {tempo(a.ultimo_sucesso_seg)}
          </span>
        )}
      </p>

      {(chips.length > 0 || a.qlik_app_id) && (
        <div className="mt-3.5">
          <BarraRodada cargas={etapas.cargas} reload={etapas.reload} rotulo={emAndamento ? resumoRodada(rodada) : "Última execução de cada etapa"} />
          {emAndamento && <p className="mt-1.5 text-[12px] text-muted-foreground">{resumoRodada(rodada)}</p>}
          {!emAndamento && a.ultimo_status === "erro" && a.ultimo_erro && (
            <p className="mt-1.5 line-clamp-2 text-[12px] text-destructive">{a.ultimo_erro}</p>
          )}
          {erro && <p className="mt-1.5 text-[12px] text-destructive">{erro}</p>}
        </div>
      )}

      <ul ref={area.lista} className="chips-cargas" aria-label={`Cargas de ${a.nome}`}>
        {chips.map((c, i) => (
          <ChipEnvolto key={c.id} antes={area.indice === i} copiar={area.copiar}>
            <ChipCarga
              cargaId={c.id}
              nome={c.nome}
              status={rodada && !rodada.terminou ? (rodada.cargas?.find((x) => x.carga_id === c.id)?.status ?? c.ultimo_status) : c.ultimo_status}
              detalhe={c.ultimo_tamanho_bytes ? tamanho(c.ultimo_tamanho_bytes) : null}
              origemId={a.id}
              ctx={ctx}
            />
          </ChipEnvolto>
        ))}
        {area.indice === chips.length && <li className="caret-insercao" aria-hidden="true" data-copiar={area.copiar || undefined} />}
        {!chips.length && (
          <li className="chips-vazio">
            <Inbox className="h-4 w-4" aria-hidden="true" />
            {ctx.admin ? "Arraste cargas para cá" : "Nenhuma carga"}
          </li>
        )}
      </ul>
    </article>
  );
}

function ChipEnvolto({ antes, copiar, children }: { antes: boolean; copiar: boolean; children: React.ReactNode }) {
  return (
    <>
      {antes && <li className="caret-insercao" aria-hidden="true" data-copiar={copiar || undefined} />}
      {children}
    </>
  );
}

function ChipCarga({
  cargaId,
  nome,
  status,
  detalhe,
  origemId,
  ctx,
}: {
  cargaId: number;
  nome: string;
  status: StatusExecucao | null;
  detalhe: string | null;
  origemId: number | null;
  ctx: Ctx;
}) {
  const [menu, setMenu] = useState(false);
  const arrastando = ctx.arrasto?.cargaId === cargaId && ctx.arrasto?.origemId === origemId;
  const apagado = !ctx.casa(nome);
  const outras = ctx.apps.filter((a) => a.id !== origemId);

  return (
    <li
      data-chip
      className={`chip-carga${arrastando ? " chip-arrastando" : ""}${apagado ? " chip-apagado" : ""}`}
      draggable={ctx.admin}
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", String(cargaId));
        e.dataTransfer.effectAllowed = "copyMove";
        ctx.setArrasto({ cargaId, origemId });
      }}
      onDragEnd={() => {
        ctx.setArrasto(null);
        ctx.setAlvo(null);
      }}
    >
      {ctx.admin && <GripVertical className="chip-alca h-3.5 w-3.5" aria-hidden="true" />}
      <span className={`ponto-status !mt-0 ponto-${status ?? "nunca"}`} aria-hidden="true" />
      <a href={link({ tela: "carga", id: cargaId })} className="chip-nome" draggable={false} title={nome}>
        {nome}
      </a>
      {detalhe && <span className="chip-detalhe">{detalhe}</span>}
      {ctx.admin && (
        <span className="relative">
          <button
            type="button"
            className="chip-menu-btn"
            aria-label={`Ações de ${nome}`}
            aria-expanded={menu}
            onClick={() => setMenu((m) => !m)}
            onBlur={(e) => !e.currentTarget.parentElement?.contains(e.relatedTarget as Node) && setMenu(false)}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
          {menu && (
            <span className="chip-menu" role="menu" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setMenu(false)}>
              {outras.map((a) => (
                <button key={`m${a.id}`} type="button" role="menuitem" onClick={() => (setMenu(false), ctx.mover(cargaId, origemId, a.id, false, null))}>
                  Mover para {a.nome}
                </button>
              ))}
              {origemId != null &&
                outras.map((a) => (
                  <button key={`c${a.id}`} type="button" role="menuitem" onClick={() => (setMenu(false), ctx.mover(cargaId, origemId, a.id, true, null))}>
                    <Copy className="h-3 w-3" /> Copiar para {a.nome}
                  </button>
                ))}
              {origemId != null && (
                <button type="button" role="menuitem" onClick={() => (setMenu(false), ctx.mover(cargaId, origemId, null, false, null))}>
                  Tirar desta aplicação
                </button>
              )}
              {!outras.length && origemId == null && <span className="px-3 py-2 text-muted-foreground">Crie uma aplicação primeiro</span>}
            </span>
          )}
        </span>
      )}
    </li>
  );
}

function SemAplicacao({ cargas, ctx }: { cargas: CargaResumo[]; ctx: Ctx }) {
  const area = useAreaSoltar(null, ctx);
  if (!cargas.length && !(ctx.arrasto && ctx.arrasto.origemId !== null)) return null;
  return (
    <section className={`sem-app${area.ehAlvo ? " app-card-alvo" : ""}`} {...area.props} aria-labelledby={SEM_APP}>
      <h2 id={SEM_APP} className="text-[13px] font-medium text-muted-foreground">
        Sem aplicação <span className="font-normal">({cargas.length})</span>
        {ctx.arrasto?.origemId != null && <span className="font-normal"> · solte aqui para tirar da aplicação</span>}
      </h2>
      <ul ref={area.lista} className="chips-cargas">
        {cargas.map((c) => (
          <ChipCarga key={c.id} cargaId={c.id} nome={c.nome} status={c.ultimo_status} detalhe={c.ultimo_tamanho_bytes ? tamanho(c.ultimo_tamanho_bytes) : null} origemId={null} ctx={ctx} />
        ))}
      </ul>
    </section>
  );
}

/** Aplica o mover na lista local (para a tela responder na hora, antes da API). */
function moverLocal(
  lista: Aplicacao[],
  cargaId: number,
  origemId: number | null,
  destinoId: number | null,
  copiar: boolean,
  posicao: number | null,
  porId: Map<number, CargaResumo>,
): Aplicacao[] {
  const original = lista.flatMap((a) => a.cargas).find((c) => c.id === cargaId);
  const c = porId.get(cargaId);
  const item = original ?? {
    id: cargaId,
    nome: c?.nome ?? "",
    ativo: c?.ativo ?? true,
    ordem: 0,
    ultimo_status: c?.ultimo_status ?? null,
    ultima_execucao_id: c?.ultima_execucao_id ?? null,
    ultima_finalizacao: c?.ultima_finalizacao ?? null,
    ultimo_tamanho_bytes: c?.ultimo_tamanho_bytes ?? null,
    ultima_duracao: null,
  };
  return lista.map((a) => {
    let cs = a.cargas;
    if (a.id === origemId && !copiar) cs = cs.filter((x) => x.id !== cargaId);
    if (a.id === destinoId) {
      cs = cs.filter((x) => x.id !== cargaId);
      const pos = posicao == null ? cs.length : Math.min(posicao, cs.length);
      cs = [...cs.slice(0, pos), item, ...cs.slice(pos)];
    }
    return cs === a.cargas ? a : { ...a, cargas: cs };
  });
}

