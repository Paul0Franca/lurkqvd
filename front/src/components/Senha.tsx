// Senha: campo com mostrar/ocultar e a troca de senha, obrigatória no primeiro acesso (senha temporária)
// e disponível no menu do perfil. O admin padrão (login "admin") informa também nome e e-mail reais.

import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { Eye, EyeOff, KeyRound, X } from "lucide-react";
import type { Api, Usuario } from "../api";
import FluxoQVD from "./FluxoQVD";
import { SignInPage } from "./ui/sign-in";

const MINIMO = 10;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function CampoSenha({
  id,
  valor,
  aoMudar,
  rotulo,
  autoComplete,
  autoFocus,
}: {
  id: string;
  valor: string;
  aoMudar: (v: string) => void;
  rotulo: string;
  autoComplete: "current-password" | "new-password";
  autoFocus?: boolean;
}) {
  const [visivel, setVisivel] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">
        {rotulo}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visivel ? "text" : "password"}
          className="campo pr-10"
          value={valor}
          onChange={(e) => aoMudar(e.target.value)}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          required
        />
        <button
          type="button"
          className="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          aria-label={visivel ? "Ocultar senha" : "Mostrar senha"}
          aria-pressed={visivel}
          onClick={() => setVisivel((v) => !v)}
        >
          {visivel ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}

/** Formulário de troca. senhaAtual: a temporária que acabou de ser digitada no login (não pede de novo). */
function FormTrocaSenha({
  api,
  usuario,
  senhaAtual,
  aoConcluir,
  rodape,
}: {
  api: Api;
  usuario: Usuario;
  senhaAtual?: string;
  aoConcluir: (u: Usuario) => void;
  rodape?: React.ReactNode;
}) {
  const id = useId();
  const completar = !EMAIL.test(usuario.email);
  const [atual, setAtual] = useState(senhaAtual ?? "");
  const [nova, setNova] = useState("");
  const [confirmacao, setConfirmacao] = useState("");
  const [nome, setNome] = useState(completar ? "" : (usuario.nome ?? ""));
  const [email, setEmail] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const problema =
    nova && nova.length < MINIMO
      ? `Pelo menos ${MINIMO} caracteres (faltam ${MINIMO - nova.length}).`
      : confirmacao && confirmacao !== nova
        ? "A confirmação não bate com a senha nova."
        : completar && email && !EMAIL.test(email)
          ? "Informe um e-mail válido."
          : null;
  const pronto = Boolean(atual && nova.length >= MINIMO && confirmacao === nova && (!completar || (nome.trim() && EMAIL.test(email))));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    if (!pronto) return;
    setEnviando(true);
    setErro(null);
    try {
      aoConcluir(await api.trocarSenha({ atual, nova, ...(completar ? { email: email.trim(), nome: nome.trim() } : {}) }));
    } catch (err) {
      setErro((err as Error).message);
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="flex flex-col gap-4">
      {completar && (
        <>
          <div>
            <label htmlFor={`${id}-nome`} className="mb-1.5 block text-sm font-medium">
              Seu nome
            </label>
            <input id={`${id}-nome`} className="campo" value={nome} onChange={(e) => setNome(e.target.value)} autoComplete="name" required autoFocus />
          </div>
          <div>
            <label htmlFor={`${id}-email`} className="mb-1.5 block text-sm font-medium">
              Seu e-mail
            </label>
            <input
              id={`${id}-email`}
              type="email"
              className="campo"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="nome@empresa.com.br"
              required
            />
            <p className="mt-1.5 text-xs text-muted-foreground">Passa a ser o seu login, no lugar de “admin”.</p>
          </div>
        </>
      )}
      {senhaAtual === undefined && (
        <CampoSenha id={`${id}-atual`} rotulo="Senha atual" valor={atual} aoMudar={setAtual} autoComplete="current-password" autoFocus={!completar} />
      )}
      <CampoSenha
        id={`${id}-nova`}
        rotulo="Senha nova"
        valor={nova}
        aoMudar={setNova}
        autoComplete="new-password"
        autoFocus={!completar && senhaAtual !== undefined}
      />
      <CampoSenha id={`${id}-confirmar`} rotulo="Confirme a senha nova" valor={confirmacao} aoMudar={setConfirmacao} autoComplete="new-password" />
      <p className={`-mt-1 text-xs ${problema ? "text-destructive" : "text-muted-foreground"}`} aria-live="polite">
        {problema ?? `Use pelo menos ${MINIMO} caracteres. Uma frase curta é mais fácil de lembrar e mais segura.`}
      </p>
      {erro && (
        <p role="alert" className="border-l-2 border-destructive pl-3 text-sm text-destructive">
          {erro}
        </p>
      )}
      <div className="flex items-center gap-3">
        {rodape}
        <button type="submit" className="btn-primario ml-auto px-5 py-2.5" disabled={!pronto || enviando}>
          {enviando ? "Salvando…" : "Salvar senha"}
        </button>
      </div>
    </form>
  );
}

/** Primeiro acesso (senha temporária): balão à frente da tela de login, que fica desfocada e inerte atrás.
 * O resto do app só abre depois da troca. */
export function PaginaTrocaSenha({
  api,
  usuario,
  senhaAtual,
  aoConcluir,
  aoSair,
}: {
  api: Api;
  usuario: Usuario;
  senhaAtual?: string;
  aoConcluir: (u: Usuario) => void;
  aoSair: () => void;
}) {
  const completar = !EMAIL.test(usuario.email);
  return (
    <div className="bg-background text-foreground">
      {/* fundo: a tela de login, só de enfeite */}
      <div inert aria-hidden="true">
        <SignInPage
          title="Suas cargas QVD, em um só lugar."
          description="Gere os arquivos fora da Qlik, publique na Qlik Cloud e acompanhe cada execução."
          extra={<FluxoQVD />}
          formulario={
            <div className="flex flex-col gap-4">
              <input className="campo" defaultValue={usuario.email} readOnly tabIndex={-1} />
              <input className="campo" type="password" defaultValue="••••••••••" readOnly tabIndex={-1} />
              <span className="btn-primario w-full py-2.5 text-center">Entrar</span>
            </div>
          }
        />
      </div>

      <div className="balao-camada">
        <div className="balao-fundo" aria-hidden="true" />
        <div role="dialog" aria-modal="true" aria-labelledby="titulo-troca" aria-describedby="texto-troca" className="balao w-[min(460px,100%)]">
          <span className="balao-icone" aria-hidden="true">
            <KeyRound className="h-5 w-5" />
          </span>
          <h2 id="titulo-troca" className="mt-4 font-sora text-lg font-semibold tracking-tight">
            {completar ? "Bem-vindo ao LurkQVD" : `Olá, ${(usuario.nome ?? usuario.email).split(" ")[0]}. Escolha a sua senha`}
          </h2>
          <p id="texto-troca" className="mt-1.5 text-sm text-muted-foreground">
            {completar
              ? "Antes de começar, informe quem você é e troque a senha da instalação por uma só sua."
              : "Você entrou com uma senha temporária. Escolha uma senha só sua para continuar."}
          </p>
          <div className="mt-5">
            <FormTrocaSenha
              api={api}
              usuario={usuario}
              senhaAtual={senhaAtual}
              aoConcluir={aoConcluir}
              rodape={
                <button type="button" className="text-sm text-muted-foreground hover:text-foreground" onClick={aoSair}>
                  Sair
                </button>
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Menu do perfil: trocar a senha a qualquer momento. Vai direto no <body>: o topo tem backdrop-filter,
 * que prende elementos "fixed" dentro dele. */
export function DialogoTrocaSenha({ api, usuario, aoFechar }: { api: Api; usuario: Usuario; aoFechar: () => void }) {
  const [concluido, setConcluido] = useState(false);

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && aoFechar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [aoFechar]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[14vh]">
      <button aria-label="Fechar" className="painel-fundo absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={aoFechar} />
      <div role="dialog" aria-modal="true" aria-labelledby="titulo-trocar-senha" className="dialogo relative w-full max-w-[420px] rounded-2xl border border-border bg-background p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="titulo-trocar-senha" className="font-sora text-lg font-semibold tracking-tight">
              Alterar senha
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">Os outros navegadores em que você está logado saem na hora.</p>
          </div>
          <button type="button" className="config-fechar" aria-label="Fechar" onClick={aoFechar}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-5">
          {concluido ? (
            <div className="flex flex-col gap-4">
              <p className="alerta !m-0 bg-[var(--lq-ok-bg)] text-[var(--lq-ok-fg)]" role="status">
                Senha alterada.
              </p>
              <button type="button" className="btn-secundario self-end" onClick={aoFechar}>
                Fechar
              </button>
            </div>
          ) : (
            <FormTrocaSenha api={api} usuario={usuario} aoConcluir={() => setConcluido(true)} />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
