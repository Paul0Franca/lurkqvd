"""Rotas dos avisos dentro da ferramenta (sino do topo + balão ao entrar) e de Configurações › Avisos.

Só pessoas logadas leem avisos (token de API não tem "quem leu"); só admin publica e remove.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from src.lurkqvd.api.auth import exigir_papel, exigir_pessoa, get_repo
from src.lurkqvd.repository.repositorio import Repositorio

router = APIRouter()

Repo = Annotated[Repositorio, Depends(get_repo)]
Admin = Annotated[dict, Depends(exigir_papel("admin"))]
Pessoa = Annotated[dict, Depends(exigir_pessoa)]


class Aviso(BaseModel):
    id: int
    titulo: str
    texto: str
    link_url: str | None
    link_rotulo: str | None
    publico: Literal["leitor", "editor", "admin"]
    abrir_ao_entrar: bool
    origem: Literal["admin", "sistema"]
    publicado_em: datetime
    expira_em: datetime | None


class AvisoDaPessoa(Aviso):
    lido: bool


class MeusAvisos(BaseModel):
    avisos: list[AvisoDaPessoa]
    nao_lidos: int


class AvisoAdmin(Aviso):
    criado_por_nome: str | None
    expirado: bool
    leituras: int
    publico_total: int


class MarcarLidos(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=200)  # vazio = todos


class NovoAviso(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)
    texto: str = Field(min_length=1, max_length=2000)
    # só http(s): o link vira <a href> na tela de todo mundo
    link_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://[^\s]+$")
    link_rotulo: str | None = Field(default=None, max_length=60)
    publico: Literal["leitor", "editor", "admin"] = "leitor"
    abrir_ao_entrar: bool = True
    expira_em: datetime | None = None

    @field_validator("titulo", "texto", "link_rotulo", "link_url", mode="before")
    @classmethod
    def _aparar(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


@router.get("/avisos", response_model=MeusAvisos)
def meus_avisos(repo: Repo, pessoa: Pessoa):
    avisos = repo.avisos_do_usuario(pessoa["id"], pessoa["papel"])
    return {"avisos": avisos, "nao_lidos": sum(not a["lido"] for a in avisos)}


@router.post("/avisos/lidos", status_code=status.HTTP_204_NO_CONTENT)
def marcar_lidos(body: MarcarLidos, repo: Repo, pessoa: Pessoa):
    repo.marcar_avisos_lidos(pessoa["id"], pessoa["papel"], body.ids)


@router.get("/config/avisos", response_model=list[AvisoAdmin])
def listar_avisos(repo: Repo, _: Admin):
    return repo.listar_avisos_admin()


@router.post("/config/avisos", response_model=Aviso, status_code=status.HTTP_201_CREATED)
def publicar_aviso(body: NovoAviso, repo: Repo, usuario: Admin):
    if usuario.get("id") is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rota disponível só para pessoas logadas.")
    if body.expira_em and body.expira_em <= datetime.now(body.expira_em.tzinfo):
        raise HTTPException(422, "A data de expiração já passou.")
    if body.link_rotulo and not body.link_url:
        raise HTTPException(422, "Informe o endereço do link.")
    return repo.publicar_aviso(usuario["id"], **body.model_dump())


@router.delete("/config/avisos/{aviso_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_aviso(aviso_id: int, repo: Repo, usuario: Admin):
    if not repo.remover_aviso(usuario["id"], aviso_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aviso não encontrado.")
