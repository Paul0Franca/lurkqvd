import { Cloud, Database, FileStack } from "lucide-react";

// O caminho que uma carga percorre. É uma sequência real, por isso a ordem visual.
// A última etapa acende no verde da Qlik quando o trilho chega nela:
// uma referência à cor da marca, sem reproduzir o logo.
// Depois de preenchido, um brilho segue correndo pelo trilho (os dados não param).
const ETAPAS = [
  { icone: Database, nome: "Banco de dados", texto: "consulta", destino: false },
  { icone: FileStack, nome: "QVD", texto: "gerado fora da Qlik", destino: false },
  { icone: Cloud, nome: "Qlik Cloud", texto: "publicado via API", destino: true },
];

/** tom "escuro": para fundos sempre escuros (o painel da tela de login), independente do tema. */
export default function FluxoQVD({ tom = "tema" }: { tom?: "tema" | "escuro" }) {
  const escuro = tom === "escuro";
  return (
    <ol className={`relative grid grid-cols-3 ${escuro ? "fluxo-qvd-escuro" : ""}`} aria-label="Caminho de uma carga">
      {/* trilho que liga as etapas; preenche em ciano uma vez, ao abrir a página */}
      <span aria-hidden="true" className={`absolute left-5 right-[calc(33.333%-1.25rem)] top-5 h-px ${escuro ? "bg-white/10" : "bg-border"}`} />
      <span
        aria-hidden="true"
        className="lurk-trilho absolute left-5 right-[calc(33.333%-1.25rem)] top-5 h-px origin-left bg-gradient-to-r from-primary to-[#009845]"
      />
      {/* brilho que corre pelo trilho depois que ele se preenche */}
      <span aria-hidden="true" className="absolute left-5 right-[calc(33.333%-1.25rem)] top-[19px] h-[3px] overflow-hidden">
        <span className="lurk-trilho-pulso" />
      </span>

      {ETAPAS.map(({ icone: Icone, nome, texto, destino }) => (
        <li key={nome} className="relative flex flex-col items-start">
          <span
            className={`relative flex h-10 w-10 items-center justify-center rounded-full border ${
              escuro ? "border-white/15 bg-[#161a1e] text-[#F2F1EC] shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]" : "border-border bg-background text-foreground"
            } ${destino ? "lurk-chegada" : ""}`}
          >
            <Icone className="relative h-[18px] w-[18px]" strokeWidth={1.6} aria-hidden="true" />
          </span>
          <span className={`mt-3 font-sora text-[13px] font-semibold ${escuro ? "text-[#F2F1EC]" : ""}`}>{nome}</span>
          <span className={`mt-0.5 text-xs ${escuro ? "text-[#F2F1EC]/55" : "text-muted-foreground"}`}>{texto}</span>
        </li>
      ))}
    </ol>
  );
}
