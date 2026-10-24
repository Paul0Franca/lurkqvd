// Escolhe o "repositório" (espaço) e a pasta de destino, navegando pela estrutura criada em Espaços.

import { useEffect, useState } from "react";
import { Check, ChevronRight, CornerLeftUp, Folder } from "lucide-react";
import type { Api, Espaco, Pasta } from "../api";
import { link } from "../rotas";

export interface Destino {
  connectionId: string; // id da conexão do espaço (inclusive o pessoal)
  pessoal: boolean;
  nomeEspaco: string;
  pasta: string;
}

interface Props {
  api: Api;
  espacos: Espaco[];
  valor: Destino | null;
  aoMudar: (d: Destino) => void;
}

export default function DestinoPicker({ api, espacos, valor, aoMudar }: Props) {
  const [pastas, setPastas] = useState<Pasta[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const connectionId = valor?.connectionId ?? "";
  const pasta = valor?.pasta ?? "";

  useEffect(() => {
    if (!connectionId) return;
    let cancelado = false;
    api
      .conteudoEspaco(connectionId, pasta)
      .then((c) => {
        if (cancelado) return;
        setPastas(c.pastas);
        setErro(c.aviso);
      })
      .catch((e: Error) => !cancelado && setErro(e.message));
    return () => {
      cancelado = true;
    };
  }, [api, connectionId, pasta]);

  function escolherEspaco(id: string) {
    const e = espacos.find((x) => x.connection_id === id);
    if (!e) return;
    setPastas(null);
    aoMudar({ connectionId: e.connection_id, pessoal: e.tipo === "personal", nomeEspaco: e.nome, pasta: "" });
  }

  function irPara(nova: string) {
    if (!valor) return;
    setPastas(null);
    aoMudar({ ...valor, pasta: nova });
  }

  const partes = pasta ? pasta.split("/") : [];

  return (
    <div className="flex flex-col gap-3">
      <select value={connectionId} onChange={(e) => escolherEspaco(e.target.value)} className="campo" aria-label="Espaço (repositório)">
        <option value="" disabled>
          Escolha o espaço
        </option>
        {espacos.map((e) => (
          <option key={e.connection_id} value={e.connection_id}>
            {e.nome}
          </option>
        ))}
      </select>

      {valor && (
        <div className="navegador-pastas">
          {/* onde estou */}
          <div className="flex flex-wrap items-center gap-1 border-b border-border px-3 py-2.5 text-sm">
            <button type="button" className="rounded px-1 hover:bg-secondary" onClick={() => irPara("")}>
              {valor.nomeEspaco}
            </button>
            {partes.map((p, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                <button type="button" className="rounded px-1 hover:bg-secondary" onClick={() => irPara(partes.slice(0, i + 1).join("/"))}>
                  {p}
                </button>
              </span>
            ))}
            <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-primary">
              <Check className="h-3.5 w-3.5" />
              destino
            </span>
          </div>

          {/* subpastas */}
          <ul className="max-h-[220px] overflow-y-auto py-1">
            {pasta && (
              <li>
                <button type="button" className="item-pasta text-muted-foreground" onClick={() => irPara(partes.slice(0, -1).join("/"))}>
                  <CornerLeftUp className="h-4 w-4" />
                  Voltar um nível
                </button>
              </li>
            )}
            {!pastas ? (
              <li className="px-3 py-2 text-sm text-muted-foreground">Carregando pastas…</li>
            ) : pastas.length === 0 ? (
              <li className="px-3 py-2 text-sm text-muted-foreground">
                Sem subpastas aqui. O QVD fica nesta pasta.{" "}
                <a className="text-primary hover:underline" href={link({ tela: "espaco", connectionId: valor.connectionId, pasta })} target="_blank" rel="noreferrer">
                  Criar pasta em Espaços
                </a>
              </li>
            ) : (
              pastas.map((p) => (
                <li key={p.caminho}>
                  <button type="button" className="item-pasta" onClick={() => irPara(p.caminho)}>
                    <Folder className="h-4 w-4 text-muted-foreground" fill="currentColor" fillOpacity={0.15} />
                    <span className="flex-1 text-left">{p.nome}</span>
                    <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  </button>
                </li>
              ))
            )}
          </ul>
          {erro && <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">{erro}</p>}
        </div>
      )}
    </div>
  );
}
