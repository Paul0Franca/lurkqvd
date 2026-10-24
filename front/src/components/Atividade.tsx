import type { ExecucaoRecente } from "../api";
import { ROTULO, duracao, relativo } from "../lib/formato";
import { link } from "../rotas";
import Avatar from "./Avatar";

interface Props {
  execucoes: ExecucaoRecente[] | null;
}

function quem(e: ExecucaoRecente): string {
  if (e.usuario_nome) return e.usuario_nome.split(" ")[0];
  if (e.usuario_email) return e.usuario_email.split("@")[0];
  if (e.token_nome) return e.token_nome;
  return e.origem === "agendador" ? "Agendamento" : e.origem === "airflow" ? "Airflow" : e.origem === "aplicacao" ? "Aplicação" : "Sistema";
}

export default function Atividade({ execucoes }: Props) {
  return (
    <section aria-labelledby="titulo-atividade" className="self-start overflow-hidden rounded-2xl border border-border bg-card">
      <h2 id="titulo-atividade" className="border-b border-border px-5 py-4 font-sora text-sm font-semibold">
        Atividade recente
      </h2>

      {!execucoes ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">Carregando…</p>
      ) : execucoes.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">As execuções aparecem aqui assim que alguém rodar uma carga.</p>
      ) : (
        <ol className="divide-y divide-border">
          {execucoes.map((e) => (
            <li key={e.id}>
              <a href={link({ tela: "carga", id: e.carga_id })} className="flex gap-3 px-5 py-3.5 transition-colors hover:bg-secondary/60">
              <span className={`ponto-status ponto-${e.status}`} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate font-mono text-[13px] font-semibold" title={e.carga_nome}>
                    {e.carga_nome}
                  </span>
                  <time className="shrink-0 text-xs text-muted-foreground" dateTime={e.solicitado_em} title={new Date(e.solicitado_em).toLocaleString("pt-BR")}>
                    {relativo(e.solicitado_em)}
                  </time>
                </div>
                <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span>
                    {ROTULO[e.status]}
                    {e.status === "sucesso" && ` em ${duracao(e.seg_total)}`}
                    {", por"}
                  </span>
                  {e.usuario_nome || e.usuario_email ? (
                    <Avatar nome={e.usuario_nome} email={e.usuario_email} foto={e.usuario_foto} tamanho={16} />
                  ) : null}
                  <span>{quem(e)}</span>
                </p>
                {e.erro && (
                  <p className="mt-1 line-clamp-2 text-xs text-destructive" title={e.erro}>
                    {e.erro}
                  </p>
                )}
              </div>
              </a>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
