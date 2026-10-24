"""Gerador de QVD em fluxo: grava enquanto lê, com memória do tamanho dos valores distintos.

O formato QVD tem duas partes: a lista de valores distintos de cada coluna (símbolos) e, para
cada linha, a posição de cada valor nessas listas (índice), empacotada em bits. O índice só pode
ser escrito depois de conhecidos todos os símbolos, porque o número de bits de cada coluna depende
de quantos símbolos ela tem. Então:

  1. adicionar(lote), a cada lote lido: guarda os valores novos de cada coluna (memória) e grava
     a posição de cada valor de cada linha num arquivo temporário (disco, comprimido);
  2. finalizar(): escreve o QVD — cabeçalho, símbolos e o índice, montado lote a lote a partir
     do arquivo temporário. Nunca há a tabela inteira na memória.

Para o arquivo sair idêntico ao do qvdrs (a biblioteca que o resto do LurkQVD usa), os símbolos
e o cabeçalho de cada coluna são escritos pelo próprio qvdrs, a partir só dos valores distintos
da coluna; aqui fica o empacotamento do índice e a montagem do arquivo. Regras do qvdrs seguidas:
  - símbolos na ordem da primeira aparição; nulo não é símbolo;
  - nulo no índice = número de símbolos da coluna (posição logo depois do último);
    exceção corrigida: com um valor só + nulos, o qvdrs grava 0 bits e perde os nulos; aqui
    vai 1 bit e os nulos são preservados;
  - colunas ordenadas por largura em bits, da maior para a menor, para definir a posição dos
    bits na linha; colunas de largura 0 (um valor só) ficam na posição 0;
  - bits da linha em little-endian.

O qvdrs também junta valores que considera iguais (ex.: data/hora que só diferem nos milissegundos
viram um símbolo só, com o texto até o segundo). Para seguir qualquer regra dele sem adivinhar, o
QVD por coluna que ele escreve (um valor distinto por linha) é lido de volta: o índice desse arquivo
diz qual símbolo do qvdrs corresponde a cada valor distinto daqui — é a "tradução" usada ao montar
o índice final.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import qvd

CODEC = "zstd"
# colunas de texto com mais valores distintos que isso têm os símbolos escritos aqui, direto
# para o disco (o qvdrs montaria um array com todos eles na memória de uma vez)
LIMITE_TEXTO_DIRETO = 50_000
_FIM_CABECALHO = b"</QvdTableHeader>"


@dataclass
class _Coluna:
    nome: str
    tipo: pa.DataType | None = None
    posicoes: dict = field(default_factory=dict)   # valor -> posição (id do símbolo)
    valores: list = field(default_factory=list)    # símbolos na ordem da primeira aparição
    tem_nulo: bool = False
    pedacos: list = field(default_factory=list)    # (offset, bytes, bytes_originais, dtype, linhas)


class EscritorQvdFluxo:
    """Uso:
        with EscritorQvdFluxo("saida.qvd", "vendas") as esc:
            for lote in lotes:            # DataFrames do Polars, mesmas colunas
                esc.adicionar(lote)
            info = esc.finalizar()
    """

    def __init__(self, destino: str | Path, tabela: str, dir_temp: str | Path | None = None) -> None:
        self.destino = Path(destino)
        self.tabela = tabela
        self._tmp = Path(tempfile.mkdtemp(prefix="lurkqvd_fluxo_", dir=dir_temp))
        self._indices = open(self._tmp / "indices.bin", "w+b")
        self._colunas: list[_Coluna] | None = None
        self.linhas = 0
        self._lotes: list[int] = []  # linhas de cada lote (o índice é remontado na mesma divisão)

    # ------------------------------------------------------------------ #
    # 1. Durante a leitura
    # ------------------------------------------------------------------ #
    def adicionar(self, lote: pl.DataFrame) -> None:
        if lote.height == 0:
            return
        if self._colunas is None:
            self._colunas = [_Coluna(n) for n in lote.columns]
        elif lote.columns != [c.nome for c in self._colunas]:
            raise ValueError(f"lote com colunas diferentes: {lote.columns}")

        for col in self._colunas:
            arr = lote.get_column(col.nome).to_arrow()
            if isinstance(arr, pa.ChunkedArray):
                arr = arr.combine_chunks()
            if pa.types.is_large_string(arr.type):
                arr = arr.cast(pa.string())
            if col.tipo is None or pa.types.is_null(col.tipo):
                if not pa.types.is_null(arr.type):
                    col.tipo = arr.type
            elif pa.types.is_null(arr.type):
                arr = pa.nulls(len(arr), col.tipo)
            elif arr.type != col.tipo:
                arr = arr.cast(col.tipo)
            self._gravar_posicoes(col, arr)

        self.linhas += lote.height
        self._lotes.append(lote.height)

    def _gravar_posicoes(self, col: _Coluna, arr: pa.Array) -> None:
        if pa.types.is_null(arr.type) or arr.null_count == len(arr):
            pos1 = np.zeros(len(arr), dtype=np.uint8)  # lote todo nulo nesta coluna
            col.tem_nulo = True
        else:
            cod = pc.dictionary_encode(arr)
            # posição global de cada valor distinto deste lote (só os distintos do lote passam pelo Python)
            mapa = np.empty(len(cod.dictionary), dtype=np.int64)
            posicoes, valores = col.posicoes, col.valores
            for j, v in enumerate(cod.dictionary.to_pylist()):
                p = posicoes.get(v)
                if p is None:
                    p = posicoes[v] = len(valores)
                    valores.append(v)
                mapa[j] = p
            ind = cod.indices
            nulos = ind.null_count
            # grava posição + 1; 0 = nulo (o número de símbolos final ainda não é conhecido)
            pos1 = mapa[ind.fill_null(0).to_numpy(zero_copy_only=False)] + 1
            if nulos:
                col.tem_nulo = True
                pos1[ind.is_null().to_numpy(zero_copy_only=False)] = 0
            maior = int(pos1.max(initial=0))
            dtype = np.uint8 if maior < 2**8 else np.uint16 if maior < 2**16 else np.uint32
            pos1 = pos1.astype(dtype)
        bruto = pos1.tobytes()
        comprimido = pa.compress(bruto, codec=CODEC, asbytes=True)
        inicio = self._indices.seek(0, os.SEEK_END)
        self._indices.write(comprimido)
        col.pedacos.append((inicio, len(comprimido), len(bruto), pos1.dtype.str, len(pos1)))

    # ------------------------------------------------------------------ #
    # 2. Montagem do arquivo
    # ------------------------------------------------------------------ #
    def finalizar(self, ao_progredir=None) -> dict:
        """Escreve o QVD. ao_progredir(feito, total): chamado ao longo da montagem do índice
        (se levantar exceção, ex.: cancelamento, a montagem para e o arquivo parcial é apagado)."""
        if not self._colunas or self.linhas == 0:
            raise ValueError("nenhuma linha recebida; QVD não gerado")
        cols = self._colunas
        for c in cols:
            c.posicoes = {}  # a tabela valor -> posição só serve durante a leitura: libera já

        # símbolos e cabeçalho de cada coluna, escritos pelo qvdrs a partir dos valores distintos
        meta = [self._simbolos_pelo_qvdrs(c, i) for i, c in enumerate(cols)]
        larguras = [m["largura"] for m in meta]

        # posição dos bits: maior largura primeiro (estável); largura 0 fica na posição 0
        bit = 0
        posicao_bit = [0] * len(cols)
        for i in sorted(range(len(cols)), key=lambda i: -larguras[i]):
            if larguras[i] > 0:
                posicao_bit[i] = bit
                bit += larguras[i]
        bytes_linha = (bit + 7) // 8 if bit else 0

        # cabeçalho: o da tabela vem de um QVD de 1 linha do qvdrs; os campos, dos QVDs por coluna
        blocos, offset = [], 0
        for i, m in enumerate(meta):
            blocos.append(_trocar(m["bloco"], BitOffset=posicao_bit[i], Offset=offset))
            offset += m["tamanho"]
        cabecalho = self._cabecalho_tabela(
            blocos, bytes_linha=bytes_linha, linhas=self.linhas,
            offset_indice=offset, tamanho_indice=bytes_linha * self.linhas,
        )

        parcial = self.destino.with_name(self.destino.name + ".parcial")
        try:
            with open(parcial, "wb") as out:
                out.write(cabecalho)
                out.write(b"\r\n\x00")
                for m in meta:
                    if m["arquivo"]:
                        with open(m["arquivo"], "rb") as f:
                            shutil.copyfileobj(f, out, 8 * 1024 * 1024)
                    else:
                        out.write(m["simbolos"])
                if bytes_linha:
                    self._escrever_indice(out, cols, meta, posicao_bit, bytes_linha, ao_progredir)
            os.replace(parcial, self.destino)
        finally:
            Path(parcial).unlink(missing_ok=True)

        return {
            "linhas": self.linhas,
            "colunas": len(cols),
            "bytes": self.destino.stat().st_size,
            "distintos": {c.nome: m["n"] for c, m in zip(cols, meta)},
            "tem_nulo": {c.nome: c.tem_nulo for c in cols},
            "bytes_simbolos": {c.nome: m["tamanho"] for c, m in zip(cols, meta)},
            "larguras": {c.nome: l for c, l in zip(cols, larguras)},
            "tipos": {c.nome: str(c.tipo or pa.string()) for c in cols},
            "bytes_linha": bytes_linha,
        }

    def _simbolos_pelo_qvdrs(self, col: _Coluna, i: int, *, permitir_direto: bool = True) -> dict:
        tipo = col.tipo or pa.string()
        if permitir_direto and pa.types.is_string(tipo) and len(col.valores) > LIMITE_TEXTO_DIRETO:
            return self._simbolos_texto_direto(col, i)
        valores = col.valores + ([None] if col.tem_nulo else [])
        if not valores:
            valores = [None]
        arr = pa.array(valores, type=tipo)
        caminho = self._tmp / f"coluna_{i}.qvd"
        qvd.write_arrow(pa.table({col.nome: arr}), str(caminho), table_name=self.tabela)
        dados = caminho.read_bytes()
        caminho.unlink()
        fim = dados.index(_FIM_CABECALHO) + len(_FIM_CABECALHO)
        cab = dados[:fim].decode("utf-8")
        base = fim + 3  # \r\n\0
        bloco = re.search(r"<QvdFieldHeader>.*?</QvdFieldHeader>", cab, re.S).group(0)
        n = int(_valor(bloco, "NoOfSymbols"))
        if int(_valor(bloco, "Bias")) != 0:  # o qvdrs grava Bias 0; outro valor mudaria a codificação
            raise ValueError(f"coluna {col.nome}: Bias {_valor(bloco, 'Bias')} inesperado do qvdrs")
        ini, tam = int(_valor(bloco, "Offset")), int(_valor(bloco, "Length"))
        traducao = None
        if n != len(col.valores):
            # o qvdrs juntou valores (ex.: milissegundos): a linha k do arquivo por coluna é o valor
            # distinto k daqui, e o índice dela diz em qual símbolo do qvdrs ele caiu
            tabela = cab.split("</Fields>", 1)[1]
            bytes_linha_col = int(_valor(tabela, "RecordByteSize"))
            ini_ind = base + int(_valor(tabela, "Offset"))
            largura_col = int(_valor(bloco, "BitWidth"))
            k = len(col.valores)
            if largura_col == 0:
                traducao = np.zeros(k, dtype=np.int64)
            else:
                brutos = np.frombuffer(dados[ini_ind: ini_ind + bytes_linha_col * k], dtype=np.uint8)
                brutos = brutos.reshape(k, bytes_linha_col).astype(np.uint64)
                linha = np.zeros(k, dtype=np.uint64)
                for j in range(bytes_linha_col):
                    linha |= brutos[:, j] << np.uint64(8 * j)
                desloc = np.uint64(int(_valor(bloco, "BitOffset")))
                traducao = ((linha >> desloc) & np.uint64((1 << largura_col) - 1)).astype(np.int64)
            if k and int(traducao.max()) >= n:
                raise ValueError(f"coluna {col.nome}: tradução inválida para os símbolos do qvdrs")
        largura = int(_valor(bloco, "BitWidth"))
        if n == 1 and col.tem_nulo and largura == 0:
            # bug do qvdrs: um valor só + nulos sai com 0 bits e os nulos viram o valor. Aqui não:
            # 1 bit, nulo na posição 1 (a mesma convenção que ele usa nas outras colunas)
            largura = 1
            bloco = _trocar(bloco, BitWidth=1)
        col.valores = []  # já viraram símbolos: libera
        return {
            "bloco": bloco,
            "simbolos": dados[base + ini: base + ini + tam],
            "arquivo": None,
            "tamanho": tam,
            "largura": largura,
            "n": n,
            "traducao": traducao,
        }

    def _simbolos_texto_direto(self, col: _Coluna, i: int) -> dict:
        """Texto com muitos valores: símbolo = 0x04 + UTF-8 + 0x00, gravado em disco aos poucos.
        O bloco do cabeçalho vem do qvdrs com uma amostra (mesmo tipo e tags) e recebe os números reais."""
        n = len(col.valores)
        amostra = _Coluna(col.nome, tipo=pa.string(), valores=col.valores[:3], tem_nulo=col.tem_nulo)
        bloco = self._simbolos_pelo_qvdrs(amostra, i, permitir_direto=False)["bloco"]
        arquivo = self._tmp / f"simbolos_{i}.bin"
        tamanho = 0
        with open(arquivo, "wb") as f:
            for k in range(0, n, 200_000):
                parte = b"".join(b"\x04" + v.encode("utf-8") + b"\x00" for v in col.valores[k:k + 200_000])
                f.write(parte)
                tamanho += len(parte)
        col.valores = []
        largura = _largura(n, col.tem_nulo)
        return {
            "bloco": _trocar(bloco, BitWidth=largura, NoOfSymbols=n, Length=tamanho),
            "simbolos": None,
            "arquivo": arquivo,
            "tamanho": tamanho,
            "largura": largura,
            "n": n,
            "traducao": None,  # texto: o qvdrs só junta textos idênticos, que já são um valor só aqui
        }

    def _cabecalho_tabela(self, campos: list[str], *, bytes_linha: int, linhas: int,
                          offset_indice: int, tamanho_indice: int) -> bytes:
        # QVD mínimo do qvdrs (1 coluna, 1 linha) só para pegar o cabeçalho da tabela no formato dele
        caminho = self._tmp / "tabela.qvd"
        qvd.write_arrow(pa.table({"x": pa.array([1])}), str(caminho), table_name=self.tabela)
        dados = caminho.read_bytes()
        caminho.unlink()
        cab = dados[: dados.index(_FIM_CABECALHO) + len(_FIM_CABECALHO)].decode("utf-8")
        # mesmo espaçamento do qvdrs entre os blocos de campo
        m = re.search(r"<Fields>(\s*)<QvdFieldHeader>.*</QvdFieldHeader>(\s*)</Fields>", cab, re.S)
        recuo, fim = m.group(1), m.group(2)
        cab = cab[: m.start()] + "<Fields>" + "".join(recuo + b for b in campos) + fim + "</Fields>" + cab[m.end():]
        antes, depois = cab.split("</Fields>", 1)
        depois = _trocar(depois, RecordByteSize=bytes_linha, NoOfRecords=linhas,
                         Offset=offset_indice, Length=tamanho_indice)
        return (antes + "</Fields>" + depois).encode("utf-8")

    def _escrever_indice(self, out, cols, meta, posicao_bit, bytes_linha, ao_progredir=None) -> None:
        ativos = [(i, c) for i, c in enumerate(cols) if meta[i]["largura"] > 0]
        total = len(self._lotes)
        for k, n in enumerate(self._lotes):
            if ao_progredir and k % 10 == 0:
                ao_progredir(k, total)
            linha = np.zeros((n, bytes_linha), dtype=np.uint8)
            for i, c in ativos:
                ini, tam, tam_bruto, dtype, qtd = c.pedacos[k]
                self._indices.seek(ini)
                bruto = pa.decompress(self._indices.read(tam), decompressed_size=tam_bruto, codec=CODEC, asbytes=True)
                pos1 = np.frombuffer(bruto, dtype=np.dtype(dtype)).astype(np.uint64)
                trad = meta[i]["traducao"]
                if trad is None:
                    v = np.where(pos1 == 0, np.uint64(meta[i]["n"]), pos1 - np.uint64(1))
                else:
                    v = np.where(pos1 == 0, np.uint64(meta[i]["n"]),
                                 trad[np.maximum(pos1, 1).astype(np.int64) - 1].astype(np.uint64))
                desloc = posicao_bit[i] % 8
                byte0 = posicao_bit[i] // 8
                v <<= np.uint64(desloc)
                for b in range((desloc + meta[i]["largura"] + 7) // 8):
                    linha[:, byte0 + b] |= ((v >> np.uint64(8 * b)) & np.uint64(0xFF)).astype(np.uint8)
            out.write(linha.tobytes())

    # ------------------------------------------------------------------ #
    def descartar(self) -> None:
        try:
            self._indices.close()
        finally:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def __enter__(self) -> "EscritorQvdFluxo":
        return self

    def __exit__(self, *_exc) -> None:
        self.descartar()


def conferir_arquivo(caminho: str | Path, linhas_esperadas: int) -> None:
    """Confere a estrutura do QVD sem carregá-lo: nº de linhas do cabeçalho e o tamanho do arquivo
    (cabeçalho + símbolos + índice) batendo com o que o cabeçalho declara."""
    caminho = Path(caminho)
    with open(caminho, "rb") as f:
        inicio = f.read(1024 * 1024)
        while _FIM_CABECALHO not in inicio:
            mais = f.read(1024 * 1024)
            if not mais:
                raise ValueError("QVD inválido: cabeçalho não encontrado")
            inicio += mais
    fim = inicio.index(_FIM_CABECALHO) + len(_FIM_CABECALHO)
    cab = inicio[:fim].decode("utf-8")
    tabela = cab.split("</Fields>", 1)[1]
    linhas = int(_valor(tabela, "NoOfRecords"))
    esperado = fim + 3 + int(_valor(tabela, "Offset")) + int(_valor(tabela, "Length"))
    if linhas != linhas_esperadas:
        raise ValueError(f"QVD inválido: {linhas} linhas no cabeçalho, esperado {linhas_esperadas}")
    if caminho.stat().st_size != esperado:
        raise ValueError(f"QVD inválido: {caminho.stat().st_size} bytes, o cabeçalho indica {esperado}")


def _largura(n: int, tem_nulo: bool) -> int:
    """Bits por linha de uma coluna com n símbolos, como o qvdrs calcula: cabe a posição n (a do nulo);
    um valor só e sem nulo não ocupa bits."""
    if n <= 1 and not tem_nulo:
        return 0
    return int(n).bit_length()


def _valor(xml: str, tag: str) -> str:
    return re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S).group(1)


def _trocar(xml: str, **valores) -> str:
    """Troca o conteúdo da PRIMEIRA ocorrência de cada tag (no nível em que aparece primeiro)."""
    for tag, v in valores.items():
        xml = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}>{v}</{tag}>", xml, count=1, flags=re.S)
    return xml
