// Configurações > API do LurkQVD: tokens para sistemas (ex.: Airflow) acionarem cargas.
// O token aparece uma única vez; o servidor guarda só o hash.

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Copy, KeyRound, Plus, X } from "lucide-react";
import { API_URL, type Api, type CargaResumo, type TokenApi } from "../api";
import { dataHora, relativo } from "../lib/formato";
import { BlocoExemplo, Comando } from "./comum";

const VALIDADES: [string, string][] = [
  ["", "Sem validade"],
  ["30", "30 dias"],
  ["90", "90 dias"],
  ["365", "1 ano"],
];

export default function ApiLurkqvd({ api }: { api: Api }) {
  const [tokens, setTokens] = useState<TokenApi[] | null>(null);
  const [cargas, setCargas] = useState<CargaResumo[]>([]);
  const [criando, setCriando] = useState(false);
  const [novo, setNovo] = useState<{ nome: string; token: string } | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api.tokens().then(setTokens).catch((e: Error) => setErro(e.message));
  }, [api]);

  useEffect(() => {
    carregar();
    api.listarCargas().then(setCargas).catch(() => {});
  }, [api, carregar]);

  async function revogar(t: TokenApi) {
    if (!confirm(`Revogar o token “${t.nome}”? Quem usa ele para de conseguir chamar a API na hora.`)) return;
    setErro(null);
    try {
      await api.revogarToken(t.id);
      carregar();
    } catch (e) {
      setErro((e as Error).message);
    }
  }

  if (!tokens) return <p className="vazio">{erro ?? "Carregando…"}</p>;
  const ativos = tokens.filter((t) => t.estado === "ativo");
  const inativos = tokens.filter((t) => t.estado !== "ativo");

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-[560px] text-sm text-muted-foreground">
          Tokens para sistemas, como o Airflow, acionarem cargas pela API. Cada token aparece <strong className="font-medium text-foreground">uma única vez</strong>; o LurkQVD guarda só uma impressão dele.
        </p>
        {!criando && (
          <button type="button" className="btn-primario inline-flex items-center gap-2" onClick={() => setCriando(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Novo token
          </button>
        )}
      </div>

      {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}

      {novo && <TokenRevelado nome={novo.nome} token={novo.token} aoFechar={() => setNovo(null)} />}

      {criando && (
        <NovoToken
          api={api}
          aoCancelar={() => setCriando(false)}
          aoCriar={(nome, token) => {
            setCriando(false);
            setNovo({ nome, token });
            carregar();
          }}
        />
      )}

      {/* ---------- tokens ---------- */}
      <section aria-labelledby="titulo-tokens">
        <h3 id="titulo-tokens" className="mb-3 text-sm font-semibold">
          Tokens <span className="ml-1 font-normal text-muted-foreground">{ativos.length} ativos</span>
        </h3>
        {tokens.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-border px-5 py-5 text-sm text-muted-foreground">Nenhum token ainda. Crie um para o Airflow começar a acionar cargas.</p>
        ) : (
          <ul className="overflow-hidden rounded-2xl border border-border">
            {[...ativos, ...inativos].map((t) => (
              <li key={t.id} className="linha-usuario" data-inativo={t.estado !== "ativo" || undefined}>
                <span className="icone-carga">
                  <KeyRound className="h-4 w-4 text-primary" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    {t.nome}
                    <span className={`selo-permissao selo-${t.permissao}`}>{t.permissao === "executar" ? "executar" : "só leitura"}</span>
                    {t.estado !== "ativo" && <span className="tag !ml-0">{t.estado}</span>}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    <span className="font-mono">{t.prefixo}_…</span>
                    {" · "}criado {relativo(t.criado_em)}
                    {t.criado_por_nome && ` por ${t.criado_por_nome.split(" ")[0]}`}
                    {t.estado === "ativo" && t.expira_em && ` · vence ${relativo(t.expira_em)}`}
                    {t.revogado_em && ` · revogado ${relativo(t.revogado_em)}${t.revogado_por_nome ? ` por ${t.revogado_por_nome.split(" ")[0]}` : ""}`}
                  </p>
                </div>
                <div className="hidden w-44 shrink-0 text-xs text-muted-foreground md:block">
                  <span className="block" title={t.ultimo_uso ? dataHora(t.ultimo_uso) : undefined}>
                    {t.ultimo_uso ? `usado ${relativo(t.ultimo_uso)}` : "nunca usado"}
                  </span>
                  <span className="block truncate">
                    {t.execucoes === 1 ? "1 execução" : `${t.execucoes} execuções`}
                    {t.ultimo_ip && ` · ${t.ultimo_ip}`}
                  </span>
                </div>
                {t.estado !== "revogado" ? (
                  <button type="button" className="btn-acesso" onClick={() => revogar(t)}>
                    Revogar
                  </button>
                ) : (
                  <span className="w-[128px]" />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <ComoUsar cargas={cargas} />
    </div>
  );
}

function NovoToken({ api, aoCancelar, aoCriar }: { api: Api; aoCancelar: () => void; aoCriar: (nome: string, token: string) => void }) {
  const [nome, setNome] = useState("");
  const [permissao, setPermissao] = useState<"executar" | "leitura">("executar");
  const [validade, setValidade] = useState("365");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function criar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setErro(null);
    try {
      const r = await api.criarToken({ nome: nome.trim(), permissao, validade_dias: validade ? Number(validade) : null });
      aoCriar(r.nome, r.token);
    } catch (err) {
      setErro((err as Error).message);
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={criar} className="form-fonte">
      <h3 className="font-sora text-[15px] font-semibold">Novo token</h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto]">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium">Nome</span>
          <input className="campo campo-pequeno" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: Airflow produção" maxLength={80} autoFocus required />
          <span className="text-[11px] text-muted-foreground">Aparece na Atividade e no Histórico: “por Airflow produção”.</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium">Validade</span>
          <select className="campo campo-pequeno w-[150px]" value={validade} onChange={(e) => setValidade(e.target.value)}>
            {VALIDADES.map(([v, r]) => (
              <option key={v} value={v}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="mt-4">
        <legend className="text-xs font-medium">Permissão</legend>
        <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
          {(
            [
              ["executar", "Executar", "Dispara cargas e consulta o status. É a do Airflow."],
              ["leitura", "Só leitura", "Só consulta cargas e execuções (ex.: um dashboard)."],
            ] as const
          ).map(([v, titulo, texto]) => (
            <button key={v} type="button" role="radio" aria-checked={permissao === v} className="tile-tipo" onClick={() => setPermissao(v)}>
              <span className="font-medium">{titulo}</span>
              <span className="text-xs text-muted-foreground">{texto}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">Nenhum token cria cargas nem mexe em configurações.</p>
      </fieldset>
      {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="btn-secundario" onClick={aoCancelar}>
          Cancelar
        </button>
        <button type="submit" className="btn-primario" disabled={!nome.trim() || enviando}>
          {enviando ? "Criando…" : "Criar token"}
        </button>
      </div>
    </form>
  );
}

function TokenRevelado({ nome, token, aoFechar }: { nome: string; token: string; aoFechar: () => void }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="token-revelado" role="status">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-sora text-[15px] font-semibold text-[#F2F1EC]">Token “{nome}” criado</p>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-[#fcd34d]">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            Copie agora: ele não aparece de novo.
          </p>
        </div>
        <button type="button" aria-label="Fechar" className="text-[#F2F1EC]/60 hover:text-[#F2F1EC]" onClick={aoFechar}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-4 flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded-lg bg-white/[0.06] px-3 py-2.5 font-mono text-[13px] text-[#F2F1EC]">{token}</code>
        <button
          type="button"
          className="btn-resumo inline-flex shrink-0 items-center gap-2 !w-auto px-4"
          onClick={() =>
            navigator.clipboard
              .writeText(token)
              .then(() => setCopiado(true))
              .catch(() => {})
          }
        >
          {copiado ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copiado ? "Copiado" : "Copiar"}
        </button>
      </div>
      <p className="mt-3 text-xs text-[#F2F1EC]/60">No Airflow, guarde na conexão “lurkqvd” (veja abaixo). Não coloque o token no código da DAG.</p>
    </div>
  );
}

// endereço completo da API para os exemplos (no Docker a API fica em /api, relativo ao front)
const API_BASE = API_URL.startsWith("/") ? `${window.location.origin}${API_URL}` : API_URL;

function ComoUsar({ cargas }: { cargas: CargaResumo[] }) {
  const [aba, setAba] = useState<"airflow" | "curl">("airflow");
  const [carga, setCarga] = useState("");
  const nome = carga || cargas[0]?.nome || "fct_vendas_item";
  const ident = nome.replace(/[^a-zA-Z0-9_]/g, "_");

  const curl = `# 1. disparar (responde na hora com o execucao_id)
curl -X POST "${API_BASE}/cargas/nome/${nome}/executar" \\
     -H "Authorization: Bearer $LURKQVD_TOKEN"

# 2. acompanhar até "terminou": true
curl "${API_BASE}/execucoes/EXECUCAO_ID" \\
     -H "Authorization: Bearer $LURKQVD_TOKEN"`;

  const airflow = `from datetime import datetime

from airflow.exceptions import AirflowException
from airflow.providers.http.operators.http import HttpOperator
from airflow.providers.http.sensors.http import HttpSensor
from airflow.sdk import dag

# Conexão "lurkqvd" no Airflow (Admin > Connections):
#   tipo HTTP, host = ${API_BASE}
#   Extra = {"Authorization": "Bearer lqvd_..."}


def terminou(response) -> bool:
    execucao = response.json()
    if execucao["status"] in ("erro", "cancelado"):
        raise AirflowException(f"A carga terminou com {execucao['status']}: {execucao['erro']}")
    return execucao["terminou"]


@dag(schedule=None, start_date=datetime(2026, 1, 1), catchup=False, tags=["lurkqvd"])
def lurkqvd_${ident}():
    disparar = HttpOperator(
        task_id="disparar",
        http_conn_id="lurkqvd",
        method="POST",
        endpoint="/cargas/nome/${nome}/executar",
        # 409 = já estava na fila: a resposta traz o id dela e a DAG espera essa execução
        response_check=lambda r: r.status_code in (202, 409),
        response_filter=lambda r: r.json()["execucao_id"],
        extra_options={"check_response": False},
    )

    esperar = HttpSensor(
        task_id="esperar",
        http_conn_id="lurkqvd",
        endpoint="/execucoes/{{ ti.xcom_pull(task_ids='disparar') }}",
        response_check=terminou,
        poke_interval=30,
        timeout=60 * 60,
        mode="reschedule",  # libera o slot do worker do Airflow enquanto espera
    )

    disparar >> esperar


lurkqvd_${ident}()`;

  return (
    <section aria-labelledby="titulo-como-usar" className="flex flex-col gap-4 border-t border-border pt-6">
      <div>
        <h3 id="titulo-como-usar" className="text-sm font-semibold">
          Como usar
        </h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Disparar responde na hora (202) com o <span className="font-mono">execucao_id</span>; depois é consultar até <span className="font-mono">terminou</span> ser verdadeiro.
        </p>
      </div>

      <div>
        <p className="mb-1.5 text-xs text-muted-foreground">Endereço da API</p>
        <Comando texto={API_BASE} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="segmentos" role="radiogroup" aria-label="Exemplo">
          {(
            [
              ["airflow", "DAG do Airflow"],
              ["curl", "curl"],
            ] as const
          ).map(([v, r]) => (
            <button key={v} type="button" role="radio" aria-checked={aba === v} className="segmento" onClick={() => setAba(v)}>
              {r}
            </button>
          ))}
        </div>
        {cargas.length > 0 && (
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            Carga
            <select className="campo campo-pequeno w-auto min-w-[180px] font-mono" value={nome} onChange={(e) => setCarga(e.target.value)}>
              {cargas.map((c) => (
                <option key={c.id} value={c.nome}>
                  {c.nome}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <BlocoExemplo linguagem={aba === "airflow" ? `dags/lurkqvd_${ident}.py` : "terminal"} codigo={aba === "airflow" ? airflow : curl} />

      <dl className="grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-[auto_1fr]">
        <dt className="font-mono text-foreground">202</dt>
        <dd className="text-muted-foreground">entrou na fila; a resposta traz o execucao_id</dd>
        <dt className="font-mono text-foreground">409</dt>
        <dd className="text-muted-foreground">já estava na fila ou rodando; a resposta traz o execucao_id dessa execução</dd>
        <dt className="font-mono text-foreground">401 / 403</dt>
        <dd className="text-muted-foreground">token inválido, revogado ou vencido / sem permissão para executar</dd>
        <dt className="font-mono text-foreground">404</dt>
        <dd className="text-muted-foreground">carga não encontrada com esse nome</dd>
      </dl>
    </section>
  );
}
