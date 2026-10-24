import { useEffect, useMemo, useState } from "react";
import type { Api, Aplicacao, Espaco, Fonte } from "../api";
import { AGENDA_PADRAO, type Agenda, descrever, paraCron } from "../lib/agenda";
import { link, navegar } from "../rotas";
import AgendamentoEditor from "./AgendamentoEditor";
import DestinoPicker, { type Destino } from "./DestinoPicker";
import EstimativaQvd from "./EstimativaQvd";
import { Migalhas } from "./comum";

interface Props {
  api: Api;
  connectionIdInicial?: string;
  pastaInicial?: string;
}

const NOME_VALIDO = /^[a-zA-Z0-9_-]+$/;
const FORMATO = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit" });

export default function NovaCargaPagina({ api, connectionIdInicial, pastaInicial = "" }: Props) {
  const [espacos, setEspacos] = useState<Espaco[] | null>(null);
  const [fontes, setFontes] = useState<Fonte[]>([]);
  const [fonteId, setFonteId] = useState(""); // "" = fonte padrão
  const [aplicacoes, setAplicacoes] = useState<Aplicacao[]>([]);
  const [aplicacaoId, setAplicacaoId] = useState(""); // "" = carga solta
  const [destino, setDestino] = useState<Destino | null>(null);
  const [nome, setNome] = useState("");
  const [query, setQuery] = useState("");
  const [agenda, setAgenda] = useState<Agenda>(AGENDA_PADRAO);
  const [proximas, setProximas] = useState<string[] | null>([]);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .espacos()
      .then((lista) => {
        setEspacos(lista);
        const inicial = lista.find((e) => e.connection_id === connectionIdInicial);
        if (inicial) setDestino({ connectionId: inicial.connection_id, pessoal: inicial.tipo === "personal", nomeEspaco: inicial.nome, pasta: pastaInicial });
      })
      .catch((e: Error) => setErro(e.message));
    api.fontes().then(setFontes).catch(() => {});
    api.aplicacoes().then(setAplicacoes).catch(() => {});
  }, [api, connectionIdInicial, pastaInicial]);

  const fontePadrao = fontes.find((f) => f.padrao);
  const aplicacao = aplicacoes.find((a) => String(a.id) === aplicacaoId);
  const nomeFonte = fonteId ? fontes.find((f) => String(f.id) === fonteId)?.nome : fontePadrao ? fontePadrao.nome : "conexão do servidor";

  const caminho = useMemo(() => (destino && nome ? [destino.pasta, `${nome}.qvd`].filter(Boolean).join("/") : ""), [destino, nome]);
  const cron = paraCron(agenda);

  const nomeInvalido = nome !== "" && !NOME_VALIDO.test(nome);
  const pronto = Boolean(destino && nome && !nomeInvalido && query.trim() && proximas !== null);

  async function criar(ev: React.FormEvent) {
    ev.preventDefault();
    if (!pronto || !destino) return;
    setEnviando(true);
    setErro(null);
    try {
      const { id } = await api.criarCarga({
        nome,
        query,
        qlik_path: caminho,
        connection_id: destino.pessoal ? null : destino.connectionId,
        agendamento: cron,
        fonte_id: fonteId ? Number(fonteId) : null,
        aplicacao_id: aplicacao ? aplicacao.id : null,
      });
      navegar({ tela: "carga", id });
    } catch (e) {
      setErro((e as Error).message);
      setEnviando(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <Migalhas itens={[{ rotulo: "Cargas", href: link({ tela: "cargas" }) }, { rotulo: "Nova carga" }]} />
      <h1 className="mt-4 font-sora text-[28px] font-semibold tracking-[-0.02em]">Nova carga</h1>
      <p className="mt-1 text-sm text-muted-foreground">Defina o que extrair, onde publicar o QVD e quando rodar.</p>

      <form onSubmit={criar} className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Etapa numero={1} titulo="Identificação" descricao="O nome também vira o nome do arquivo QVD.">
            <label htmlFor="nome-carga" className="sr-only">
              Nome
            </label>
            <input
              id="nome-carga"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="fct_vendas_item"
              className="campo font-mono"
              aria-invalid={nomeInvalido}
              aria-describedby="ajuda-nome"
              autoComplete="off"
              autoFocus
            />
            <p id="ajuda-nome" className={`mt-1.5 text-xs ${nomeInvalido ? "text-destructive" : "text-muted-foreground"}`}>
              {nomeInvalido ? "Use só letras, números, _ e -, sem espaços." : "Letras, números, _ e -."}
            </p>
          </Etapa>

          <Etapa numero={2} titulo="Consulta" descricao="SELECT executado no banco a cada carga. Traga só as colunas que os apps usam.">
            {fontes.length > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
                <label htmlFor="fonte-carga" className="text-muted-foreground">
                  Ler de
                </label>
                <select id="fonte-carga" className="campo campo-pequeno w-auto min-w-[220px]" value={fonteId} onChange={(e) => setFonteId(e.target.value)}>
                  <option value="">{fontePadrao ? `Fonte padrão (${fontePadrao.nome})` : "Conexão do servidor (padrão)"}</option>
                  {fontes.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.nome} · {f.banco}
                    </option>
                  ))}
                </select>
                {!fonteId && <span className="text-xs text-muted-foreground">Se a fonte padrão mudar, a carga acompanha.</span>}
              </div>
            )}
            <label htmlFor="consulta" className="sr-only">
              Consulta
            </label>
            <textarea
              id="consulta"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={"SELECT *\n  FROM marts.fct_vendas_item"}
              rows={9}
              spellCheck={false}
              className="campo campo-codigo min-h-[200px] resize-y"
            />
            <EstimativaQvd api={api} query={query} fonteId={fonteId ? Number(fonteId) : null} desativado={!query.trim()} />
          </Etapa>

          <Etapa numero={3} titulo="Destino" descricao="Escolha o espaço e navegue até a pasta. As pastas são as mesmas da aba Espaços.">
            {espacos ? (
              <DestinoPicker api={api} espacos={espacos} valor={destino} aoMudar={setDestino} />
            ) : (
              <p className="text-sm text-muted-foreground">Carregando espaços…</p>
            )}
          </Etapa>

          <Etapa numero={4} titulo="Agendamento" descricao="No fuso da instalação. O worker dispara a carga sozinho quando chegar a hora.">
            <AgendamentoEditor api={api} valor={agenda} aoMudar={setAgenda} aoValidar={setProximas} />
          </Etapa>

          <Etapa
            numero={5}
            titulo="Aplicação (opcional)"
            descricao="Inclua a carga numa aplicação para ela rodar junto no “executar tudo”, antes do reload do app. Sem aplicação, ela fica solta e roda pelo próprio agendamento ou manualmente."
          >
            <label htmlFor="aplicacao-carga" className="sr-only">
              Aplicação
            </label>
            <select id="aplicacao-carga" className="campo" value={aplicacaoId} onChange={(e) => setAplicacaoId(e.target.value)}>
              <option value="">Nenhuma (carga solta)</option>
              {aplicacoes.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nome}
                  {a.ativo ? "" : " (inativa)"}
                </option>
              ))}
            </select>
            {aplicacoes.length === 0 && (
              <p className="mt-1.5 text-xs text-muted-foreground">Nenhuma aplicação cadastrada. Dá para incluir a carga depois, arrastando na visão por aplicação.</p>
            )}
          </Etapa>
        </div>

        {/* ---------- resumo fixo ao lado ---------- */}
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <div className="resumo-carga">
            <p className="text-xs text-[#F2F1EC]/55">Resumo</p>
            <p className="mt-2 break-all font-mono text-lg font-semibold text-[#F2F1EC]">{nome || "nome_da_carga"}</p>

            <dl className="mt-5 flex flex-col gap-4 text-sm">
              <div>
                <dt className="text-xs text-[#F2F1EC]/55">Lê de</dt>
                <dd className="mt-1 text-[#F2F1EC]">{nomeFonte}</dd>
              </div>
              <div>
                <dt className="text-xs text-[#F2F1EC]/55">Publica em</dt>
                <dd className="mt-1 text-[#F2F1EC]">
                  {destino ? (
                    <>
                      {destino.nomeEspaco}
                      <span className="block break-all font-mono text-xs text-[#F2F1EC]/70">{caminho || `${destino.pasta ? destino.pasta + "/" : ""}…`}</span>
                    </>
                  ) : (
                    <span className="text-[#F2F1EC]/45">escolha o espaço</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-[#F2F1EC]/55">Quando</dt>
                <dd className="mt-1 text-[#F2F1EC]">{descrever(cron)}</dd>
                {proximas && proximas[0] && <dd className="mt-0.5 text-xs text-[#F2F1EC]/70">próxima: {FORMATO.format(new Date(proximas[0]))}</dd>}
              </div>
              <div>
                <dt className="text-xs text-[#F2F1EC]/55">Aplicação</dt>
                <dd className={`mt-1 ${aplicacao ? "text-[#F2F1EC]" : "text-[#F2F1EC]/45"}`}>{aplicacao ? aplicacao.nome : "nenhuma (solta)"}</dd>
              </div>
            </dl>

            {erro && (
              <p role="alert" className="mt-5 rounded-lg bg-[#f97066]/15 px-3 py-2 text-sm text-[#fda29b]">
                {erro}
              </p>
            )}

            <button type="submit" disabled={!pronto || enviando} className="btn-resumo mt-6 w-full">
              {enviando ? "Criando…" : "Criar carga"}
            </button>
            {!pronto && !enviando && (
              <p className="mt-2 text-center text-xs text-[#F2F1EC]/45">
                {!nome ? "Falta o nome" : nomeInvalido ? "Nome inválido" : !query.trim() ? "Falta a consulta" : !destino ? "Falta o destino" : "Agendamento inválido"}
              </p>
            )}
          </div>
        </aside>
      </form>
    </div>
  );
}

function Etapa({ numero, titulo, descricao, children }: { numero: number; titulo: string; descricao: string; children: React.ReactNode }) {
  return (
    <section className="etapa">
      <div className="flex gap-4">
        <span className="etapa-numero" aria-hidden="true">
          {numero}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-sora text-[15px] font-semibold">{titulo}</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{descricao}</p>
          <div className="mt-4">{children}</div>
        </div>
      </div>
    </section>
  );
}
