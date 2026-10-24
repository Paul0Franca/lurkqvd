// Gestão da estrutura de um espaço: navegar e criar pastas (espelhadas na Qlik)
// e ver os arquivos de cada pasta, com a carga que gera cada um.

import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, CalendarClock, ChevronRight, FileText, Folder, FolderPlus, Plus } from "lucide-react";
import type { Api, ArquivoPasta, ConteudoEspaco, Usuario } from "../api";
import { descrever } from "../lib/agenda";
import { TIPO_ESPACO, dataHora, relativo, tamanho } from "../lib/formato";
import { link } from "../rotas";
import { IconeEspaco, Migalhas, StatusBadge, type Migalha } from "./comum";
import NovaPasta from "./NovaPasta";

interface Props {
  api: Api;
  usuario: Usuario;
  connectionId: string;
  pasta: string;
}

export default function EspacoView({ api, usuario, connectionId, pasta }: Props) {
  const [conteudo, setConteudo] = useState<ConteudoEspaco | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [novaPasta, setNovaPasta] = useState(false);

  const admin = usuario.papel === "admin";

  const carregar = useCallback(() => {
    api
      .conteudoEspaco(connectionId, pasta)
      .then((c) => {
        setConteudo(c);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));
  }, [api, connectionId, pasta]);

  // recriado a cada pasta (key no App): o estado já começa vazio
  useEffect(carregar, [carregar]);

  const fecharPasta = useCallback(() => setNovaPasta(false), []);

  const nomeEspaco = conteudo?.espaco.nome ?? "…";
  const partes = pasta ? pasta.split("/") : [];
  const migalhas: Migalha[] = [
    { rotulo: "Espaços", href: link({ tela: "espacos" }) },
    { rotulo: nomeEspaco, href: link({ tela: "espaco", connectionId, pasta: "" }) },
    ...partes.map((p, i) => ({ rotulo: p, href: link({ tela: "espaco", connectionId, pasta: partes.slice(0, i + 1).join("/") }) })),
  ];

  const arquivos = conteudo?.arquivos ?? [];
  const vazio = conteudo && conteudo.pastas.length === 0 && arquivos.length === 0;

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6">
      <Migalhas itens={migalhas} />

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate font-sora text-[28px] font-semibold tracking-[-0.02em]">{partes.at(-1) ?? nomeEspaco}</h1>
          {conteudo && (
            <p className="mt-1 text-sm text-muted-foreground">
              {partes.length ? `Pasta em ${nomeEspaco}` : `Espaço ${(TIPO_ESPACO[conteudo.espaco.tipo] ?? conteudo.espaco.tipo).toLowerCase()} na Qlik Cloud`}
            </p>
          )}
        </div>
        {admin && conteudo && (
          <button className="btn-primario inline-flex items-center gap-2" onClick={() => setNovaPasta(true)}>
            <FolderPlus className="h-4 w-4" />
            Nova pasta
          </button>
        )}
      </div>

      {erro && <p className="alerta alerta-erro mt-6">{erro}</p>}
      {conteudo?.aviso && <p className="mt-6 text-sm text-muted-foreground">{conteudo.aviso}</p>}

      {!conteudo && !erro ? (
        <p className="vazio mt-8">Carregando…</p>
      ) : (
        conteudo && (
          <>
            {vazio ? (
              <div className="vazio-grande mt-8">
                <p className="vazio-titulo">{partes.length ? "Pasta vazia." : "Este espaço ainda não tem pastas."}</p>
                <p className="vazio">
                  {admin ? "Crie subpastas para organizar ou publique a primeira carga aqui." : "Quando houver pastas ou arquivos, eles aparecem aqui."}
                </p>
                {admin && (
                  <a href={link({ tela: "nova-carga", connectionId, pasta: pasta || undefined })} className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
                    <Plus className="h-3.5 w-3.5" />
                    Nova carga nesta pasta
                  </a>
                )}
              </div>
            ) : (
              <>
                {conteudo.pastas.length > 0 && (
                  <section className="mt-8" aria-labelledby="titulo-pastas">
                    <h2 id="titulo-pastas" className="mb-3 text-sm font-medium text-muted-foreground">
                      Pastas
                    </h2>
                    <ul className="lista-repo overflow-hidden rounded-2xl border border-border bg-card">
                      {conteudo.pastas.map((p) => (
                        <li key={p.caminho}>
                          <a href={link({ tela: "espaco", connectionId, pasta: p.caminho })} className="linha-repo">
                            <span className="icone-carga">
                              <Folder className="h-4 w-4 text-muted-foreground" fill="currentColor" fillOpacity={0.15} />
                            </span>
                            <span className="min-w-0 flex-1 truncate font-medium">{p.nome}</span>
                            <span className="text-sm text-muted-foreground">
                              {p.qtd_cargas === 0 ? "sem cargas" : p.qtd_cargas === 1 ? "1 carga" : `${p.qtd_cargas} cargas`}
                            </span>
                            <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                          </a>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <section className="mt-8" aria-labelledby="titulo-arquivos">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h2 id="titulo-arquivos" className="text-sm font-medium text-muted-foreground">
                      Arquivos nesta pasta{arquivos.length > 0 && ` (${arquivos.length})`}
                    </h2>
                    {admin && (
                      <a href={link({ tela: "nova-carga", connectionId, pasta: pasta || undefined })} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                        Nova carga aqui
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                  {arquivos.length === 0 ? (
                    <p className="rounded-2xl border border-dashed border-border px-5 py-4 text-sm text-muted-foreground">
                      Nenhum arquivo diretamente nesta pasta.
                    </p>
                  ) : (
                    <div className="grid gap-4 md:grid-cols-2">
                      {arquivos.map((a) => (
                        <CartaoArquivo key={a.file_id ?? a.caminho} arquivo={a} />
                      ))}
                    </div>
                  )}
                </section>
              </>
            )}
          </>
        )
      )}

      {admin && conteudo && novaPasta && (
        <NovaPasta
          api={api}
          aberto
          aoFechar={fecharPasta}
          connectionId={connectionId}
          pasta={pasta}
          nomeEspaco={nomeEspaco}
          aoCriar={() => {
            setNovaPasta(false);
            carregar();
          }}
        />
      )}
    </div>
  );
}

/** Um arquivo da pasta: o QVD em destaque em cima, a carga que o gera embaixo. */
function CartaoArquivo({ arquivo: a }: { arquivo: ArquivoPasta }) {
  const c = a.carga;
  const qvd = a.nome.toLowerCase().endsWith(".qvd");
  const publicado = Boolean(a.file_id);

  return (
    <article className={`cartao-arquivo ${c ? "cartao-arquivo-gerenciado" : ""}`}>
      {/* o arquivo */}
      <div className="flex items-start gap-3 p-4">
        <span className={`icone-arquivo ${publicado ? "" : "icone-arquivo-pendente"}`}>
          {qvd ? <IconeEspaco ativo={publicado} className="h-5 w-5" /> : <FileText className="h-5 w-5 text-muted-foreground" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-[13px] font-semibold" title={a.caminho}>
            {a.nome}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {publicado ? (
              <>
                {tamanho(a.tamanho_bytes)}
                {a.modificado_em && (
                  <>
                    {", atualizado "}
                    <time dateTime={a.modificado_em} title={dataHora(a.modificado_em)}>
                      {relativo(a.modificado_em)}
                    </time>
                  </>
                )}
              </>
            ) : (
              "Ainda não publicado na Qlik"
            )}
          </p>
        </div>
      </div>

      {/* quem gera */}
      {c ? (
        <a href={link({ tela: "carga", id: c.id })} className="rodape-arquivo group">
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-muted-foreground">Gerado pela carga</span>
            <span className="block truncate font-mono text-[13px] font-semibold group-hover:underline">{c.nome}</span>
            <span className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              {c.agendamento && <CalendarClock className="h-3 w-3 text-primary" aria-hidden="true" />}
              {descrever(c.agendamento)}
              {c.agendamento && c.ativo && c.proxima_execucao && `, próxima ${relativo(c.proxima_execucao)}`}
            </span>
          </span>
          <StatusBadge status={c.ultimo_status} />
          <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        </a>
      ) : (
        <div className="rodape-arquivo text-xs text-muted-foreground">Não é gerado pelo LurkQVD (enviado por outro processo ou à mão).</div>
      )}
    </article>
  );
}
