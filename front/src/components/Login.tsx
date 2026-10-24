import { useState } from "react";
import { entrar, type Sessao } from "@/api";
import { SignInPage, type Destaque } from "@/components/ui/sign-in";
import FluxoQVD from "@/components/FluxoQVD";
import { CampoSenha } from "@/components/Senha";
import { BotaoTema } from "@/components/Tema";

const DESTAQUES: Destaque[] = [
  { titulo: "Menos capacidade consumida", texto: "Os QVDs são gerados fora da Qlik e só o arquivo final entra na cota." },
  { titulo: "Um arquivo por carga", texto: "Cada execução substitui o próprio QVD, com o mesmo ID na Qlik Cloud." },
  { titulo: "Cada execução registrada", texto: "Quem pediu, quando rodou, quantas linhas e quanto tempo levou." },
];

interface Props {
  /** senha: a digitada agora; se for temporária, a troca não pede de novo */
  aoEntrar: (sessao: Sessao, senha: string) => void;
  erro: string | null;
}

export default function Login({ aoEntrar, erro: erroInicial }: Props) {
  const [login, setLogin] = useState("");
  const [senha, setSenha] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(erroInicial);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setErro(null);
    try {
      aoEntrar(await entrar(login.trim(), senha), senha);
    } catch (err) {
      setErro((err as Error).message);
      setEnviando(false);
    }
  }

  return (
    <div className="bg-background text-foreground">
      <div className="fixed right-4 top-4 z-20">
        <BotaoTema />
      </div>
      <SignInPage
        title="Suas cargas QVD, em um só lugar."
        description="Gere os arquivos fora da Qlik, publique na Qlik Cloud e acompanhe cada execução."
        erro={erro}
        ajuda="Sem acesso? Fale com um administrador do LurkQVD."
        destaques={DESTAQUES}
        extra={<FluxoQVD />}
        formulario={
          <form onSubmit={enviar} className="flex flex-col gap-4">
            <div>
              <label htmlFor="login" className="mb-1.5 block text-sm font-medium">
                E-mail
              </label>
              <input
                id="login"
                className="campo"
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                autoComplete="username"
                placeholder="nome@empresa.com.br"
                autoFocus
                required
              />
            </div>
            <CampoSenha id="senha" rotulo="Senha" valor={senha} aoMudar={setSenha} autoComplete="current-password" />
            <button type="submit" className="btn-primario mt-1 w-full py-2.5" disabled={enviando || !login.trim() || !senha}>
              {enviando ? "Entrando…" : "Entrar"}
            </button>
            <p className="text-xs text-muted-foreground">Primeiro acesso? Use a senha temporária que chegou no seu e-mail.</p>
          </form>
        }
      />
    </div>
  );
}
