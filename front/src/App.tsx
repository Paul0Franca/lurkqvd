import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Api, type Sessao, type Usuario } from "./api";
import { limparToken, salvarToken, tokenSalvo } from "./sessao";
import Login from "./components/Login";
import { PaginaTrocaSenha } from "./components/Senha";
import Painel from "./components/Painel";
import Espacos from "./components/Espacos";
import EspacoView from "./components/EspacoView";
import CargaDetalhe from "./components/CargaDetalhe";
import CargasLista from "./components/CargasLista";
import AplicacaoDetalhe from "./components/AplicacaoDetalhe";
import NovaCargaPagina from "./components/NovaCargaPagina";
import { link, useRota } from "./rotas";
import { Assinatura, SubLogoQVD } from "./components/Logo";
import MenuUsuario from "./components/MenuUsuario";
import { BotaoTema } from "./components/Tema";
import Configuracoes from "./components/Configuracoes";
import { Settings } from "lucide-react";

/** true quando a página já rolou um pouco (o topo muda de visual). */
function useRolado(limite = 8): boolean {
  const [rolado, setRolado] = useState(() => typeof window !== "undefined" && window.scrollY > limite);
  useEffect(() => {
    const aoRolar = () => setRolado(window.scrollY > limite);
    window.addEventListener("scroll", aoRolar, { passive: true });
    return () => window.removeEventListener("scroll", aoRolar);
  }, [limite]);
  return rolado;
}

export default function App() {
  const [token, setToken] = useState<string | null>(() => tokenSalvo());
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [configAberta, setConfigAberta] = useState(false);
  const fecharConfig = useCallback(() => setConfigAberta(false), []);
  const tokenLogado = useRef<string | null>(null); // evita buscar o mesmo usuário duas vezes
  const [senhaTemporaria, setSenhaTemporaria] = useState<string>(); // a digitada no login, para não pedir de novo
  const rota = useRota();
  const rolado = useRolado();
  const secao = rota.tela === "painel" ? "painel" : rota.tela === "espacos" || rota.tela === "espaco" ? "espacos" : "cargas";

  const sair = useCallback((motivo?: string) => {
    limparToken();
    setSenhaTemporaria(undefined);
    setToken(null);
    setUsuario(null);
    setErro(motivo ?? null);
  }, []);

  const api = useMemo(
    () => (token ? new Api(token, () => sair("Sessão expirada. Faça login novamente.")) : null),
    [token, sair],
  );

  // Com token (login novo ou aba recarregada), busca o usuário.
  useEffect(() => {
    if (!api || tokenLogado.current === token) return;
    tokenLogado.current = token;
    api
      .eu()
      .then(setUsuario)
      .catch((e: Error) => sair(e.message));
  }, [api, token, sair]);

  function aoEntrar(sessao: Sessao, senha: string) {
    salvarToken(sessao.token, sessao.expira_em);
    setSenhaTemporaria(sessao.usuario.trocar_senha ? senha : undefined);
    tokenLogado.current = sessao.token; // o usuário já veio na resposta do login
    setErro(null);
    setUsuario(sessao.usuario);
    setToken(sessao.token);
  }

  // "Sair": encerra a sessão na API (se falhar, a sessão vence sozinha) e volta para o login
  const sairDaConta = useCallback(() => {
    api?.sair().catch(() => {});
    sair();
  }, [api, sair]);

  if (!api) return <Login aoEntrar={aoEntrar} erro={erro} />;
  if (!usuario) return <div className="carregando">Entrando…</div>;
  if (usuario.trocar_senha)
    return (
      <PaginaTrocaSenha
        api={api}
        usuario={usuario}
        senhaAtual={senhaTemporaria}
        aoConcluir={(u) => {
          setSenhaTemporaria(undefined);
          setUsuario(u);
        }}
        aoSair={sairDaConta}
      />
    );

  return (
    <div className="app">
      <header className="topo" data-rolado={rolado || undefined}>
        <div className="flex items-center gap-8">
          <a href={link({ tela: "painel" })} className="marca-topo" aria-label="LurkQVD, ir para o painel">
            <SubLogoQVD tamanho={30} corForma="currentColor" corOlhos="var(--lq-surface)" pisca />
            <Assinatura />
          </a>
          <nav aria-label="Seções" className="abas">
            <a href={link({ tela: "painel" })} className="aba" aria-current={secao === "painel" ? "page" : undefined}>
              Painel
            </a>
            <a href={link({ tela: "cargas" })} className="aba" aria-current={secao === "cargas" ? "page" : undefined}>
              Cargas
            </a>
            <a href={link({ tela: "espacos" })} className="aba" aria-current={secao === "espacos" ? "page" : undefined}>
              Espaços
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-1.5">
          <BotaoTema />
          {usuario.papel === "admin" && (
            <button
              type="button"
              className="botao-config"
              aria-label="Configurações"
              title="Configurações"
              aria-haspopup="dialog"
              aria-expanded={configAberta}
              onClick={() => setConfigAberta(true)}
            >
              <Settings className="h-[18px] w-[18px]" />
            </button>
          )}
          <MenuUsuario api={api} usuario={usuario} aoSair={sairDaConta} />
        </div>
      </header>
      <main>
        {rota.tela === "painel" && <Painel api={api} usuario={usuario} aoAbrirConfig={usuario.papel === "admin" ? () => setConfigAberta(true) : undefined} />}
        {rota.tela === "espacos" && <Espacos api={api} usuario={usuario} />}
        {rota.tela === "espaco" && (
          <EspacoView key={`${rota.connectionId}/${rota.pasta}`} api={api} usuario={usuario} connectionId={rota.connectionId} pasta={rota.pasta} />
        )}
        {rota.tela === "cargas" && (
          <CargasLista key={`${rota.connectionId}/${rota.pasta}`} api={api} usuario={usuario} connectionId={rota.connectionId} pasta={rota.pasta} visao={rota.visao} />
        )}
        {rota.tela === "nova-carga" && <NovaCargaPagina api={api} connectionIdInicial={rota.connectionId} pastaInicial={rota.pasta} />}
        {rota.tela === "aplicacao" && <AplicacaoDetalhe key={rota.id} api={api} usuario={usuario} id={rota.id} />}
        {rota.tela === "carga" && <CargaDetalhe key={rota.id} api={api} usuario={usuario} id={rota.id} />}
      </main>
      {configAberta && usuario.papel === "admin" && <Configuracoes api={api} usuario={usuario} aoFechar={fecharConfig} />}
    </div>
  );
}
