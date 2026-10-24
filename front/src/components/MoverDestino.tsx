// Mover o destino de uma carga (espaço e/ou pasta na Qlik Cloud). Balão à frente, fundo desfocado.
// O nome do arquivo não muda; o arquivo antigo fica na Qlik e deixa de ser atualizado.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, FolderInput, X } from "lucide-react";
import type { Api, CargaDetalhe, Espaco } from "../api";
import DestinoPicker, { type Destino } from "./DestinoPicker";

interface Props {
  api: Api;
  carga: CargaDetalhe;
  espacos: Espaco[];
  emAndamento: boolean;
  aoMover: (c: CargaDetalhe) => void;
  aoFechar: () => void;
}

export default function MoverDestino({ api, carga, espacos, emAndamento, aoMover, aoFechar }: Props) {
  const espacoAtual = espacos.find((e) => e.connection_id === carga.connection_id) ?? espacos.find((e) => !carga.connection_id && e.tipo === "personal");
  const pastaAtual = carga.qlik_path.split("/").slice(0, -1).join("/");
  const arquivo = carga.qlik_path.split("/").at(-1) ?? "";
  const [destino, setDestino] = useState<Destino | null>(
    espacoAtual ? { connectionId: espacoAtual.connection_id, pessoal: espacoAtual.tipo === "personal", nomeEspaco: espacoAtual.nome, pasta: pastaAtual } : null,
  );
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Esc fecha só o balão
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      if (!salvando) aoFechar();
    };
    window.addEventListener("keydown", tecla, true);
    return () => window.removeEventListener("keydown", tecla, true);
  }, [aoFechar, salvando]);

  const mudou = !!destino && (destino.connectionId !== espacoAtual?.connection_id || destino.pasta !== pastaAtual);
  const de = [espacoAtual?.nome ?? "?", ...(pastaAtual ? pastaAtual.split("/") : [])].join(" / ");
  const para = destino ? [destino.nomeEspaco, ...(destino.pasta ? destino.pasta.split("/") : [])].join(" / ") : "";

  async function mover() {
    if (!destino) return;
    setSalvando(true);
    setErro(null);
    try {
      aoMover(await api.mudarDestino(carga.id, { connection_id: destino.pessoal ? null : destino.connectionId, pasta: destino.pasta }));
    } catch (e) {
      setErro((e as Error).message);
      setSalvando(false);
    }
  }

  return createPortal(
    <div className="balao-camada">
      <button type="button" aria-label="Fechar" className="balao-fundo" onClick={() => !salvando && aoFechar()} />
      <div role="dialog" aria-modal="true" aria-labelledby="titulo-mover" className="balao w-[min(620px,100%)]">
        <div className="flex items-start justify-between gap-4">
          <span className="balao-icone" aria-hidden="true">
            <FolderInput className="h-5 w-5" />
          </span>
          <button type="button" className="config-fechar" aria-label="Fechar" onClick={aoFechar} disabled={salvando}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <h2 id="titulo-mover" className="mt-4 font-sora text-lg font-semibold tracking-tight">
          Mover o destino de <span className="break-all font-mono">{carga.nome}</span>
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">Escolha o espaço e a pasta da Qlik Cloud onde o QVD passa a ser publicado.</p>

        <div className="mt-5 max-h-[44vh] overflow-y-auto pr-1">
          {espacos.length ? <DestinoPicker api={api} espacos={espacos} valor={destino} aoMudar={setDestino} /> : <p className="vazio">Carregando espaços…</p>}
        </div>

        <div className="mt-5 rounded-xl border border-border bg-[var(--lq-surface-2)] px-3.5 py-3 text-[13px]">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-muted-foreground line-through decoration-muted-foreground/50">{de}</span>
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="font-medium">{mudou ? para : "escolha um destino diferente"}</span>
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{arquivo}</p>
        </div>

        <ul className="mt-4 flex flex-col gap-1.5 text-xs text-muted-foreground">
          <li>Vale a partir da próxima execução; se houver um QVD guardado de um envio que falhou, ele é aproveitado.</li>
          <li>O arquivo antigo continua na Qlik e deixa de ser atualizado: apague-o lá se ninguém mais usar.</li>
          <li>Apps que leem o QVD precisam passar a ler do novo caminho.</li>
        </ul>

        {emAndamento && <p className="alerta alerta-aviso !mt-4 text-sm">A carga está na fila ou rodando: mova o destino depois que ela terminar.</p>}
        {erro && (
          <p role="alert" className="mt-4 border-l-2 border-destructive pl-3 text-sm text-destructive">
            {erro}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className="btn-secundario px-4 py-2" onClick={aoFechar} disabled={salvando}>
            Cancelar
          </button>
          <button type="button" className="btn-primario px-4 py-2" onClick={mover} disabled={!mudou || salvando || emAndamento}>
            {salvando ? "Movendo…" : "Mover destino"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
