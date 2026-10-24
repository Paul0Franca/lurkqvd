"""E-mails do LurkQVD: acesso (login e senha temporária) e avisos (carga/aplicação com erro, voltou a funcionar, API key da Qlik).

Quem envia:
  - acesso: a API, quando o admin cadastra alguém ou redefine a senha (sem SMTP, não cadastra);
  - avisos: o worker, numa thread à parte (Notificador.ciclo a cada ~20s).

O visual dos e-mails fica em src/lurkqvd/emails.py.

Os avisos nunca derrubam quem chamou: sem SMTP configurado, são só descartados, e uma falha
de envio fica registrada no histórico (lurkqvd.notificacoes_enviadas) e no log.

Variáveis de ambiente:
  LURKQVD_URL_APP   endereço do front para os links dos e-mails
                    (padrão: a 1ª origem de LURKQVD_CORS, ou http://localhost:5173)
"""

import logging
import os
from datetime import datetime, timezone

from src.lurkqvd import emails, fuso
from src.lurkqvd.config import qlik_conexao, smtp
from src.lurkqvd.repository.repositorio import Repositorio

logger = logging.getLogger("lurkqvd.notificacoes")

DIAS_AVISO_QLIK = 7
MAX_ERRO = 800  # caracteres do erro no e-mail (o completo está na tela da execução)

ORIGEM = {"agendador": "agendamento", "manual": "manual", "api": "manual", "token": "token de API",
          "aplicacao": "aplicação", "airflow": "Airflow"}


def url_app() -> str:
    url = os.getenv("LURKQVD_URL_APP") or next(
        (o.strip() for o in os.getenv("LURKQVD_CORS", "").split(",") if o.strip()), "http://localhost:5173")
    return url.rstrip("/")


def _quando(valor) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    return valor.astimezone(fuso.ZONA).strftime("%d/%m %H:%M")


class SemEmail(RuntimeError):
    """O e-mail com a senha temporária não pôde sair (SMTP não configurado ou falha no envio)."""


class Notificador:
    def __init__(self, repo: Repositorio) -> None:
        self.repo = repo

    def _servidor(self) -> tuple[dict, str | None] | None:
        """(configuração do SMTP, senha) ou None se o SMTP não estiver configurado."""
        cfg = self.repo.config_smtp()["smtp"]
        if not cfg or not cfg.get("host") or not cfg.get("remetente"):
            return None
        return cfg, (smtp.ler_senha() if cfg.get("usuario") else None)

    def destinatarios(self, prefs: dict | None = None) -> list[str]:
        prefs = prefs or self.repo.config_notificacoes()
        emails_ = (self.repo.emails_admins() if prefs.get("para_admins") else []) + list(prefs.get("extras") or [])
        vistos: dict[str, None] = {}
        for e in emails_:
            vistos.setdefault(e.strip().lower(), None)
        return [e for e in vistos if e]

    def _enviar(self, servidor: tuple[dict, str | None], tipo: str, para: list[str], email: emails.Email,
                detalhes: dict | None = None) -> str | None:
        """Envia e registra no histórico. Devolve a mensagem de erro (None = enviado)."""
        cfg, senha = servidor
        erro = None
        try:
            smtp.enviar(cfg, senha, para, email)
        except Exception as e:
            erro = smtp.mensagem_erro(e, cfg)
            logger.warning("e-mail '%s' para %s não saiu: %s", email.assunto, para, erro)
        try:
            self.repo.registrar_notificacao(tipo, email.assunto, para, erro is None, erro, detalhes)
        except Exception:
            logger.warning("não consegui registrar o envio no histórico", exc_info=True)
        return erro

    # ------------------------------------------------------------------ #
    # Acesso: login e senha temporária (chamado pela API)
    # ------------------------------------------------------------------ #
    def acesso(self, email: str, papel: str, senha: str, quem: str | None, *, redefinida: bool = False) -> None:
        """Manda o login e a senha temporária. Sem SMTP ou com falha no envio, levanta SemEmail
        (quem chama não deve gravar uma senha que a pessoa nunca vai receber)."""
        try:
            servidor = self._servidor()
        except Exception as e:  # sem acesso à senha nos segredos
            raise SemEmail(f"Não consegui ler a senha do SMTP: {e}") from e
        if not servidor:
            raise SemEmail("Configure o servidor de e-mail (Configurações › Notificações) para cadastrar usuários: "
                           "a senha temporária vai por e-mail.")
        mensagem = emails.acesso(email=email, papel=papel, senha=senha, quem=quem or "Um administrador",
                                 url=url_app(), redefinida=redefinida)
        erro = self._enviar(servidor, "acesso", [email], mensagem, {"papel": papel, "redefinida": redefinida})
        if erro:
            raise SemEmail(f"O e-mail não saiu: {erro}")

    # ------------------------------------------------------------------ #
    # Avisos (chamado pelo worker)
    # ------------------------------------------------------------------ #
    def ciclo(self) -> int:
        """Olha as execuções que terminaram e a API key da Qlik. Devolve quantos e-mails saíram."""
        prefs = self.repo.config_notificacoes()
        # sempre "pega" as execuções, mesmo com tudo desligado: ao ligar, não chega o passado de uma vez
        itens = self._classificar(self.repo.notif_pegar_execucoes(), "carga", prefs, prefs.get("erros_cargas"))
        itens += self._classificar(self.repo.notif_pegar_execucoes_aplicacao(), "aplicacao", prefs,
                                   prefs.get("erros_aplicacoes"))
        if not itens and not prefs.get("qlik"):
            return 0
        cfg = self.repo.config_smtp()["smtp"]
        if not cfg or not cfg.get("host") or not cfg.get("remetente"):
            return 0
        para = self.destinatarios(prefs)
        if not para:
            if itens:
                logger.info("%s aviso(s) sem destinatário (ninguém configurado para receber)", len(itens))
            return 0
        # o aviso da Qlik só é "gasto" daqui em diante, com SMTP e destinatário
        qlik = self._avisos_qlik() if prefs.get("qlik") else []
        if not itens and not qlik:
            return 0
        try:
            servidor = (cfg, smtp.ler_senha() if cfg.get("usuario") else None)
        except Exception:
            logger.warning("avisos: não consegui ler a senha do SMTP", exc_info=True)
            return 0

        enviados = 0
        if itens:
            detalhes = {"itens": [{"tipo": i["tipo"], "id": i["id"], "status": i["status"]} for i in itens]}
            mensagem = emails.execucoes(itens, url=url_app(), max_erro=MAX_ERRO)
            enviados += self._enviar(servidor, "falhas", para, mensagem, detalhes) is None
        for mensagem in qlik:
            enviados += self._enviar(servidor, "qlik", para, mensagem) is None
        return enviados

    def _classificar(self, linhas: list[dict], tipo: str, prefs: dict, ligado) -> list[dict]:
        """Só o que merece e-mail: falha (a 1ª seguida, se so_mudanca) e volta a funcionar."""
        if not ligado:
            return []
        url = url_app()
        itens = []
        for x in linhas:
            falhou_antes = x["status_anterior"] == "erro"
            if x["status"] == "erro" and not (prefs.get("so_mudanca") and falhou_antes):
                situacao = "continua falhando" if falhou_antes else "falhou"
            elif x["status"] == "sucesso" and falhou_antes and prefs.get("recuperacao"):
                situacao = "voltou a funcionar"
            else:
                continue
            dono = x["carga_id"] if tipo == "carga" else x["aplicacao_id"]
            itens.append({
                "tipo": tipo,
                "tipo_nome": "Carga" if tipo == "carga" else "Aplicação",
                "id": x["id"],
                "status": x["status"],
                "erro": x["erro"],
                "nome": x["nome"] or str(dono),
                "situacao": situacao,
                "detalhe": f"{_quando(x['finalizado_em'])} · {ORIGEM.get(x['origem'], x['origem'])} · execução {x['id']}",
                "link": f"{url}/#/{'cargas' if tipo == 'carga' else 'aplicacoes'}/{dono}",
            })
        return itens

    def _avisos_qlik(self) -> list[emails.Email]:
        """API key recusada (na mudança de ok para falha) e vencendo em até DIAS_AVISO_QLIK dias (1 vez por key)."""
        status = self.repo.config_qlik(qlik_conexao.TENANT_PADRAO)["status"] or {}
        if status.get("ok") is None:
            return []
        if status["ok"] is False:
            if self.repo.marcar_aviso("qlik_falha", True):
                return [emails.qlik_recusada(erro=status.get("erro") or "A Qlik recusou a API key.", url=url_app())]
            return []
        self.repo.marcar_aviso("qlik_falha", False)

        expira = status.get("expira_em")
        if not expira:
            return []
        expira_em = datetime.fromisoformat(str(expira).replace("Z", "+00:00"))
        dias = (expira_em - datetime.now(timezone.utc)).total_seconds() / 86400
        chave = status.get("chave_id") or status.get("token_mascara") or str(expira)
        if dias <= DIAS_AVISO_QLIK and self.repo.marcar_aviso("qlik_vencimento", chave):
            quando = "hoje" if dias < 1 else f"em {int(dias)} dia{'s' if int(dias) != 1 else ''}"
            data = expira_em.astimezone(fuso.ZONA).strftime("%d/%m/%Y")
            return [emails.qlik_vencendo(quando=quando, data=data, url=url_app())]
        return []
