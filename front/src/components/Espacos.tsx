import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, Search } from "lucide-react";
import type { Api, EspacoResumo, Usuario } from "../api";
import { TIPO_ESPACO, relativo, tamanho } from "../lib/formato";
import { link } from "../rotas";
import { IconeEspaco } from "./comum";

interface Props {
  api: Api;
  usuario: Usuario;
}

export default function Espacos({ api, usuario }: Props) {
  const [espacos, setEspacos] = useState<EspacoResumo[] | null>(null);
  const [busca, setBusca] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [sincronizando, setSincronizando] = useState(false);

  useEffect(() => {
    api.resumoEspacos().then(setEspacos).catch((e: Error) => setErro(e.message));
  }, [api]);

  async function sincronizar() {
    setSincronizando(true);
    setErro(null);
    try {
      await api.sincronizarEspacos();
      setEspacos(await api.resumoEspacos());
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSincronizando(false);
    }
  }

  const termo = busca.trim().toLowerCase();
  const visiveis = (espacos ?? []).filter((e) => !termo || e.nome.toLowerCase().includes(termo));
  const comCargas = visiveis.filter((e) => e.qtd_cargas > 0);
  const semCargas = visiveis.filter((e) => e.qtd_cargas === 0);

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-sora text-[28px] font-semibold tracking-[-0.02em]">Espaços</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Cada espaço da Qlik Cloud funciona como um repositório: pastas e cargas ficam exatamente onde os apps leem os QVDs.
          </p>
        </div>
        <div className="flex gap-3">
          <label className="relative">
            <span className="sr-only">Buscar espaço</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar espaço" className="campo w-[240px] pl-9" />
          </label>
          {usuario.papel === "admin" && (
            <button className="btn-secundario inline-flex items-center gap-2" onClick={sincronizar} disabled={sincronizando}>
              <RefreshCw className={`h-4 w-4 ${sincronizando ? "animate-spin" : ""}`} />
              Atualizar da Qlik
            </button>
          )}
        </div>
      </div>

      {erro && <p className="alerta alerta-erro mt-6">{erro}</p>}

      {!espacos ? (
        <p className="vazio mt-8">Carregando espaços…</p>
      ) : visiveis.length === 0 ? (
        <div className="vazio-grande mt-8">
          <p className="vazio-titulo">{termo ? "Nenhum espaço com esse nome." : "Nenhum espaço sincronizado."}</p>
          <p className="vazio">{termo ? "Tente outro termo." : "Use “Atualizar da Qlik” para trazer os espaços do tenant."}</p>
        </div>
      ) : (
        <>
          {comCargas.length > 0 && (
            <Grupo titulo="Com cargas">
              {comCargas.map((e) => (
                <CartaoEspaco key={e.connection_id} espaco={e} />
              ))}
            </Grupo>
          )}
          {semCargas.length > 0 && (
            <Grupo titulo={comCargas.length ? "Outros espaços" : "Espaços"}>
              {semCargas.map((e) => (
                <CartaoEspaco key={e.connection_id} espaco={e} />
              ))}
            </Grupo>
          )}
        </>
      )}
    </div>
  );
}

function Grupo({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">{titulo}</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{children}</div>
    </section>
  );
}

function CartaoEspaco({ espaco: e }: { espaco: EspacoResumo }) {
  const temCargas = e.qtd_cargas > 0;
  return (
    <a
      href={link({ tela: "espaco", connectionId: e.connection_id, pasta: "" })}
      className="cartao-espaco group relative flex flex-col rounded-2xl border border-border bg-card p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-background">
          <IconeEspaco ativo={temCargas} className="h-5 w-5" />
        </span>
        <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
          {TIPO_ESPACO[e.tipo] ?? e.tipo}
        </span>
      </div>

      <h3 className="mt-4 truncate font-sora text-[15px] font-semibold tracking-tight" title={e.nome}>
        {e.nome}
      </h3>

      {temCargas ? (
        <>
          <p className="mt-1 text-sm text-muted-foreground">
            {e.qtd_cargas === 1 ? "1 carga" : `${e.qtd_cargas} cargas`}
            {e.bytes_publicados > 0 && <>, {tamanho(e.bytes_publicados)} publicados</>}
          </p>
          <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-3 text-xs text-muted-foreground">
            {e.com_erro > 0 ? (
              <span className="inline-flex items-center gap-1.5 text-destructive">
                <AlertTriangle className="h-3.5 w-3.5" />
                {e.com_erro === 1 ? "1 com erro" : `${e.com_erro} com erro`}
              </span>
            ) : e.em_andamento > 0 ? (
              <span className="inline-flex items-center gap-1.5 text-primary">
                <span className="ponto-status ponto-rodando !mt-0" aria-hidden="true" />
                Rodando agora
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5">
                <span className="ponto-status ponto-sucesso !mt-0" aria-hidden="true" />
                Tudo em dia
              </span>
            )}
            {e.ultima_execucao && <span>{relativo(e.ultima_execucao)}</span>}
          </div>
        </>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">Nenhuma carga ainda</p>
      )}
    </a>
  );
}
