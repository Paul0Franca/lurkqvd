// Topo do painel: o estado do LurkQVD numa frase, a saúde das peças (worker, Qlik, agenda) e o caminho
// de uma carga (banco → QVD → Qlik Cloud) com os números do sistema. Fica em tinta escura nos dois temas.

import { Cloud, Database, FileStack, type LucideIcon } from "lucide-react";
import type { CargaResumo, ExecucoesDia, Resumo, StatusSistema } from "../api";
import { relativo, tamanho } from "../lib/formato";
import { diasAte, textoDias } from "../lib/vencimento";

type Estado = "ok" | "rodando" | "erro" | "parado";

interface Props {
  nome: string;
  resumo: Resumo | null;
  sistema: StatusSistema | null;
  cargas: CargaResumo[] | null;
  diario: ExecucoesDia[] | null;
}

function saudacao(): string {
  const h = new Date().getHours();
  return h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite";
}

function plural(n: number, um: string, varios: string): string {
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? um : varios}`;
}

export default function PainelHero({ nome, resumo, sistema, cargas, diario }: Props) {
  const workerParado = !!sistema && sistema.workers_ativos === 0;
  const rodando = (cargas ?? []).filter((c) => c.ultimo_status === "rodando" || c.ultimo_status === "pendente").length;
  const erros = resumo?.com_erro ?? 0;
  const estado: Estado = workerParado ? "parado" : erros > 0 ? "erro" : rodando > 0 ? "rodando" : "ok";

  const titulo = !resumo
    ? "Carregando…"
    : {
        parado: "O worker está parado.",
        erro: `${plural(erros, "carga falhou", "cargas falharam")} na última execução.`,
        rodando: `${plural(rodando, "carga rodando", "cargas rodando")} agora.`,
        ok: "Tudo em dia.",
      }[estado];

  const total = (diario ?? []).reduce((s, d) => s + d.sucesso + d.erro, 0);
  const sucesso = (diario ?? []).reduce((s, d) => s + d.sucesso, 0);
  const sub = resumo
    ? [
        plural(resumo.execucoes_24h, "execução nas últimas 24 horas", "execuções nas últimas 24 horas"),
        total > 0 && `${Math.round((sucesso / total) * 100)}% de sucesso em 14 dias`,
      ]
        .filter(Boolean)
        .join(", ") + "."
    : "";

  // próxima carga agendada (ativa)
  const proxima = (cargas ?? [])
    .filter((c) => c.ativo && c.agendamento && c.proxima_execucao)
    .sort((a, b) => a.proxima_execucao!.localeCompare(b.proxima_execucao!))[0];

  const dias = sistema?.qlik?.expira_em ? diasAte(sistema.qlik.expira_em) : null;
  const qlikSemKey = !!sistema && (!sistema.qlik || (sistema.qlik.ok == null && !sistema.qlik.verificado_em));
  const qlikOk = !qlikSemKey && sistema?.qlik?.ok !== false && (dias === null || dias > 7);

  return (
    <section className={`hero-painel hero-${estado}`} aria-labelledby="hero-titulo">
      <div className="hero-texto">
        <p className="hero-sobrelinha">
          <span className="hero-pulso" aria-hidden="true" />
          {saudacao()}, {nome}
        </p>
        <h1 id="hero-titulo" className="hero-titulo" aria-live="polite">
          {titulo}
        </h1>
        {sub && <p className="hero-sub">{sub}</p>}

        <ul className="hero-saude" aria-label="Saúde do sistema">
          <Saude
            ok={!workerParado}
            rotulo="Worker"
            valor={!sistema ? "—" : workerParado ? "parado" : plural(sistema.workers_ativos, "ativo", "ativos")}
          />
          <Saude
            ok={qlikOk}
            rotulo="Qlik Cloud"
            valor={!sistema ? "—" : qlikSemKey ? "não configurada" : sistema.qlik!.ok === false ? "key recusada" : dias !== null && dias <= 30 ? `key ${textoDias(dias)}` : "conectada"}
          />
          <Saude
            ok={!sistema?.agenda.pausada}
            rotulo="Agenda"
            valor={
              sistema?.agenda.pausada ? "pausada" : proxima ? `${proxima.nome} ${relativo(proxima.proxima_execucao!)}` : "nada agendado"
            }
            titulo={proxima ? `Próxima: ${proxima.nome}` : undefined}
          />
        </ul>
      </div>

      <ol className="hero-fluxo" aria-label="Caminho de uma carga">
        <span className="hero-trilho" aria-hidden="true">
          <span className="hero-trilho-pulso" />
        </span>
        <Etapa icone={Database} nome="Banco de dados" valor={resumo ? resumo.cargas_ativas.toLocaleString("pt-BR") : "—"} rotulo="cargas ativas" />
        <Etapa icone={FileStack} nome="QVD" valor={resumo ? tamanho(resumo.bytes_publicados) : "—"} rotulo="publicados" />
        <Etapa icone={Cloud} nome="Qlik Cloud" valor={resumo ? resumo.execucoes_24h.toLocaleString("pt-BR") : "—"} rotulo="execuções em 24h" destino />
      </ol>
    </section>
  );
}

function Saude({ ok, rotulo, valor, titulo }: { ok: boolean; rotulo: string; valor: string; titulo?: string }) {
  return (
    <li className="hero-saude-item" data-ok={ok || undefined} title={titulo}>
      <span className="hero-saude-ponto" aria-hidden="true" />
      <span className="hero-saude-rotulo">{rotulo}</span>
      <span className="hero-saude-valor">{valor}</span>
    </li>
  );
}

function Etapa({ icone: Icone, nome, valor, rotulo, destino }: { icone: LucideIcon; nome: string; valor: string; rotulo: string; destino?: boolean }) {
  return (
    <li className="hero-etapa" data-destino={destino || undefined}>
      <span className="hero-etapa-icone">
        <Icone className="h-[18px] w-[18px]" strokeWidth={1.6} aria-hidden="true" />
      </span>
      <span className="hero-etapa-nome">{nome}</span>
      <span className="hero-etapa-valor">{valor}</span>
      <span className="hero-etapa-rotulo">{rotulo}</span>
    </li>
  );
}
