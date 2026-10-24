// Configurações > Qlik Cloud: conexão, vencimento da API key e troca da key/tenant.
// A key nunca volta do servidor: a tela só mostra o final dela.

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Eye, EyeOff, KeyRound, Loader2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import type { Api, ConfigQlik, TesteQlik } from "../api";
import { dataHora, relativo } from "../lib/formato";
import { diasAte, nivel, textoDias } from "../lib/vencimento";

const dataCurta = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "long", year: "numeric" });

export default function QlikCloud({ api }: { api: Api }) {
  const [cfg, setCfg] = useState<ConfigQlik | null>(null);
  const [testando, setTestando] = useState(true); // já abre testando
  const [editando, setEditando] = useState<null | "token" | "tenant">(null);
  const [erro, setErro] = useState<string | null>(null);

  const rodarTeste = useCallback(() => {
    api
      .configQlik(true)
      .then((c) => {
        setCfg(c);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message))
      .finally(() => setTestando(false));
  }, [api]);

  // ao abrir: mostra o que está guardado e já testa de novo em segundo plano
  useEffect(() => {
    api.configQlik().then(setCfg).catch((e: Error) => setErro(e.message));
    rodarTeste();
  }, [api, rodarTeste]);

  function testarAgora() {
    setTestando(true);
    rodarTeste();
  }

  if (!cfg) return <p className="vazio">{erro ?? "Carregando…"}</p>;
  const st = cfg.status;

  return (
    <div className="flex flex-col gap-8">
      {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}

      {/* ---------- conexão ---------- */}
      <section className={`cartao-worker ${st?.ok === false ? "cartao-worker-parado" : ""}`} aria-live="polite">
        <div className="flex flex-wrap items-start gap-4">
          {testando && !st ? (
            <Loader2 className="mt-0.5 h-5 w-5 animate-spin text-muted-foreground" />
          ) : st?.ok ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-[var(--lq-ok-fg)]" />
          ) : (
            <XCircle className="mt-0.5 h-5 w-5 text-destructive" />
          )}
          <div className="min-w-0 flex-1">
            <h3 className="font-sora text-base font-semibold">{!st ? "Testando a conexão…" : st.ok ? "Conectado à Qlik Cloud" : "Sem conexão com a Qlik Cloud"}</h3>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {st?.ok ? (
                <>
                  Como <span className="text-foreground">{st.dono_nome ?? "—"}</span>
                  {st.dono_email && ` (${st.dono_email})`} em <span className="font-mono text-[13px] text-foreground">{cfg.tenant}.qlikcloud.com</span>
                  {st.latencia_ms != null && `, ${st.latencia_ms} ms`}
                </>
              ) : (
                st?.erro ?? "Aguardando o teste."
              )}
            </p>
            {st?.verificado_em && (
              <p className="mt-1 text-xs text-muted-foreground" title={dataHora(st.verificado_em)}>
                Testado {relativo(st.verificado_em)}. O worker testa de novo a cada 6 horas.
              </p>
            )}
          </div>
          <button type="button" className="btn-secundario inline-flex items-center gap-2" disabled={testando} onClick={testarAgora}>
            <RefreshCw className={`h-4 w-4 ${testando ? "animate-spin" : ""}`} aria-hidden="true" />
            {testando ? "Testando…" : "Testar agora"}
          </button>
        </div>
      </section>

      {/* ---------- API key ---------- */}
      <section aria-labelledby="titulo-key">
        <h3 id="titulo-key" className="mb-3 text-sm font-semibold">
          API key
        </h3>
        <div className="overflow-hidden rounded-2xl border border-border">
          <div className="flex flex-wrap items-center gap-4 p-4">
            <span className="icone-carga">
              <KeyRound className="h-4 w-4 text-primary" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-mono text-[13px] font-semibold">{st?.token_mascara ?? "••••"}</p>
              <p className="truncate text-xs text-muted-foreground">
                {st?.chave_descricao ? `“${st.chave_descricao}”` : "Sem descrição"}
                {st?.chave_id && <> · id {st.chave_id.slice(0, 8)}…</>}
              </p>
            </div>
            {st?.token_mascara && <Vencimento expiraEm={st.expira_em ?? null} />}
            {editando !== "token" && (
              <button type="button" className="btn-secundario" disabled={!cfg.tenant} title={cfg.tenant ? undefined : "Informe o tenant primeiro"} onClick={() => setEditando("token")}>
                {st?.token_mascara ? "Substituir" : "Adicionar"}
              </button>
            )}
          </div>
          {editando === "token" && (
            <Editor
              api={api}
              tipo="token"
              tenant={cfg.tenant}
              aoCancelar={() => setEditando(null)}
              aoSalvar={(c) => {
                setCfg(c);
                setEditando(null);
              }}
            />
          )}
          <div className="flex items-center gap-2 border-t border-border bg-[color-mix(in_oklab,var(--lq-bg)_55%,var(--lq-surface))] px-4 py-2.5 text-xs text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>
              Guardada criptografada nos segredos do LurkQVD (<span className="font-mono text-foreground">{cfg.secret}</span>). O LurkQVD nunca mostra a key.
            </span>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          As API keys da Qlik vencem. Gere uma nova na Qlik Cloud (Perfil › Configurações › API keys) antes do vencimento e substitua aqui: a API e o worker passam a usar a nova sozinhos, sem reiniciar.
        </p>
      </section>

      {/* ---------- tenant ---------- */}
      <section aria-labelledby="titulo-tenant" className="border-t border-border pt-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 id="titulo-tenant" className="text-sm font-semibold">
              Tenant
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Endereço da Qlik Cloud da empresa.
              {cfg.alterado_em && ` Alterado ${relativo(cfg.alterado_em)}${cfg.alterado_por ? ` por ${cfg.alterado_por.split(" ")[0]}` : ""}.`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {cfg.tenant ? (
              <span className="font-mono text-[13px]">
                https://<span className="font-semibold">{cfg.tenant}</span>.qlikcloud.com
              </span>
            ) : (
              <span className="text-[13px] text-muted-foreground">não configurado: comece por aqui</span>
            )}
            {editando !== "tenant" && (
              <button type="button" className={cfg.tenant ? "btn-secundario" : "btn-primario"} onClick={() => setEditando("tenant")}>
                {cfg.tenant ? "Alterar" : "Informar tenant"}
              </button>
            )}
          </div>
        </div>
        {editando === "tenant" && (
          <div className="mt-4 overflow-hidden rounded-2xl border border-border">
            <Editor
              api={api}
              tipo="tenant"
              tenant={cfg.tenant}
              semKey={!st?.token_mascara}
              aoCancelar={() => setEditando(null)}
              aoSalvar={(c) => {
                setCfg(c);
                setEditando(null);
              }}
            />
          </div>
        )}
      </section>
    </div>
  );
}

function Vencimento({ expiraEm }: { expiraEm: string | null }) {
  if (!expiraEm) return <span className="vencimento vencimento-ok">sem vencimento informado</span>;
  const dias = diasAte(expiraEm);
  return (
    <span className={`vencimento vencimento-${nivel(dias)}`} title={dataHora(expiraEm)}>
      {textoDias(dias)}
      <span className="font-normal opacity-80"> · {dataCurta.format(new Date(expiraEm))}</span>
    </span>
  );
}

/** Formulário de troca: testa primeiro, só libera o Salvar com o teste ok. */
function Editor({
  api,
  tipo,
  tenant,
  semKey = false,
  aoCancelar,
  aoSalvar,
}: {
  api: Api;
  tipo: "token" | "tenant";
  tenant: string;
  /** instalação nova: ainda sem API key, o tenant é salvo sem teste (é testado junto com a key) */
  semKey?: boolean;
  aoCancelar: () => void;
  aoSalvar: (c: ConfigQlik) => void;
}) {
  const [valor, setValor] = useState(tipo === "tenant" ? tenant : "");
  const [visivel, setVisivel] = useState(false);
  const [teste, setTeste] = useState<TesteQlik | null>(null);
  const [ocupado, setOcupado] = useState<null | "testando" | "salvando">(null);
  const [erro, setErro] = useState<string | null>(null);

  // aceita colar a URL inteira do tenant
  const limpo = tipo === "tenant" ? valor.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\.qlikcloud\.com.*$/, "").replace(/\/.*$/, "") : valor.trim();
  const dados = tipo === "token" ? { token: limpo } : { tenant: limpo };
  const podeTestar = tipo === "token" ? limpo.length >= 20 : /^[a-z0-9-]+(\.[a-z0-9-]+)*$/.test(limpo) && limpo !== tenant;
  const semTeste = tipo === "tenant" && semKey; // não há key para testar com o tenant

  async function testar() {
    setOcupado("testando");
    setErro(null);
    setTeste(null);
    try {
      setTeste(await api.testarQlik(dados));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(null);
    }
  }

  async function salvar() {
    setOcupado("salvando");
    setErro(null);
    try {
      aoSalvar(await api.salvarQlik(dados));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(null);
    }
  }

  return (
    <div className="editor-qlik">
      <label htmlFor={`editor-${tipo}`} className="text-xs font-medium">
        {tipo === "token" ? "Nova API key" : "Novo tenant"}
      </label>
      <div className="mt-1.5 flex flex-wrap gap-2">
        <div className="relative min-w-[240px] flex-1">
          <input
            id={`editor-${tipo}`}
            className={`campo campo-pequeno ${tipo === "token" ? "pr-9 font-mono" : ""}`}
            type={tipo === "token" && !visivel ? "password" : "text"}
            autoComplete="off"
            spellCheck={false}
            placeholder={tipo === "token" ? "Cole aqui a key gerada na Qlik Cloud (eyJ…)" : "ex.: minha-empresa.us"}
            value={valor}
            autoFocus
            onChange={(e) => {
              setValor(e.target.value);
              setTeste(null);
            }}
          />
          {tipo === "token" && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={visivel ? "Esconder key" : "Mostrar key"}
              onClick={() => setVisivel((v) => !v)}
            >
              {visivel ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          )}
        </div>
        {!semTeste && (
          <button type="button" className="btn-secundario" disabled={!podeTestar || ocupado !== null} onClick={testar}>
            {ocupado === "testando" ? "Testando…" : "Testar"}
          </button>
        )}
      </div>
      {tipo === "tenant" && limpo && limpo !== valor.trim() && <p className="mt-1.5 text-xs text-muted-foreground">Vai ser usado: {limpo}</p>}
      {semTeste && <p className="mt-1.5 text-xs text-muted-foreground">Ainda não há API key: o tenant é salvo agora e testado junto com a key.</p>}

      {teste && (
        <div className={`resultado-teste ${teste.ok ? "resultado-ok" : "resultado-erro"}`} role="status">
          {teste.ok ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <XCircle className="h-4 w-4 shrink-0" />}
          <p className="min-w-0 flex-1">
            {teste.ok ? (
              <>
                Funciona. Conecta como <strong>{teste.dono_nome ?? teste.dono_email}</strong>
                {teste.expira_em && <>, {textoDias(diasAte(teste.expira_em))} ({dataCurta.format(new Date(teste.expira_em))})</>}.
              </>
            ) : (
              teste.erro
            )}
          </p>
        </div>
      )}
      {erro && <p className="mt-2 text-sm text-destructive">{erro}</p>}

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn-secundario" onClick={aoCancelar}>
          Cancelar
        </button>
        <button
          type="button"
          className="btn-primario"
          disabled={(semTeste ? !podeTestar : !teste?.ok) || ocupado !== null}
          title={!semTeste && !teste?.ok ? "Teste antes de salvar" : undefined}
          onClick={salvar}
        >
          {ocupado === "salvando" ? "Salvando…" : tipo === "token" ? "Salvar nova key" : "Salvar tenant"}
        </button>
      </div>
    </div>
  );
}
