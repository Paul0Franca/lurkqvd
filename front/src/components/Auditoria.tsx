// Configurações > Auditoria: linha do tempo de quem fez o quê, agrupada por dia.

import { useCallback, useEffect, useState } from "react";
import { Bot, ChevronDown, Database, FolderPlus, KeyRound, LogIn, Mail, Play, Settings2, UserCog, type LucideIcon } from "lucide-react";
import type { Api, RegistroAuditoria, UsuarioAdmin } from "../api";
import { descrever } from "../lib/agenda";
import { dataHora } from "../lib/formato";
import { NOME_PAPEL } from "../lib/papeis";
import { link } from "../rotas";
import Avatar from "./Avatar";

type Categoria = "" | "cargas" | "execucoes" | "acessos" | "sistema";

const CATEGORIAS: [Categoria, string][] = [
  ["", "Tudo"],
  ["cargas", "Cargas"],
  ["execucoes", "Execuções"],
  ["acessos", "Acessos"],
  ["sistema", "Sistema"],
];

const ICONE: Record<string, LucideIcon> = {
  "carga.criar": Database,
  "carga.alterar": Database,
  "carga.destino": Database,
  "pasta.criar": FolderPlus,
  "carga.executar": Play,
  "usuario.criar": UserCog,
  "usuario.alterar": UserCog,
  "convite.criar": KeyRound,
  "convite.remover": KeyRound,
  "usuario.redefinir_senha": KeyRound,
  "usuario.trocar_senha": KeyRound,
  "usuario.completar_conta": UserCog,
  "agenda.pausar": Settings2,
  "agenda.retomar": Settings2,
  "config.alterar": Settings2,
  "usuario.login": LogIn,
  "fonte.criar": Database,
  "fonte.alterar": Database,
  "fonte.padrao": Database,
  "fonte.remover": Database,
  "config.qlik": KeyRound,
  "token.criar": KeyRound,
  "token.revogar": KeyRound,
  "config.smtp": Mail,
  "config.smtp_remover": Mail,
  "config.notificacoes": Mail,
};

const AVISO: Record<string, string> = {
  convites: "convite",
  erros_cargas: "carga com erro",
  erros_aplicacoes: "aplicação com erro",
  recuperacao: "voltou a funcionar",
  qlik: "API key da Qlik",
  so_mudanca: "só a primeira falha",
  para_admins: "envio aos admins",
  extras: "os outros e-mails",
};

const CAMPO: Record<string, string> = { query: "a consulta", agendamento: "o agendamento", ativo: "o status" };

const hora = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const diaLongo = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "numeric", month: "long" });

function rotuloDia(iso: string): string {
  const d = new Date(iso);
  const hoje = new Date();
  const ontem = new Date(hoje);
  ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === hoje.toDateString()) return "Hoje";
  if (d.toDateString() === ontem.toDateString()) return "Ontem";
  const t = diaLongo.format(d);
  return t.charAt(0).toUpperCase() + t.slice(1);
}

type De<T> = { de: T; para: T };
const papel = (p: unknown) => NOME_PAPEL[p as keyof typeof NOME_PAPEL] ?? String(p);

/** Quem fez: pessoa, ou o próprio sistema (agendador). */
function autor(r: RegistroAuditoria): string {
  if (r.usuario_nome) return r.usuario_nome.split(" ")[0];
  if (r.usuario_email) return r.usuario_email.split("@")[0];
  if (r.detalhes.token_nome) return String(r.detalhes.token_nome);
  return r.detalhes.origem === "agendador" ? "Agendamento" : "Sistema";
}

/** Frase do registro. Devolve partes para o alvo sair em destaque (e com link, se for carga). */
function frase(r: RegistroAuditoria): { antes: string; alvo?: string; depois?: string } {
  const d = r.detalhes as Record<string, unknown>;
  const alvo = r.alvo_nome ?? r.alvo_id ?? "";
  switch (r.acao) {
    case "carga.criar":
      return { antes: "criou a carga", alvo, depois: d.agendamento ? `, ${descrever(d.agendamento as string).toLowerCase()}` : ", manual" };
    case "carga.alterar": {
      const depois = (d.depois ?? {}) as Record<string, unknown>;
      const campos = Object.keys(depois);
      if (campos.length === 1 && campos[0] === "ativo") return { antes: depois.ativo ? "ativou a carga" : "desativou a carga", alvo };
      const nomes = campos.map((c) => CAMPO[c] ?? c);
      const lista = nomes.length > 1 ? `${nomes.slice(0, -1).join(", ")} e ${nomes.at(-1)}` : (nomes[0] ?? "a carga");
      return { antes: `alterou ${lista} de`, alvo };
    }
    case "carga.executar":
      return { antes: "executou", alvo };
    case "carga.destino": {
      const para = d.para as { qlik_path?: string } | undefined;
      return { antes: "moveu o destino de", alvo, depois: para?.qlik_path ? ` para ${para.qlik_path}` : "" };
    }
    case "pasta.criar":
      return { antes: "criou a pasta", alvo, depois: d.espaco ? ` em ${d.espaco}` : "" };
    case "usuario.criar":
      if (d.admin_padrao) return { antes: "instalação: criou o admin padrão" };
      // antes do login próprio, o usuário era criado no 1º login com o Google (sem alvo)
      return d.por_convite !== undefined || !r.alvo_id || r.alvo_id === String(r.usuario_id)
        ? { antes: d.por_convite ? `entrou pela primeira vez, por convite, como ${papel(d.papel)}` : `entrou pela primeira vez, como ${papel(d.papel)}` }
        : { antes: "cadastrou", alvo, depois: ` como ${papel(d.papel)}` };
    case "usuario.redefinir_senha":
      return { antes: "redefiniu a senha de", alvo };
    case "usuario.trocar_senha":
      return { antes: "trocou a própria senha" };
    case "usuario.completar_conta":
      return { antes: "completou a conta de administrador", depois: d.email ? ` (${d.email})` : "" };
    case "usuario.alterar": {
      const partes: string[] = [];
      const p = d.papel as De<string> | undefined;
      const a = d.ativo as De<boolean> | undefined;
      if (a) partes.push(a.para ? "devolveu o acesso de" : "removeu o acesso de");
      if (p) return { antes: `${partes.length ? partes[0] + " e mudou o papel de" : "mudou o papel de"}`, alvo, depois: ` de ${papel(p.de)} para ${papel(p.para)}` };
      return { antes: partes[0] ?? "alterou", alvo };
    }
    case "convite.criar":
      return { antes: "convidou", alvo, depois: ` como ${papel(d.papel)}` };
    case "convite.remover":
      return { antes: "cancelou o convite de", alvo };
    case "agenda.pausar":
      return { antes: "pausou todos os agendamentos", depois: d.motivo ? `: “${d.motivo}”` : "" };
    case "agenda.retomar":
      return { antes: "retomou os agendamentos" };
    case "config.alterar": {
      const l = d.limite_travada_min as De<number> | undefined;
      return l ? { antes: `mudou o limite de execução travada de ${l.de ?? "—"} para ${l.para} min` } : { antes: "alterou uma configuração" };
    }
    case "usuario.login":
      return { antes: "entrou no LurkQVD" };
    case "fonte.criar":
      return { antes: "cadastrou a fonte", alvo, depois: d.banco ? ` (${d.banco} em ${d.host})${d.padrao ? " como padrão" : ""}` : "" };
    case "fonte.alterar": {
      const campos = Object.keys(d).filter((k) => k !== "nome");
      const nomes: Record<string, string> = { host: "o host", porta: "a porta", banco: "o banco", usuario: "o usuário", senha: "a senha", opcoes: "as opções", tipo: "o tipo" };
      const lista = campos.map((c) => nomes[c] ?? c);
      return { antes: `alterou ${lista.length > 1 ? `${lista.slice(0, -1).join(", ")} e ${lista.at(-1)}` : (lista[0] ?? "")} da fonte`, alvo };
    }
    case "fonte.padrao":
      return { antes: "tornou padrão a fonte", alvo };
    case "fonte.remover":
      return { antes: "removeu a fonte", alvo };
    case "token.criar":
      return { antes: "criou o token de API", alvo, depois: ` (${d.permissao === "leitura" ? "só leitura" : "executar"}${d.validade_dias ? `, ${d.validade_dias} dias` : ", sem validade"})` };
    case "token.revogar":
      return { antes: "revogou o token de API", alvo };
    case "config.qlik":
      return { antes: d.api_key ? "substituiu a API key da Qlik" : "alterou o tenant da Qlik", depois: d.tenant ? ` (${d.tenant})` : "" };
    case "config.smtp":
      if (d.criado) return { antes: "configurou o servidor de e-mail", depois: d.host ? ` (${d.host}:${d.porta})` : "" };
      return { antes: d.senha && Object.keys(d).length <= 2 ? "trocou a senha do servidor de e-mail" : "alterou o servidor de e-mail", depois: d.host ? ` (${d.host})` : "" };
    case "config.smtp_remover":
      return { antes: "desligou o envio de e-mails" };
    case "config.notificacoes": {
      const mudancas = Object.entries(d as Record<string, De<unknown>>).map(([k, v]) =>
        typeof v?.para === "boolean" ? `${v.para ? "ligou" : "desligou"} ${AVISO[k] ?? k}` : `alterou ${AVISO[k] ?? k}`,
      );
      return { antes: `nos avisos por e-mail, ${mudancas.join(", ") || "alterou as preferências"}` };
    }
    default:
      return { antes: r.acao, alvo };
  }
}

export default function Auditoria({ api }: { api: Api }) {
  const [categoria, setCategoria] = useState<Categoria>("");
  const [pessoa, setPessoa] = useState("");
  const [logins, setLogins] = useState(false);
  const [itens, setItens] = useState<RegistroAuditoria[] | null>(null);
  const [proximo, setProximo] = useState<number | null>(null);
  const [carregandoMais, setCarregandoMais] = useState(false);
  const [usuarios, setUsuarios] = useState<UsuarioAdmin[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.usuarios().then(setUsuarios).catch(() => {});
  }, [api]);

  const buscar = useCallback(
    (antesDe?: number) =>
      api.auditoria({
        categoria: categoria || undefined,
        usuarioId: pessoa ? Number(pessoa) : undefined,
        incluirLogins: logins,
        antesDe,
      }),
    [api, categoria, pessoa, logins],
  );

  // filtros mudaram: recomeça do mais recente
  useEffect(() => {
    let vivo = true;
    buscar()
      .then((p) => {
        if (!vivo) return;
        setItens(p.itens);
        setProximo(p.proximo);
        setErro(null);
      })
      .catch((e: Error) => vivo && setErro(e.message));
    return () => {
      vivo = false;
    };
  }, [buscar]);

  async function carregarMais() {
    if (proximo === null) return;
    setCarregandoMais(true);
    try {
      const p = await buscar(proximo);
      setItens((atual) => [...(atual ?? []), ...p.itens]);
      setProximo(p.proximo);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setCarregandoMais(false);
    }
  }

  // agrupa por dia, mantendo a ordem
  const grupos: { dia: string; itens: RegistroAuditoria[] }[] = [];
  for (const r of itens ?? []) {
    const dia = rotuloDia(r.criado_em);
    if (grupos.at(-1)?.dia === dia) grupos.at(-1)!.itens.push(r);
    else grupos.push({ dia, itens: [r] });
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">Tudo o que muda no LurkQVD fica registrado aqui: quem fez, quando e o que mudou.</p>

      {/* filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="segmentos" role="radiogroup" aria-label="Tipo de ação">
          {CATEGORIAS.map(([v, rotulo]) => (
            <button key={v} type="button" role="radio" aria-checked={categoria === v} className="segmento" onClick={() => setCategoria(v)}>
              {rotulo}
            </button>
          ))}
        </div>
        <label htmlFor="filtro-pessoa" className="sr-only">
          Pessoa
        </label>
        <select id="filtro-pessoa" className="campo campo-pequeno w-auto min-w-[160px]" value={pessoa} onChange={(e) => setPessoa(e.target.value)}>
          <option value="">Todas as pessoas</option>
          {usuarios.map((u) => (
            <option key={u.id} value={u.id}>
              {u.nome ?? u.email}
            </option>
          ))}
        </select>
        {categoria === "" && (
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" className="accent-[var(--lq-accent)]" checked={logins} onChange={(e) => setLogins(e.target.checked)} />
            Incluir logins
          </label>
        )}
      </div>

      {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}

      {!itens ? (
        <p className="vazio">Carregando…</p>
      ) : itens.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-border px-5 py-6 text-sm text-muted-foreground">Nada registrado com esses filtros.</p>
      ) : (
        <div className="flex flex-col gap-6">
          {grupos.map((g) => (
            <section key={g.dia} aria-label={g.dia}>
              <h3 className="aud-dia">{g.dia}</h3>
              <ol className="aud-lista">
                {g.itens.map((r) => (
                  <Registro key={r.id} r={r} />
                ))}
              </ol>
            </section>
          ))}
          {proximo !== null && (
            <button type="button" className="btn-secundario self-center" disabled={carregandoMais} onClick={carregarMais}>
              {carregandoMais ? "Carregando…" : "Carregar mais antigos"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Registro({ r }: { r: RegistroAuditoria }) {
  const [aberto, setAberto] = useState(false);
  const Icone = ICONE[r.acao] ?? Settings2;
  const f = frase(r);
  const mudancas = r.acao === "carga.alterar" ? (r.detalhes as { antes?: Record<string, unknown>; depois?: Record<string, unknown> }) : null;
  const temDetalhe = Boolean(mudancas?.depois && Object.keys(mudancas.depois).some((k) => k !== "ativo"));

  return (
    <li className="aud-item">
      <span className="aud-avatar">
        {r.usuario_id ? (
          <Avatar nome={r.usuario_nome} email={r.usuario_email} foto={r.usuario_foto} tamanho={30} />
        ) : (
          <span className="aud-sistema" aria-hidden="true">
            <Bot className="h-4 w-4" />
          </span>
        )}
        <span className="aud-icone" aria-hidden="true">
          <Icone className="h-2.5 w-2.5" />
        </span>
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed">
          <span className="font-medium">{autor(r)}</span> {f.antes}
          {f.alvo && " "}
          {f.alvo &&
            (r.alvo_tipo === "carga" && r.alvo_id ? (
              <a href={link({ tela: "carga", id: Number(r.alvo_id) })} className="aud-alvo aud-alvo-link">
                {f.alvo}
              </a>
            ) : (
              <span className="aud-alvo">{f.alvo}</span>
            ))}
          {f.depois}
        </p>
        {temDetalhe && (
          <button type="button" className="aud-ver" aria-expanded={aberto} onClick={() => setAberto((a) => !a)}>
            <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            {aberto ? "Esconder o que mudou" : "Ver o que mudou"}
          </button>
        )}
        {aberto && mudancas?.depois && (
          <div className="mt-2 flex flex-col gap-3">
            {Object.keys(mudancas.depois)
              .filter((k) => k !== "ativo")
              .map((k) => (
                <div key={k} className="grid gap-2 md:grid-cols-2">
                  <Valor rotulo={`Antes (${CAMPO[k]?.replace(/^[ao] /, "") ?? k})`} valor={mudancas.antes?.[k]} campo={k} tom="antes" />
                  <Valor rotulo="Depois" valor={mudancas.depois?.[k]} campo={k} tom="depois" />
                </div>
              ))}
          </div>
        )}
      </div>

      <time className="aud-hora" dateTime={r.criado_em} title={dataHora(r.criado_em)}>
        {hora.format(new Date(r.criado_em))}
      </time>
    </li>
  );
}

function Valor({ rotulo, valor, campo, tom }: { rotulo: string; valor: unknown; campo: string; tom: "antes" | "depois" }) {
  const texto = valor == null ? "—" : campo === "agendamento" ? `${descrever(valor as string)}  (${valor})` : String(valor);
  return (
    <div className={`aud-valor aud-valor-${tom}`}>
      <p className="aud-valor-rotulo">{rotulo}</p>
      <pre>{texto}</pre>
    </div>
  );
}
