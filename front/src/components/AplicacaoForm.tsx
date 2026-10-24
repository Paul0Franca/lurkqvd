// Janela de criar/editar aplicação: nome, app da Qlik (busca por nome), agenda e, ao criar, as cargas.
import { useEffect, useMemo, useRef, useState } from "react";
import { AppWindow, Check, Loader2, Search, X } from "lucide-react";
import type { Api, Aplicacao, AppQlik, CargaResumo } from "../api";
import { AGENDA_PADRAO, deCron, paraCron, type Agenda } from "../lib/agenda";
import AgendamentoEditor from "./AgendamentoEditor";

interface Props {
  api: Api;
  aplicacao?: Aplicacao | null; // ausente = criar
  cargas?: CargaResumo[]; // para escolher ao criar
  cargasIniciais?: number[];
  aoFechar: () => void;
  aoSalvar: (a: Aplicacao) => void;
}

export default function AplicacaoForm({ api, aplicacao, cargas = [], cargasIniciais = [], aoFechar, aoSalvar }: Props) {
  const editando = Boolean(aplicacao);
  const [nome, setNome] = useState(aplicacao?.nome ?? "");
  const [descricao, setDescricao] = useState(aplicacao?.descricao ?? "");
  const [app, setApp] = useState<AppQlik | null>(
    aplicacao?.qlik_app_id ? { id: aplicacao.qlik_app_id, nome: aplicacao.qlik_app_nome ?? aplicacao.qlik_app_id, espaco_id: null, link: null } : null,
  );
  const [agenda, setAgenda] = useState<Agenda>(() => (aplicacao?.agendamento ? deCron(aplicacao.agendamento) : AGENDA_PADRAO));
  const [agendaValida, setAgendaValida] = useState(true);
  const [escolhidas, setEscolhidas] = useState<Set<number>>(() => new Set(cargasIniciais));
  const [buscaCarga, setBuscaCarga] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const janela = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && aoFechar();
    document.addEventListener("keydown", tecla);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    janela.current?.querySelector<HTMLInputElement>("input")?.focus();
    return () => {
      document.removeEventListener("keydown", tecla);
      document.body.style.overflow = overflow;
    };
  }, [aoFechar]);

  const termo = buscaCarga.trim().toLowerCase();
  const cargasVisiveis = useMemo(() => cargas.filter((c) => !termo || c.nome.toLowerCase().includes(termo)), [cargas, termo]);

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    if (!nome.trim()) return setErro("Dê um nome para a aplicação.");
    if (!agendaValida) return setErro("O agendamento não é válido.");
    setSalvando(true);
    setErro(null);
    try {
      const dados = {
        nome: nome.trim(),
        descricao: descricao.trim() || null,
        qlik_app_id: app?.id ?? "",
        agendamento: paraCron(agenda),
      };
      const salva = aplicacao
        ? await api.alterarAplicacao(aplicacao.id, dados)
        : await api.criarAplicacao({ ...dados, qlik_app_id: app?.id ?? null, carga_ids: [...escolhidas] });
      aoSalvar(salva);
    } catch (err) {
      setErro((err as Error).message);
      setSalvando(false);
    }
  }

  return (
    <div className="config-camada" role="presentation">
      <button type="button" className="config-fundo" aria-label="Fechar" onClick={aoFechar} />
      <form ref={janela} onSubmit={salvar} role="dialog" aria-modal="true" aria-labelledby="titulo-app-form" className="janela-app">
        <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
          <div>
            <h2 id="titulo-app-form" className="font-sora text-[17px] font-semibold">
              {editando ? "Editar aplicação" : "Nova aplicação"}
            </h2>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Um grupo de cargas que alimenta um app. Executar a aplicação atualiza todas e, no fim, recarrega o app na Qlik.
            </p>
          </div>
          <button type="button" className="icone-btn" onClick={aoFechar} aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="janela-app-corpo">
          <label className="campo-grupo">
            <span className="campo-rotulo">Nome</span>
            <input className="campo" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Estoque oficial" maxLength={120} />
          </label>

          <label className="campo-grupo">
            <span className="campo-rotulo">
              Descrição <span className="font-normal text-muted-foreground">(opcional)</span>
            </span>
            <input className="campo" value={descricao} onChange={(e) => setDescricao(e.target.value)} placeholder="Para que serve o app" maxLength={500} />
          </label>

          <div className="campo-grupo">
            <span className="campo-rotulo">
              App da Qlik <span className="font-normal text-muted-foreground">(opcional)</span>
            </span>
            <SeletorApp api={api} valor={app} aoMudar={setApp} />
            <span className="text-[12px] text-muted-foreground">
              {app ? "Depois que todas as cargas terminarem bem, este app é recarregado." : "Sem app, executar a aplicação só atualiza os QVDs."}
            </span>
          </div>

          <div className="campo-grupo">
            <span className="campo-rotulo">Quando executar</span>
            <AgendamentoEditor api={api} valor={agenda} aoMudar={setAgenda} aoValidar={(p) => setAgendaValida(p !== null)} />
          </div>

          {!editando && (
            <div className="campo-grupo">
              <span className="campo-rotulo flex items-center justify-between">
                Cargas
                <span className="font-normal text-muted-foreground">{escolhidas.size} escolhida(s)</span>
              </span>
              <label className="relative">
                <span className="sr-only">Buscar carga</span>
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input className="campo campo-pequeno pl-9" value={buscaCarga} onChange={(e) => setBuscaCarga(e.target.value)} placeholder="Buscar carga" />
              </label>
              <ul className="lista-escolha" aria-label="Cargas da aplicação">
                {cargasVisiveis.map((c) => {
                  const marcada = escolhidas.has(c.id);
                  return (
                    <li key={c.id}>
                      <label className="item-escolha">
                        <input
                          type="checkbox"
                          checked={marcada}
                          onChange={() =>
                            setEscolhidas((s) => {
                              const n = new Set(s);
                              if (marcada) n.delete(c.id);
                              else n.add(c.id);
                              return n;
                            })
                          }
                        />
                        <span className="truncate font-mono text-[12.5px]">{c.nome}</span>
                      </label>
                    </li>
                  );
                })}
                {!cargasVisiveis.length && <li className="px-3 py-2 text-[13px] text-muted-foreground">Nenhuma carga com esse nome.</li>}
              </ul>
              <span className="text-[12px] text-muted-foreground">Depois dá para arrastar cargas entre aplicações.</span>
            </div>
          )}

          {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}
        </div>

        <footer className="flex justify-end gap-2 border-t border-border px-6 py-4">
          <button type="button" className="btn-secundario" onClick={aoFechar}>
            Cancelar
          </button>
          <button type="submit" className="btn-primario inline-flex items-center gap-2" disabled={salvando}>
            {salvando && <Loader2 className="h-4 w-4 animate-spin" />}
            {editando ? "Salvar alterações" : "Criar aplicação"}
          </button>
        </footer>
      </form>
    </div>
  );
}

/** Busca apps da Qlik por nome (a API key do LurkQVD precisa enxergar o app). */
function SeletorApp({ api, valor, aoMudar }: { api: Api; valor: AppQlik | null; aoMudar: (a: AppQlik | null) => void }) {
  const [busca, setBusca] = useState("");
  const [resultados, setResultados] = useState<AppQlik[] | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState(false);

  useEffect(() => {
    if (!aberto) return;
    let cancelado = false;
    const t = setTimeout(() => {
      setCarregando(true);
      api
        .appsQlik(busca.trim())
        .then((r) => !cancelado && (setResultados(r), setErro(null)))
        .catch((e: Error) => !cancelado && setErro(e.message))
        .finally(() => !cancelado && setCarregando(false));
    }, 250);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [api, busca, aberto]);

  if (valor && !aberto) {
    return (
      <div className="app-escolhido">
        <AppWindow className="h-4 w-4 text-primary" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{valor.nome}</span>
          <span className="block truncate font-mono text-[11px] text-muted-foreground">{valor.id}</span>
        </span>
        <button type="button" className="btn-link text-[13px]" onClick={() => setAberto(true)}>
          Trocar
        </button>
        <button type="button" className="btn-link text-[13px] text-muted-foreground" onClick={() => aoMudar(null)}>
          Remover
        </button>
      </div>
    );
  }

  return (
    <div className="seletor-app">
      <label className="relative block">
        <span className="sr-only">Buscar app da Qlik</span>
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          className="campo pl-9"
          value={busca}
          onFocus={() => setAberto(true)}
          onChange={(e) => {
            setBusca(e.target.value);
            setAberto(true);
          }}
          placeholder="Buscar app pelo nome"
        />
        {carregando && <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />}
      </label>
      {aberto && (
        <ul className="seletor-app-lista" role="listbox" aria-label="Apps da Qlik">
          {erro && <li className="px-3 py-2 text-[13px] text-destructive">{erro}</li>}
          {resultados?.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                role="option"
                aria-selected={valor?.id === a.id}
                className="seletor-app-item"
                onClick={() => {
                  aoMudar(a);
                  setAberto(false);
                  setBusca("");
                }}
              >
                <AppWindow className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{a.nome}</span>
                {valor?.id === a.id && <Check className="h-4 w-4 text-primary" />}
              </button>
            </li>
          ))}
          {resultados && !resultados.length && !erro && (
            <li className="px-3 py-2 text-[13px] text-muted-foreground">Nenhum app encontrado. A API key do LurkQVD precisa ter acesso ao app.</li>
          )}
          {valor && (
            <li>
              <button type="button" className="seletor-app-item text-muted-foreground" onClick={() => setAberto(false)}>
                Manter {valor.nome}
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
