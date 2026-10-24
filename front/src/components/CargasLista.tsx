import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock, LayoutGrid, List, Plus, Search, X } from "lucide-react";
import type { Api, CargaResumo, Espaco, StatusExecucao, Usuario } from "../api";
import { descrever } from "../lib/agenda";
import { dataHora, relativo, tamanho } from "../lib/formato";
import { useExecucao } from "../lib/useExecucao";
import { link, navegar } from "../rotas";
import AplicacoesQuadro from "./AplicacoesQuadro";
import Avatar from "./Avatar";
import { BotaoExecutar, IconeEspaco, StatusBadge } from "./comum";

function primeiroNome(nome?: string | null, email?: string | null): string {
  return nome?.split(" ")[0] ?? email?.split("@")[0] ?? "";
}

interface Props {
  api: Api;
  usuario: Usuario;
  connectionId?: string;
  pasta?: string;
  visao?: "lista" | "aplicacoes";
}

type FiltroStatus = "" | "erro" | "agendadas" | "manuais";

export default function CargasLista({ api, usuario, connectionId = "", pasta = "", visao = "aplicacoes" }: Props) {
  const porApp = visao === "aplicacoes";
  const [cargas, setCargas] = useState<CargaResumo[] | null>(null);
  const [espacos, setEspacos] = useState<Espaco[]>([]);
  const [busca, setBusca] = useState("");
  const [espaco, setEspaco] = useState(connectionId);
  const [filtroStatus, setFiltroStatus] = useState<FiltroStatus>("");
  const [erro, setErro] = useState<string | null>(null);

  const admin = usuario.papel === "admin";
  const podeExecutar = admin || usuario.papel === "editor";

  const carregar = useCallback(() => {
    api
      .listarCargas()
      .then((c) => {
        setCargas(c);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(() => {
    carregar();
    api.espacos().then(setEspacos).catch(() => {});
  }, [api, carregar]);

  const pessoal = espacos.find((e) => e.tipo === "personal")?.connection_id;
  const nomeEspaco = useMemo(() => new Map(espacos.map((e) => [e.connection_id, e.nome])), [espacos]);

  const termo = busca.trim().toLowerCase();
  const visiveis = (cargas ?? []).filter((c) => {
    const conn = c.connection_id ?? pessoal;
    if (espaco && conn !== espaco) return false;
    if (pasta && c.qlik_path.split("/").slice(0, -1).join("/") !== pasta) return false;
    if (termo && !c.nome.toLowerCase().includes(termo) && !c.qlik_path.toLowerCase().includes(termo)) return false;
    if (filtroStatus === "erro" && c.ultimo_status !== "erro") return false;
    if (filtroStatus === "agendadas" && !c.agendamento) return false;
    if (filtroStatus === "manuais" && c.agendamento) return false;
    return true;
  });

  const temFiltro = Boolean(busca || espaco || pasta || filtroStatus);

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-sora text-[28px] font-semibold tracking-[-0.02em]">Cargas</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {porApp ? "Agrupadas pelo app da Qlik que alimentam. Arraste para reorganizar." : "O que é extraído, para onde vai e quando roda."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
        <div role="radiogroup" aria-label="Visão" className="segmentos">
          <button type="button" role="radio" aria-checked={porApp} className="segmento inline-flex items-center gap-1.5" onClick={() => navegar({ tela: "cargas" })}>
            <LayoutGrid className="h-3.5 w-3.5" aria-hidden="true" /> Por aplicação
          </button>
          <button type="button" role="radio" aria-checked={!porApp} className="segmento inline-flex items-center gap-1.5" onClick={() => navegar({ tela: "cargas", visao: "lista", connectionId: connectionId || undefined, pasta: pasta || undefined })}>
            <List className="h-3.5 w-3.5" aria-hidden="true" /> Lista
          </button>
        </div>
        {admin && (
          <a href={link({ tela: "nova-carga", connectionId: espaco || undefined, pasta: pasta || undefined })} className="btn-primario inline-flex items-center gap-2 no-underline">
            <Plus className="h-4 w-4" strokeWidth={2.2} />
            Nova carga
          </a>
        )}
        </div>
      </div>

      {/* ---------- filtros ---------- */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <label className="relative min-w-[220px] flex-1">
          <span className="sr-only">Buscar carga</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar por nome ou caminho" className="campo pl-9" />
        </label>
        {!porApp && (<>
        <label>
          <span className="sr-only">Espaço</span>
          <select value={espaco} onChange={(e) => setEspaco(e.target.value)} className="campo min-w-[190px]">
            <option value="">Todos os espaços</option>
            {espacos.map((e) => (
              <option key={e.connection_id} value={e.connection_id}>
                {e.nome}
              </option>
            ))}
          </select>
        </label>
        <div role="radiogroup" aria-label="Mostrar" className="segmentos">
          {(
            [
              ["", "Todas"],
              ["agendadas", "Agendadas"],
              ["manuais", "Manuais"],
              ["erro", "Com erro"],
            ] as [FiltroStatus, string][]
          ).map(([v, r]) => (
            <button key={v} type="button" role="radio" aria-checked={filtroStatus === v} className="segmento" onClick={() => setFiltroStatus(v)}>
              {r}
            </button>
          ))}
        </div>
        </>)}
      </div>

      {pasta && (
        <p className="mt-3 inline-flex items-center gap-2 text-sm text-muted-foreground">
          Só a pasta <span className="font-mono text-foreground">{pasta}</span>
          <a href={link({ tela: "cargas", visao: "lista", connectionId: espaco || undefined })} className="inline-flex items-center rounded p-0.5 hover:bg-secondary" aria-label="Remover filtro de pasta">
            <X className="h-3.5 w-3.5" />
          </a>
        </p>
      )}

      {erro && <p className="alerta alerta-erro mt-6">{erro}</p>}

      {porApp ? (
        cargas ? (
          <div className="mt-6">
            <AplicacoesQuadro api={api} usuario={usuario} cargas={cargas} busca={busca} aoMudarCargas={carregar} />
          </div>
        ) : (
          <p className="vazio mt-8">Carregando…</p>
        )
      ) : !cargas ? (
        <p className="vazio mt-8">Carregando cargas…</p>
      ) : cargas.length === 0 ? (
        <div className="vazio-grande mt-8">
          <p className="vazio-titulo">Nenhuma carga cadastrada.</p>
          <p className="vazio">{admin ? "Use “Nova carga” para cadastrar a primeira tabela que vai virar QVD." : "Peça a um admin para cadastrar a primeira carga."}</p>
        </div>
      ) : visiveis.length === 0 ? (
        <div className="vazio-grande mt-8">
          <p className="vazio-titulo">Nenhuma carga com esses filtros.</p>
          {temFiltro && <p className="vazio">Limpe a busca ou escolha outro espaço.</p>}
        </div>
      ) : (
        <ul className="lista-repo mt-6 overflow-hidden rounded-2xl border border-border bg-card">
          {visiveis.map((c) => (
            <LinhaCarga
              key={c.id}
              api={api}
              carga={c}
              espacoNome={nomeEspaco.get(c.connection_id ?? pessoal ?? "") ?? c.espaco_nome ?? "Pessoal"}
              podeExecutar={podeExecutar}
              aoTerminar={carregar}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function LinhaCarga({
  api,
  carga: c,
  espacoNome,
  podeExecutar,
  aoTerminar,
}: {
  api: Api;
  carga: CargaResumo;
  espacoNome: string;
  podeExecutar: boolean;
  aoTerminar: () => void;
}) {
  const { status, emAndamento, executar, erro } = useExecucao({
    api,
    cargaId: c.id,
    statusInicial: c.ultimo_status as StatusExecucao | null,
    execucaoInicial: c.ultima_execucao_id,
    aoMudar: (e) => e && aoTerminar(),
  });
  const pastaDestino = c.qlik_path.split("/").slice(0, -1).join(" / ");

  return (
    <li className="linha-repo-wrap">
      <a href={link({ tela: "carga", id: c.id })} className="linha-repo min-w-0 flex-1 flex-wrap sm:flex-nowrap">
        <span className="icone-carga">
          <IconeEspaco ativo={c.ativo} className="h-4 w-4" />
        </span>

        <span className="min-w-[180px] flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate font-mono text-[13px] font-semibold">{c.nome}</span>
            {!c.ativo && <span className="tag !ml-0">inativa</span>}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {espacoNome}
            {pastaDestino && ` / ${pastaDestino}`}
            {c.ultimo_tamanho_bytes ? `, ${tamanho(c.ultimo_tamanho_bytes)}` : ""}
          </span>
          {erro && <span className="block text-xs text-destructive">{erro}</span>}
        </span>

        <span className="agenda-celula">
          <span className={`inline-flex items-center gap-1.5 text-sm ${c.agendamento ? "" : "text-muted-foreground"}`}>
            {c.agendamento && <CalendarClock className="h-3.5 w-3.5 text-primary" aria-hidden="true" />}
            {descrever(c.agendamento)}
          </span>
          <span className="block text-xs text-muted-foreground">
            {c.agendamento && c.ativo && c.proxima_execucao
              ? `próxima ${relativo(c.proxima_execucao)}`
              : c.ultima_finalizacao
                ? `última ${relativo(c.ultima_finalizacao)}`
                : "nunca rodou"}
          </span>
        </span>

        {(c.criador_nome || c.criador_email) && (
          <span className="criador-celula" title={`Criada por ${c.criador_nome ?? c.criador_email}${c.criado_em ? ` em ${dataHora(c.criado_em)}` : ""}`}>
            <Avatar nome={c.criador_nome} email={c.criador_email} foto={c.criador_foto} tamanho={24} />
            <span className="min-w-0">
              <span className="block truncate text-sm">{primeiroNome(c.criador_nome, c.criador_email)}</span>
              <span className="block text-xs text-muted-foreground">{c.criado_em ? `criou ${relativo(c.criado_em)}` : "criador"}</span>
            </span>
          </span>
        )}

        <span className="status-celula">
          <StatusBadge status={status} />
        </span>
      </a>
      {podeExecutar && (
        <div className="flex w-[148px] shrink-0 justify-end pr-4">
          <BotaoExecutar emAndamento={emAndamento} desativado={!c.ativo} aoClicar={executar} />
        </div>
      )}
    </li>
  );
}
