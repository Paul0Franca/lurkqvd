// Configurações > Fontes de dados: bancos de onde as cargas leem. A senha vai para os segredos (Configurações › Segredos).

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Database, Eye, EyeOff, Pencil, Plus, RefreshCw, Star, Trash2, XCircle } from "lucide-react";
import type { Api, Fonte, FonteDados, TesteFonte, TipoBanco } from "../api";
import { dataHora, relativo } from "../lib/formato";

const NOMES_MOTOR: Record<string, string> = {
  odbc: "ODBC",
  "arrow-odbc": "arrow-odbc (ODBC direto para Arrow)",
  connectorx: "connectorx (experimental)",
  psycopg: "psycopg",
};

export default function FontesDados({ api }: { api: Api }) {
  const [fontes, setFontes] = useState<Fonte[] | null>(null);
  const [tipos, setTipos] = useState<TipoBanco[]>([]);
  const [editando, setEditando] = useState<number | "nova" | null>(null);
  const [testando, setTestando] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api.fontes().then(setFontes).catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(() => {
    carregar();
    api.tiposBanco().then(setTipos).catch(() => {});
  }, [api, carregar]);

  async function acao(f: () => Promise<unknown>) {
    setErro(null);
    try {
      await f();
      carregar();
    } catch (e) {
      setErro((e as Error).message);
    }
  }

  async function testar(id: number) {
    setTestando(id);
    await acao(() => api.testarFonteSalva(id));
    setTestando(null);
  }

  if (!fontes) return <p className="vazio">{erro ?? "Carregando…"}</p>;
  const nomeTipo = (t: string) => tipos.find((x) => x.tipo === t)?.nome ?? t;
  const motorDe = (f: Fonte) => String(f.opcoes.motor ?? tipos.find((x) => x.tipo === f.tipo)?.motores?.[0] ?? "odbc");
  const betaTipo = (t: string) => Boolean(tipos.find((x) => x.tipo === t)?.beta);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-[560px] text-sm text-muted-foreground">
          Bancos de onde as cargas leem. Cada carga escolhe a sua; as que não escolhem usam a <strong className="font-medium text-foreground">fonte padrão</strong>.
        </p>
        {editando !== "nova" && (
          <button type="button" className="btn-primario inline-flex items-center gap-2" onClick={() => setEditando("nova")}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Nova fonte
          </button>
        )}
      </div>

      {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}

      {editando === "nova" && (
        <FormFonte
          api={api}
          tipos={tipos}
          primeira={fontes.length === 0}
          aoCancelar={() => setEditando(null)}
          aoSalvar={() => {
            setEditando(null);
            carregar();
          }}
        />
      )}

      {fontes.length === 0 && editando !== "nova" && (
        <div className="aviso-legado">
          <Database className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium">Nenhuma fonte cadastrada ainda.</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              As cargas leem do banco cadastrado aqui. Cadastre o banco de origem e marque como padrão: as cargas sem fonte própria usam a padrão. Dica: use um usuário só de leitura.
            </p>
          </div>
        </div>
      )}

      {fontes.length > 0 && (
        <ul className="flex flex-col gap-3">
          {fontes.map((f) =>
            editando === f.id ? (
              <li key={f.id}>
                <FormFonte
                  api={api}
                  tipos={tipos}
                  fonte={f}
                  aoCancelar={() => setEditando(null)}
                  aoSalvar={() => {
                    setEditando(null);
                    carregar();
                  }}
                />
              </li>
            ) : (
              <li key={f.id} className={`cartao-fonte ${f.padrao ? "cartao-fonte-padrao" : ""}`}>
                <div className="flex flex-wrap items-start gap-4">
                  <span className="icone-carga">
                    <Database className="h-4 w-4 text-primary" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="font-sora text-[15px] font-semibold">{f.nome}</span>
                      {f.padrao && (
                        <span className="selo-padrao">
                          <Star className="h-3 w-3" fill="currentColor" aria-hidden="true" />
                          padrão
                        </span>
                      )}
                      <span className="tag !ml-0">{nomeTipo(f.tipo)}</span>
                      {betaTipo(f.tipo) && <span className="tag !ml-0">beta</span>}
                      <span className="tag !ml-0">{motorDe(f)}</span>
                    </p>
                    <p className="mt-1 truncate font-mono text-[12.5px] text-muted-foreground">
                      {f.host}:{f.porta} / <span className="text-foreground">{f.banco}</span> · {f.usuario}
                    </p>
                    <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <StatusTeste teste={f.ultimo_teste} />
                      <span>{f.qtd_cargas === 1 ? "1 carga" : `${f.qtd_cargas} cargas`}</span>
                    </p>
                    {f.ultimo_teste && !f.ultimo_teste.ok && f.ultimo_teste.erro && <p className="mt-1 text-xs text-muted-foreground">{f.ultimo_teste.erro}</p>}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    <button type="button" className="botao-icone" title="Testar conexão" aria-label={`Testar ${f.nome}`} disabled={testando === f.id} onClick={() => testar(f.id)}>
                      <RefreshCw className={`h-4 w-4 ${testando === f.id ? "animate-spin" : ""}`} />
                    </button>
                    <button type="button" className="botao-icone" title="Editar" aria-label={`Editar ${f.nome}`} onClick={() => setEditando(f.id)}>
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      className="botao-icone botao-icone-perigo"
                      title={f.qtd_cargas > 0 ? "Há cargas usando esta fonte" : "Remover"}
                      aria-label={`Remover ${f.nome}`}
                      disabled={f.qtd_cargas > 0}
                      onClick={() => confirm(`Remover a fonte “${f.nome}”?`) && acao(() => api.removerFonte(f.id))}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    {!f.padrao && (
                      <button type="button" className="btn-secundario ml-1" onClick={() => acao(() => api.definirFontePadrao(f.id))}>
                        Tornar padrão
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function StatusTeste({ teste }: { teste: TesteFonte | null }) {
  if (!teste) return <span>nunca testada</span>;
  return (
    <span className={`inline-flex items-center gap-1.5 ${teste.ok ? "text-[var(--lq-ok-fg)]" : "text-destructive"}`} title={teste.testado_em ? dataHora(teste.testado_em) : undefined}>
      {teste.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
      {teste.ok ? "conectou" : "falhou"}
      {teste.testado_em && ` ${relativo(teste.testado_em)}`}
      {teste.ok && teste.latencia_ms != null && <span className="text-muted-foreground">· {teste.latencia_ms} ms</span>}
    </span>
  );
}

/** Formulário de nova fonte / edição. Testa antes; só salva o que foi testado. */
function FormFonte({
  api,
  tipos,
  fonte,
  primeira,
  aoCancelar,
  aoSalvar,
}: {
  api: Api;
  tipos: TipoBanco[];
  fonte?: Fonte;
  primeira?: boolean;
  aoCancelar: () => void;
  aoSalvar: () => void;
}) {
  const [dados, setDados] = useState<FonteDados>(() =>
    fonte
      ? { nome: fonte.nome, tipo: fonte.tipo, host: fonte.host, porta: fonte.porta, banco: fonte.banco, usuario: fonte.usuario, opcoes: { ...fonte.opcoes } }
      : { nome: "", tipo: "mssql", host: "", porta: 1433, banco: "", usuario: "", opcoes: { encrypt: true, trust_cert: true } },
  );
  const [senha, setSenha] = useState("");
  const [verSenha, setVerSenha] = useState(false);
  const [padrao, setPadrao] = useState(Boolean(primeira));
  const [teste, setTeste] = useState<{ assinatura: string; r: TesteFonte } | null>(null);
  const [ocupado, setOcupado] = useState<null | "testando" | "salvando">(null);
  const [erro, setErro] = useState<string | null>(null);

  const tipo = tipos.find((t) => t.tipo === dados.tipo);
  const assinatura = JSON.stringify({ ...dados, senha });
  const testeValido = teste?.assinatura === assinatura && teste.r.ok;
  const completo = Boolean(dados.nome.trim() && dados.host.trim() && dados.porta && dados.banco.trim() && dados.usuario.trim() && (fonte || senha));

  function mudar<K extends keyof FonteDados>(campo: K, valor: FonteDados[K]) {
    setDados((d) => ({ ...d, [campo]: valor }));
  }

  async function testar() {
    setOcupado("testando");
    setErro(null);
    try {
      const r = await api.testarFonte({ ...dados, senha: senha || undefined, fonte_id: fonte && !senha ? fonte.id : undefined });
      setTeste({ assinatura, r });
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
      if (fonte) await api.alterarFonte(fonte.id, { ...dados, senha: senha || undefined });
      else await api.criarFonte({ ...dados, senha, padrao });
      aoSalvar();
    } catch (e) {
      setErro((e as Error).message);
      setOcupado(null);
    }
  }

  return (
    <div className="form-fonte">
      <h3 className="font-sora text-[15px] font-semibold">{fonte ? `Editar ${fonte.nome}` : "Nova fonte"}</h3>

      {/* tipo de banco */}
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Tipo de banco">
        {tipos.map((t) => (
          <button
            key={t.tipo}
            type="button"
            role="radio"
            aria-checked={dados.tipo === t.tipo}
            disabled={!t.suportado}
            className="tile-tipo"
            onClick={() => {
              // o motor só acompanha a troca se o novo tipo também tiver esse motor
              const motor = t.motores?.includes(String(dados.opcoes.motor)) ? dados.opcoes.motor : undefined;
              const opcoes: Record<string, unknown> = { ...Object.fromEntries(t.opcoes.map((o) => [o.chave, o.padrao])), ...(motor ? { motor } : {}) };
              setDados((d) => ({ ...d, tipo: t.tipo, porta: d.porta === tipo?.porta ? t.porta : d.porta, opcoes }));
            }}
          >
            <Database className="h-4 w-4" aria-hidden="true" />
            <span className="font-medium">{t.nome}</span>
            {!t.suportado && <span className="text-[10.5px] text-muted-foreground">em breve</span>}
            {t.suportado && t.beta && <span className="text-[10.5px] text-muted-foreground">beta</span>}
          </button>
        ))}
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-6">
        <Campo rotulo="Nome" classe="sm:col-span-6" ajuda="Como a fonte aparece nas cargas, ex.: DW produção">
          <input className="campo campo-pequeno" value={dados.nome} onChange={(e) => mudar("nome", e.target.value)} maxLength={80} />
        </Campo>
        <Campo rotulo="Host" classe="sm:col-span-4">
          <input className="campo campo-pequeno font-mono" value={dados.host} onChange={(e) => mudar("host", e.target.value.trim())} placeholder="10.0.0.5 ou servidor.empresa.local" spellCheck={false} />
        </Campo>
        <Campo rotulo="Porta" classe="sm:col-span-2">
          <input className="campo campo-pequeno tabular-nums" type="number" min={1} max={65535} value={dados.porta} onChange={(e) => mudar("porta", Number(e.target.value))} />
        </Campo>
        <Campo rotulo="Banco" classe="sm:col-span-2">
          <input className="campo campo-pequeno font-mono" value={dados.banco} onChange={(e) => mudar("banco", e.target.value)} placeholder="DW" spellCheck={false} />
        </Campo>
        <Campo rotulo="Usuário" classe="sm:col-span-2">
          <input className="campo campo-pequeno font-mono" value={dados.usuario} onChange={(e) => mudar("usuario", e.target.value)} autoComplete="off" spellCheck={false} />
        </Campo>
        <Campo rotulo="Senha" classe="sm:col-span-2">
          <div className="relative">
            <input
              className="campo campo-pequeno pr-9"
              type={verSenha ? "text" : "password"}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              placeholder={fonte ? "manter a atual" : ""}
              autoComplete="new-password"
            />
            <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label={verSenha ? "Esconder senha" : "Mostrar senha"} onClick={() => setVerSenha((v) => !v)}>
              {verSenha ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </Campo>
      </div>

      {tipo && tipo.opcoes.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
          {tipo.opcoes.map((o) => (
            <label key={o.chave} className="inline-flex cursor-pointer items-center gap-2 text-sm">
              <input type="checkbox" className="accent-[var(--lq-accent)]" checked={Boolean(dados.opcoes[o.chave] ?? o.padrao)} onChange={(e) => mudar("opcoes", { ...dados.opcoes, [o.chave]: e.target.checked })} />
              {o.rotulo}
            </label>
          ))}
        </div>
      )}
      {tipo?.motores && tipo.motores.length > 1 && (
        <label className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-xs font-medium">Motor de leitura</span>
          <select
            className="campo campo-pequeno w-auto"
            value={String(dados.opcoes.motor ?? tipo.motores[0])}
            onChange={(e) => mudar("opcoes", { ...dados.opcoes, motor: e.target.value })}
          >
            {tipo.motores.map((m, i) => (
              <option key={m} value={m}>
                {(NOMES_MOTOR[m] ?? m) + (i === 0 ? " (padrão)" : "")}
              </option>
            ))}
          </select>
          <span className="text-[11px] text-muted-foreground">
            Se o motor escolhido falhar numa consulta, a leitura cai para o {NOMES_MOTOR[tipo.motores[0]] ?? tipo.motores[0]} sozinha.
          </span>
        </label>
      )}
      {!fonte && (
        <label className="mt-3 inline-flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" className="accent-[var(--lq-accent)]" checked={padrao} onChange={(e) => setPadrao(e.target.checked)} />
          Usar como fonte padrão
          <span className="text-xs text-muted-foreground">(cargas sem fonte escolhida passam a ler daqui)</span>
        </label>
      )}

      {teste && teste.assinatura === assinatura && (
        <div className={`resultado-teste ${teste.r.ok ? "resultado-ok" : "resultado-erro"}`} role="status">
          {teste.r.ok ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <XCircle className="h-4 w-4 shrink-0" />}
          <p className="min-w-0 flex-1">
            {teste.r.ok ? (
              <>
                Conectou em {teste.r.latencia_ms} ms{teste.r.banco_conectado && <> no banco <strong>{teste.r.banco_conectado}</strong></>}.
                {teste.r.versao && <span className="mt-0.5 block text-xs opacity-80">{teste.r.versao}</span>}
              </>
            ) : (
              teste.r.erro
            )}
          </p>
        </div>
      )}
      {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}

      <div className="mt-5 flex flex-wrap items-center justify-end gap-2">
        <p className="mr-auto text-xs text-muted-foreground">A senha é guardada à parte, nos segredos do LurkQVD.</p>
        <button type="button" className="btn-secundario" onClick={aoCancelar}>
          Cancelar
        </button>
        <button type="button" className="btn-secundario" disabled={!completo || ocupado !== null} onClick={testar}>
          {ocupado === "testando" ? "Testando…" : "Testar conexão"}
        </button>
        <button type="button" className="btn-primario" disabled={!testeValido || ocupado !== null} title={!testeValido ? "Teste a conexão antes de salvar" : undefined} onClick={salvar}>
          {ocupado === "salvando" ? "Salvando…" : fonte ? "Salvar alterações" : "Salvar fonte"}
        </button>
      </div>
    </div>
  );
}

function Campo({ rotulo, classe, ajuda, children }: { rotulo: string; classe?: string; ajuda?: string; children: React.ReactNode }) {
  return (
    <label className={`flex flex-col gap-1 ${classe ?? ""}`}>
      <span className="text-xs font-medium">{rotulo}</span>
      {children}
      {ajuda && <span className="text-[11px] text-muted-foreground">{ajuda}</span>}
    </label>
  );
}
