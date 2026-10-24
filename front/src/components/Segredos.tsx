// Configurações > Segredos (só leitura): a API key da Qlik e as senhas das fontes e do SMTP ficam no Postgres
// do LurkQVD, criptografadas com a chave do servidor (LURKQVD_FERNET_KEY). Esta tela mostra se estão legíveis.

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, KeyRound, LockKeyhole, MinusCircle, RefreshCw, XCircle } from "lucide-react";
import type { Api, StatusSegredos } from "../api";
import { dataHora, relativo } from "../lib/formato";
import { Comando } from "./comum";

type Item = StatusSegredos["secrets"][number];

export default function Segredos({ api }: { api: Api }) {
  const [st, setSt] = useState<StatusSegredos | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api
      .statusSegredos()
      .then((s) => {
        setSt(s);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message))
      .finally(() => setCarregando(false));
  }, [api]);

  useEffect(carregar, [carregar]);

  if (!st) return <p className="vazio">{erro ?? "Consultando os segredos…"}</p>;

  const ilegiveis = st.secrets.filter((s) => !s.legivel).length;
  const ok = !st.erro && ilegiveis === 0;

  return (
    <div className="flex flex-col gap-8">
      <p className="max-w-[620px] text-sm text-muted-foreground">
        A API key da Qlik e as senhas das fontes e do SMTP ficam guardadas à parte, criptografadas no Postgres do LurkQVD. Nenhuma sai para serviços externos.
        Esta tela só mostra o estado; as senhas são gravadas nas próprias telas (Qlik Cloud, Fontes de dados, Notificações).
      </p>
      {erro && <p className="alerta alerta-erro !mb-0">{erro}</p>}

      {/* ---------- estado ---------- */}
      <section className={`cartao-worker ${ok ? "" : "cartao-worker-parado"}`} aria-live="polite">
        <div className="flex flex-wrap items-start gap-4">
          {ok ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-[var(--lq-ok-fg)]" /> : <XCircle className="mt-0.5 h-5 w-5 text-destructive" />}
          <div className="min-w-0 flex-1">
            <h3 className="font-sora text-base font-semibold">
              {st.erro ? "Segredos inacessíveis" : ilegiveis ? `${ilegiveis === 1 ? "1 segredo ilegível" : `${ilegiveis} segredos ilegíveis`}` : "Segredos protegidos"}
            </h3>
            {st.erro ? (
              <p className="mt-0.5 text-sm text-muted-foreground">{st.erro}</p>
            ) : (
              <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Onde</dt>
                <dd className="text-[13px]">
                  Postgres do LurkQVD, tabela <span className="font-mono">lurkqvd.segredos</span>
                </dd>
                <dt className="text-muted-foreground">Criptografia</dt>
                <dd className="text-[13px]">
                  Fernet (AES), com {st.chaves_fernet === 1 ? "1 chave" : `${st.chaves_fernet} chaves`} em <span className="font-mono">LURKQVD_FERNET_KEY</span>, no servidor
                </dd>
              </dl>
            )}
          </div>
          <button type="button" className="btn-secundario inline-flex items-center gap-2" disabled={carregando} onClick={() => {
              setCarregando(true);
              carregar();
            }}>
            <RefreshCw className={`h-4 w-4 ${carregando ? "animate-spin" : ""}`} aria-hidden="true" />
            {carregando ? "Verificando…" : "Atualizar"}
          </button>
        </div>
      </section>

      {/* ---------- sem chave ---------- */}
      {st.erro && (
        <section aria-labelledby="titulo-chave" className="flex flex-col gap-2">
          <h3 id="titulo-chave" className="text-sm font-semibold">
            Como corrigir
          </h3>
          <p className="text-xs text-muted-foreground">
            Gere uma chave na raiz do projeto, coloque em <span className="font-mono text-foreground">LURKQVD_FERNET_KEY</span> no .env da API e do worker e
            reinicie os dois. Guarde uma cópia da chave fora do servidor: sem ela, os segredos não podem ser lidos.
          </p>
          <Comando texto="python -m src.lurkqvd.config.segredos gerar-chave" />
        </section>
      )}

      {/* ---------- segredos ---------- */}
      {!st.erro && (
        <section aria-labelledby="titulo-secrets">
          <h3 id="titulo-secrets" className="mb-3 text-sm font-semibold">
            Segredos usados pelo LurkQVD
          </h3>
          <div className="overflow-hidden rounded-2xl border border-border">
            <table className="tabela-secrets">
              <thead>
                <tr>
                  <th scope="col">Segredo</th>
                  <th scope="col">Situação</th>
                  <th scope="col">Gravado</th>
                </tr>
              </thead>
              <tbody>
                {st.secrets.map((s) => (
                  <tr key={s.nome}>
                    <td>
                      <span className="flex items-center gap-2.5">
                        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                        <span className="min-w-0">
                          <span className="block font-mono text-[13px] font-semibold">{s.nome}</span>
                          <span className="block text-xs text-muted-foreground">{s.erro ?? s.finalidade}</span>
                        </span>
                      </span>
                    </td>
                    <td>
                      <Situacao s={s} />
                    </td>
                    <td className="text-[13px] text-muted-foreground" title={s.atualizado_em ? dataHora(s.atualizado_em) : undefined}>
                      {s.atualizado_em ? relativo(s.atualizado_em) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
            <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
            Para trocar a chave sem perder nada, coloque a nova antes da antiga em LURKQVD_FERNET_KEY (separadas por vírgula) e rode o comando abaixo.
          </p>
          <div className="mt-2">
            <Comando texto="python -m src.lurkqvd.config.segredos rotacionar" />
          </div>
        </section>
      )}
    </div>
  );
}

function Situacao({ s }: { s: Item }) {
  if (!s.existe)
    return (
      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
        <MinusCircle className="h-4 w-4" aria-hidden="true" />
        ainda não gravado
      </span>
    );
  if (!s.legivel)
    return (
      <span className="inline-flex items-center gap-1.5 text-destructive">
        <XCircle className="h-4 w-4" aria-hidden="true" />
        ilegível (outra chave)
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-[var(--lq-ok-fg)]">
      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
      guardado{s.chaves > 1 ? ` (${s.chaves} valores)` : ""}
    </span>
  );
}
