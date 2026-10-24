"""Rotas das aplicações (grupos de cargas que alimentam um app da Qlik)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.lurkqvd.api.auth import exigir_papel, get_repo
from src.lurkqvd.repository.repositorio import (
    AgendamentoInvalido,
    AplicacaoJaEmExecucao,
    OperacaoNaoPermitida,
    Repositorio,
)

router = APIRouter()

Repo = Annotated[Repositorio, Depends(get_repo)]
Leitor = Annotated[dict, Depends(exigir_papel("leitor"))]
Editor = Annotated[dict, Depends(exigir_papel("editor"))]
Admin = Annotated[dict, Depends(exigir_papel("admin"))]

TERMINADOS = ("sucesso", "erro", "cancelado")


class AplicacaoCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    descricao: str | None = Field(default=None, max_length=500)
    qlik_app_id: str | None = Field(default=None, max_length=100)
    agendamento: str | None = Field(default=None, max_length=100)
    carga_ids: list[int] = []


class AplicacaoAlterar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    descricao: str | None = Field(default=None, max_length=500)
    qlik_app_id: str | None = Field(default=None, max_length=100)
    agendamento: str | None = Field(default=None, max_length=100)
    ativo: bool | None = None


class MoverCarga(BaseModel):
    carga_id: int
    origem_id: int | None = None   # None = vinha de "sem aplicação"
    destino_id: int | None = None  # None = só tirar da origem
    copiar: bool = False           # True = mantém na origem também
    posicao: int | None = None     # posição no destino (None = no fim)


def _qlik():
    from src.lurkqvd.api.main import get_qlik

    return get_qlik()


def _validar_app(app_id: str | None) -> tuple[str | None, str | None]:
    """(id, nome) do app na Qlik; 422 se não existir ou a API key não tiver acesso."""
    app_id = (app_id or "").strip() or None
    if not app_id:
        return None, None
    try:
        app = _qlik().obter_app(app_id)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Não consegui consultar a Qlik agora: {e}")
    if not app:
        raise HTTPException(422, "App não encontrado na Qlik, ou a API key do LurkQVD não tem acesso a ele.")
    return app["id"], app["nome"]


def _com_terminou(x: dict) -> dict:
    return {**x, "terminou": x["status"] in TERMINADOS}


@router.get("/aplicacoes")
def listar_aplicacoes(repo: Repo, _: Leitor):
    return repo.listar_aplicacoes()


@router.post("/aplicacoes", status_code=status.HTTP_201_CREATED)
def criar_aplicacao(body: AplicacaoCriar, repo: Repo, usuario: Admin):
    app_id, app_nome = _validar_app(body.qlik_app_id)
    try:
        aplicacao_id = repo.criar_aplicacao(
            {**body.model_dump(), "qlik_app_id": app_id, "qlik_app_nome": app_nome}, usuario["id"])
    except AgendamentoInvalido as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        if "aplicacoes_nome_key" in str(e):
            raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma aplicação com esse nome.")
        raise
    return repo.buscar_aplicacao(aplicacao_id)


@router.get("/aplicacoes/{aplicacao_id}")
def detalhar_aplicacao(aplicacao_id: int, repo: Repo, _: Leitor):
    aplicacao = repo.buscar_aplicacao(aplicacao_id)
    if not aplicacao:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aplicação não encontrada.")
    return aplicacao


@router.patch("/aplicacoes/{aplicacao_id}")
def alterar_aplicacao(aplicacao_id: int, body: AplicacaoAlterar, repo: Repo, usuario: Admin):
    campos = body.model_dump(exclude_unset=True)
    if "qlik_app_id" in campos:
        campos["qlik_app_id"], campos["qlik_app_nome"] = _validar_app(campos["qlik_app_id"])
    try:
        aplicacao = repo.alterar_aplicacao(aplicacao_id, campos, usuario["id"])
    except AgendamentoInvalido as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        if "aplicacoes_nome_key" in str(e):
            raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma aplicação com esse nome.")
        raise
    if not aplicacao:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aplicação não encontrada.")
    return aplicacao


@router.delete("/aplicacoes/{aplicacao_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_aplicacao(aplicacao_id: int, repo: Repo, usuario: Admin):
    try:
        if not repo.remover_aplicacao(aplicacao_id, usuario["id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Aplicação não encontrada.")
    except OperacaoNaoPermitida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.post("/aplicacoes/mover-carga")
def mover_carga(body: MoverCarga, repo: Repo, usuario: Admin):
    """Arrastar e soltar entre aplicações. Devolve a lista atualizada de aplicações."""
    if body.origem_id is None and body.destino_id is None:
        raise HTTPException(422, "Informe a origem ou o destino.")
    try:
        repo.mover_carga(body.carga_id, body.origem_id, body.destino_id, copiar=body.copiar,
                         posicao=body.posicao, usuario_id=usuario["id"])
    except Exception as e:
        if "foreign key" in str(e).lower():
            raise HTTPException(422, "Carga ou aplicação não encontrada.")
        raise
    return repo.listar_aplicacoes()


def _executar(aplicacao: dict | None, repo: Repositorio, usuario: dict):
    if not aplicacao:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aplicação não encontrada.")
    if not aplicacao["ativo"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aplicação inativa.")
    if not aplicacao["cargas"] and not aplicacao["qlik_app_id"]:
        raise HTTPException(422, "A aplicação não tem cargas nem app da Qlik para recarregar.")
    token_id = usuario.get("token_id")
    try:
        execucao_id = repo.enfileirar_aplicacao(aplicacao["id"], origem="token" if token_id else "manual",
                                                usuario_id=usuario["id"], token_id=token_id)
    except AplicacaoJaEmExecucao as e:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT,
                            content={"detail": "A aplicação já está executando.",
                                     "execucao_aplicacao_id": getattr(e, "execucao_id", None)})
    return {"execucao_aplicacao_id": execucao_id}


@router.post("/aplicacoes/{aplicacao_id}/executar", status_code=status.HTTP_202_ACCEPTED)
def executar_aplicacao(aplicacao_id: int, repo: Repo, usuario: Editor):
    """Dispara todas as cargas da aplicação e, se todas derem certo, recarrega o app na Qlik.
    Acompanhe por GET /execucoes-aplicacao/{execucao_aplicacao_id}."""
    return _executar(repo.buscar_aplicacao(aplicacao_id), repo, usuario)


@router.post("/aplicacoes/nome/{nome}/executar", status_code=status.HTTP_202_ACCEPTED)
def executar_aplicacao_por_nome(nome: str, repo: Repo, usuario: Editor):
    """Igual, pelo nome da aplicação (bom para DAGs do Airflow)."""
    return _executar(repo.buscar_aplicacao_por_nome(nome), repo, usuario)


@router.get("/aplicacoes/{aplicacao_id}/execucoes")
def historico_aplicacao(aplicacao_id: int, repo: Repo, _: Leitor, limite: int = 20):
    return [_com_terminou(x) for x in repo.historico_aplicacao(aplicacao_id, limite=min(limite, 100))]


@router.get("/execucoes-aplicacao/{execucao_aplicacao_id}")
def status_execucao_aplicacao(execucao_aplicacao_id: int, repo: Repo, _: Leitor):
    """Status da rodada e de cada carga. terminou=true em sucesso, erro ou cancelado (bom para sensores)."""
    x = repo.execucao_aplicacao(execucao_aplicacao_id)
    if not x:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
    return _com_terminou(x)


@router.post("/execucoes-aplicacao/{execucao_aplicacao_id}/cancelar")
def cancelar_execucao_aplicacao(execucao_aplicacao_id: int, repo: Repo, usuario: Editor):
    try:
        x = repo.pedir_cancelamento_aplicacao(execucao_aplicacao_id, usuario["id"])
    except OperacaoNaoPermitida as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if not x:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
    return _com_terminou(x)


@router.get("/qlik/apps")
def buscar_apps_qlik(_: Admin, busca: str | None = None):
    """Apps da Qlik que a API key enxerga (para vincular a uma aplicação)."""
    try:
        return _qlik().buscar_apps(busca, limite=30)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Não consegui consultar a Qlik agora: {e}")
