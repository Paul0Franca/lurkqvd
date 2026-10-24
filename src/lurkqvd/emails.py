"""Modelos dos e-mails do LurkQVD, com a identidade do front (DataLurk).

Cliente de e-mail não é navegador: nada de variáveis CSS, SVG ou flexbox. Por isso:
  - layout em tabelas, estilos inline e as cores do tema claro do front escritas por extenso;
  - a sub-logo vai como PNG embutido na mensagem (cid:), gerado a partir das formas do Logo.tsx
    (assets/logo_email.png); não depende de nenhum servidor no ar para aparecer;
  - Sora quando o cliente aceita web font (Apple Mail, iOS); senão, Segoe UI/Arial.

Cada função devolve um Email (assunto, texto puro e HTML). O texto puro vai junto para quem
não lê HTML e para os filtros de spam.
"""

import html
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

# tema claro do front (front/src/index.css)
BG = "#f2f1ec"
SUPERFICIE = "#ffffff"
SUPERFICIE_2 = "#e7e6df"
TEXTO = "#121417"
APAGADO = "#5f6168"
BORDA = "#dad9d1"
ACENTO = "#0e7490"
OK_BG, OK_FG = "#e3f1ea", "#1d6b47"
ERRO_BG, ERRO_FG = "#fbe7e5", "#a33a2e"
# identidade (Logo.tsx)
GRAFITE = "#121417"
OFFWHITE = "#F2F1EC"
CIANO = "#22D3EE"

FONTE = "Sora,'Segoe UI',Helvetica,Arial,sans-serif"
# sem Cascadia Code: as ligaduras dela trocam ">=" por "≥" no SQL das mensagens de erro
MONO = "font-family:Consolas,SFMono-Regular,Menlo,'Courier New',monospace;font-variant-ligatures:none"

CID_LOGO = "logo-lurkqvd"


@lru_cache
def imagens() -> dict[str, bytes]:
    """Imagens embutidas na mensagem, por Content-ID."""
    return {CID_LOGO: (Path(__file__).parent / "assets" / "logo_email.png").read_bytes()}


@dataclass
class Email:
    assunto: str
    texto: str
    html: str
    imagens: dict[str, bytes] = field(default_factory=imagens)


def _e(valor) -> str:
    return html.escape(str(valor))


# ---------------------------------------------------------------------- #
# Peças
# ---------------------------------------------------------------------- #
def paragrafo(conteudo_html: str, *, apagado: bool = False, margem: str = "0 0 16px") -> str:
    return (f'<p style="margin:{margem};font-family:{FONTE};font-size:15px;line-height:1.6;'
            f'color:{APAGADO if apagado else TEXTO}">{conteudo_html}</p>')


def selo(texto: str, fundo: str, cor: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;background:{fundo};color:{cor};'
            f'font-family:{FONTE};font-size:12px;font-weight:600;line-height:18px;white-space:nowrap">{_e(texto)}</span>')


def botao(rotulo: str, url: str) -> str:
    # tabela + bgcolor: o Outlook ignora padding e border-radius em <a>
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 4px">'
        f'<tr><td bgcolor="{ACENTO}" style="border-radius:10px;background:{ACENTO}">'
        f'<a href="{_e(url)}" style="display:inline-block;padding:12px 22px;font-family:{FONTE};font-size:14px;'
        f'font-weight:600;color:#ffffff;text-decoration:none;border-radius:10px">{_e(rotulo)}</a>'
        f"</td></tr></table>"
    )


def quadro(linhas: list[tuple[str, str]]) -> str:
    """Pares rótulo/valor num quadro claro (valor já em HTML)."""
    corpo = "".join(
        f'<tr><td style="padding:9px 14px;font-family:{FONTE};font-size:12px;color:{APAGADO};white-space:nowrap;'
        f'vertical-align:top;{"border-top:1px solid " + BORDA + ";" if i else ""}">{_e(r)}</td>'
        f'<td style="padding:9px 14px;font-family:{FONTE};font-size:13px;color:{TEXTO};word-break:break-word;'
        f'{"border-top:1px solid " + BORDA + ";" if i else ""}">{v}</td></tr>'
        for i, (r, v) in enumerate(linhas)
    )
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin:4px 0 8px;border:1px solid {BORDA};border-radius:12px;border-collapse:separate;'
            f'background:{BG}">{corpo}</table>')


def mono(texto: str) -> str:
    return f'<span style="{MONO};font-size:13px">{_e(texto)}</span>'


def bloco_codigo(texto: str) -> str:
    return (f'<div style="margin:8px 0 0;padding:10px 12px;background:{BG};border:1px solid {BORDA};border-radius:10px;'
            f'{MONO};font-size:12px;line-height:1.5;color:{TEXTO};white-space:pre-wrap;'
            f'word-break:break-word">{_e(texto)}</div>')


# ---------------------------------------------------------------------- #
# Layout
# ---------------------------------------------------------------------- #
def layout(*, titulo: str, chamada: str, corpo: str, rotulo: str | None = None, rodape: str = "",
           previa: str = "") -> str:
    """Página do e-mail: cabeçalho escuro com a marca e o horizonte ciano (como na tela de login),
    cartão branco com o conteúdo e rodapé.

    chamada: parágrafo de abertura (HTML). previa: texto que o cliente mostra na lista de e-mails.
    """
    ano = datetime.now().year
    etiqueta = (f'<p style="margin:0 0 8px;font-family:{FONTE};font-size:12px;font-weight:600;letter-spacing:.08em;'
                f'text-transform:uppercase;color:{ACENTO}">{_e(rotulo)}</p>') if rotulo else ""
    return f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;600;700&display=swap" rel="stylesheet">
<title>{_e(titulo)}</title>
</head>
<body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG}">{_e(previa or titulo)}&#8199;&#65279;&#847;&#8199;&#65279;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{BG}" style="background:{BG}">
<tr><td align="center" style="padding:32px 12px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">
    <!-- cabeçalho -->
    <tr><td bgcolor="{GRAFITE}" style="background:{GRAFITE};border-radius:16px 16px 0 0;padding:20px 28px 18px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:middle">
          <img src="cid:{CID_LOGO}" width="43" height="32" alt="" style="display:inline-block;vertical-align:middle;border:0">
          <span style="display:inline-block;vertical-align:middle;margin-left:8px;font-family:{FONTE};font-size:19px;letter-spacing:-.02em;color:{OFFWHITE}"><b style="font-weight:700">Lurk</b><span style="font-weight:300">QVD</span></span>
        </td>
        <td align="right" style="vertical-align:middle;font-family:{FONTE};font-size:12px;letter-spacing:-.01em;color:#8f9093">
          <b style="font-weight:700">Data</b><span style="font-weight:300">Lurk</span>
        </td>
      </tr></table>
    </td></tr>
    <!-- horizonte -->
    <tr><td height="3" bgcolor="{CIANO}" style="height:3px;line-height:3px;font-size:0;background:{CIANO};background-image:linear-gradient(90deg,{GRAFITE},{CIANO} 25%,{CIANO} 75%,{GRAFITE})">&nbsp;</td></tr>
    <!-- conteúdo -->
    <tr><td bgcolor="{SUPERFICIE}" style="background:{SUPERFICIE};border:1px solid {BORDA};border-top:0;border-radius:0 0 16px 16px;padding:30px 28px 26px">
      {etiqueta}
      <h1 style="margin:0 0 14px;font-family:{FONTE};font-size:23px;line-height:1.25;font-weight:600;letter-spacing:-.02em;color:{TEXTO}">{_e(titulo)}</h1>
      {paragrafo(chamada, apagado=True)}
      {corpo}
      <p style="margin:28px 0 0;padding-top:16px;border-top:1px solid {BORDA};font-family:{FONTE};font-size:12px;line-height:1.55;color:{APAGADO}">{rodape or "E-mail automático do LurkQVD. Os avisos são configurados em Configurações › Notificações."}</p>
    </td></tr>
    <tr><td align="center" style="padding:18px 8px 0;font-family:{FONTE};font-size:11px;color:#8f9093">© {ano} DataLurk · Tem muito mais nos seus dados do que você vê.</td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


# ---------------------------------------------------------------------- #
# E-mails
# ---------------------------------------------------------------------- #
NOME_PAPEL = {"leitor": "Leitor", "editor": "Editor", "admin": "Admin"}
DESCRICAO_PAPEL = {
    "leitor": "acompanhar cargas e execuções",
    "editor": "acompanhar e executar cargas",
    "admin": "criar cargas e pastas, executar e gerenciar acessos",
}


def acesso(*, email: str, papel: str, senha: str, quem: str, url: str, redefinida: bool = False) -> Email:
    """Login e senha temporária: conta nova ou senha redefinida por um admin. No 1º login a troca é obrigatória."""
    papel_nome = NOME_PAPEL.get(papel, papel)
    pode = DESCRICAO_PAPEL.get(papel, "")
    selo_papel = selo(papel_nome, ACENTO, "#ffffff") if papel == "admin" else selo(papel_nome, SUPERFICIE_2, TEXTO)
    linhas = [("Login", mono(email)), ("Senha temporária", mono(senha))]
    if not redefinida:
        linhas.insert(0, ("Papel", f"{selo_papel}&nbsp; <span style=\"color:{APAGADO}\">{_e(pode)}</span>"))
    corpo = (
        quadro(linhas)
        + botao("Entrar no LurkQVD", url)
        + paragrafo("No primeiro acesso você vai escolher uma senha só sua; a temporária deixa de valer. "
                    f'Se o botão não abrir, copie este endereço: <a href="{_e(url)}" style="color:{ACENTO}">{_e(url)}</a>',
                    apagado=True, margem="14px 0 0")
    )
    primeiro = quem.split(" ")[0]
    if redefinida:
        assunto, titulo = "Sua senha do LurkQVD foi redefinida", "Sua senha foi redefinida"
        chamada = (f"<b style=\"color:{TEXTO}\">{_e(quem)}</b> redefiniu a sua senha do LurkQVD. "
                   "Entre com a senha temporária abaixo.")
        texto_abertura = f"{quem} redefiniu a sua senha do LurkQVD."
    else:
        assunto, titulo = f"{primeiro} criou o seu acesso ao LurkQVD", "Seu acesso ao LurkQVD"
        chamada = (f"<b style=\"color:{TEXTO}\">{_e(quem)}</b> deu acesso a você no LurkQVD, onde as cargas que "
                   "viram QVD na Qlik Cloud são criadas, agendadas e acompanhadas.")
        texto_abertura = f"{quem} criou o seu acesso ao LurkQVD como {papel_nome}: você vai poder {pode}."
    return Email(
        assunto=assunto,
        texto=(f"{texto_abertura}\n\nEntre em {url}\n  Login: {email}\n  Senha temporária: {senha}\n\n"
               "No primeiro acesso você vai escolher uma senha só sua.\n"),
        html=layout(
            rotulo="Acesso",
            titulo=titulo,
            chamada=chamada,
            corpo=corpo,
            previa=f"Login {email}. No primeiro acesso você escolhe a sua senha.",
            rodape="Você recebeu este e-mail porque um administrador do LurkQVD da sua empresa cadastrou este endereço. "
                   "Se não esperava, avise o time de dados.",
        ),
    )


def teste(*, host: str, porta: int, seguranca: str, remetente: str, quando: str) -> Email:
    seg = {"starttls": "STARTTLS", "ssl": "SSL/TLS", "nenhuma": "sem criptografia"}.get(seguranca, seguranca)
    return Email(
        assunto="LurkQVD: e-mail de teste",
        texto=(f"Se você recebeu esta mensagem, o LurkQVD já consegue enviar e-mails.\n\n"
               f"Servidor: {host}:{porta} ({seg})\nRemetente: {remetente}\nEnviado em: {quando}\n"),
        html=layout(
            rotulo="Teste",
            titulo="O e-mail do LurkQVD está funcionando",
            chamada="Se esta mensagem chegou, o servidor aceitou o envio. Confira se ela não caiu no spam: "
                    "é por aqui que vão sair os acessos de novos usuários e os avisos de erro.",
            corpo=quadro([("Servidor", mono(f"{host}:{porta}")), ("Segurança", _e(seg)),
                          ("Remetente", mono(remetente)), ("Enviado em", _e(quando))]),
            previa="O servidor aceitou o envio. É por aqui que vão sair os acessos e os avisos.",
        ),
    )


def item_execucao(item: dict, max_erro: int) -> str:
    """Uma carga/aplicação no e-mail de avisos. item: status, titulo, nome, situacao, detalhe, link, erro."""
    falhou = item["status"] == "erro"
    erro = ""
    if falhou and item.get("erro"):
        texto = item["erro"].strip()
        erro = bloco_codigo(texto if len(texto) <= max_erro else texto[:max_erro] + "…")
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 12px;border:1px solid {BORDA};border-radius:12px;border-collapse:separate">'
        f'<tr><td style="padding:14px 16px">'
        f'<p style="margin:0 0 4px;font-family:{FONTE};font-size:12px;color:{APAGADO}">{_e(item["tipo_nome"])}</p>'
        f'<p style="margin:0;font-family:{FONTE};font-size:14px;line-height:1.5">'
        f'<a href="{_e(item["link"])}" style="{MONO};font-size:14px;font-weight:600;color:{TEXTO};'
        f'text-decoration:none">{_e(item["nome"])}</a>&nbsp; '
        f'{selo(item["situacao"], ERRO_BG if falhou else OK_BG, ERRO_FG if falhou else OK_FG)}</p>'
        f'<p style="margin:4px 0 0;font-family:{FONTE};font-size:12px;color:{APAGADO}">{_e(item["detalhe"])}</p>'
        f"{erro}</td></tr></table>"
    )


def execucoes(itens: list[dict], *, url: str, max_erro: int) -> Email:
    falhas = [i for i in itens if i["status"] == "erro"]
    voltaram = [i for i in itens if i["status"] != "erro"]
    if len(itens) == 1:
        i = itens[0]
        titulo = f"{i['tipo_nome']} {i['nome']} {i['situacao']}"
        assunto = f"LurkQVD: {i['tipo_nome'].lower()} {i['nome']} {i['situacao']}"
    else:
        partes = []
        if falhas:
            partes.append(f"{len(falhas)} falha{'s' if len(falhas) > 1 else ''}")
        if voltaram:
            partes.append(f"{len(voltaram)} voltou a funcionar" if len(voltaram) == 1
                          else f"{len(voltaram)} voltaram a funcionar")
        assunto = "LurkQVD: " + ", ".join(partes)
        titulo = ", ".join(partes).capitalize()
    chamada = (f"O erro completo e o histórico estão na tela da {itens[0]['tipo_nome'].lower()}." if len(falhas) == 1 and not voltaram else
               "O erro completo e o histórico estão na tela de cada uma." if falhas and not voltaram else
               "Depois de falhar, voltaram a terminar com sucesso." if not falhas else
               "Execuções que mudaram de situação desde o último aviso.")
    ordenados = falhas + voltaram

    def linha_texto(i: dict) -> str:
        linhas = [f"- {i['tipo_nome']} {i['nome']} {i['situacao']} ({i['detalhe']})", f"  {i['link']}"]
        if i["status"] == "erro" and i.get("erro"):
            linhas += ["  " + x for x in i["erro"].strip()[:max_erro].splitlines()]
        return "\n".join(linhas)

    return Email(
        assunto=assunto,
        texto=f"{titulo}\n\n{chamada}\n\n" + "\n\n".join(linha_texto(i) for i in ordenados) + "\n",
        html=layout(
            rotulo="Falha" if falhas and not voltaram else "Execuções",
            titulo=titulo, chamada=_e(chamada),
            corpo="".join(item_execucao(i, max_erro) for i in ordenados) + botao("Abrir o LurkQVD", url),
            previa=" · ".join(f"{i['nome']} {i['situacao']}" for i in ordenados[:4]),
        ),
    )


def qlik_recusada(*, erro: str, url: str) -> Email:
    return Email(
        assunto="LurkQVD: sem conexão com a Qlik Cloud",
        texto=(f"O teste da API key da Qlik falhou: {erro}\n\nAs cargas não conseguem publicar os QVDs até a key "
               f"ser substituída em Configurações › Qlik Cloud ({url}).\n"),
        html=layout(
            rotulo="Qlik Cloud",
            titulo="Sem conexão com a Qlik Cloud",
            chamada="O teste da API key usada pelo LurkQVD falhou. Até ela ser substituída, as cargas não "
                    "conseguem publicar os QVDs.",
            corpo=bloco_codigo(erro) + paragrafo("Gere uma nova key na Qlik Cloud (Perfil › Configurações › API keys) e "
                                                 "substitua em Configurações › Qlik Cloud.", margem="16px 0 0")
                  + botao("Abrir o LurkQVD", url),
        ),
    )


def qlik_vencendo(*, quando: str, data: str, url: str) -> Email:
    frase = f"A API key da Qlik usada pelo LurkQVD vence {quando} ({data})."
    return Email(
        assunto=f"LurkQVD: a API key da Qlik vence {quando}",
        texto=(f"{frase}\n\nGere uma nova na Qlik Cloud (Perfil › Configurações › API keys) e substitua em "
               f"Configurações › Qlik Cloud ({url}). A API e o worker passam a usar a nova sozinhos.\n"),
        html=layout(
            rotulo="Qlik Cloud",
            titulo=f"A API key da Qlik vence {quando}",
            chamada=_e(frase) + " Depois disso, as cargas param de publicar os QVDs.",
            corpo=paragrafo("Gere uma nova na Qlik Cloud (Perfil › Configurações › API keys) e substitua em "
                            "Configurações › Qlik Cloud. A API e o worker passam a usar a nova sozinhos, sem reiniciar.")
                  + botao("Abrir o LurkQVD", url),
        ),
    )
