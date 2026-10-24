import { useEffect, useRef, useState } from "react";
import type { Api } from "../api";

interface Props {
  api: Api;
  aberto: boolean;
  aoFechar: () => void;
  aoCriar: () => void;
  connectionId: string;
  pasta: string;
  nomeEspaco: string;
}

const INVALIDO = /[<>":|?*/\\]/;

export default function NovaPasta({ api, aberto, aoFechar, aoCriar, connectionId, pasta, nomeEspaco }: Props) {
  const [nome, setNome] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const campo = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!aberto) return;
    campo.current?.focus();
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && aoFechar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [aberto, aoFechar]);

  if (!aberto) return null;

  const invalido = INVALIDO.test(nome);
  const destino = [nomeEspaco, pasta, nome.trim() || "…"].filter(Boolean).join(" / ");

  async function enviar(ev: React.FormEvent) {
    ev.preventDefault();
    if (!nome.trim() || invalido) return;
    setEnviando(true);
    setErro(null);
    try {
      await api.criarPasta(connectionId, pasta, nome.trim());
      aoCriar();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[18vh]">
      <button aria-label="Fechar" className="painel-fundo absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={aoFechar} />
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="titulo-nova-pasta"
        onSubmit={enviar}
        className="dialogo relative w-full max-w-[440px] rounded-2xl border border-border bg-background p-6 shadow-2xl"
      >
        <h2 id="titulo-nova-pasta" className="font-sora text-lg font-semibold tracking-tight">
          Nova pasta
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">A pasta é criada também na Qlik Cloud.</p>

        <label htmlFor="nome-pasta" className="mt-5 block text-sm font-medium">
          Nome
        </label>
        <input
          id="nome-pasta"
          ref={campo}
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="vendas"
          className="campo mt-1.5"
          aria-invalid={invalido}
          aria-describedby="ajuda-pasta"
          autoComplete="off"
        />
        <p id="ajuda-pasta" className={`mt-1.5 truncate text-xs ${invalido ? "text-destructive" : "text-muted-foreground"}`}>
          {invalido ? "O nome não pode ter / \\ < > : \" | ? *" : destino}
        </p>

        {erro && (
          <p role="alert" className="mt-4 border-l-2 border-destructive pl-3 text-sm text-destructive">
            {erro}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={aoFechar} className="btn-secundario">
            Cancelar
          </button>
          <button type="submit" disabled={!nome.trim() || invalido || enviando} className="btn-primario">
            {enviando ? "Criando…" : "Criar pasta"}
          </button>
        </div>
      </form>
    </div>
  );
}
