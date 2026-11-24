// Avisos dentro da ferramenta: o sino do topo (com a contagem de não lidos), a lista que ele abre
// e o balão que aparece sobre a tela com o fundo desfocado quando há aviso novo para ler.
//
// - O balão abre sozinho ao entrar com os avisos não lidos marcados "abrir ao entrar".
//   "Entendi" marca como lido; "Ver depois" (ou Esc) só fecha: o aviso continua no sino e o
//   balão não volta nesta aba (sessionStorage), mas volta no próximo login se seguir sem ler.
// - Clicar num aviso da lista abre o mesmo balão com ele.
// - Busca de novo a cada 5 min e quando a aba volta ao foco.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bell, CheckCheck, ExternalLink, Megaphone, Sparkles, X } from "lucide-react";
import type { Api, AvisoDaPessoa } from "../api";
import { dataHora, relativo } from "../lib/formato";

const INTERVALO_MS = 5 * 60 * 1000;
const CHAVE_ADIADOS = "lurkqvd.avisos_adiados";

function lerAdiados(): number[] {
  try {
    return JSON.parse(sessionStorage.getItem(CHAVE_ADIADOS) ?? "[]");
  } catch {
    return [];
  }
}

function salvarAdiados(ids: number[]) {
  try {
    sessionStorage.setItem(CHAVE_ADIADOS, JSON.stringify(ids));
  } catch {
    /* navegação privada sem storage: o balão só pode voltar ao recarregar */
  }
}

/** Avisos da pessoa logada, com marcar como lido otimista. */
function useAvisos(api: Api) {
  const [avisos, setAvisos] = useState<AvisoDaPessoa[] | null>(null);

  const carregar = useCallback(() => {
    api
      .meusAvisos()
      .then((r) => setAvisos(r.avisos))
      .catch(() => {}); // aviso não é essencial: sem API, o sino só fica quieto
  }, [api]);

  useEffect(() => {
    carregar();
    const timer = window.setInterval(carregar, INTERVALO_MS);
    const aoVoltar = () => document.visibilityState === "visible" && carregar();
    document.addEventListener("visibilitychange", aoVoltar);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", aoVoltar);
    };
  }, [carregar]);

  const marcarLidos = useCallback(
    (ids?: number[]) => {
      setAvisos((lista) => lista?.map((a) => (!ids || ids.includes(a.id) ? { ...a, lido: true } : a)) ?? lista);
      api.marcarAvisosLidos(ids).catch(carregar); // falhou: volta ao que o servidor tem
    },
    [api, carregar],
  );

  return { avisos, marcarLidos };
}

/** Sino do topo + lista + balão. Fica no cabeçalho; o balão vai para o <body> (o topo tem backdrop-filter). */
export default function CentralAvisos({ api }: { api: Api }) {
  const { avisos, marcarLidos } = useAvisos(api);
  const [aberto, setAberto] = useState(false);
  const [adiados, setAdiados] = useState<number[]>(lerAdiados);
  const [escolhido, setEscolhido] = useState<number | null>(null); // aberto pela lista
  const raiz = useRef<HTMLDivElement>(null);

  const naoLidos = avisos?.filter((a) => !a.lido).length ?? 0;

  // fila do balão: o escolhido na lista, ou os novos que abrem sozinhos (do mais antigo ao mais novo)
  const fila = useMemo(() => {
    if (!avisos) return [];
    if (escolhido != null) return avisos.filter((a) => a.id === escolhido);
    return avisos.filter((a) => !a.lido && a.abrir_ao_entrar && !adiados.includes(a.id)).reverse();
  }, [avisos, escolhido, adiados]);

  // lista: fecha ao clicar fora ou com Esc
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => !raiz.current?.contains(e.target as Node) && setAberto(false);
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && setAberto(false);
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto]);

  function adiar(ids: number[]) {
    if (escolhido != null) {
      setEscolhido(null);
      return;
    }
    const novos = [...new Set([...adiados, ...ids])];
    setAdiados(novos);
    salvarAdiados(novos);
  }

  function entendi(id: number) {
    marcarLidos([id]);
    if (escolhido != null) setEscolhido(null);
  }

  return (
    <div ref={raiz} className="relative">
      <button
        type="button"
        className="botao-sino"
        aria-label={naoLidos ? `Avisos: ${naoLidos} não lido${naoLidos > 1 ? "s" : ""}` : "Avisos"}
        title="Avisos"
        aria-haspopup="dialog"
        aria-expanded={aberto}
        data-novo={naoLidos > 0 || undefined}
        onClick={() => setAberto((a) => !a)}
      >
        <Bell className="h-[18px] w-[18px]" aria-hidden="true" />
        {naoLidos > 0 && (
          <span className="sino-contador" aria-hidden="true">
            {naoLidos > 9 ? "9+" : naoLidos}
          </span>
        )}
      </button>

      {aberto && (
        <div role="dialog" aria-label="Avisos" className="painel-avisos">
          <div className="flex items-center justify-between gap-3 px-4 pb-2 pt-3.5">
            <p className="font-sora text-sm font-semibold">Avisos</p>
            {naoLidos > 0 && (
              <button type="button" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground" onClick={() => marcarLidos()}>
                <CheckCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Marcar todos como lidos
              </button>
            )}
          </div>
          {!avisos ? (
            <p className="px-4 pb-5 pt-2 text-sm text-muted-foreground">Carregando…</p>
          ) : avisos.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 pb-7 pt-4 text-center">
              <span className="grid h-10 w-10 place-items-center rounded-full bg-secondary text-muted-foreground">
                <Bell className="h-5 w-5" aria-hidden="true" />
              </span>
              <p className="text-sm font-medium">Nenhum aviso por aqui</p>
              <p className="text-xs text-muted-foreground">Novidades do LurkQVD e recados do time aparecem neste sino.</p>
            </div>
          ) : (
            <ul className="max-h-[min(420px,60vh)] overflow-y-auto pb-1.5">
              {avisos.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    className="aviso-item"
                    data-lido={a.lido || undefined}
                    onClick={() => {
                      setAberto(false);
                      setEscolhido(a.id);
                    }}
                  >
                    <IconeAviso origem={a.origem} pequeno />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{a.titulo}</span>
                      <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{a.texto}</span>
                      <span className="mt-1 block text-[11px] text-muted-foreground" title={dataHora(a.publicado_em)}>
                        {relativo(a.publicado_em)}
                      </span>
                    </span>
                    {!a.lido && <span className="aviso-ponto" aria-label="Não lido" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {fila.length > 0 && <BalaoAvisos key={escolhido ?? "novos"} fila={fila} aoEntender={entendi} aoAdiar={adiar} />}
    </div>
  );
}

function IconeAviso({ origem, pequeno = false }: { origem: AvisoDaPessoa["origem"]; pequeno?: boolean }) {
  const Icone = origem === "sistema" ? Sparkles : Megaphone;
  return (
    <span className={pequeno ? "aviso-icone aviso-icone-p" : "aviso-icone"} aria-hidden="true">
      <Icone className={pequeno ? "h-4 w-4" : "h-5 w-5"} />
    </span>
  );
}

interface BalaoProps {
  fila: AvisoDaPessoa[];
  aoEntender: (id: number) => void;
  aoAdiar: (ids: number[]) => void;
}

/** O balão sobre a tela, com o fundo desfocado. Mostra um aviso por vez. */
function BalaoAvisos({ fila, aoEntender, aoAdiar }: BalaoProps) {
  // a fila encolhe quando um aviso é lido; o primeiro da fila é sempre o atual
  const aviso = fila[0];
  const [total] = useState(fila.length);
  const posicao = Math.max(1, total - fila.length + 1);
  const cartao = useRef<HTMLDivElement>(null);
  const adiarTodos = useCallback(() => aoAdiar(fila.map((a) => a.id)), [aoAdiar, fila]);

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && adiarTodos();
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [adiarTodos]);

  // a página de trás não rola com o balão aberto; o foco vai para ele
  useEffect(() => {
    const anterior = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    cartao.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      anterior?.focus?.();
    };
  }, []);

  return createPortal(
    <div className="balao-camada" role="presentation">
      <button type="button" className="balao-fundo" aria-label="Ver depois" tabIndex={-1} onClick={adiarTodos} />
      <div ref={cartao} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="balao-titulo" aria-describedby="balao-texto" className="balao">
        <div className="balao-brilho" aria-hidden="true" />
        <button type="button" className="balao-fechar" aria-label="Fechar (ver depois)" onClick={adiarTodos}>
          <X className="h-4 w-4" />
        </button>

        <div className="balao-sino" aria-hidden="true">
          <Bell className="h-6 w-6" />
        </div>

        <p className="balao-rotulo">
          {aviso.origem === "sistema" ? "Novidade do LurkQVD" : "Aviso"}
          {total > 1 && (
            <span className="text-muted-foreground">
              {" "}· {posicao} de {Math.max(total, posicao)}
            </span>
          )}
        </p>
        <h2 id="balao-titulo" className="mt-1.5 font-sora text-xl font-semibold tracking-[-0.02em] text-balance">
          {aviso.titulo}
        </h2>
        <p id="balao-texto" className="mt-3 whitespace-pre-line text-[14.5px] leading-relaxed text-muted-foreground">
          {aviso.texto}
        </p>
        <p className="mt-3 text-xs text-muted-foreground" title={dataHora(aviso.publicado_em)}>
          Publicado {relativo(aviso.publicado_em)}
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {aviso.link_url && (
            <a
              href={aviso.link_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secundario inline-flex items-center gap-2 !py-2"
              onClick={() => aoEntender(aviso.id)}
            >
              {aviso.link_rotulo || "Abrir link"}
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </a>
          )}
          <span className="flex-1" />
          <button type="button" className="text-sm text-muted-foreground hover:text-foreground" onClick={adiarTodos}>
            Ver depois
          </button>
          <button type="button" className="btn-primario !px-4 !py-2" onClick={() => aoEntender(aviso.id)}>
            {fila.length > 1 ? "Entendi, próximo" : "Entendi"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
