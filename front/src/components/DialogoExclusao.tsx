// Balão de confirmação de exclusão (carga ou aplicação). As opções (caixas) vêm como children.
// Se a exclusão deu certo, mas com ressalva (ex.: o arquivo não saiu da Qlik), mostra o aviso antes de seguir.

import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Trash2, X } from "lucide-react";

interface Props {
  titulo: ReactNode;
  descricao: ReactNode;
  children?: ReactNode;
  rotuloBotao: string;
  /** Exclui. Devolve um aviso para mostrar antes de seguir, ou null. Erro (throw) mantém o balão aberto. */
  aoConfirmar: () => Promise<string | null>;
  /** Depois de excluir (ex.: voltar para a lista). */
  aoConcluir: () => void;
  aoFechar: () => void;
}

export default function DialogoExclusao({ titulo, descricao, children, rotuloBotao, aoConfirmar, aoConcluir, aoFechar }: Props) {
  const [excluindo, setExcluindo] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const fechar = aviso ? aoConcluir : aoFechar;

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      if (!excluindo) fechar();
    };
    window.addEventListener("keydown", tecla, true);
    return () => window.removeEventListener("keydown", tecla, true);
  }, [fechar, excluindo]);

  async function excluir() {
    setExcluindo(true);
    setErro(null);
    try {
      const a = await aoConfirmar();
      if (a) {
        setAviso(a);
        setExcluindo(false);
      } else {
        aoConcluir();
      }
    } catch (e) {
      setErro((e as Error).message);
      setExcluindo(false);
    }
  }

  return createPortal(
    <div className="balao-camada">
      <button type="button" aria-label="Fechar" className="balao-fundo" onClick={() => !excluindo && fechar()} />
      <div role="dialog" aria-modal="true" aria-labelledby="titulo-exclusao" className="balao w-[min(520px,100%)]">
        <div className="flex items-start justify-between gap-4">
          <span className="balao-icone text-destructive" aria-hidden="true">
            <Trash2 className="h-5 w-5" />
          </span>
          <button type="button" className="config-fechar" aria-label="Fechar" onClick={fechar} disabled={excluindo}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <h2 id="titulo-exclusao" className="mt-4 font-sora text-lg font-semibold tracking-tight">
          {titulo}
        </h2>

        {aviso ? (
          <>
            <p role="status" className="alerta alerta-aviso !mt-4 whitespace-pre-line text-sm">
              {aviso}
            </p>
            <div className="mt-6 flex justify-end">
              <button type="button" className="btn-primario px-4 py-2" onClick={aoConcluir}>
                Entendi
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="mt-1.5 text-sm text-muted-foreground">{descricao}</div>
            {children && <div className="mt-5 flex flex-col gap-3">{children}</div>}
            {erro && (
              <p role="alert" className="mt-4 border-l-2 border-destructive pl-3 text-sm text-destructive">
                {erro}
              </p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="btn-secundario px-4 py-2" onClick={aoFechar} disabled={excluindo}>
                Cancelar
              </button>
              <button type="button" className="btn-perigo inline-flex items-center gap-1.5 px-4 py-2" onClick={excluir} disabled={excluindo}>
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                {excluindo ? "Excluindo…" : rotuloBotao}
              </button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Caixa de opção do balão de exclusão. */
export function OpcaoExclusao({ marcada, aoMudar, rotulo, dica, desativada }: {
  marcada: boolean;
  aoMudar: (v: boolean) => void;
  rotulo: ReactNode;
  dica?: ReactNode;
  desativada?: boolean;
}) {
  return (
    <label className={`flex items-start gap-2.5 rounded-xl border border-border px-3.5 py-3 text-sm ${desativada ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="mt-0.5" checked={marcada} disabled={desativada} onChange={(e) => aoMudar(e.target.checked)} />
      <span>
        <span className="font-medium">{rotulo}</span>
        {dica && <span className="mt-0.5 block text-xs text-muted-foreground">{dica}</span>}
      </span>
    </label>
  );
}
