// Janela de configurações (só admin): flutua sobre a tela com o fundo desfocado.
// Menu lateral com as seções; as que ainda não existem aparecem em "Em breve".

import { useEffect, useRef, useState } from "react";
import { Bell, Cable, Cloud, Database, KeyRound, ScrollText, Server, Users, X, type LucideIcon } from "lucide-react";
import type { Api, Usuario } from "../api";
import UsuariosAcesso from "./UsuariosAcesso";
import WorkerAgenda from "./WorkerAgenda";
import Auditoria from "./Auditoria";
import QlikCloud from "./QlikCloud";
import FontesDados from "./FontesDados";
import Segredos from "./Segredos";
import ApiLurkqvd from "./ApiLurkqvd";
import Notificacoes from "./Notificacoes";

type Secao = "usuarios" | "qlik" | "fontes" | "segredos" | "api" | "worker" | "notificacoes" | "auditoria";

const SECOES: { id: Secao; nome: string; icone: LucideIcon; pronta: boolean }[] = [
  { id: "usuarios", nome: "Usuários e acesso", icone: Users, pronta: true },
  { id: "worker", nome: "Worker e agenda", icone: Server, pronta: true },
  { id: "qlik", nome: "Qlik Cloud", icone: Cloud, pronta: true },
  { id: "fontes", nome: "Fontes de dados", icone: Database, pronta: true },
  { id: "segredos", nome: "Segredos", icone: KeyRound, pronta: true },
  { id: "api", nome: "API do LurkQVD", icone: Cable, pronta: true },
  { id: "notificacoes", nome: "Notificações", icone: Bell, pronta: true },
  { id: "auditoria", nome: "Auditoria", icone: ScrollText, pronta: true },
];

interface Props {
  api: Api;
  usuario: Usuario;
  aoFechar: () => void;
}

export default function Configuracoes({ api, usuario, aoFechar }: Props) {
  const [secao, setSecao] = useState<Secao>("usuarios");
  const janela = useRef<HTMLDivElement>(null);

  // Esc fecha; a página de trás não rola enquanto a janela está aberta
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && aoFechar();
    document.addEventListener("keydown", tecla);
    window.addEventListener("hashchange", aoFechar); // clicou num link (ex.: uma carga): fecha
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    janela.current?.focus();
    return () => {
      document.removeEventListener("keydown", tecla);
      window.removeEventListener("hashchange", aoFechar);
      document.body.style.overflow = overflow;
    };
  }, [aoFechar]);

  const atual = SECOES.find((s) => s.id === secao)!;

  return (
    <div className="config-camada" role="presentation">
      <button type="button" className="config-fundo" aria-label="Fechar configurações" onClick={aoFechar} />

      <div ref={janela} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="titulo-config" className="config-janela">
        <nav className="config-menu" aria-label="Seções das configurações">
          <p id="titulo-config" className="px-3 pb-3 font-sora text-[15px] font-semibold">
            Configurações
          </p>
          {[true, false].filter((pronta) => SECOES.some((s) => s.pronta === pronta)).map((pronta) => (
            <div key={String(pronta)} className={pronta ? "" : "config-grupo-breve"}>
              {!pronta && <p className="config-grupo-titulo">Em breve</p>}
              <ul className="flex gap-1 md:flex-col">
                {SECOES.filter((s) => s.pronta === pronta).map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className="config-item"
                      aria-current={secao === s.id ? "page" : undefined}
                      disabled={!s.pronta}
                      onClick={() => setSecao(s.id)}
                    >
                      <s.icone className="h-4 w-4 shrink-0" aria-hidden="true" />
                      <span className="truncate">{s.nome}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="config-conteudo">
          <header className="config-cabecalho">
            <h2 className="font-sora text-lg font-semibold tracking-[-0.01em]">{atual.nome}</h2>
            <button type="button" className="config-fechar" aria-label="Fechar" onClick={aoFechar}>
              <X className="h-4 w-4" />
            </button>
          </header>
          <div className="config-rolagem">
            {secao === "usuarios" && <UsuariosAcesso api={api} usuario={usuario} aoAbrirNotificacoes={() => setSecao("notificacoes")} />}
            {secao === "worker" && <WorkerAgenda api={api} />}
            {secao === "qlik" && <QlikCloud api={api} />}
            {secao === "fontes" && <FontesDados api={api} />}
            {secao === "segredos" && <Segredos api={api} />}
            {secao === "api" && <ApiLurkqvd api={api} />}
            {secao === "notificacoes" && <Notificacoes api={api} usuario={usuario} />}
            {secao === "auditoria" && <Auditoria api={api} />}
          </div>
        </div>
      </div>
    </div>
  );
}
