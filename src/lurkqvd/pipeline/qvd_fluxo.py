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

Memória: a tabela valor -> posição do Python custa ~150 bytes por valor, então ela tem um orçamento
para a tabela toda (DISTINTOS_PYTHON, somando as colunas). Passado o orçamento, a coluna com mais
valores sai do Python e entra no modo bruto: cada valor vai para o disco junto com o número da linha
(a "chave"), espalhado por hash em PARTICOES arquivos (Arrow IPC, comprimido). Valores iguais caem
sempre no mesmo arquivo, então no fim cada grupo de arquivos (até ALVO_GRUPO bytes; um arquivo maior
é espalhado de novo, com outra semente) é resolvido sozinho na memória:
  - primeira aparição de cada valor = menor chave entre as linhas com aquele valor;
  - "marca" (arquivo mapeado, uma posição por linha) guarda em que grupo está o valor que aparece
    pela primeira vez naquela linha; percorrida em ordem, dá a ordem dos símbolos, e a contagem
    acumulada dá o número do símbolo de cada primeira aparição;
  - o índice de cada linha (chave da primeira aparição do seu valor) vai para outro arquivo mapeado.
Os símbolos saem em janelas, juntando os grupos na ordem da marca. Nada disso depende do número de
valores distintos: a memória fica em ~um grupo, mesmo com centenas de milhões de valores. Os valores
já vistos no Python entram nos arquivos com chaves negativas (antes de todas as linhas), e por isso
mantêm as posições que já foram gravadas no índice.

Ponto flutuante e data/hora vão para o disco como o inteiro que o Arrow guarda: valores iguais se e
só se os bits são iguais, como o qvdrs compara (0.0 e -0.0 separados); onde o qvdrs juntar valores,
a tradução acerta.
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
# total de valores distintos guardados no Python, somando todas as colunas (~150 bytes cada); passado
# isso, a coluna com mais valores vai para o modo bruto (disco)
DISTINTOS_PYTHON = int(os.getenv("LURKQVD_DISTINTOS_PYTHON", "500000"))
# coluna com menos distintos que isso fica no Python mesmo com o orçamento estourado (no disco,
# poucos valores repetidos custariam mais que a tabela)
MINIMO_BRUTO = 10_000
# arquivos por coluna no modo bruto (valores espalhados por hash)
PARTICOES = 16
# bytes de valores resolvidos de uma vez no fim (memória do modo bruto ~ 4x isso)
ALVO_GRUPO = 32 * 1024 * 1024
# posições da marca por janela ao montar os símbolos em ordem
JANELA = 262_144
# símbolos de uma coluna acima disso vão para um arquivo temporário até a montagem (não ficam na memória)
SIMBOLOS_EM_DISCO = 64 * 1024 * 1024
_FIM_CABECALHO = b"</QvdTableHeader>"


@dataclass
class _Coluna:
    nome: str
    tipo: pa.DataType | None = None
    posicoes: dict = field(default_factory=dict)   # valor -> posição (id do símbolo)
    valores: list = field(default_factory=list)    # símbolos na ordem da primeira aparição
    tem_nulo: bool = False
    pedacos: list = field(default_factory=list)    # (offset, bytes, bytes_originais, dtype, linhas)
    # modo bruto (muitos distintos): valores e chaves espalhados em arquivos por hash
    bruto: _Particoes | None = None
    anteriores: int = 0                            # símbolos vistos no Python antes do modo bruto
    linhas_bruto: int = 0                          # linhas recebidas no modo bruto


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
        self._fim_indices = 0  # onde o próximo pedaço começa (evita um seek por pedaço)
        self._brutos: list[_Coluna] = []  # colunas no modo bruto (valores em disco)
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

        tabela = lote.to_arrow()  # uma conversão para o lote todo, não uma por coluna
        for col, arr in zip(self._colunas, tabela.columns):
            arr = arr.chunk(0) if arr.num_chunks == 1 else arr.combine_chunks()
            # texto do Polars chega como large_string (ou string_view): em vez de converter a coluna
            # toda para string a cada lote, converte só os valores distintos (em _gravar_posicoes)
            texto_largo = pa.types.is_large_string(arr.type) or pa.types.is_string_view(arr.type)
            tipo_arr = pa.string() if texto_largo else arr.type
            if col.tipo is None or pa.types.is_null(col.tipo):
                if not pa.types.is_null(tipo_arr):
                    col.tipo = tipo_arr
            elif pa.types.is_null(tipo_arr):
                arr, texto_largo = pa.nulls(len(arr), col.tipo), False
            elif tipo_arr != col.tipo:
                arr, texto_largo = arr.cast(col.tipo), False
            if col.bruto is not None:
                self._guardar_bruto(col, arr)
            else:
                self._gravar_posicoes(col, arr, texto_largo)
                # a cada coluna, não só no fim do lote: no 1º lote, todas as colunas com muitos
                # distintos encheriam o Python juntas antes de alguma sair
                self._conter_python()

        self.linhas += lote.height
        self._lotes.append(lote.height)

    def _conter_python(self) -> None:
        """Mantém os distintos guardados no Python (todas as colunas) dentro de DISTINTOS_PYTHON,
        passando para o modo bruto a coluna com mais valores até caber."""
        no_python = [c for c in self._colunas if c.bruto is None]
        total = sum(len(c.valores) for c in no_python)
        candidatas = [c for c in no_python if len(c.valores) >= MINIMO_BRUTO and _aceita_bruto(c.tipo)]
        while total > DISTINTOS_PYTHON and candidatas:
            maior = max(candidatas, key=lambda c: len(c.valores))
            candidatas.remove(maior)
            total -= len(maior.valores)
            self._passar_para_bruto(maior)

    def _gravar_posicoes(self, col: _Coluna, arr: pa.Array, texto_largo: bool = False) -> None:
        if pa.types.is_null(arr.type) or arr.null_count == len(arr):
            pos1 = np.zeros(len(arr), dtype=np.uint8)  # lote todo nulo nesta coluna
            col.tem_nulo = True
        else:
            cod = pc.dictionary_encode(arr)
            dicionario = cod.dictionary
            if texto_largo:
                dicionario = dicionario.cast(pa.string())
            # posição global de cada valor distinto deste lote. Só os distintos do lote passam pelo
            # Python, e em operações de lote (map/zip do próprio CPython), sem laço valor a valor
            mapa = _posicoes_globais(col, _como_lista(dicionario))
            # posição + 1 (0 = nulo: o número de símbolos final ainda não é conhecido), já no menor
            # tipo que cabe; todo valor do dicionário aparece em alguma linha, então o maior daqui
            # é o maior do lote
            mapa1 = mapa + 1
            maior = int(mapa1.max(initial=0))
            mapa1 = mapa1.astype(np.uint8 if maior < 2**8 else np.uint16 if maior < 2**16 else np.uint32)
            ind = cod.indices
            if ind.null_count == 0:
                pos1 = mapa1[ind.to_numpy()]  # sem nulos: leitura direta, sem cópia
            else:
                col.tem_nulo = True
                pos1 = mapa1[ind.fill_null(0).to_numpy()]
                pos1[ind.is_null().to_numpy(zero_copy_only=False)] = 0
        self._gravar_pedaco(col, pos1)

    def _passar_para_bruto(self, col: _Coluna) -> None:
        """A coluna deixa a tabela do Python: o que já foi visto entra nos arquivos com chaves negativas
        (na ordem, antes de qualquer linha) e os próximos lotes vão direto para o disco."""
        anteriores = _para_arrow(col.valores, col.tipo)
        col.valores, col.posicoes = [], {}
        col.anteriores = len(anteriores)
        col.bruto = _Particoes(self._tmp / f"bruto_{len(self._brutos)}", PARTICOES, semente=0)
        col.bruto.escrever(np.arange(-col.anteriores, 0, dtype=np.int64), _fisico(anteriores))
        self._brutos.append(col)

    def _guardar_bruto(self, col: _Coluna, arr: pa.Array) -> None:
        if arr.null_count:
            col.tem_nulo = True
        chaves = np.arange(col.linhas_bruto, col.linhas_bruto + len(arr), dtype=np.int64)
        col.linhas_bruto += len(arr)
        col.bruto.escrever(chaves, _fisico(arr))

    def _resolver_bruto(self, col: _Coluna, i: int) -> dict:
        """Resolve a coluna do modo bruto (ver o docstring do módulo): grava as posições dos lotes do
        modo bruto (pedacos) e devolve os símbolos e o cabeçalho da coluna."""
        pasta = col.bruto.pasta
        partes = col.bruto.fechar()
        col.bruto = None
        n0, linhas = col.anteriores, col.linhas_bruto
        tam = n0 + linhas
        # índice: chave da 1ª aparição + n0 + 1 de cada linha do modo bruto (0 = nulo)
        indice = np.lib.format.open_memmap(pasta / "indice.npy", mode="w+", dtype=np.int64, shape=(max(linhas, 1),))
        # marca: grupo + 1 na chave (+ n0) em que um valor aparece pela 1ª vez; 0 nas outras
        marca = np.lib.format.open_memmap(pasta / "marca.npy", mode="w+", dtype=np.uint32, shape=(max(tam, 1),))
        grupos: list[Path] = []
        for tabela in _grupos(partes, semente=1):
            df = pl.from_arrow(tabela).with_columns(pl.col("k").min().over("v").alias("f"))
            del tabela
            reais = df.filter(pl.col("k") >= 0)
            indice[reais.get_column("k").to_numpy()] = reais.get_column("f").to_numpy() + (n0 + 1)
            del reais
            primeiros = df.filter(pl.col("k") == pl.col("f")).select("f", "v").sort("f")
            del df
            marca[primeiros.get_column("f").to_numpy() + n0] = len(grupos) + 1
            caminho = pasta / f"distintos_{len(grupos)}.arrow"
            v = primeiros.get_column("v").to_arrow()
            with pa.OSFile(str(caminho), "wb") as f, pa.ipc.new_file(f, pa.schema([("v", v.type)])) as w:
                w.write_table(pa.table({"v": v}))  # sem compressão: lido de volta mapeado, sem cópia
            grupos.append(caminho)
            del primeiros, v

        # número do símbolo de cada 1ª aparição: contagem acumulada da marca (reaproveita o arquivo)
        simbolo = np.lib.format.open_memmap(pasta / "simbolo.npy", mode="w+", dtype=np.uint32, shape=(max(tam, 1),))
        n = 0
        for ini in range(0, tam, JANELA * 16):
            acumulado = np.cumsum(marca[ini:ini + JANELA * 16] > 0, dtype=np.int64)
            simbolo[ini:ini + len(acumulado)] = acumulado + (n - 1)
            n += int(acumulado[-1])

        lotes = self._lotes[len(col.pedacos):]
        ini = 0
        for qtd in lotes:
            v = indice[ini:ini + qtd]
            pos1 = simbolo[np.maximum(v, 1) - 1].astype(np.int64) + 1
            pos1[v == 0] = 0
            maior = int(pos1.max(initial=0))
            self._gravar_pedaco(col, pos1.astype(np.uint8 if maior < 2**8 else np.uint16 if maior < 2**16 else np.uint32))
            ini += qtd
        v = None  # a última fatia ainda aponta para o arquivo mapeado (no Windows, impediria apagar)
        del indice, simbolo, v

        janelas = _em_ordem(marca, grupos)
        try:
            if pa.types.is_string(col.tipo) and n > LIMITE_TEXTO_DIRETO:
                return self._simbolos_texto_direto(col, i, janelas, n)
            col.valores = _do_fisico(pa.concat_arrays(list(janelas)) if n else pa.array([], _fisico_tipo(col.tipo)), col.tipo)
            return self._simbolos_pelo_qvdrs(col, i)
        finally:
            janelas.close()
            del marca
            shutil.rmtree(pasta, ignore_errors=True)

    def _gravar_pedaco(self, col: _Coluna, pos1: np.ndarray) -> None:
        bruto = pos1.tobytes()
        comprimido = pa.compress(bruto, codec=CODEC, asbytes=True)
        self._indices.write(comprimido)
        col.pedacos.append((self._fim_indices, len(comprimido), len(bruto), pos1.dtype.str, len(pos1)))
        self._fim_indices += len(comprimido)

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
        self._indices.seek(0, os.SEEK_END)

        # símbolos e cabeçalho de cada coluna, escritos pelo qvdrs a partir dos valores distintos
        meta = [self._resolver_bruto(c, i) if c.bruto is not None else self._simbolos_pelo_qvdrs(c, i)
                for i, c in enumerate(cols)]
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
        if isinstance(col.valores, pa.Array):  # veio do modo bruto
            arr = col.valores
            if col.tem_nulo or len(arr) == 0:
                arr = pa.concat_arrays([arr, pa.nulls(1, arr.type)])
        else:
            arr = _para_arrow(col.valores, tipo)
            if col.tem_nulo or len(arr) == 0:
                arr = pa.concat_arrays([arr, pa.nulls(1, arr.type)])
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
        simbolos, arquivo = dados[base + ini: base + ini + tam], None
        if tam > SIMBOLOS_EM_DISCO:  # muitos símbolos: esperam a montagem no disco, não na memória
            arquivo = self._tmp / f"simbolos_{i}.bin"
            arquivo.write_bytes(simbolos)
            simbolos = None
        del dados
        return {
            "bloco": bloco,
            "simbolos": simbolos,
            "arquivo": arquivo,
            "tamanho": tam,
            "largura": largura,
            "n": n,
            "traducao": traducao,
        }

    def _simbolos_texto_direto(self, col: _Coluna, i: int, janelas=None, n: int | None = None) -> dict:
        """Texto com muitos valores: símbolo = 0x04 + UTF-8 + 0x00, gravado em disco aos poucos.
        O bloco do cabeçalho vem do qvdrs com uma amostra (mesmo tipo e tags) e recebe os números reais.
        janelas: arrays de texto com os n símbolos em ordem (modo bruto); sem elas, os do Python."""
        if janelas is None:
            n = len(col.valores)
            janelas = (pa.array(col.valores[k:k + 200_000], type=pa.large_string()) for k in range(0, n, 200_000))
        arquivo = self._tmp / f"simbolos_{i}.bin"
        tamanho, amostra = 0, None
        with open(arquivo, "wb") as f:
            for arr in janelas:
                if amostra is None:
                    amostra = arr.slice(0, 3).to_pylist()
                parte = _texto_qvd(arr)
                f.write(parte)
                tamanho += len(parte)
        col.valores = []
        amostra = _Coluna(col.nome, tipo=pa.string(), valores=amostra, tem_nulo=col.tem_nulo)
        bloco = self._simbolos_pelo_qvdrs(amostra, i, permitir_direto=False)["bloco"]
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
        for col in self._brutos:
            if col.bruto is not None:
                try:
                    col.bruto.fechar()
                except Exception:
                    pass
                col.bruto = None
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


def _aceita_bruto(tipo: pa.DataType | None) -> bool:
    """Tipos que o Arrow codifica (o que ele e o Python discordam, o qvdrs decide pela tradução)."""
    if tipo is None:
        return False
    return (pa.types.is_integer(tipo) or pa.types.is_floating(tipo) or pa.types.is_string(tipo)
            or pa.types.is_decimal(tipo)
            or pa.types.is_timestamp(tipo) or pa.types.is_date(tipo) or pa.types.is_time(tipo)
            or pa.types.is_duration(tipo))



_INTEIRO_DO_FLUTUANTE = {16: np.int16, 32: np.int32, 64: np.int64}


def _para_arrow(valores: list, tipo: pa.DataType) -> pa.Array:
    """Símbolos guardados por _como_lista de volta num array do tipo da coluna."""
    if pa.types.is_floating(tipo):
        bits = np.array(valores, dtype=_INTEIRO_DO_FLUTUANTE[tipo.bit_width])
        return pa.array(bits.view(tipo.to_pandas_dtype()), type=tipo)
    return pa.array(valores, type=tipo)


def _como_lista(arr: pa.Array) -> list:
    """Valores (sem nulos) como lista Python, pelo caminho mais rápido para o tipo.

    Números saem pelo numpy (bem mais rápido que to_pylist). Data/hora sai como o inteiro
    guardado pelo Arrow (micro/mili/segundos, dias): dois valores são iguais se e só se os inteiros
    são iguais, e pa.array(inteiros, type=tipo) refaz a coluna igualzinha na montagem dos símbolos.
    Ponto flutuante sai como os bits (inteiro de mesma largura): o qvdrs separa 0.0 de -0.0, e o
    Python, comparando os números, juntaria os dois. _para_arrow desfaz na montagem.
    """
    t = arr.type
    if pa.types.is_integer(t):
        return arr.to_numpy(zero_copy_only=False).tolist()
    if pa.types.is_floating(t):
        return arr.to_numpy(zero_copy_only=False).view(_INTEIRO_DO_FLUTUANTE[t.bit_width]).tolist()
    if pa.types.is_timestamp(t) or pa.types.is_date(t) or pa.types.is_time(t) or pa.types.is_duration(t):
        return arr.view(pa.int64() if t.bit_width == 64 else pa.int32()).to_numpy(zero_copy_only=False).tolist()
    return arr.to_pylist()


def _posicoes_globais(col: _Coluna, vals: list) -> np.ndarray:
    """Posição (id do símbolo) de cada valor de vals; os ainda não vistos entram no fim, na ordem.

    Igual ao laço "get ou acrescenta" valor a valor, só que em lote. vals vem sem repetição (é o
    dicionário do lote no Arrow, em inteiros, bits ou texto: o que o Arrow separa, o Python também).
    """
    posicoes, valores = col.posicoes, col.valores
    inicio = len(valores)
    if not posicoes:
        achadas = [None] * len(vals)
    else:
        achadas = list(map(posicoes.get, vals))
    if None not in achadas:
        return np.fromiter(achadas, dtype=np.int64, count=len(achadas))
    if achadas.count(None) == len(achadas):
        novos = vals
    else:
        novos = [v for v, p in zip(vals, achadas) if p is None]
    posicoes.update(zip(novos, range(inicio, inicio + len(novos))))
    valores.extend(novos)
    if novos is vals:
        return np.arange(inicio, inicio + len(vals), dtype=np.int64)  # tudo novo: na ordem
    return np.fromiter(map(posicoes.__getitem__, vals), dtype=np.int64, count=len(vals))


class _Particoes:
    """Valores de uma coluna (sem os nulos) com a chave de cada um, espalhados por hash em n arquivos
    Arrow: valores iguais sempre no mesmo arquivo."""

    def __init__(self, pasta: Path, n: int, semente: int) -> None:
        pasta.mkdir()
        self.pasta, self.n, self.semente = pasta, n, semente
        self.bytes = [0] * n
        self._arquivos: list = [None] * n  # (arquivo, writer), abertos no primeiro valor de cada um

    def escrever(self, chaves: np.ndarray, valores: pa.Array) -> None:
        if valores.null_count:
            validos = valores.is_valid()
            chaves = chaves[validos.to_numpy(zero_copy_only=False)]
            valores = valores.filter(validos)
        if not len(valores):
            return
        parte = (pl.from_arrow(valores).hash(self.semente) % self.n).to_numpy()
        parte = parte.astype(np.uint8 if self.n <= 256 else np.uint32)  # ordenação estável de uint8: radix, ~4x mais rápida
        ordem = np.argsort(parte, kind="stable")
        lote = pa.record_batch([pa.array(chaves[ordem]), valores.take(ordem)], names=["k", "v"])
        ini = 0
        for p, qtd in enumerate(np.bincount(parte, minlength=self.n)):
            if qtd:
                pedaco = lote.slice(ini, qtd)
                if self._arquivos[p] is None:
                    arquivo = pa.OSFile(str(self.pasta / f"p{p}.arrow"), "wb")
                    self._arquivos[p] = (arquivo, pa.ipc.new_stream(
                        arquivo, lote.schema, options=pa.ipc.IpcWriteOptions(compression="lz4")))
                self._arquivos[p][1].write_batch(pedaco)
                self.bytes[p] += pedaco.nbytes
                ini += int(qtd)

    def fechar(self) -> list[tuple[Path, int]]:
        """Fecha os arquivos; devolve (caminho, bytes dos valores) dos que receberam algo."""
        partes = []
        for p, aberto in enumerate(self._arquivos):
            if aberto is not None:
                aberto[1].close()
                aberto[0].close()
                partes.append((self.pasta / f"p{p}.arrow", self.bytes[p]))
        self._arquivos = [None] * self.n
        return partes


def _grupos(partes: list[tuple[Path, int]], semente: int):
    """Tabelas (k, v) com até ALVO_GRUPO bytes: arquivos vizinhos juntos, e um arquivo maior que isso
    espalhado de novo, com outra semente (valores iguais continuam juntos). Apaga cada arquivo lido."""
    juntos, soma = [], 0
    for caminho, tam in partes + [(None, 0)]:
        if juntos and (caminho is None or soma + tam > ALVO_GRUPO):
            yield pa.concat_tables([_ler_parte(c) for c in juntos])
            juntos, soma = [], 0
        if caminho is None:
            break
        if tam > ALVO_GRUPO and semente < 5:  # semente: limita a recursão (um valor só muito repetido)
            sub = _Particoes(caminho.parent / f"s{semente}_{caminho.stem}", 2 + tam // ALVO_GRUPO, semente)
            with pa.memory_map(str(caminho)) as fonte:
                for rb in pa.ipc.open_stream(fonte):
                    sub.escrever(rb.column(0).to_numpy(), rb.column(1))
            caminho.unlink()
            yield from _grupos(sub.fechar(), semente + 1)
            continue
        juntos.append(caminho)
        soma += tam


def _ler_parte(caminho: Path) -> pa.Table:
    with pa.memory_map(str(caminho)) as fonte:
        tabela = pa.ipc.open_stream(fonte).read_all()  # comprimido: a leitura já copia para a memória
    caminho.unlink()
    return tabela


def _em_ordem(marca: np.ndarray, grupos: list[Path]):
    """Os valores distintos na ordem da 1ª aparição, em janelas: a marca diz de que grupo vem cada um,
    e cada grupo já está na ordem (por chave)."""
    fontes = [pa.memory_map(str(c)) for c in grupos]
    try:
        colunas = [pa.ipc.open_file(f).read_all().column("v") for f in fontes]
        cursores = [0] * len(grupos)
        for ini in range(0, len(marca), JANELA):
            m = marca[ini:ini + JANELA]
            seq = m[m > 0].astype(np.int64) - 1
            if not len(seq):
                continue
            pedacos = []
            for g, qtd in enumerate(np.bincount(seq, minlength=len(grupos))):
                if qtd:
                    pedacos.extend(colunas[g].slice(cursores[g], qtd).chunks)
                    cursores[g] += int(qtd)
            juntos = pa.concat_arrays(pedacos)
            # juntos está agrupado por grupo; a janela quer a ordem da marca
            ordem = np.argsort(seq, kind="stable")
            inversa = np.empty_like(ordem)
            inversa[ordem] = np.arange(len(ordem))
            yield juntos.take(inversa)
    finally:
        colunas = None
        for f in fontes:
            f.close()


def _fisico_tipo(tipo: pa.DataType) -> pa.DataType:
    """Tipo em que a coluna vai para o disco no modo bruto: ponto flutuante e data/hora como o inteiro
    guardado (iguais se e só se os bits são iguais), texto como large_string."""
    if pa.types.is_floating(tipo) or pa.types.is_temporal(tipo):
        return {16: pa.int16(), 32: pa.int32(), 64: pa.int64()}[tipo.bit_width]
    if pa.types.is_string(tipo) or pa.types.is_large_string(tipo) or pa.types.is_string_view(tipo):
        return pa.large_string()
    return tipo


def _fisico(arr: pa.Array) -> pa.Array:
    tipo = _fisico_tipo(arr.type)
    if tipo == arr.type:
        return arr
    return arr.cast(tipo) if tipo == pa.large_string() else arr.view(tipo)


def _do_fisico(arr: pa.Array, tipo: pa.DataType) -> pa.Array:
    if arr.type == tipo:
        return arr
    return arr.cast(tipo) if pa.types.is_string(tipo) else arr.view(tipo)


def _texto_qvd(arr: pa.Array) -> bytes:
    """Símbolos de texto do QVD (0x04 + UTF-8 + 0x00) de um array sem nulos, sem laço em Python."""
    if not pa.types.is_large_string(arr.type):
        arr = arr.cast(pa.large_string())
    n = len(arr)
    _, buf_offsets, buf_dados = arr.buffers()
    offsets = np.frombuffer(buf_offsets, dtype=np.int64)[arr.offset:arr.offset + n + 1]
    ini, fim = int(offsets[0]), int(offsets[-1])
    saida = np.empty(fim - ini + 2 * n, dtype=np.uint8)
    comeco = offsets[:-1] - ini + 2 * np.arange(n, dtype=np.int64)  # onde fica o 0x04 de cada um
    final = offsets[1:] - ini + 2 * np.arange(1, n + 1, dtype=np.int64) - 1  # e o 0x00
    saida[comeco] = 4
    saida[final] = 0
    dados = np.ones(len(saida), dtype=bool)
    dados[comeco] = False
    dados[final] = False
    if fim > ini:
        saida[dados] = np.frombuffer(buf_dados, dtype=np.uint8)[ini:fim]
    return saida.tobytes()


def _trocar(xml: str, **valores) -> str:
    """Troca o conteúdo da PRIMEIRA ocorrência de cada tag (no nível em que aparece primeiro)."""
    for tag, v in valores.items():
        xml = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}>{v}</{tag}>", xml, count=1, flags=re.S)
    return xml