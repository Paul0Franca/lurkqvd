// Configurações > Usuários e acesso: cadastrar (senha temporária por e-mail), papéis, redefinir senha
// e desativar/reativar. Sem o servidor de e-mail configurado, não dá para cadastrar.

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, KeyRound, MailCheck, Search, UserPlus, X } from "lucide-react";
import type { Api, Papel, Usuario, UsuarioAdmin } from "../api";
import { dataHora, relativo } from "../lib/formato";
import { DESCRICAO_PAPEL, NOME_PAPEL, PAPEIS } from "../lib/papeis";
import Avatar from "./Avatar";

interface Props {
  api: Api;
  usuario: Usuario;
  /** leva para Configurações › Notificações (onde fica o servidor de e-mail) */
  aoAbrirNotificacoes: () => void;
}

export default function UsuariosAcesso({ api, usuario, aoAbrirNotificacoes }: Props) {
  const [usuarios, setUsuarios] = useState<UsuarioAdmin[] | null>(null);
  const [smtp, setSmtp] = useState<boolean | null>(null); // null = ainda consultando
  const [busca, setBusca] = useState("");
  const [salvando, setSalvando] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [redefinindo, setRedefinindo] = useState<UsuarioAdmin | null>(null);

  const carregar = useCallback(() => {
    api.usuarios().then(setUsuarios).catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(() => {
    api
      .configNotificacoes()
      .then((c) => setSmtp(Boolean(c.smtp)))
      .catch(() => setSmtp(false));
  }, [api]);

  useEffect(carregar, [carregar]);

  async function alterar(u: UsuarioAdmin, dados: { papel?: Papel; ativo?: boolean }) {
    setSalvando(u.id);
    setErro(null);
    try {
      const novo = await api.alterarUsuario(u.id, dados);
      setUsuarios((lista) => lista?.map((x) => (x.id === novo.id ? novo : x)) ?? null);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(null);
    }
  }

  const termo = busca.trim().toLowerCase();
  const visiveis = (usuarios ?? []).filter((u) => !termo || u.email.includes(termo) || (u.nome ?? "").toLowerCase().includes(termo));
  const ativos = (usuarios ?? []).filter((u) => u.ativo).length;

  return (
    <div className="flex flex-col gap-8">
      {/* legenda dos papéis */}
      <dl className="grid gap-2 sm:grid-cols-3">
        {PAPEIS.map((p) => (
          <div key={p} className="rounded-xl border border-border px-3.5 py-3">
            <dt>
              <span className={`papel papel-${p}`}>{NOME_PAPEL[p]}</span>
            </dt>
            <dd className="mt-1.5 text-xs text-muted-foreground">{DESCRICAO_PAPEL[p]}</dd>
          </div>
        ))}
      </dl>

      {erro && (
        <p className="alerta alerta-erro !mb-0 flex items-start justify-between gap-3" role="alert">
          {erro}
          <button type="button" aria-label="Fechar aviso" onClick={() => setErro(null)}>
            <X className="h-4 w-4" />
          </button>
        </p>
      )}

      {/* ---------- usuários ---------- */}
      <section aria-labelledby="titulo-usuarios">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 id="titulo-usuarios" className="text-sm font-semibold">
            Usuários
            {usuarios && <span className="ml-2 font-normal text-muted-foreground">{ativos} com acesso</span>}
          </h3>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <label htmlFor="busca-usuario" className="sr-only">
              Buscar usuário
            </label>
            <input id="busca-usuario" className="campo campo-pequeno pl-9" placeholder="Buscar por nome ou e-mail" value={busca} onChange={(e) => setBusca(e.target.value)} />
          </div>
        </div>

        {!usuarios ? (
          <p className="vazio">Carregando…</p>
        ) : (
          <ul className="overflow-hidden rounded-2xl border border-border">
            {visiveis.map((u) => {
              const eu = u.id === usuario.id;
              return (
                <li key={u.id} className="linha-usuario" data-inativo={!u.ativo || undefined}>
                  <Avatar nome={u.nome} email={u.email} foto={u.foto_url} tamanho={34} />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 truncate text-sm font-medium">
                      <span className="truncate">{u.nome ?? u.email}</span>
                      {eu && <span className="tag !ml-0">você</span>}
                      {!u.ativo && <span className="tag !ml-0">sem acesso</span>}
                      {u.ativo && !u.tem_senha && (
                        <span className="tag !ml-0" title="Veio do login com o Google: redefina a senha para a pessoa conseguir entrar">
                          sem senha
                        </span>
                      )}
                      {u.ativo && u.tem_senha && u.trocar_senha && (
                        <span className="tag !ml-0" title="Ainda não trocou a senha temporária">
                          senha temporária
                        </span>
                      )}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{u.email}</p>
                  </div>

                  <div className="hidden w-36 shrink-0 text-xs text-muted-foreground md:block">
                    <span title={u.ultimo_login ? dataHora(u.ultimo_login) : undefined}>
                      {u.ultimo_login ? `entrou ${relativo(u.ultimo_login)}` : "nunca entrou"}
                    </span>
                    <span className="block">{u.cargas_criadas === 1 ? "1 carga criada" : `${u.cargas_criadas} cargas criadas`}</span>
                  </div>

                  <label className="sr-only" htmlFor={`papel-${u.id}`}>
                    Papel de {u.nome ?? u.email}
                  </label>
                  <select
                    id={`papel-${u.id}`}
                    className="campo campo-pequeno w-[108px] shrink-0"
                    value={u.papel}
                    disabled={eu || !u.ativo || salvando === u.id}
                    title={eu ? "Você não pode alterar o próprio acesso" : undefined}
                    onChange={(e) => alterar(u, { papel: e.target.value as Papel })}
                  >
                    {PAPEIS.map((p) => (
                      <option key={p} value={p}>
                        {NOME_PAPEL[p]}
                      </option>
                    ))}
                  </select>

                  <button
                    type="button"
                    className="config-fechar"
                    aria-label={`Redefinir a senha de ${u.nome ?? u.email}`}
                    title={eu ? "Para trocar a sua senha, use o menu do seu perfil" : !smtp ? "Configure o servidor de e-mail para redefinir senhas" : "Redefinir senha (envia uma temporária por e-mail)"}
                    disabled={eu || !u.ativo || !smtp || salvando === u.id}
                    onClick={() => setRedefinindo(u)}
                  >
                    <KeyRound className="h-4 w-4" />
                  </button>

                  <button
                    type="button"
                    className={`btn-acesso ${u.ativo ? "" : "btn-acesso-reativar"}`}
                    disabled={eu || salvando === u.id}
                    title={eu ? "Você não pode alterar o próprio acesso" : undefined}
                    onClick={() => alterar(u, { ativo: !u.ativo })}
                  >
                    {u.ativo ? "Remover acesso" : "Devolver acesso"}
                  </button>
                </li>
              );
            })}
            {visiveis.length === 0 && <li className="px-4 py-5 text-sm text-muted-foreground">Ninguém encontrado com “{busca}”.</li>}
          </ul>
        )}
      </section>

      {/* ---------- novo usuário ---------- */}
      <NovoUsuario api={api} smtp={smtp} aoCriar={carregar} aoAbrirNotificacoes={aoAbrirNotificacoes} />

      {redefinindo && <DialogoRedefinir api={api} alvo={redefinindo} aoEnviar={carregar} aoFechar={() => setRedefinindo(null)} />}
    </div>
  );
}

/** Confirmação de "redefinir senha": à frente de tudo (inclusive da janela de configurações), com o fundo desfocado. */
function DialogoRedefinir({ api, alvo, aoEnviar, aoFechar }: { api: Api; alvo: UsuarioAdmin; aoEnviar: () => void; aoFechar: () => void }) {
  const [enviando, setEnviando] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const primeiroNome = (alvo.nome ?? alvo.email).split(" ")[0];

  // Esc fecha só este diálogo: captura antes da janela de configurações (que também fecha com Esc)
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      if (!enviando) aoFechar();
    };
    window.addEventListener("keydown", tecla, true);
    return () => window.removeEventListener("keydown", tecla, true);
  }, [aoFechar, enviando]);

  async function enviar() {
    setEnviando(true);
    setErro(null);
    try {
      await api.redefinirSenha(alvo.id);
      setEnviado(true);
      aoEnviar();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setEnviando(false);
    }
  }

  return createPortal(
    <div className="balao-camada">
      <button type="button" aria-label="Fechar" className="balao-fundo" onClick={() => !enviando && aoFechar()} />
      <div role="alertdialog" aria-modal="true" aria-labelledby="titulo-redefinir" aria-describedby="texto-redefinir" className="balao">
        {enviado ? (
          <>
            <span className="balao-icone balao-icone-ok" aria-hidden="true">
              <CheckCircle2 className="h-5 w-5" />
            </span>
            <h2 id="titulo-redefinir" className="mt-4 font-sora text-lg font-semibold tracking-tight">
              Senha enviada
            </h2>
            <p id="texto-redefinir" className="mt-1.5 text-sm text-muted-foreground">
              A senha temporária foi para <span className="font-medium text-foreground">{alvo.email}</span>. No próximo acesso, {primeiroNome} escolhe uma senha nova.
            </p>
            <div className="mt-6 flex justify-end">
              <button type="button" className="btn-primario px-4 py-2" onClick={aoFechar} autoFocus>
                Fechar
              </button>
            </div>
          </>
        ) : (
          <>
            <span className="balao-icone" aria-hidden="true">
              <KeyRound className="h-5 w-5" />
            </span>
            <h2 id="titulo-redefinir" className="mt-4 font-sora text-lg font-semibold tracking-tight">
              Redefinir a senha de {primeiroNome}?
            </h2>
            <div className="mt-4 flex items-center gap-3 rounded-xl border border-border bg-[var(--lq-surface-2)] px-3.5 py-3">
              <Avatar nome={alvo.nome} email={alvo.email} foto={alvo.foto_url} tamanho={34} />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{alvo.nome ?? alvo.email}</p>
                <p className="truncate text-xs text-muted-foreground">{alvo.email}</p>
              </div>
              <span className={`papel papel-${alvo.papel} ml-auto`}>{NOME_PAPEL[alvo.papel]}</span>
            </div>
            <ul id="texto-redefinir" className="mt-4 flex flex-col gap-2 text-sm text-muted-foreground">
              <li className="flex gap-2.5">
                <MailCheck className="mt-0.5 h-4 w-4 shrink-0 text-foreground" aria-hidden="true" />
                Uma senha temporária vai por e-mail para {primeiroNome}.
              </li>
              <li className="flex gap-2.5">
                <X className="mt-0.5 h-4 w-4 shrink-0 text-foreground" aria-hidden="true" />A senha atual para de funcionar e {primeiroNome} sai na hora de todos os navegadores.
              </li>
              <li className="flex gap-2.5">
                <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-foreground" aria-hidden="true" />
                No próximo acesso, escolhe uma senha nova.
              </li>
            </ul>
            {erro && (
              <p role="alert" className="mt-4 border-l-2 border-destructive pl-3 text-sm text-destructive">
                {erro}
              </p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="btn-secundario px-4 py-2" onClick={aoFechar} disabled={enviando}>
                Cancelar
              </button>
              <button type="button" className="btn-primario px-4 py-2" onClick={enviar} disabled={enviando} autoFocus>
                {enviando ? "Enviando…" : "Enviar senha temporária"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

function NovoUsuario({
  api,
  smtp,
  aoCriar,
  aoAbrirNotificacoes,
}: {
  api: Api;
  smtp: boolean | null;
  aoCriar: () => void;
  aoAbrirNotificacoes: () => void;
}) {
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [papel, setPapel] = useState<Papel>("editor");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [criado, setCriado] = useState<string | null>(null);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setErro(null);
    setCriado(null);
    try {
      const u = await api.criarUsuario({ email: email.trim(), nome: nome.trim(), papel });
      setCriado(u.email);
      setNome("");
      setEmail("");
      aoCriar();
    } catch (err) {
      setErro((err as Error).message.includes("pattern") ? "Informe um e-mail válido." : (err as Error).message);
    } finally {
      setEnviando(false);
    }
  }

  const bloqueado = smtp === false;
  return (
    <section aria-labelledby="titulo-novo-usuario" className="config-convidar">
      <h3 id="titulo-novo-usuario" className="text-sm font-semibold">
        Adicionar usuário
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        O login é o e-mail. O LurkQVD sorteia uma senha temporária e manda por e-mail; no primeiro acesso a pessoa escolhe a dela.
      </p>
      {bloqueado && (
        <p className="alerta alerta-aviso !mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" role="status">
          <span className="flex-1">Para cadastrar usuários, configure antes o servidor de e-mail: é por ele que a senha temporária chega.</span>
          <button type="button" className="aviso-acao" onClick={aoAbrirNotificacoes}>
            Configurar e-mail
          </button>
        </p>
      )}
      <form onSubmit={enviar} className="mt-3 flex flex-wrap gap-2">
        <label htmlFor="novo-nome" className="sr-only">
          Nome
        </label>
        <input
          id="novo-nome"
          required
          disabled={bloqueado}
          className="campo campo-pequeno min-w-[160px] flex-1"
          placeholder="Nome"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          autoComplete="off"
        />
        <label htmlFor="novo-email" className="sr-only">
          E-mail
        </label>
        <input
          id="novo-email"
          type="email"
          required
          disabled={bloqueado}
          className="campo campo-pequeno min-w-[220px] flex-[1.4]"
          placeholder="nome@empresa.com.br"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="off"
        />
        <label htmlFor="novo-papel" className="sr-only">
          Papel
        </label>
        <select id="novo-papel" className="campo campo-pequeno w-[108px]" disabled={bloqueado} value={papel} onChange={(e) => setPapel(e.target.value as Papel)}>
          {PAPEIS.map((p) => (
            <option key={p} value={p}>
              {NOME_PAPEL[p]}
            </option>
          ))}
        </select>
        <button type="submit" className="btn-primario inline-flex items-center gap-2" disabled={bloqueado || smtp === null || enviando || !email.trim() || !nome.trim()}>
          <UserPlus className="h-4 w-4" aria-hidden="true" />
          {enviando ? "Enviando…" : "Adicionar"}
        </button>
      </form>
      {erro && <p className="mt-2 text-sm text-destructive">{erro}</p>}
      {criado && (
        <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground" role="status">
          <MailCheck className="h-3.5 w-3.5 text-[var(--lq-ok-fg)]" aria-hidden="true" />
          Usuário criado. O login e a senha temporária foram enviados para {criado}.
        </p>
      )}
    </section>
  );
}
