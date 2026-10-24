import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Check, Copy, Pencil } from "lucide-react";
import type { Api, CargaDetalhe as Carga, Espaco, Execucao, Fonte, Usuario } from "../api";
import { deCron, descrever, paraCron } from "../lib/agenda";
import { ROTULO, dataHora, duracao, relativo, tamanho } from "../lib/formato";
import { useExecucao } from "../lib/useExecucao";
import { link } from "../rotas";
import AgendamentoEditor from "./AgendamentoEditor";
import Avatar from "./Avatar";
import GraficoExecucoes from "./GraficoExecucoes";
import ProgressoExecucao from "./ProgressoExecucao";
import { ComposicaoCarga } from "./ComposicaoQvd";
import { BotaoExecutar, Migalhas, StatusBadge } from "./comum";
import MoverDestino from "./MoverDestino";

interface Props {
  api: Api;
  usuario: Usuario;
  id: number;
}

function segundos(e: Execucao): number {
  return [e.seg_extracao, e.seg_geracao, e.seg_upload].reduce((s, v) => s + Number(v ?? 0), 0);
}

function quem(e: Execucao): string {
  if (e.usuario_nome) return e.usuario_nome;
  if (e.usuario_email) return e.usuario_email;
  if (e.token_nome) return e.token_nome;
  return e.origem === "agendador" ? "Agendamento" : e.origem === "airflow" ? "Airflow" : e.origem === "aplicacao" ? "Aplicação" : "Sistema";
}

export default function CargaDetalhe({ api, usuario, id }: Props) {
  const [carga, setCarga] = useState<Carga | null>(null);
  const [historico, setHistorico] = useState<Execucao[] | null>(null);
  const [espacos, setEspacos] = useState<Espaco[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  const carregarHistorico = useCallback(() => {
    api.historico(id).then(setHistorico).catch(() => {});
  }, [api, id]);

  // o componente é recriado a cada carga (key no App), então o estado já começa vazio
  useEffect(() => {
    api.carga(id).then(setCarga).catch((e: Error) => setErro(e.message));
    api.espacos().then(setEspacos).catch(() => {});
    carregarHistorico();
    // de tempos em tempos, para pegar execuções do agendador ou de outras pessoas
    const t = setInterval(carregarHistorico, 15_000);
    return () => clearInterval(t);
  }, [api, id, carregarHistorico]);

  if (erro) {
    return (
      <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
        <p className="alerta alerta-erro">{erro}</p>
        <a href={link({ tela: "cargas" })} className="text-sm text-primary hover:underline">
          Voltar para as cargas
        </a>
      </div>
    );
  }
  if (!carga || !historico) return <p className="vazio mx-auto max-w-[1100px] px-6 py-8">Carregando…</p>;

  return (
    <Conteudo
      api={api}
      usuario={usuario}
      carga={carga}
      historico={historico}
      espacos={espacos}
      aoMudar={carregarHistorico}
      aoAlterar={setCarga}
    />
  );
}

function Conteudo({
  api,
  usuario,
  carga,
  historico,
  espacos,
  aoMudar,
  aoAlterar,
}: {
  api: Api;
  usuario: Usuario;
  carga: Carga;
  historico: Execucao[];
  espacos: Espaco[];
  aoMudar: () => void;
  aoAlterar: (c: Carga) => void;
}) {
  const ultima = historico[0] ?? null;
  const ultimoSucesso = historico.find((e) => e.status === "sucesso") ?? null;

  const { status, emAndamento, executar, erro, execucao, cancelar, cancelando } = useExecucao({
    api,
    cargaId: carga.id,
    statusInicial: ultima?.status ?? null,
    execucaoInicial: ultima?.id ?? null,
    aoMudar,
  });

  const espaco =
    espacos.find((e) => e.connection_id === carga.connection_id) ?? espacos.find((e) => !carga.connection_id && e.tipo === "personal");
  const pastas = carga.qlik_path.split("/").slice(0, -1);
  const arquivo = carga.qlik_path.split("/").at(-1);

  const destinoHref = espaco ? link({ tela: "espaco", connectionId: espaco.connection_id, pasta: pastas.join("/") }) : undefined;

  const podeExecutar = usuario.papel === "admin" || usuario.papel === "editor";
  const [movendo, setMovendo] = useState(false);

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <Migalhas itens={[{ rotulo: "Cargas", href: link({ tela: "cargas" }) }, { rotulo: carga.nome }]} />

      {/* ---------- cabeçalho ---------- */}
      <header className="mt-5 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="truncate font-mono text-[26px] font-semibold tracking-[-0.02em]">{carga.nome}</h1>
            <StatusBadge status={status} />
            {!carga.ativo && <span className="tag">inativa</span>}
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">
            <FonteDaCarga api={api} carga={carga} podeEditar={usuario.papel === "admin"} aoAlterar={aoAlterar} />
            {" · "}publica <span className="font-mono text-foreground">{arquivo}</span>
            {espaco && (
              <>
                {" "}em{" "}
                <a href={destinoHref} className="text-foreground underline decoration-border underline-offset-4 hover:decoration-current">
                  {[espaco.nome, ...pastas].join(" / ")}
                </a>
              </>
            )}
            {usuario.papel === "admin" && (
              <button
                type="button"
                onClick={() => setMovendo(true)}
                title="Mover para outro espaço ou pasta"
                aria-label="Mover o destino da carga"
                className="ml-1 inline-flex size-5 items-center justify-center rounded align-[-3px] text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <Pencil className="size-3" />
              </button>
            )}
          </p>
        </div>
        {podeExecutar && (
          <div className="flex flex-col items-end gap-1.5">
            <BotaoExecutar emAndamento={emAndamento} desativado={!carga.ativo} aoClicar={executar} tamanho="grande" />
            {erro && <span className="text-xs text-destructive">{erro}</span>}
          </div>
        )}
      </header>

      {movendo && (
        <MoverDestino
          api={api}
          carga={carga}
          espacos={espacos}
          emAndamento={emAndamento}
          aoMover={(c) => {
            aoAlterar(c);
            setMovendo(false);
          }}
          aoFechar={() => setMovendo(false)}
        />
      )}

      {emAndamento && (
        <ProgressoExecucao
          status={status}
          execucao={execucao}
          podeCancelar={podeExecutar}
          cancelando={cancelando}
          aoCancelar={cancelar}
        />
      )}

      {/* ---------- números da última execução com sucesso ---------- */}
      <dl className="mt-8 grid grid-cols-2 overflow-hidden rounded-2xl border border-border bg-card md:grid-cols-5">
        <Metrica rotulo="Última publicação" valor={ultimoSucesso?.finalizado_em ? relativo(ultimoSucesso.finalizado_em) : "—"} dica={dataHora(ultimoSucesso?.finalizado_em ?? null)} />
        <Metrica rotulo="Linhas" valor={ultimoSucesso?.linhas?.toLocaleString("pt-BR") ?? "—"} dica={ultimoSucesso?.colunas ? `${ultimoSucesso.colunas} colunas` : undefined} />
        <Metrica rotulo="Tamanho do QVD" valor={tamanho(ultimoSucesso?.tamanho_bytes)} dica="o que entra na cota da Qlik" />
        <Metrica rotulo="Duração" valor={ultimoSucesso ? duracao(segundos(ultimoSucesso)) : "—"} dica={ultimoSucesso ? <Etapas e={ultimoSucesso} /> : undefined} />
        <Metrica
          rotulo="Memória"
          valor={tamanho(ultimoSucesso?.memoria_pico_bytes)}
          dica={ultimoSucesso?.memoria_pico_bytes != null ? "o que a fila reserva para ela" : "medida na próxima execução"}
        />
      </dl>

      <GraficoExecucoes historico={historico} />

      <section className="mt-8" aria-labelledby="titulo-composicao">
        <h2 id="titulo-composicao" className="font-sora text-sm font-semibold">
          Composição do QVD
        </h2>
        <ComposicaoCarga api={api} cargaId={carga.id} versao={ultimoSucesso?.id} />
      </section>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        {/* ---------- agendamento + consulta ---------- */}
        <section className="min-w-0">
          <Agendamento api={api} carga={carga} admin={usuario.papel === "admin"} aoAlterar={aoAlterar} />

          <Consulta api={api} carga={carga} admin={usuario.papel === "admin"} emAndamento={emAndamento} aoAlterar={aoAlterar} />
          <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Caminho na Qlik</dt>
            <dd className="truncate font-mono text-[13px]" title={carga.qlik_path}>
              {carga.qlik_path}
            </dd>
            <dt className="text-muted-foreground">ID do arquivo</dt>
            <dd className="truncate font-mono text-[13px]">{carga.file_id ?? "criado na 1ª execução"}</dd>
            <dt className="text-muted-foreground">Cadastrada</dt>
            <dd>{dataHora(carga.criado_em)}</dd>
          </dl>
        </section>

        {/* ---------- histórico em linha do tempo ---------- */}
        <section>
          <h2 className="mb-3 font-sora text-sm font-semibold">Histórico</h2>
          {historico.length === 0 ? (
            <div className="vazio-grande">
              <p className="vazio-titulo">Ainda não rodou.</p>
              <p className="vazio">Use “Executar” para gerar e publicar o primeiro QVD.</p>
            </div>
          ) : (
            <ol className="linha-tempo">
              {historico.slice(0, 10).map((e) => (
                <li key={e.id} className="linha-tempo-item">
                  <span className={`linha-tempo-ponto ponto-${e.status}`} aria-hidden="true" />
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-sm font-medium">{ROTULO[e.status]}</span>
                    <time className="text-xs text-muted-foreground" dateTime={e.solicitado_em} title={dataHora(e.solicitado_em)}>
                      {relativo(e.solicitado_em)}
                    </time>
                  </div>
                  <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                    {(e.usuario_nome || e.usuario_email) && (
                      <Avatar nome={e.usuario_nome} email={e.usuario_email} foto={e.usuario_foto} tamanho={18} />
                    )}
                    <span>
                      {quem(e)}
                      {e.status === "sucesso" && (
                        <>
                          {", "}
                          {e.linhas?.toLocaleString("pt-BR")} linhas, {tamanho(e.tamanho_bytes)}, {duracao(segundos(e))}
                        </>
                      )}
                      {e.memoria_pico_bytes != null && `, ${tamanho(e.memoria_pico_bytes)} de memória`}
                    </span>
                  </p>
                  {e.erro && <pre className="erro-bloco">{e.erro}</pre>}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}

function Metrica({ rotulo, valor, dica }: { rotulo: string; valor: string; dica?: React.ReactNode }) {
  return (
    <div className="metrica border-border p-5">
      <dt className="text-xs text-muted-foreground">{rotulo}</dt>
      <dd className="mt-1.5 font-sora text-[22px] font-semibold tracking-[-0.02em] tabular-nums">{valor}</dd>
      {dica && <div className="mt-1 text-xs text-muted-foreground">{dica}</div>}
    </div>
  );
}

/** Barra fina mostrando quanto cada etapa pesou no tempo total. */
function Etapas({ e }: { e: Execucao }) {
  const partes = [
    { nome: "extração", s: Number(e.seg_extracao ?? 0), cor: "#0a7ca6" },
    { nome: "QVD", s: Number(e.seg_geracao ?? 0), cor: "#2cc3df" },
    { nome: "upload", s: Number(e.seg_upload ?? 0), cor: "#7c83db" },
  ];
  const total = partes.reduce((t, p) => t + p.s, 0) || 1;
  return (
    <div title={partes.map((p) => `${p.nome}: ${duracao(p.s)}`).join(", ")}>
      <div className="mt-1 flex h-1.5 gap-[2px] overflow-hidden rounded-full bg-secondary" aria-hidden="true">
        {partes.map((p) => (
          <span key={p.nome} style={{ width: `${(p.s / total) * 100}%`, background: p.cor }} />
        ))}
      </div>
      <span className="mt-1 block">
        {partes.map((p) => `${p.nome} ${duracao(p.s)}`).join(", ")}
      </span>
    </div>
  );
}

function BlocoCodigo({ codigo }: { codigo: string }) {
  const [copiado, setCopiado] = useState(false);
  async function copiar() {
    try {
      await navigator.clipboard.writeText(codigo);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1600);
    } catch {
      /* sem permissão de clipboard: ignora */
    }
  }
  return (
    <div className="bloco-codigo group relative">
      <button onClick={copiar} className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-[#F2F1EC]/80 hover:text-[#F2F1EC]">
        {copiado ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        {copiado ? "Copiado" : "Copiar"}
      </button>
      <pre>
        <code>{codigo}</code>
      </pre>
    </div>
  );
}

const FORMATO_PROXIMA = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit" });

function Agendamento({ api, carga, admin, aoAlterar }: { api: Api; carga: Carga; admin: boolean; aoAlterar: (c: Carga) => void }) {
  const [editando, setEditando] = useState(false);
  const [agenda, setAgenda] = useState(() => deCron(carga.agendamento));
  const [valido, setValido] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function salvar(dados: { agendamento?: string | null; ativo?: boolean; query?: string }) {
    setSalvando(true);
    setErro(null);
    try {
      aoAlterar(await api.alterarCarga(carga.id, dados));
      setEditando(false);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="cartao-agenda">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-3">
          <span className="icone-carga">
            <CalendarClock className="h-4 w-4 text-primary" />
          </span>
          <div>
            <h2 className="font-sora text-sm font-semibold">{descrever(carga.agendamento)}</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {!carga.ativo
                ? "Carga inativa: não roda pelo agendamento nem pelo botão."
                : carga.agendamento && carga.proxima_execucao
                  ? `Próxima: ${FORMATO_PROXIMA.format(new Date(carga.proxima_execucao))}`
                  : "Roda só quando alguém executar."}
            </p>
          </div>
        </div>
        {admin && !editando && (
          <div className="flex shrink-0 gap-2">
            <button className="btn-secundario inline-flex items-center gap-1.5" onClick={() => setEditando(true)}>
              <Pencil className="h-3.5 w-3.5" />
              Alterar
            </button>
            <button className="btn-secundario" onClick={() => salvar({ ativo: !carga.ativo })} disabled={salvando}>
              {carga.ativo ? "Desativar" : "Ativar"}
            </button>
          </div>
        )}
      </div>

      {editando && (
        <div className="mt-5 border-t border-border pt-5">
          <AgendamentoEditor api={api} valor={agenda} aoMudar={setAgenda} aoValidar={(p) => setValido(p !== null)} />
          <div className="mt-5 flex justify-end gap-3">
            <button
              className="btn-secundario"
              onClick={() => {
                setAgenda(deCron(carga.agendamento));
                setEditando(false);
              }}
            >
              Cancelar
            </button>
            <button className="btn-primario" disabled={!valido || salvando} onClick={() => salvar({ agendamento: paraCron(agenda) })}>
              {salvando ? "Salvando…" : "Salvar agendamento"}
            </button>
          </div>
        </div>
      )}
      {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}
    </div>
  );
}

function Consulta({
  api,
  carga,
  admin,
  emAndamento,
  aoAlterar,
}: {
  api: Api;
  carga: Carga;
  admin: boolean;
  emAndamento: boolean;
  aoAlterar: (c: Carga) => void;
}) {
  const [editando, setEditando] = useState(false);
  const [texto, setTexto] = useState(carga.query);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const mudou = texto.trim() !== carga.query.trim();

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      aoAlterar(await api.alterarCarga(carga.id, { query: texto }));
      setEditando(false);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <>
      <div className="mb-3 mt-8 flex items-center justify-between gap-3">
        <h2 className="font-sora text-sm font-semibold">Consulta</h2>
        {admin && !editando && (
          <button
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
            onClick={() => {
              setTexto(carga.query);
              setEditando(true);
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
            Editar consulta
          </button>
        )}
      </div>

      {editando ? (
        <div className="flex flex-col gap-3">
          <label htmlFor="editar-consulta" className="sr-only">
            Consulta
          </label>
          <textarea
            id="editar-consulta"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            rows={Math.min(Math.max(texto.split("\n").length + 1, 8), 24)}
            spellCheck={false}
            autoFocus
            className="campo campo-codigo resize-y"
          />
          <p className="text-xs text-muted-foreground">
            {emAndamento
              ? "Há uma execução em andamento: ela termina com a consulta atual. A nova vale a partir da próxima."
              : "A nova consulta vale a partir da próxima execução. Confira se as colunas continuam as que os apps usam."}
          </p>
          {erro && <p className="text-sm text-destructive">{erro}</p>}
          <div className="flex justify-end gap-3">
            <button className="btn-secundario" onClick={() => setEditando(false)}>
              Cancelar
            </button>
            <button className="btn-primario" disabled={!mudou || !texto.trim() || salvando} onClick={salvar}>
              {salvando ? "Salvando…" : "Salvar consulta"}
            </button>
          </div>
        </div>
      ) : (
        <BlocoCodigo codigo={carga.query} />
      )}
    </>
  );
}

/** "Lê de <fonte>" no cabeçalho; admin troca a fonte ali mesmo. Vale a partir da próxima execução. */
function FonteDaCarga({
  api,
  carga,
  podeEditar,
  aoAlterar,
}: {
  api: Api;
  carga: Carga;
  podeEditar: boolean;
  aoAlterar: (c: Carga) => void;
}) {
  const [fontes, setFontes] = useState<Fonte[] | null>(null);
  const [editando, setEditando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  function abrir() {
    setErro(null);
    setEditando(true);
    if (!fontes) api.fontes().then(setFontes).catch((e: Error) => setErro(e.message));
  }

  async function trocar(valor: string) {
    const fonte_id = valor ? Number(valor) : null;
    if (fonte_id === (carga.fonte_padrao ? null : carga.fonte_id)) return setEditando(false);
    setSalvando(true);
    setErro(null);
    try {
      aoAlterar(await api.alterarCarga(carga.id, { fonte_id }));
      setEditando(false);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  if (editando) {
    const padrao = fontes?.find((f) => f.padrao);
    return (
      <span className="inline-flex flex-wrap items-center gap-2 align-middle">
        Lê de
        <select
          autoFocus
          aria-label="Fonte de dados da carga"
          className="campo campo-pequeno w-auto min-w-[220px]"
          disabled={!fontes || salvando}
          value={carga.fonte_padrao ? "" : String(carga.fonte_id ?? "")}
          onChange={(e) => trocar(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setEditando(false)}
        >
          {!fontes ? (
            <option>Carregando…</option>
          ) : (
            <>
              <option value="">{padrao ? `Fonte padrão (${padrao.nome})` : "Conexão do servidor (padrão)"}</option>
              {fontes.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.nome} · {f.banco}
                </option>
              ))}
            </>
          )}
        </select>
        <button type="button" className="text-xs hover:text-foreground" onClick={() => setEditando(false)} disabled={salvando}>
          {salvando ? "Salvando…" : "Cancelar"}
        </button>
        {erro && <span className="text-xs text-destructive">{erro}</span>}
        {!erro && !salvando && <span className="text-xs">Vale a partir da próxima execução.</span>}
      </span>
    );
  }

  return (
    <>
      Lê de <span className="text-foreground">{carga.fonte_nome ?? "conexão do servidor"}</span>
      {carga.fonte_padrao && carga.fonte_nome && <span className="text-xs"> (padrão)</span>}
      {podeEditar && (
        <button
          type="button"
          onClick={abrir}
          title="Trocar a fonte de dados"
          aria-label="Trocar a fonte de dados"
          className="ml-1 inline-flex size-5 items-center justify-center rounded align-[-3px] text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Pencil className="size-3" />
        </button>
      )}
    </>
  );
}
