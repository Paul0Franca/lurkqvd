"""API do lurkqvd: camada fina sobre o repositório. Não executa cargas — só enfileira.

Uso, na raiz do projeto:
    uvicorn src.lurkqvd.api.main:app --reload
Documentação interativa: http://localhost:8000/docs

O worker precisa estar rodando em paralelo para as execuções saírem da fila.
Autenticação: ver src/lurkqvd/api/auth.py (login próprio, papéis leitor/editor/admin).
Na primeira subida, com o banco sem usuários, cria o admin padrão (veja src/lurkqvd/senhas.py).
"""

import logging
import os
import posixpath
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

import psycopg

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.lurkqvd import __version__, fuso
from src.lurkqvd.pipeline.gerador_qvd import CargaQvd
from src.lurkqvd.api.auth import UsuarioAtual, exigir_papel, get_repo
from src.lurkqvd.repository.repositorio import (
    AgendamentoInvalido,
    CargaJaEmExecucao,
    OperacaoNaoPermitida,
    Repositorio,
    proximas_execucoes,
)

# LURKQVD_DOCS=0 esconde a documentação interativa (/docs, /redoc, /openapi.json)
_DOCS = os.getenv("LURKQVD_DOCS", "1") != "0"
app = FastAPI(title="LurkQVD", version=__version__,docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
              openapi_url="/openapi.json" if _DOCS else None)

# Origens do front autorizadas a chamar a API (separadas por vírgula).
logger = logging.getLogger("lurkqvd.api")


# Erro inesperado vira JSON 500 *dentro* do CORS. Sem isso, o 500 sai pelo
# ServerErrorMiddleware do Starlette (fora do CORS), sem Access-Control-Allow-Origin,
# e o navegador só mostra "Failed to fetch". Tem que ser registrado ANTES do CORS
# (o último middleware registrado é o mais externo).
@app.middleware("http")
async def erro_inesperado(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("erro inesperado em %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno na API. Veja o log do servidor."},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("LURKQVD_CORS", "http://localhost:5173").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------- #
# Dependências
# ---------------------------------------------------------------------- #
@lru_cache
def get_qlik():
    """Client da Qlik, criado só na 1ª rota que precisar (key nos segredos, tenant nas configurações).

    Quando a key ou o tenant mudam pela tela, o cache é limpo (get_qlik.cache_clear()).
    """
    from src.lurkqvd.clients.qlik import QlikCredentials, QlikQvd
    from src.lurkqvd.config import qlik_conexao

    tenant = get_repo().config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
    try:
        return QlikQvd(QlikCredentials(token=qlik_conexao.ler_token()), tenant)
    except RuntimeError as e:  # Qlik ainda não configurada (instalação nova) ou segredos inacessíveis
        raise HTTPException(422, f"Qlik Cloud indisponível: {e} Configure em Configurações › Qlik Cloud.")


Repo = Annotated[Repositorio, Depends(get_repo)]
Leitor = Annotated[dict, Depends(exigir_papel("leitor"))]   # qualquer usuário logado
Editor = Annotated[dict, Depends(exigir_papel("editor"))]   # pode executar cargas
Admin = Annotated[dict, Depends(exigir_papel("admin"))]


# ---------------------------------------------------------------------- #
# Schemas
# ---------------------------------------------------------------------- #
class Espaco(BaseModel):
    connection_id: UUID
    space_id: str | None
    nome: str
    tipo: str
    atualizado_em: datetime


class CargaResumo(BaseModel):
    id: int
    nome: str
    qlik_path: str
    connection_id: UUID | None
    espaco_nome: str | None
    file_id: UUID | None
    ativo: bool
    ultima_execucao_id: int | None
    ultimo_status: str | None
    ultima_finalizacao: datetime | None
    ultimo_tamanho_bytes: int | None = None
    agendamento: str | None = None
    proxima_execucao: datetime | None = None
    criado_em: datetime | None = None
    criador_nome: str | None = None
    criador_email: str | None = None
    criador_foto: str | None = None
    fonte_id: int | None = None
    fonte_nome: str | None = None
    fonte_padrao: bool | None = None


class EspacoResumo(BaseModel):
    connection_id: UUID
    space_id: str | None
    nome: str
    tipo: str
    qtd_cargas: int
    com_erro: int
    em_andamento: int
    bytes_publicados: int
    ultima_execucao: datetime | None


class Pasta(BaseModel):
    nome: str
    caminho: str
    qtd_cargas: int


class ArquivoPasta(BaseModel):
    """Um arquivo da pasta na Qlik, ligado (ou não) a uma carga do LurkQVD."""
    file_id: UUID | None          # None = carga ainda não publicou o arquivo
    nome: str
    caminho: str
    tamanho_bytes: int | None
    modificado_em: datetime | None
    carga: CargaResumo | None     # None = arquivo que não é gerado pelo LurkQVD


class ConteudoEspaco(BaseModel):
    espaco: Espaco
    pasta: str
    pastas: list[Pasta]
    cargas: list[CargaResumo]
    arquivos: list[ArquivoPasta] = []
    aviso: str | None = None


class PastaCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=100, pattern=r"^[^<>\":|?*/\\]+$")


class CargaCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$")
    query: str = Field(min_length=1)
    qlik_path: str = Field(pattern=r"^[^<>\":|?*]+\.qvd$")  # mesmo padrão de nome da API da Qlik
    connection_id: UUID | None = None
    params: dict = Field(default_factory=dict)
    agendamento: str | None = Field(default=None, max_length=100, description="Expressão cron; vazio = só manual")
    fonte_id: int | None = Field(default=None, description="Fonte de dados; vazio = a fonte padrão")
    aplicacao_id: int | None = Field(default=None, description="Aplicação em que a carga entra (no fim); vazio = solta")


class DestinoAlterar(BaseModel):
    connection_id: UUID | None = Field(default=None, description="Espaço de destino; vazio = espaço pessoal")
    pasta: str = Field(default="", max_length=400, pattern=r'^[^<>":|?*\\]*$', description="Pasta dentro do espaço; vazio = raiz")


class CargaAlterar(BaseModel):
    agendamento: str | None = Field(default=None, max_length=100)
    ativo: bool | None = None
    query: str | None = Field(default=None, min_length=1)
    fonte_id: int | None = Field(default=None, description="Fonte de dados; null = acompanhar a fonte padrão")


class PreviaAgendamento(BaseModel):
    agendamento: str = Field(min_length=1, max_length=100)


class CargaDetalhe(BaseModel):
    id: int
    nome: str
    query: str
    params: dict
    qlik_path: str
    connection_id: UUID | None
    file_id: UUID | None
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime
    agendamento: str | None = None
    fuso: str | None = None
    proxima_execucao: datetime | None = None
    fonte_id: int | None = None
    fonte_nome: str | None = None
    fonte_padrao: bool | None = None


class Execucao(BaseModel):
    id: int
    carga_id: int
    status: str
    origem: str
    solicitado_em: datetime
    iniciado_em: datetime | None
    finalizado_em: datetime | None
    linhas: int | None
    colunas: int | None
    tamanho_bytes: int | None
    seg_extracao: Decimal | None
    seg_geracao: Decimal | None
    seg_upload: Decimal | None
    erro: str | None
    usuario_nome: str | None = None
    usuario_email: str | None = None
    usuario_foto: str | None = None
    token_nome: str | None = None
    carga_nome: str | None = None
    terminou: bool | None = None
    progresso: dict | None = None      # fase, linhas, bytes... enquanto roda (atualizado a cada ~2s)
    cancelar_em: datetime | None = None  # cancelamento pedido (o worker para no próximo ponto seguro)
    memoria_pico_bytes: int | None = None  # quanto a execução fez o worker crescer (base da reserva na fila)


class Resumo(BaseModel):
    total_cargas: int
    cargas_ativas: int
    com_erro: int
    em_andamento: int
    bytes_publicados: int
    execucoes_24h: int


class ExecucaoRecente(BaseModel):
    id: int
    carga_id: int
    carga_nome: str
    status: str
    origem: str
    solicitado_em: datetime
    iniciado_em: datetime | None
    finalizado_em: datetime | None
    linhas: int | None
    tamanho_bytes: int | None
    seg_total: Decimal
    erro: str | None
    usuario_nome: str | None
    usuario_email: str | None
    usuario_foto: str | None = None
    token_nome: str | None = None


class ExecucaoCriada(BaseModel):
    execucao_id: int
    status: str = "pendente"


# ---------------------------------------------------------------------- #
# Rotas
# ---------------------------------------------------------------------- #
@app.get("/health")
def health(repo: Repo) -> dict:
    repo.listar_espacos()  # falha aqui se o Postgres estiver fora
    return {"status": "ok", "versao": __version__}


@app.get("/resumo", response_model=Resumo)
def resumo(repo: Repo, _: Leitor):
    return repo.resumo()


class ExecucoesDia(BaseModel):
    dia: date
    sucesso: int
    erro: int
    em_andamento: int
    cargas_com_erro: list[str]


@app.get("/resumo/diario", response_model=list[ExecucoesDia])
def resumo_diario(repo: Repo, _: Leitor, dias: int = 14):
    """Execuções por dia (no fuso da instalação, LURKQVD_FUSO), para o gráfico do painel."""
    return repo.execucoes_por_dia(dias=min(max(dias, 1), 90))


@app.get("/execucoes", response_model=list[ExecucaoRecente])
def execucoes_recentes(repo: Repo, _: Leitor, limite: int = 10):
    return repo.execucoes_recentes(limite=min(max(limite, 1), 100))


@app.post("/espacos/sincronizar", response_model=list[Espaco])
def sincronizar_espacos(repo: Repo, _: Admin):
    """Atualiza o cache de espaços consultando a Qlik Cloud."""
    repo.sincronizar_espacos(get_qlik().list_spaces())
    return repo.listar_espacos()


@app.get("/espacos/resumo", response_model=list[EspacoResumo])
def resumo_espacos(repo: Repo, _: Leitor):
    return repo.resumo_espacos()


def _espaco_ou_404(repo: Repositorio, connection_id: UUID) -> dict:
    espaco = repo.buscar_espaco(str(connection_id))
    if not espaco:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Espaço não encontrado. Atualize a lista de espaços.")
    return espaco


def _normalizar_pasta(pasta: str) -> str:
    return "/".join(p for p in pasta.strip().strip("/").split("/") if p and p not in (".", ".."))


@app.get("/espacos/{connection_id}/conteudo", response_model=ConteudoEspaco)
def conteudo_espaco(connection_id: UUID, repo: Repo, _: Leitor, pasta: str = ""):
    """Pastas (espelhadas da Qlik) e cargas que estão diretamente numa pasta do espaço."""
    espaco = _espaco_ou_404(repo, connection_id)
    pessoal = espaco["tipo"] == "personal"
    pasta = _normalizar_pasta(pasta)
    prefixo = f"{pasta}/" if pasta else ""

    # cargas do espaço (no pessoal, as cargas são gravadas sem connection_id)
    cargas = [
        c for c in repo.listar_cargas()
        if (str(c["connection_id"]) == str(connection_id)) or (pessoal and c["connection_id"] is None)
    ]

    diretas, contagem = [], {}
    for c in cargas:
        caminho = c["qlik_path"].strip("/")
        diretorio = posixpath.dirname(caminho)
        if diretorio == pasta:
            diretas.append(c)
        elif caminho.startswith(prefixo):
            sub = caminho[len(prefixo):].split("/", 1)[0]
            contagem[sub] = contagem.get(sub, 0) + 1

    # pastas e arquivos reais da Qlik; se a Qlik falhar, mostra ao menos o que as cargas indicam
    nomes, aviso, itens = set(contagem), None, []
    try:
        itens = get_qlik().list_files(None if pessoal else str(connection_id), pasta or None)
        nomes |= {i["base_name"] for i in itens if i["is_folder"]}
    except Exception:
        aviso = "Não foi possível ler a pasta na Qlik agora; mostrando só o que as cargas indicam."

    pastas = [
        Pasta(nome=n, caminho=f"{prefixo}{n}", qtd_cargas=contagem.get(n, 0))
        for n in sorted(nomes, key=str.lower)
    ]

    # cada arquivo da Qlik, ligado à carga que o gera (pelo ID do arquivo ou pelo caminho)
    por_id = {str(c["file_id"]): c for c in diretas if c["file_id"]}
    por_caminho = {c["qlik_path"].strip("/"): c for c in diretas}
    ligadas: set[int] = set()
    arquivos: list[ArquivoPasta] = []
    for i in itens:
        if i["is_folder"]:
            continue
        carga = por_id.get(str(i["id"])) or por_caminho.get(i["name"].strip("/"))
        if carga:
            ligadas.add(carga["id"])
        arquivos.append(ArquivoPasta(
            file_id=i["id"], nome=i["base_name"], caminho=i["name"], tamanho_bytes=i.get("size"),
            modificado_em=i.get("modified_date"), carga=carga,
        ))
    # cargas desta pasta que ainda não publicaram o arquivo (nunca rodaram ou só falharam)
    for c in diretas:
        if c["id"] not in ligadas:
            caminho = c["qlik_path"].strip("/")
            arquivos.append(ArquivoPasta(
                file_id=None, nome=posixpath.basename(caminho), caminho=caminho,
                tamanho_bytes=None, modificado_em=None, carga=c,
            ))
    # primeiro os gerados pelo LurkQVD, depois os demais; dentro de cada grupo, por nome
    arquivos.sort(key=lambda a: (a.carga is None, a.nome.lower()))

    return ConteudoEspaco(espaco=espaco, pasta=pasta, pastas=pastas, cargas=diretas, arquivos=arquivos, aviso=aviso)


@app.post("/espacos/{connection_id}/pastas", response_model=Pasta, status_code=status.HTTP_201_CREATED)
def criar_pasta(connection_id: UUID, body: PastaCriar, repo: Repo, usuario: Admin, pasta: str = ""):
    """Cria a pasta de verdade no espaço da Qlik (o app espelha a estrutura da Qlik)."""
    import requests

    espaco = _espaco_ou_404(repo, connection_id)
    caminho = "/".join(p for p in [_normalizar_pasta(pasta), body.nome.strip()] if p)
    try:
        get_qlik().create_folder(None if espaco["tipo"] == "personal" else str(connection_id), caminho)
    except FileExistsError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Já existe uma pasta '{body.nome}' aqui.")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sem permissão para criar pastas nesse espaço da Qlik.")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "A Qlik recusou a criação da pasta.")

    repo.auditar(usuario["id"], "pasta.criar", "pasta", caminho, {"espaco": espaco["nome"]})
    return Pasta(nome=body.nome.strip(), caminho=caminho, qtd_cargas=0)


@app.get("/espacos", response_model=list[Espaco])
def listar_espacos(repo: Repo, _: Leitor):
    return repo.listar_espacos()


@app.get("/cargas", response_model=list[CargaResumo])
def listar_cargas(repo: Repo, _: Leitor):
    return repo.listar_cargas()


@app.post("/cargas", response_model=CargaDetalhe, status_code=status.HTTP_201_CREATED)
def criar_carga(body: CargaCriar, repo: Repo, usuario: Admin):
    carga = CargaQvd(
        nome=body.nome,
        query=body.query,
        qlik_path=body.qlik_path.strip("/"),
        connection_id=str(body.connection_id) if body.connection_id else None,
        params=body.params,
        fonte_id=body.fonte_id,
    )
    try:
        carga_id = repo.criar_carga(carga, usuario_id=usuario["id"], agendamento=(body.agendamento or "").strip() or None,
                                    aplicacao_id=body.aplicacao_id)
    except AgendamentoInvalido as e:
        raise HTTPException(422, str(e))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe carga com esse nome ou esse destino.")
    except psycopg.errors.ForeignKeyViolation as e:
        if "fonte" in str(e):
            raise HTTPException(422, "Fonte de dados não encontrada.")
        if "aplicac" in str(e):
            raise HTTPException(422, "Aplicação não encontrada.")
        raise HTTPException(422, "connection_id não está no cache de espaços.")
    return repo.buscar_carga_detalhe(carga_id)


@app.post("/agendamento/previa")
def previa_agendamento(body: PreviaAgendamento, _: Leitor) -> dict:
    """Valida um cron e devolve os próximos horários e o fuso em que ele vale (para o front mostrar antes de salvar)."""
    try:
        proximas = proximas_execucoes(body.agendamento, quantidade=3)
    except AgendamentoInvalido as e:
        raise HTTPException(422, str(e))
    return {"proximas": [p.isoformat() for p in proximas], "fuso": fuso.FUSO}


@app.patch("/cargas/{carga_id}", response_model=CargaDetalhe)
def alterar_carga(carga_id: int, body: CargaAlterar, repo: Repo, usuario: Admin):
    """Muda agendamento, consulta, fonte e/ou ativa/desativa. Agendamento enviado como null remove o
    agendamento; fonte_id enviado como null faz a carga acompanhar a fonte padrão.

    Consulta e fonte novas valem a partir da próxima execução (a que estiver rodando termina com as antigas).
    """
    campos = body.model_dump(exclude_unset=True)
    kwargs = {}
    if "agendamento" in campos:
        kwargs["agendamento"] = (campos["agendamento"] or "").strip() or None
    if "ativo" in campos:
        kwargs["ativo"] = campos["ativo"]
    if campos.get("query") is not None:
        if not campos["query"].strip():
            raise HTTPException(422, "A consulta não pode ficar vazia.")
        kwargs["query"] = campos["query"]
    if "fonte_id" in campos:
        from src.lurkqvd.config import fontes

        if campos["fonte_id"] is not None:
            fonte = repo.buscar_fonte(campos["fonte_id"])
            if not fonte:
                raise HTTPException(422, "Fonte de dados não encontrada.")
            if not fontes.TIPOS.get(fonte["tipo"], {}).get("suportado"):
                raise HTTPException(422, "Essa fonte é de um tipo de banco ainda não suportado.")
        kwargs["fonte_id"] = campos["fonte_id"]
    try:
        carga = repo.atualizar_carga(carga_id, usuario["id"], **kwargs)
    except AgendamentoInvalido as e:
        raise HTTPException(422, str(e))
    if not carga:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carga não encontrada.")
    return carga


@app.post("/cargas/{carga_id}/destino", response_model=CargaDetalhe)
def mudar_destino_carga(carga_id: int, body: DestinoAlterar, repo: Repo, usuario: Admin):
    """Move a carga para outro espaço e/ou pasta. O nome do arquivo continua o mesmo. Vale a partir da próxima
    execução; o arquivo antigo fica na Qlik (apague-o lá se ninguém mais usar)."""
    atual = repo.buscar_carga_detalhe(carga_id)
    if not atual:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carga não encontrada.")
    partes = [p.strip() for p in body.pasta.split("/") if p.strip()]
    if any(p in (".", "..") for p in partes):
        raise HTTPException(422, "Pasta inválida.")
    arquivo = atual["qlik_path"].rsplit("/", 1)[-1]
    qlik_path = "/".join([*partes, arquivo])
    connection_id = str(body.connection_id) if body.connection_id else None
    try:
        return repo.mudar_destino(carga_id, connection_id, qlik_path, usuario["id"])
    except OperacaoNaoPermitida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "Espaço não encontrado: atualize a lista de espaços da Qlik e tente de novo.")


@app.get("/cargas/{carga_id}", response_model=CargaDetalhe)
def detalhar_carga(carga_id: int, repo: Repo, _: Leitor):
    carga = repo.buscar_carga_detalhe(carga_id)
    if not carga:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carga não encontrada.")
    return carga


def _executar(carga: dict | None, repo: Repositorio, usuario: dict):
    """Põe a carga na fila. 409 traz o execucao_id da execução que já estava ativa."""
    if not carga:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carga não encontrada.")
    if not carga["ativo"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Carga inativa.")
    token_id = usuario.get("token_id")
    try:
        execucao_id = repo.enfileirar(carga["id"], origem="token" if token_id else "api",
                                      usuario_id=usuario["id"], token_id=token_id)
    except CargaJaEmExecucao as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "A carga já está na fila ou rodando.", "execucao_id": getattr(e, "execucao_id", None)},
        )
    return ExecucaoCriada(execucao_id=execucao_id)


@app.post("/cargas/{carga_id}/executar", response_model=ExecucaoCriada, status_code=status.HTTP_202_ACCEPTED)
def executar_carga(carga_id: int, repo: Repo, usuario: Editor):
    """202: aceito na fila. Acompanhe por GET /execucoes/{execucao_id}."""
    return _executar(repo.buscar_carga_detalhe(carga_id), repo, usuario)


@app.post("/cargas/nome/{nome}/executar", response_model=ExecucaoCriada, status_code=status.HTTP_202_ACCEPTED)
def executar_carga_por_nome(nome: str, repo: Repo, usuario: Editor):
    """Igual a /cargas/{id}/executar, mas pelo nome (estável entre ambientes; bom para DAGs)."""
    achada = repo.buscar_carga_por_nome(nome)
    return _executar(repo.buscar_carga_detalhe(achada[0]) if achada else None, repo, usuario)


@app.get("/cargas/{carga_id}/execucoes", response_model=list[Execucao])
def historico_carga(carga_id: int, repo: Repo, _: Leitor, limite: int = 20):
    return repo.historico(carga_id, limite=min(limite, 200))


@app.get("/execucoes/{execucao_id}", response_model=Execucao)
def status_execucao(execucao_id: int, repo: Repo, _: Leitor):
    """Status de uma execução. terminou=true quando chega em sucesso, erro ou cancelado (bom para sensores)."""
    execucao = repo.buscar_execucao(execucao_id)
    if not execucao:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
    return {**execucao, "terminou": execucao["status"] in ("sucesso", "erro", "cancelado")}


@app.post("/execucoes/{execucao_id}/cancelar", response_model=Execucao)
def cancelar_execucao(execucao_id: int, repo: Repo, usuario: Editor):
    """Cancela uma execução. Na fila: sai na hora. Rodando: o worker para no próximo ponto seguro
    (a cada lote lido ou pedaço enviado) e o QVD na Qlik fica como estava."""
    try:
        execucao = repo.pedir_cancelamento(execucao_id, usuario["id"])
    except OperacaoNaoPermitida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if not execucao:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
    return {**execucao, "terminou": execucao["status"] in ("sucesso", "erro", "cancelado")}


# ---------------------------------------------------------------------- #
# Configurações: usuários e acesso (só admin)
# ---------------------------------------------------------------------- #
PapelTipo = Literal["admin", "editor", "leitor"]


class UsuarioAdmin(BaseModel):
    id: int
    email: str
    nome: str | None
    papel: str
    ativo: bool
    criado_em: datetime
    ultimo_login: datetime | None
    foto_url: str | None = None
    trocar_senha: bool = False
    tem_senha: bool = True
    cargas_criadas: int = 0


class UsuarioAlterar(BaseModel):
    papel: PapelTipo | None = None
    ativo: bool | None = None


@app.get("/usuarios", response_model=list[UsuarioAdmin])
def listar_usuarios(repo: Repo, _: Admin):
    return repo.listar_usuarios()


@app.patch("/usuarios/{usuario_id}", response_model=UsuarioAdmin)
def alterar_usuario(usuario_id: int, body: UsuarioAlterar, repo: Repo, usuario: Admin):
    try:
        alterado = repo.alterar_usuario(usuario_id, usuario["id"], papel=body.papel, ativo=body.ativo)
    except OperacaoNaoPermitida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if not alterado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    # devolve no mesmo formato da lista (com a contagem de cargas)
    return next(u for u in repo.listar_usuarios() if u["id"] == usuario_id)


# ---------------------------------------------------------------------- #
# Configurações: worker e agenda
# ---------------------------------------------------------------------- #
class WorkerStatus(BaseModel):
    id: str
    host: str
    pid: int
    iniciado_em: datetime
    ultimo_sinal: datetime
    encerrado_em: datetime | None
    execucao_id: int | None
    carga_nome: str | None
    estado: Literal["ativo", "sem_sinal", "encerrado"]


class FilaStatus(BaseModel):
    pendentes: int
    rodando: int
    pendente_desde: datetime | None
    agendadas: int


class AgendaStatus(BaseModel):
    pausada: bool
    motivo: str | None
    desde: datetime | None
    por_nome: str | None


class QlikResumo(BaseModel):
    ok: bool | None = None
    expira_em: datetime | None = None
    verificado_em: datetime | None = None


class StatusSistema(BaseModel):
    workers: list[WorkerStatus]
    workers_ativos: int
    ultimo_sinal: datetime | None
    fila: FilaStatus
    agenda: AgendaStatus
    limite_travada_min: int
    fuso_padrao: str
    qlik: QlikResumo | None = None


class AgendaAlterar(BaseModel):
    pausada: bool
    motivo: str | None = Field(default=None, max_length=200)


class ExecucaoConfig(BaseModel):
    limite_travada_min: int = Field(ge=10, le=720)


@app.get("/sistema/status", response_model=StatusSistema)
def status_sistema(repo: Repo, _: Leitor):
    """Workers, fila e agenda. Leitor pode ver (o painel mostra aviso se o worker parar)."""
    return repo.status_sistema()


@app.put("/sistema/agenda", response_model=StatusSistema)
def alterar_agenda(body: AgendaAlterar, repo: Repo, usuario: Admin):
    repo.pausar_agenda(body.pausada, body.motivo, usuario["id"])
    return repo.status_sistema()


@app.put("/sistema/execucao", response_model=StatusSistema)
def alterar_execucao(body: ExecucaoConfig, repo: Repo, usuario: Admin):
    repo.alterar_limite_travada(body.limite_travada_min, usuario["id"])
    return repo.status_sistema()


# ---------------------------------------------------------------------- #
# Configurações: auditoria (só admin)
# ---------------------------------------------------------------------- #
class RegistroAuditoria(BaseModel):
    id: int
    acao: str
    alvo_tipo: str | None
    alvo_id: str | None
    alvo_nome: str | None
    detalhes: dict
    criado_em: datetime
    usuario_id: int | None
    usuario_nome: str | None
    usuario_email: str | None
    usuario_foto: str | None = None


class PaginaAuditoria(BaseModel):
    itens: list[RegistroAuditoria]
    proximo: int | None  # passe como antes_de para carregar os mais antigos


@app.get("/auditoria", response_model=PaginaAuditoria)
def listar_auditoria(
    repo: Repo,
    _: Admin,
    categoria: Literal["cargas", "execucoes", "acessos", "sistema", "logins"] | None = None,
    usuario_id: int | None = None,
    incluir_logins: bool = False,
    antes_de: int | None = None,
    limite: int = 50,
):
    limite = min(max(limite, 1), 200)
    # pede 1 a mais para saber se existe próxima página
    itens = repo.listar_auditoria(categoria=categoria, usuario_id=usuario_id, incluir_logins=incluir_logins,
                                  antes_de=antes_de, limite=limite + 1)
    tem_mais = len(itens) > limite
    itens = itens[:limite]
    return {"itens": itens, "proximo": itens[-1]["id"] if tem_mais and itens else None}


# ---------------------------------------------------------------------- #
# Configurações: Qlik Cloud (só admin)
# ---------------------------------------------------------------------- #
class TesteQlik(BaseModel):
    ok: bool | None = None
    erro: str | None = None
    tenant: str | None = None
    latencia_ms: int | None = None
    dono_nome: str | None = None
    dono_email: str | None = None
    chave_id: str | None = None
    chave_descricao: str | None = None
    chave_status: str | None = None
    expira_em: datetime | None = None
    token_mascara: str | None = None
    verificado_em: datetime | None = None


class ConfigQlik(BaseModel):
    tenant: str
    secret: str
    alterado_em: datetime | None
    alterado_por: str | None
    status: TesteQlik | None


TENANT_PATTERN = r"^[a-z0-9-]+(\.[a-z0-9-]+)*$"  # ex.: minha-empresa.us (sem https:// e sem .qlikcloud.com)


class QlikAlterar(BaseModel):
    tenant: str | None = Field(default=None, pattern=TENANT_PATTERN, max_length=100)
    token: str | None = Field(default=None, min_length=20, max_length=4000)


def _testar_qlik(tenant: str, token: str | None) -> dict:
    from src.lurkqvd.config import qlik_conexao

    if not tenant:  # instalação nova: o tenant vem antes da key
        return qlik_conexao.testar("", "")
    if token is None and not qlik_conexao.tem_token():
        from datetime import timezone

        return {"ok": False, "erro": "Falta a API key da Qlik Cloud: adicione-a em API key, abaixo.", "tenant": tenant,
                "verificado_em": datetime.now(timezone.utc)}
    if token is None:
        try:
            token = qlik_conexao.ler_token()
        except Exception as e:  # sem acesso aos segredos, segredo sem a chave...
            logger.exception("falha ao ler a API key da Qlik")
            return {"ok": False, "erro": f"Não consegui ler a API key salva: {e}", "tenant": tenant}
    return qlik_conexao.testar(tenant, token.strip())


def _config_qlik(repo: Repositorio) -> dict:
    from src.lurkqvd.config import qlik_conexao

    cfg = repo.config_qlik(qlik_conexao.TENANT_PADRAO)
    return {**cfg, "secret": qlik_conexao.nome_secret()}


@app.get("/config/qlik", response_model=ConfigQlik)
def ver_config_qlik(repo: Repo, _: Admin, testar: bool = False):
    """Configuração atual. Com ?testar=true, testa a key salva agora e atualiza o status guardado."""
    from src.lurkqvd.config import qlik_conexao

    if testar:
        cfg = repo.config_qlik(qlik_conexao.TENANT_PADRAO)
        repo.salvar_status_qlik(qlik_conexao.para_cache(_testar_qlik(cfg["tenant"], None)))
    return _config_qlik(repo)


@app.post("/config/qlik/testar", response_model=TesteQlik)
def testar_config_qlik(body: QlikAlterar, repo: Repo, _: Admin):
    """Testa uma key e/ou tenant ANTES de salvar (nada é gravado)."""
    from src.lurkqvd.config import qlik_conexao

    tenant = body.tenant or repo.config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
    return _testar_qlik(tenant, body.token)


@app.put("/config/qlik", response_model=ConfigQlik)
def alterar_config_qlik(body: QlikAlterar, repo: Repo, usuario: Admin):
    """Troca a key e/ou o tenant. Só grava se o teste com os valores novos passar."""
    from src.lurkqvd.config import qlik_conexao, segredos

    atual = repo.config_qlik(qlik_conexao.TENANT_PADRAO)["tenant"]
    tenant = body.tenant or atual
    if not body.token and tenant == atual:
        raise HTTPException(422, "Nada para alterar.")

    # instalação nova: o tenant vem antes da key, e sem key não há o que testar
    if not body.token and not qlik_conexao.tem_token():
        repo.alterar_qlik(usuario["id"], tenant=tenant, tenant_mudou=tenant != atual, token_mascara=None, chave_id=None)
        repo.salvar_status_qlik(qlik_conexao.para_cache(_testar_qlik(tenant, None)))
        get_qlik.cache_clear()
        return _config_qlik(repo)

    teste = _testar_qlik(tenant, body.token)
    if not teste.get("ok"):
        raise HTTPException(422, f"Não salvei: {teste.get('erro')}")

    if body.token:
        try:
            qlik_conexao.gravar_token(body.token.strip())
        except Exception as e:
            logger.exception("falha ao gravar a API key da Qlik")
            codigo, msg = segredos.mensagem_erro(e, qlik_conexao.nome_secret())
            raise HTTPException(codigo, msg)

    repo.alterar_qlik(usuario["id"], tenant=tenant, tenant_mudou=tenant != atual,
                      token_mascara=teste.get("token_mascara") if body.token else None,
                      chave_id=teste.get("chave_id") if body.token else None)
    repo.salvar_status_qlik(qlik_conexao.para_cache(teste))
    get_qlik.cache_clear()  # próximas rotas já usam a key/tenant novos (o worker percebe sozinho)
    return _config_qlik(repo)


# ---------------------------------------------------------------------- #
# Configurações: fontes de dados (só admin)
# ---------------------------------------------------------------------- #
TipoBanco = Literal["mssql", "postgres", "mysql", "oracle"]


class TesteFonte(BaseModel):
    ok: bool | None = None
    erro: str | None = None
    versao: str | None = None
    latencia_ms: int | None = None
    banco_conectado: str | None = None
    testado_em: datetime | None = None


class Fonte(BaseModel):
    id: int
    nome: str
    tipo: str
    host: str
    porta: int
    banco: str
    usuario: str
    opcoes: dict
    padrao: bool
    ultimo_teste: TesteFonte | None
    criado_em: datetime
    atualizado_em: datetime
    qtd_cargas: int = 0


class FonteDados(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    tipo: TipoBanco = "mssql"
    host: str = Field(min_length=1, max_length=255, pattern=r"^[^\s;]+$")
    porta: int = Field(ge=1, le=65535)
    banco: str = Field(min_length=1, max_length=128)
    usuario: str = Field(min_length=1, max_length=128)
    opcoes: dict = Field(default_factory=dict)


class FonteCriar(FonteDados):
    senha: str = Field(min_length=1, max_length=512)
    padrao: bool = False


class FonteAlterar(FonteDados):
    senha: str | None = Field(default=None, max_length=512)  # vazio = mantém a atual


class FonteTestar(FonteDados):
    senha: str | None = Field(default=None, max_length=512)
    fonte_id: int | None = None  # testando a edição de uma fonte salva sem trocar a senha


def _tipo_suportado(tipo: str) -> None:
    from src.lurkqvd.config import fontes

    if not fontes.TIPOS.get(tipo, {}).get("suportado"):
        raise HTTPException(422, f"{fontes.TIPOS.get(tipo, {}).get('nome', tipo)} ainda não é suportado.")


def _senha_salva(fonte_id: int) -> str:
    from src.lurkqvd.config import fontes

    try:
        return fontes.ler_senha(fonte_id)
    except Exception as e:
        raise HTTPException(502, f"Não consegui ler a senha salva: {e}")


def _erro_secret(e: Exception):
    from src.lurkqvd.config import fontes, segredos

    logger.exception("falha nos segredos (fontes)")
    codigo, msg = segredos.mensagem_erro(e, fontes.nome_secret())
    raise HTTPException(codigo, msg)


@app.get("/fontes/tipos")
def tipos_de_banco(_: Admin) -> list[dict]:
    from src.lurkqvd.config import fontes

    return [{"tipo": k, **v} for k, v in fontes.TIPOS.items()]


@app.get("/fontes", response_model=list[Fonte])
def listar_fontes(repo: Repo, _: Admin):
    return repo.listar_fontes()


@app.post("/fontes/testar", response_model=TesteFonte)
def testar_fonte(body: FonteTestar, _: Admin):
    """Testa a conexão com os dados informados (nada é gravado)."""
    from src.lurkqvd.config import fontes

    _tipo_suportado(body.tipo)
    senha = body.senha or (_senha_salva(body.fonte_id) if body.fonte_id else None)
    if not senha:
        raise HTTPException(422, "Informe a senha.")
    return fontes.testar(body.model_dump(exclude={"senha", "fonte_id"}), senha)


@app.post("/fontes", response_model=Fonte, status_code=status.HTTP_201_CREATED)
def criar_fonte(body: FonteCriar, repo: Repo, usuario: Admin):
    """Cria a fonte só se o teste de conexão passar; a senha vai para os segredos."""
    from src.lurkqvd.config import fontes

    _tipo_suportado(body.tipo)
    dados = body.model_dump(exclude={"senha"})
    teste = fontes.testar(dados, body.senha)
    if not teste["ok"]:
        raise HTTPException(422, f"Não salvei: {teste['erro']}")
    try:
        fonte = repo.criar_fonte(dados, usuario["id"], teste)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma fonte com esse nome.")
    try:
        fontes.gravar_senha(fonte["id"], body.senha)
    except Exception as e:
        repo.remover_fonte(fonte["id"], usuario["id"])  # sem senha guardada, a fonte não serve
        _erro_secret(e)
    return next(f for f in repo.listar_fontes() if f["id"] == fonte["id"])


@app.put("/fontes/{fonte_id}", response_model=Fonte)
def alterar_fonte(fonte_id: int, body: FonteAlterar, repo: Repo, usuario: Admin):
    from src.lurkqvd.config import fontes

    if not repo.buscar_fonte(fonte_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    _tipo_suportado(body.tipo)
    dados = body.model_dump(exclude={"senha"})
    senha = body.senha or _senha_salva(fonte_id)
    teste = fontes.testar(dados, senha)
    if not teste["ok"]:
        raise HTTPException(422, f"Não salvei: {teste['erro']}")
    if body.senha:
        try:
            fontes.gravar_senha(fonte_id, body.senha)
        except Exception as e:
            _erro_secret(e)
    try:
        repo.alterar_fonte(fonte_id, dados, usuario["id"], ultimo_teste=teste, senha_trocada=bool(body.senha))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma fonte com esse nome.")
    return next(f for f in repo.listar_fontes() if f["id"] == fonte_id)


@app.post("/fontes/{fonte_id}/testar", response_model=TesteFonte)
def testar_fonte_salva(fonte_id: int, repo: Repo, _: Admin):
    """Testa a fonte como está salva e guarda o resultado."""
    from src.lurkqvd.config import fontes

    fonte = repo.buscar_fonte(fonte_id)
    if not fonte:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    teste = fontes.testar(fonte, _senha_salva(fonte_id))
    repo.salvar_teste_fonte(fonte_id, teste)
    return teste


@app.post("/fontes/{fonte_id}/padrao", response_model=list[Fonte])
def definir_fonte_padrao(fonte_id: int, repo: Repo, usuario: Admin):
    if not repo.definir_fonte_padrao(fonte_id, usuario["id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    return repo.listar_fontes()


@app.delete("/fontes/{fonte_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_fonte(fonte_id: int, repo: Repo, usuario: Admin):
    from src.lurkqvd.config import fontes

    try:
        nome = repo.remover_fonte(fonte_id, usuario["id"])
    except OperacaoNaoPermitida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if nome is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte não encontrada.")
    try:
        fontes.apagar_senha(fonte_id)
    except Exception:  # a fonte já saiu; a senha órfã não é usada por ninguém
        logger.warning("fonte %s removida, mas a senha não saiu dos segredos", fonte_id, exc_info=True)


# ---------------------------------------------------------------------- #
# Configurações: segredos (só leitura, só admin)
# ---------------------------------------------------------------------- #
class SecretStatus(BaseModel):
    nome: str
    finalidade: str
    existe: bool
    legivel: bool
    erro: str | None
    atualizado_em: datetime | None = None
    chaves: int = 0                    # quantas chaves o JSON tem (ex.: senhas de fontes)


class StatusSegredos(BaseModel):
    erro: str | None
    chaves_fernet: int                 # quantas chaves em LURKQVD_FERNET_KEY
    secrets: list[SecretStatus]
    verificado_em: datetime | None = None


@app.get("/config/segredos", response_model=StatusSegredos)
def status_segredos(_: Admin):
    """Estado de cada segredo (no Postgres, criptografado). Consulta na hora: é só o Postgres."""
    from src.lurkqvd.config import segredos

    return segredos.diagnostico_lurkqvd()


# ---------------------------------------------------------------------- #
# Configurações: tokens de API (só admin)
# ---------------------------------------------------------------------- #
class TokenApi(BaseModel):
    id: int
    nome: str
    prefixo: str
    permissao: str
    expira_em: datetime | None
    criado_em: datetime
    ultimo_uso: datetime | None
    ultimo_ip: str | None
    revogado_em: datetime | None
    criado_por_nome: str | None
    revogado_por_nome: str | None
    estado: Literal["ativo", "vencido", "revogado"]
    execucoes: int = 0


class TokenCriado(TokenApi):
    token: str  # aparece só nesta resposta


class TokenCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    permissao: Literal["executar", "leitura"] = "executar"
    validade_dias: int | None = Field(default=None, ge=1, le=3650)


@app.get("/tokens", response_model=list[TokenApi])
def listar_tokens(repo: Repo, _: Admin):
    return repo.listar_tokens_api()


@app.post("/tokens", response_model=TokenCriado, status_code=status.HTTP_201_CREATED)
def criar_token(body: TokenCriar, repo: Repo, usuario: Admin):
    """O token em texto volta só aqui; depois disso, só o hash fica guardado."""
    linha, token = repo.criar_token_api(body.nome, body.permissao, body.validade_dias, usuario["id"])
    return {**linha, "token": token}


@app.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revogar_token(token_id: int, repo: Repo, usuario: Admin):
    if not repo.revogar_token_api(token_id, usuario["id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token não encontrado ou já revogado.")


# ---------------------------------------------------------------------- #
# Estimativa do tamanho do QVD (antes de gerar) e composição medida (depois)
# ---------------------------------------------------------------------- #
class ColunaEstimada(BaseModel):
    nome: str
    categoria: str
    distintos: int
    tem_nulo: bool
    bits: int
    bytes_simbolos: int
    bytes_indice: int
    bytes_total: int
    pct: float
    unica_por_linha: bool
    origem: str | None = None  # medido | exato | estatística | amostra


class Estimativa(BaseModel):
    linhas: int
    tamanho_bytes: int
    simbolos_bytes: int
    indice_bytes: int
    cabecalho_bytes: int
    bytes_por_linha: int
    pct_cota: float
    cota_gb: float
    colunas: list[ColunaEstimada]
    sugestoes: list[str]
    segundos: float
    origem_linhas: str | None = None  # exato | plano | amostra
    amostra: int | None = None
    amostra_aleatoria: bool | None = None  # True = páginas sorteadas da tabela (TABLESAMPLE)
    avisos: list[str] = []
    fonte_nome: str | None = None


class EstimativaPedido(BaseModel):
    query: str = Field(min_length=1)
    fonte_id: int | None = None
    params: dict = Field(default_factory=dict)


class Composicao(BaseModel):
    execucao_id: int
    finalizado_em: datetime | None
    tamanho_bytes: int | None  # tamanho real do QVD publicado
    linhas: int | None
    composicao: Estimativa


def _engine_para(repo: Repositorio, fonte_id: int | None):
    """(engine, nome da fonte, fechar) para a fonte informada ou a padrão."""
    from src.lurkqvd.config import fontes

    fonte = repo.fonte_para_execucao(fonte_id)
    if fonte:
        conexao = fontes.FonteSql(fonte, fontes.ler_senha(fonte["id"]))
        return conexao.engine, fonte["nome"], conexao.fechar
    if fonte_id is not None:
        raise HTTPException(422, "Fonte de dados não encontrada.")
    raise HTTPException(422, "Cadastre uma fonte em Configurações › Fontes de dados para estimar.")


@app.post("/estimativa", response_model=Estimativa)
def estimar_tamanho(body: EstimativaPedido, repo: Repo, _: Admin):
    """Estimativa rápida, sem varrer a tabela: plano estimado + estatísticas do banco + amostra TOP N."""
    from src.lurkqvd.pipeline import estimativa

    engine, fonte_nome, fechar = _engine_para(repo, body.fonte_id)
    try:
        resultado = estimativa.estimar_rapida(engine, body.query, body.params)
    except estimativa.ConsultaNaoSuportada as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        msg = str(e.args[-1] if getattr(e, "args", None) else e)
        if "HYT00" in msg or "timeout" in msg.lower():
            raise HTTPException(422, f"A estimativa passou de {estimativa.TIMEOUT_ESTIMATIVA}s.")
        raise HTTPException(422, f"O banco recusou a consulta: {msg.splitlines()[0][:300]}")
    finally:
        fechar()
    return {**resultado, "fonte_nome": fonte_nome}


@app.get("/cargas/{carga_id}/composicao", response_model=Composicao)
def composicao_carga(carga_id: int, repo: Repo, _: Leitor):
    """Peso de cada coluna no QVD, medido na última execução (sem consultar o banco de origem)."""
    c = repo.ultima_composicao(carga_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ainda sem composição: aparece depois da próxima execução.")
    return c


# ---------------------------------------------------------------------- #
# Aplicações (grupos de cargas + reload do app na Qlik)
# ---------------------------------------------------------------------- #
from src.lurkqvd.api import acesso as _acesso  # noqa: E402
from src.lurkqvd.api import aplicacoes as _aplicacoes  # noqa: E402
from src.lurkqvd.api import notificacoes as _notificacoes  # noqa: E402

app.include_router(_acesso.router)
app.include_router(_aplicacoes.router)
app.router.on_startup.append(_acesso.conferir_migracoes)
app.router.on_startup.append(_acesso.preparar_admin_padrao)
app.include_router(_notificacoes.router)
