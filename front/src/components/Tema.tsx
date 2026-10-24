// Botão do topo (alterna claro/escuro) e seletor do menu do usuário (claro, escuro ou seguir o sistema).

import { Monitor, Moon, Sun } from "lucide-react";
import { centro, definirTema, type PreferenciaTema, useTema } from "../lib/tema";

export function BotaoTema() {
  const { tema } = useTema();
  const proximo = tema === "escuro" ? "claro" : "escuro";
  return (
    <button
      type="button"
      className="botao-tema"
      aria-label={`Mudar para o tema ${proximo}`}
      title={`Tema ${proximo}`}
      onClick={(e) => definirTema(proximo, centro(e.currentTarget))}
    >
      <Sun className="icone-sol h-[18px] w-[18px]" aria-hidden="true" />
      <Moon className="icone-lua h-[17px] w-[17px]" aria-hidden="true" />
    </button>
  );
}

const OPCOES: { valor: PreferenciaTema; rotulo: string; Icone: typeof Sun }[] = [
  { valor: "claro", rotulo: "Claro", Icone: Sun },
  { valor: "escuro", rotulo: "Escuro", Icone: Moon },
  { valor: "sistema", rotulo: "Sistema", Icone: Monitor },
];

export function SeletorTema() {
  const { preferencia } = useTema();
  return (
    <div className="seletor-tema">
      <span className="text-xs text-muted-foreground">Aparência</span>
      <div role="radiogroup" aria-label="Aparência" className="segmentos w-full">
        {OPCOES.map(({ valor, rotulo, Icone }) => (
          <button
            key={valor}
            type="button"
            role="radio"
            aria-checked={preferencia === valor}
            className="segmento inline-flex flex-1 items-center justify-center gap-1.5"
            onClick={(e) => definirTema(valor, centro(e.currentTarget))}
          >
            <Icone className="h-3.5 w-3.5" aria-hidden="true" />
            {rotulo}
          </button>
        ))}
      </div>
    </div>
  );
}
