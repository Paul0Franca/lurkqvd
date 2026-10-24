// Nova carga: "Estimar tamanho do QVD" sem varrer a tabela
// (plano estimado + estatísticas do banco + amostra das primeiras linhas).

import { useState } from "react";
import { Loader2, Scale } from "lucide-react";
import type { Api, Estimativa } from "../api";
import PainelComposicao from "./ComposicaoQvd";

interface Props {
  api: Api;
  query: string;
  fonteId?: number | null;
  desativado?: boolean;
}

export default function EstimativaQvd({ api, query, fonteId, desativado }: Props) {
  const [resultado, setResultado] = useState<Estimativa | null>(null);
  const [calculando, setCalculando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [consultaEstimada, setConsultaEstimada] = useState<string | null>(null);

  async function estimar() {
    setCalculando(true);
    setErro(null);
    try {
      setResultado(await api.estimar({ query, fonte_id: fonteId ?? null }));
      setConsultaEstimada(query);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setCalculando(false);
    }
  }

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn-secundario inline-flex items-center gap-2" disabled={desativado || calculando} onClick={estimar}>
          {calculando ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Scale className="h-4 w-4" aria-hidden="true" />}
          {calculando ? "Estimando…" : resultado ? "Estimar de novo" : "Estimar tamanho do QVD"}
        </button>
        <span className="text-xs text-muted-foreground">Sem varrer a tabela: plano do banco, estatísticas e uma amostra sorteada.</span>
      </div>

      {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}

      {resultado && (
        <PainelComposicao
          r={resultado}
          titulo="Tamanho previsto do QVD"
          desatualizada={consultaEstimada !== query}
          rodape={
            resultado.origem_linhas === "exato"
              ? "A consulta inteira coube na amostra: números exatos."
              : `Linhas pelo plano estimado do banco; distintos pelas estatísticas do banco ou por ${
                  resultado.amostra_aleatoria ? "amostra sorteada de" : "amostra das primeiras"
                } ${resultado.amostra?.toLocaleString("pt-BR")} linhas. Depois da primeira execução, a página da carga mostra a composição real.`
          }
        />
      )}
    </div>
  );
}
