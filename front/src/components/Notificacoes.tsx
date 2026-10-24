// Configurações > Notificações: servidor SMTP (senha nos segredos), o que avisar e para quem.
// Os avisos de erro saem do worker; o e-mail de acesso (senha temporária) sai da API ao cadastrar ou redefinir.

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Eye, EyeOff, Mail, MailX, Pencil, Plus, Send, ShieldCheck, Trash2, X, XCircle } from "lucide-react";
import type { Api, ConfigNotificacoes, EnvioEmail, PreferenciasNotificacao, SegurancaSmtp, SmtpDados, TesteSmtp, Usuario } from "../api";
import { dataHora, relativo } from "../lib/formato";

const SEGURANCA: Record<SegurancaSmtp, string> = { starttls: "STARTTLS", ssl: "SSL/TLS", nenhuma: "Sem criptografia" };
const PORTA_PADRAO: Record<SegurancaSmtp, number> = { starttls: 587, ssl: 465, nenhuma: 25 };

/** Atalhos para os servidores mais comuns (só preenchem o formulário). */
const MODELOS: { nome: string; dica: string; dados: Partial<SmtpDados> }[] = [
  { nome: "Google (senha de app)", dica: "Conta do Workspace com verificação em duas etapas e uma senha de app", dados: { host: "smtp.gmail.com", porta: 587, seguranca: "starttls" } },
  { nome: "Google (relay)", dica: "Serviço de relay SMTP do Workspace, liberado pelo IP do servidor (sem usuário)", dados: { host: "smtp-relay.gmail.com", porta: 587, seguranca: "starttls", usuario: "" } },
  { nome: "Microsoft 365", dica: "Caixa com SMTP AUTH habilitado", dados: { host: "smtp.office365.com", porta: 587, seguranca: "starttls" } },
];

const TIPO_ENVIO: Record<string, string> = { acesso: "Acesso", convite: "Convite", falhas: "Execuções", qlik: "Qlik Cloud", teste: "Teste" };

export default function Notificacoes({ api, usuario }: { api: Api; usuario: Usuario }) {
  const [cfg, setCfg] = useState<ConfigNotificacoes | null>(null);
  const [editando, setEditando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [teste, setTeste] = useState<TesteSmtp | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api
      .configNotificacoes()
      .then((c) => {
        setCfg(c);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(carregar, [carregar]);

  async function enviarTeste() {
    setEnviando(true);
    setErro(null);
    try {
      setTeste(await api.enviarTesteSmtp());
      carregar();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setEnviando(false);
    }
  }

  async function remover() {
    if (!confirm("Desligar o envio de e-mails? Convites e avisos deixam de sair até um servidor ser configurado de novo.")) return;
    setErro(null);
    try {
      await api.removerSmtp();
      setTeste(null);
      carregar();
    } catch (e) {
      setErro((e as Error).message);
    }
  }

  if (!cfg) return <p className="vazio">{erro ?? "Carregando…"}</p>;
  const s = cfg.smtp;
  const st = teste ?? cfg.status;

  return (
    <div className="flex flex-col gap-8">
      {erro && (
        <p className="alerta alerta-erro !mb-0 flex items-start justify-between gap-3" role="alert">
          {erro}
          <button type="button" aria-label="Fechar aviso" onClick={() => setErro(null)}>
            <X className="h-4 w-4" />
          </button>
        </p>
      )}

      {/* ---------- servidor ---------- */}
      {editando ? (
        <FormSmtp
          api={api}
          atual={cfg}
          meuEmail={usuario.email}
          aoCancelar={() => setEditando(false)}
          aoSalvar={(c) => {
            setCfg(c);
            setTeste(null);
            setEditando(false);
          }}
        />
      ) : (
        <section className={`cartao-worker ${s && st?.ok === false ? "cartao-worker-parado" : ""}`} aria-live="polite">
          <div className="flex flex-wrap items-start gap-4">
            {s ? (
              st?.ok === false ? <XCircle className="mt-0.5 h-5 w-5 text-destructive" /> : <CheckCircle2 className="mt-0.5 h-5 w-5 text-[var(--lq-ok-fg)]" />
            ) : (
              <MailX className="mt-0.5 h-5 w-5 text-muted-foreground" />
            )}
            <div className="min-w-0 flex-1">
              <h3 className="font-sora text-base font-semibold">{!s ? "E-mails desligados" : st?.ok === false ? "O último envio falhou" : "Enviando e-mails"}</h3>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {s ? (
                  <>
                    Por <span className="font-mono text-[13px] text-foreground">{s.host}:{s.porta}</span> ({SEGURANCA[s.seguranca]}), como{" "}
                    <span className="text-foreground">
                      {s.remetente_nome} &lt;{s.remetente}&gt;
                    </span>
                    {s.usuario ? (
                      <>
                        , autenticando com <span className="font-mono text-[13px] text-foreground">{s.usuario}</span>
                      </>
                    ) : (
                      ", sem autenticação"
                    )}
                    .
                  </>
                ) : (
                  "Configure um servidor SMTP para o LurkQVD mandar a senha temporária de novos usuários e avisar quando uma carga ou aplicação falhar."
                )}
              </p>
              {s && st?.ok === false && st.erro && <p className="mt-1 text-sm text-destructive">{st.erro}</p>}
              {s && st?.testado_em && (
                <p className="mt-1 text-xs text-muted-foreground" title={dataHora(st.testado_em)}>
                  {st.ok ? (st.para ? `E-mail de teste entregue a ${st.para}` : "Conexão testada") : "Testado"} {relativo(st.testado_em)}
                  {st.ok && st.latencia_ms != null && `, ${st.latencia_ms} ms`}.
                </p>
              )}
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-1.5">
              {s && (
                <>
                  <button type="button" className="btn-secundario inline-flex items-center gap-2" disabled={enviando} onClick={enviarTeste} title={`Envia um e-mail de teste para ${usuario.email}`}>
                    <Send className="h-4 w-4" aria-hidden="true" />
                    {enviando ? "Enviando…" : "Enviar teste"}
                  </button>
                  <button type="button" className="botao-icone" title="Editar" aria-label="Editar servidor" onClick={() => setEditando(true)}>
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button type="button" className="botao-icone botao-icone-perigo" title="Desligar e-mails" aria-label="Remover servidor" onClick={remover}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </>
              )}
              {!s && (
                <button type="button" className="btn-primario inline-flex items-center gap-2" onClick={() => setEditando(true)}>
                  <Mail className="h-4 w-4" aria-hidden="true" />
                  Configurar servidor
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      {/* key: depois de salvar (ou recarregar), o formulário recomeça do que está gravado */}
      <Preferencias key={JSON.stringify(cfg.preferencias)} api={api} cfg={cfg} semSmtp={!s} aoSalvar={setCfg} />

      <Historico envios={cfg.historico} />
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Formulário do servidor: testa (enviando um e-mail) antes de salvar      */
/* ---------------------------------------------------------------------- */
function FormSmtp({
  api,
  atual,
  meuEmail,
  aoCancelar,
  aoSalvar,
}: {
  api: Api;
  atual: ConfigNotificacoes;
  meuEmail: string;
  aoCancelar: () => void;
  aoSalvar: (c: ConfigNotificacoes) => void;
}) {
  const salvo = atual.smtp;
  const [dados, setDados] = useState<SmtpDados>(() =>
    salvo
      ? { host: salvo.host, porta: salvo.porta, seguranca: salvo.seguranca, usuario: salvo.usuario, remetente: salvo.remetente, remetente_nome: salvo.remetente_nome }
      : { host: "", porta: 587, seguranca: "starttls", usuario: "", remetente: "", remetente_nome: "LurkQVD" },
  );
  const [senha, setSenha] = useState("");
  const [verSenha, setVerSenha] = useState(false);
  const [para, setPara] = useState(meuEmail);
  const [teste, setTeste] = useState<{ assinatura: string; r: TesteSmtp } | null>(null);
  const [ocupado, setOcupado] = useState<null | "testando" | "salvando">(null);
  const [erro, setErro] = useState<string | null>(null);

  const assinatura = JSON.stringify({ ...dados, senha });
  const testeValido = teste?.assinatura === assinatura && teste.r.ok;
  const temSenhaSalva = Boolean(salvo?.usuario && salvo.senha_mascara);
  const precisaSenha = Boolean(dados.usuario.trim()) && !senha && !temSenhaSalva;
  const completo = Boolean(dados.host.trim() && dados.porta && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(dados.remetente.trim()) && !precisaSenha);

  function mudar<K extends keyof SmtpDados>(campo: K, valor: SmtpDados[K]) {
    setDados((d) => ({ ...d, [campo]: valor }));
  }

  async function testar() {
    setOcupado("testando");
    setErro(null);
    try {
      const r = await api.testarSmtp({ ...dados, senha: senha || undefined, para: para.trim() || undefined });
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
      aoSalvar(await api.salvarSmtp({ ...dados, senha: senha || undefined }));
    } catch (e) {
      setErro((e as Error).message);
      setOcupado(null);
    }
  }

  return (
    <div className="form-fonte">
      <h3 className="font-sora text-[15px] font-semibold">{salvo ? "Editar servidor de e-mail" : "Servidor de e-mail (SMTP)"}</h3>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Preencher para:</span>
        {MODELOS.map((m) => (
          <button
            key={m.nome}
            type="button"
            className="tag !ml-0 cursor-pointer hover:text-foreground"
            title={m.dica}
            onClick={() => setDados((d) => ({ ...d, ...m.dados, usuario: m.dados.usuario ?? d.usuario }))}
          >
            {m.nome}
          </button>
        ))}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-6">
        <Campo rotulo="Servidor" classe="sm:col-span-3">
          <input className="campo campo-pequeno font-mono" value={dados.host} onChange={(e) => mudar("host", e.target.value.trim())} placeholder="smtp.empresa.com.br" spellCheck={false} />
        </Campo>
        <Campo rotulo="Segurança" classe="sm:col-span-2">
          <select
            className="campo campo-pequeno"
            value={dados.seguranca}
            onChange={(e) => {
              const seg = e.target.value as SegurancaSmtp;
              // troca a porta junto, se ela ainda era a padrão da segurança anterior
              setDados((d) => ({ ...d, seguranca: seg, porta: d.porta === PORTA_PADRAO[d.seguranca] ? PORTA_PADRAO[seg] : d.porta }));
            }}
          >
            {(Object.keys(SEGURANCA) as SegurancaSmtp[]).map((k) => (
              <option key={k} value={k}>
                {SEGURANCA[k]}
              </option>
            ))}
          </select>
        </Campo>
        <Campo rotulo="Porta" classe="sm:col-span-1">
          <input className="campo campo-pequeno tabular-nums" type="number" min={1} max={65535} value={dados.porta} onChange={(e) => mudar("porta", Number(e.target.value))} />
        </Campo>
        <Campo rotulo="Usuário" classe="sm:col-span-3" ajuda="Vazio = servidor sem autenticação (relay liberado por IP)">
          <input className="campo campo-pequeno font-mono" value={dados.usuario} onChange={(e) => mudar("usuario", e.target.value.trim())} autoComplete="off" spellCheck={false} placeholder="lurkqvd@empresa.com.br" />
        </Campo>
        <Campo rotulo="Senha" classe="sm:col-span-3" ajuda={dados.usuario ? "No Google e no Microsoft 365, use uma senha de app" : undefined}>
          <div className="relative">
            <input
              className="campo campo-pequeno pr-9"
              type={verSenha ? "text" : "password"}
              value={senha}
              disabled={!dados.usuario}
              onChange={(e) => setSenha(e.target.value)}
              placeholder={!dados.usuario ? "não usa" : temSenhaSalva ? `manter a atual (${salvo?.senha_mascara})` : ""}
              autoComplete="new-password"
            />
            <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label={verSenha ? "Esconder senha" : "Mostrar senha"} onClick={() => setVerSenha((v) => !v)}>
              {verSenha ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </Campo>
        <Campo rotulo="Remetente" classe="sm:col-span-3" ajuda="O servidor precisa aceitar enviar como este endereço">
          <input className="campo campo-pequeno font-mono" type="email" value={dados.remetente} onChange={(e) => mudar("remetente", e.target.value.trim())} placeholder="lurkqvd@empresa.com.br" spellCheck={false} />
        </Campo>
        <Campo rotulo="Nome do remetente" classe="sm:col-span-3">
          <input className="campo campo-pequeno" value={dados.remetente_nome} onChange={(e) => mudar("remetente_nome", e.target.value)} maxLength={80} />
        </Campo>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-border pt-4">
        <Campo rotulo="Enviar o e-mail de teste para" classe="min-w-[220px] flex-1">
          <input className="campo campo-pequeno" type="email" value={para} onChange={(e) => setPara(e.target.value)} />
        </Campo>
        <button type="button" className="btn-secundario inline-flex items-center gap-2" disabled={!completo || ocupado !== null} onClick={testar}>
          <Send className="h-4 w-4" aria-hidden="true" />
          {ocupado === "testando" ? "Enviando…" : "Enviar teste"}
        </button>
      </div>

      {teste && teste.assinatura === assinatura && (
        <div className={`resultado-teste ${teste.r.ok ? "resultado-ok" : "resultado-erro"}`} role="status">
          {teste.r.ok ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <XCircle className="h-4 w-4 shrink-0" />}
          <p className="min-w-0 flex-1">
            {teste.r.ok ? (
              <>
                O servidor aceitou o e-mail para <strong>{teste.r.para}</strong> em {teste.r.latencia_ms} ms. Confira a caixa de entrada (e o spam) antes de salvar.
              </>
            ) : (
              teste.r.erro
            )}
          </p>
        </div>
      )}
      {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}

      <div className="mt-5 flex flex-wrap items-center justify-end gap-2">
        <p className="mr-auto text-xs text-muted-foreground">
          A senha fica criptografada nos segredos do LurkQVD (<span className="font-mono">{atual.secret}</span>).
        </p>
        <button type="button" className="btn-secundario" onClick={aoCancelar}>
          Cancelar
        </button>
        <button type="button" className="btn-primario" disabled={!testeValido || ocupado !== null} title={!testeValido ? "Envie um teste antes de salvar" : undefined} onClick={salvar}>
          {ocupado === "salvando" ? "Salvando…" : "Salvar servidor"}
        </button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* O que avisar e para quem                                                */
/* ---------------------------------------------------------------------- */
const AVISOS: { chave: keyof PreferenciasNotificacao; rotulo: string; ajuda: string }[] = [
  { chave: "erros_cargas", rotulo: "Carga com erro", ajuda: "Inclui as interrompidas porque o worker parou no meio" },
  { chave: "erros_aplicacoes", rotulo: "Aplicação com erro", ajuda: "Carga da aplicação falhou ou o reload na Qlik falhou" },
  { chave: "recuperacao", rotulo: "Voltou a funcionar", ajuda: "Carga ou aplicação que falhou e depois terminou com sucesso" },
  { chave: "qlik", rotulo: "API key da Qlik", ajuda: "7 dias antes de vencer e quando a Qlik recusar a key" },
];

function Preferencias({ api, cfg, semSmtp, aoSalvar }: { api: Api; cfg: ConfigNotificacoes; semSmtp: boolean; aoSalvar: (c: ConfigNotificacoes) => void }) {
  const [p, setP] = useState<PreferenciasNotificacao>(cfg.preferencias);
  const [novo, setNovo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const mudou = JSON.stringify(p) !== JSON.stringify(cfg.preferencias);
  const emailNovo = novo.trim().toLowerCase();
  const novoValido = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(emailNovo) && !p.extras.includes(emailNovo);
  const ninguem = !p.para_admins && p.extras.length === 0;

  function adicionar(e: React.FormEvent) {
    e.preventDefault();
    if (!novoValido) return;
    setP((x) => ({ ...x, extras: [...x.extras, emailNovo].sort() }));
    setNovo("");
  }

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      aoSalvar(await api.salvarPreferencias(p));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section aria-labelledby="titulo-avisos" className={semSmtp ? "opacity-70" : undefined}>
      <h3 id="titulo-avisos" className="text-sm font-semibold">
        O que avisar
      </h3>
      {semSmtp && <p className="mt-0.5 text-xs text-muted-foreground">Fica valendo quando um servidor for configurado.</p>}
      <ul className="mt-3 overflow-hidden rounded-2xl border border-border">
        {AVISOS.map((a) => (
          <li key={a.chave} className="linha-usuario">
            <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
              <input type="checkbox" className="mt-1 accent-[var(--lq-accent)]" checked={Boolean(p[a.chave])} onChange={(e) => setP((x) => ({ ...x, [a.chave]: e.target.checked }))} />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{a.rotulo}</span>
                <span className="block text-xs text-muted-foreground">{a.ajuda}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <label className="mt-3 inline-flex cursor-pointer items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1 accent-[var(--lq-accent)]" checked={p.so_mudanca} onChange={(e) => setP((x) => ({ ...x, so_mudanca: e.target.checked }))} />
        <span>
          Avisar só a primeira falha seguida
          <span className="block text-xs text-muted-foreground">Uma carga agendada que falha toda hora manda um e-mail ao quebrar e outro ao voltar, não um por execução.</span>
        </span>
      </label>

      <h3 className="mt-8 text-sm font-semibold">Quem recebe os avisos</h3>
      <p className="mt-0.5 text-xs text-muted-foreground">O e-mail com a senha temporária vai só para a própria pessoa.</p>
      <label className="mt-3 inline-flex cursor-pointer items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1 accent-[var(--lq-accent)]" checked={p.para_admins} onChange={(e) => setP((x) => ({ ...x, para_admins: e.target.checked }))} />
        <span>
          Todos os admins
          <span className="block text-xs text-muted-foreground">{cfg.admins.length ? cfg.admins.join(", ") : "Nenhum admin ativo"}</span>
        </span>
      </label>

      <div className="mt-4">
        <p className="text-xs font-medium">Outros e-mails</p>
        {p.extras.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {p.extras.map((e) => (
              <li key={e} className="tag !ml-0 inline-flex items-center gap-1 font-mono text-[12px]">
                {e}
                <button type="button" aria-label={`Tirar ${e}`} className="text-muted-foreground hover:text-foreground" onClick={() => setP((x) => ({ ...x, extras: x.extras.filter((y) => y !== e) }))}>
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={adicionar} className="mt-2 flex flex-wrap gap-2">
          <label htmlFor="extra-email" className="sr-only">
            E-mail para receber os avisos
          </label>
          <input id="extra-email" type="email" className="campo campo-pequeno min-w-[220px] flex-1" placeholder="ex.: time-dados@empresa.com.br" value={novo} onChange={(e) => setNovo(e.target.value)} />
          <button type="submit" className="btn-secundario inline-flex items-center gap-2" disabled={!novoValido}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Adicionar
          </button>
        </form>
      </div>

      {ninguem && <p className="alerta alerta-aviso mt-4">Ninguém vai receber os avisos de erro.</p>}
      {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}
      <div className="mt-5 flex justify-end gap-2">
        {mudou && (
          <button type="button" className="btn-secundario" onClick={() => setP(cfg.preferencias)}>
            Desfazer
          </button>
        )}
        <button type="button" className="btn-primario" disabled={!mudou || salvando} onClick={salvar}>
          {salvando ? "Salvando…" : "Salvar avisos"}
        </button>
      </div>

      <p className="mt-6 flex items-start gap-2 text-xs text-muted-foreground">
        <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>
          Os avisos saem do worker (a cada ~20 s) e os links apontam para <span className="font-mono text-foreground">{cfg.url_app}</span>. Para mudar, defina LURKQVD_URL_APP no servidor.
        </span>
      </p>
    </section>
  );
}

function Historico({ envios }: { envios: EnvioEmail[] }) {
  return (
    <section aria-labelledby="titulo-envios" className="border-t border-border pt-6">
      <h3 id="titulo-envios" className="mb-3 text-sm font-semibold">
        Últimos envios
      </h3>
      {envios.length === 0 ? (
        <p className="vazio">Nenhum e-mail enviado ainda.</p>
      ) : (
        <ul className="overflow-hidden rounded-2xl border border-border">
          {envios.map((e) => (
            <li key={e.id} className="linha-usuario !items-start">
              {e.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--lq-ok-fg)]" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium" title={e.assunto}>
                  {e.assunto}
                </p>
                <p className="truncate text-xs text-muted-foreground" title={e.destinatarios.join(", ")}>
                  para {e.destinatarios.join(", ")}
                </p>
                {!e.ok && e.erro && <p className="mt-0.5 text-xs text-destructive">{e.erro}</p>}
              </div>
              <span className="tag !ml-0 shrink-0">{TIPO_ENVIO[e.tipo] ?? e.tipo}</span>
              <span className="w-24 shrink-0 text-right text-xs text-muted-foreground" title={dataHora(e.criado_em)}>
                {relativo(e.criado_em)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
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
