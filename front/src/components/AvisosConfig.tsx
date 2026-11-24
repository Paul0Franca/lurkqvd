// Configurações › Avisos na ferramenta: o admin publica um recado que aparece no sino de todo mundo
// (ou só de editores/admins) e, se quiser, abre o balão na tela de quem entrar.

import { useCallback, useEffect, useState } from "react";
import { Megaphone, Sparkles, Trash2, X } from "lucide-react";
import type { Api, AvisoAdmin, NovoAviso, Papel } from "../api";
import { dataHora, relativo } from "../lib/formato";

const PUBLICO: Record<Papel, string> = { leitor: "Todo mundo", editor: "Editores e admins", admin: "Só admins" };

const VAZIO: NovoAviso = { titulo: "", texto: "", link_url: "", link_rotulo: "", publico: "leitor", abrir_ao_entrar: true, expira_em: "" };

export default function AvisosConfig({ api }: { api: Api }) {
  const [lista, setLista] = useState<AvisoAdmin[] | null>(null);
  const [form, setForm] = useState<NovoAviso>(VAZIO);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api
      .avisosAdmin()
      .then(setLista)
      .catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(carregar, [carregar]);

  async function publicar(e: React.FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setErro(null);
    setOk(null);
    try {
      // a data do campo é o fim do dia escolhido, no fuso de quem publica
      const expira = form.expira_em ? new Date(`${form.expira_em}T23:59:59`).toISOString() : null;
      await api.publicarAviso({ ...form, link_url: form.link_url || null, link_rotulo: form.link_rotulo || null, expira_em: expira });
      setForm(VAZIO);
      setOk("Aviso publicado. Ele aparece no sino de quem for do público na próxima vez que a tela buscar (até 5 min).");
      carregar();
    } catch (err) {
      setErro((err as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  async function remover(a: AvisoAdmin) {
    if (!confirm(`Remover o aviso "${a.titulo}"? Ele some do sino de todo mundo.`)) return;
    setErro(null);
    try {
      await api.removerAviso(a.id);
      carregar();
    } catch (err) {
      setErro((err as Error).message);
    }
  }

  const campo = <K extends keyof NovoAviso>(k: K, v: NovoAviso[K]) => setForm((f) => ({ ...f, [k]: v }));
  const [hoje] = useState(() => new Date().toISOString().slice(0, 10));

  return (
    <div className="flex flex-col gap-8">
      <p className="text-sm text-muted-foreground">
        Recados para quem usa o LurkQVD: aparecem no sino do topo e, se você quiser, abrem num balão na tela até a pessoa marcar
        como lido. Para avisos por e-mail (carga com erro, API key da Qlik), veja Notificações.
      </p>

      {erro && (
        <p className="alerta alerta-erro !mb-0 flex items-start justify-between gap-3" role="alert">
          {erro}
          <button type="button" aria-label="Fechar aviso" onClick={() => setErro(null)}>
            <X className="h-4 w-4" />
          </button>
        </p>
      )}

      <form onSubmit={publicar} className="flex flex-col gap-4 rounded-2xl border border-border p-5">
        <h3 className="text-sm font-semibold">Publicar um aviso</h3>
        <Campo rotulo="Título">
          <input className="campo" required maxLength={120} value={form.titulo} onChange={(e) => campo("titulo", e.target.value)} placeholder="Ex.: Manutenção do SQL Server no sábado" />
        </Campo>
        <Campo rotulo="Mensagem" ajuda="Texto simples; as quebras de linha são mantidas.">
          <textarea className="campo min-h-[96px] resize-y" required maxLength={2000} value={form.texto} onChange={(e) => campo("texto", e.target.value)} placeholder="O que as pessoas precisam saber" />
        </Campo>
        <div className="grid gap-4 sm:grid-cols-5">
          <Campo rotulo="Link (opcional)" classe="sm:col-span-3">
            <input className="campo" type="url" pattern="https?://.+" maxLength={500} value={form.link_url ?? ""} onChange={(e) => campo("link_url", e.target.value)} placeholder="https://…" />
          </Campo>
          <Campo rotulo="Texto do botão" classe="sm:col-span-2">
            <input className="campo" maxLength={60} value={form.link_rotulo ?? ""} disabled={!form.link_url} onChange={(e) => campo("link_rotulo", e.target.value)} placeholder="Abrir link" />
          </Campo>
          <Campo rotulo="Quem vê" classe="sm:col-span-3">
            <select className="campo" value={form.publico} onChange={(e) => campo("publico", e.target.value as Papel)}>
              {(Object.keys(PUBLICO) as Papel[]).map((p) => (
                <option key={p} value={p}>
                  {PUBLICO[p]}
                </option>
              ))}
            </select>
          </Campo>
          <Campo rotulo="Some em (opcional)" classe="sm:col-span-2" ajuda="Vazio = fica até você remover">
            <input className="campo" type="date" min={hoje} value={form.expira_em ?? ""} onChange={(e) => campo("expira_em", e.target.value)} />
          </Campo>
        </div>
        <label className="inline-flex cursor-pointer items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1 accent-[var(--lq-accent)]" checked={form.abrir_ao_entrar} onChange={(e) => campo("abrir_ao_entrar", e.target.checked)} />
          <span>
            Abrir na tela ao entrar
            <span className="block text-xs text-muted-foreground">Mostra o balão com o fundo desfocado até a pessoa clicar em “Entendi”. Desligado, fica só no sino.</span>
          </span>
        </label>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {ok && <p className="mr-auto text-xs text-[var(--lq-ok-fg)]">{ok}</p>}
          <button type="submit" className="btn-primario inline-flex items-center gap-2" disabled={salvando}>
            <Megaphone className="h-4 w-4" aria-hidden="true" />
            {salvando ? "Publicando…" : "Publicar aviso"}
          </button>
        </div>
      </form>

      <section aria-labelledby="titulo-publicados">
        <h3 id="titulo-publicados" className="text-sm font-semibold">
          Publicados
        </h3>
        {!lista ? (
          <p className="vazio">Carregando…</p>
        ) : lista.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Nenhum aviso publicado.</p>
        ) : (
          <ul className="mt-3 overflow-hidden rounded-2xl border border-border">
            {lista.map((a) => (
              <li key={a.id} className={`linha-usuario ${a.expirado ? "opacity-60" : ""}`}>
                <span className="aviso-icone aviso-icone-p" aria-hidden="true">
                  {a.origem === "sistema" ? <Sparkles className="h-4 w-4" /> : <Megaphone className="h-4 w-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{a.titulo}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    <span title={dataHora(a.publicado_em)}>{relativo(a.publicado_em)}</span>
                    {" · "}
                    {a.origem === "sistema" ? "novidade do LurkQVD" : a.criado_por_nome ? `por ${a.criado_por_nome.split(" ")[0]}` : "admin"}
                    {" · "}
                    {PUBLICO[a.publico].toLowerCase()}
                    {a.abrir_ao_entrar ? ", abre na tela" : ", só no sino"}
                    {" · "}
                    {a.expirado ? "expirado" : a.expira_em ? `some ${relativo(a.expira_em)}` : "sem prazo"}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground" title="Pessoas ativas do público que já leram">
                  {a.leituras} de {a.publico_total} leram
                </span>
                <button type="button" className="botao-icone botao-icone-perigo" title="Remover" aria-label={`Remover o aviso ${a.titulo}`} onClick={() => remover(a)}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Campo({ rotulo, classe, ajuda, children }: { rotulo: string; classe?: string; ajuda?: string; children: React.ReactNode }) {
  return (
    <label className={`flex flex-col gap-1 ${classe ?? ""}`}>
      <span className="text-xs font-medium">{rotulo}</span>
      {children}
      {ajuda && <span className="text-[11px] text-muted-foreground">{ajuda}</span>}
    </label>
  );
}
