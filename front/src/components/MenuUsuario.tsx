import { useEffect, useRef, useState } from "react";
import { ChevronDown, KeyRound, LogOut } from "lucide-react";
import type { Api, Usuario } from "../api";
import Avatar from "./Avatar";
import { DESCRICAO_PAPEL } from "../lib/papeis";
import { DialogoTrocaSenha } from "./Senha";
import { SeletorTema } from "./Tema";

interface Props {
  api: Api;
  usuario: Usuario;
  aoSair: () => void;
}

export default function MenuUsuario({ api, usuario, aoSair }: Props) {
  const [aberto, setAberto] = useState(false);
  const [trocandoSenha, setTrocandoSenha] = useState(false);
  const [versao, setVersao] = useState<string | null>(null);
  const raiz = useRef<HTMLDivElement>(null);
  const primeiroNome = (usuario.nome ?? usuario.email).split(" ")[0];

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => !raiz.current?.contains(e.target as Node) && setAberto(false);
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && setAberto(false);
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto]);

  // versão do servidor: buscada só na 1ª vez que o menu abre
  useEffect(() => {
    if (!aberto || versao) return;
    api.saude().then((s) => setVersao(s.versao)).catch(() => {});
  }, [aberto, versao, api]);

  return (
    <div ref={raiz} className="relative">
      <button
        type="button"
        className="botao-usuario"
        aria-haspopup="menu"
        aria-expanded={aberto}
        onClick={() => setAberto((a) => !a)}
      >
        <Avatar nome={usuario.nome} email={usuario.email} foto={usuario.foto_url} tamanho={30} className="avatar-anel" />
        <span className="hidden text-sm font-medium sm:inline">{primeiroNome}</span>
        <ChevronDown className="hidden h-3.5 w-3.5 text-muted-foreground sm:inline" aria-hidden="true" />
      </button>

      {aberto && (
        <div role="menu" className="menu-usuario">
          <div className="flex items-center gap-3 p-4">
            <Avatar nome={usuario.nome} email={usuario.email} foto={usuario.foto_url} tamanho={44} />
            <div className="min-w-0">
              <p className="truncate font-sora text-sm font-semibold">{usuario.nome ?? usuario.email}</p>
              <p className="truncate text-xs text-muted-foreground">{usuario.email}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 border-t border-border px-4 py-3">
            <span className={`papel papel-${usuario.papel}`}>{usuario.papel}</span>
            <span className="text-xs text-muted-foreground">{DESCRICAO_PAPEL[usuario.papel]}</span>
          </div>
          <SeletorTema />
          <button
            role="menuitem"
            type="button"
            className="menu-usuario-item"
            onClick={() => {
              setAberto(false);
              setTrocandoSenha(true);
            }}
          >
            <KeyRound className="h-4 w-4" aria-hidden="true" />
            Alterar senha
          </button>
          <button role="menuitem" type="button" className="menu-usuario-item" onClick={aoSair}>
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Sair
          </button>
          {versao && (
            <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">LurkQVD v{versao}</p>
          )}
        </div>
      )}
      {trocandoSenha && <DialogoTrocaSenha api={api} usuario={usuario} aoFechar={() => setTrocandoSenha(false)} />}
    </div>
  );
}
