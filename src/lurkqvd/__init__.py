"""LurkQVD.

O .env da raiz do projeto é carregado aqui, antes de qualquer módulo: vários deles leem variáveis
de ambiente ao serem importados. Variáveis já definidas no ambiente têm precedência.
"""

from dotenv import load_dotenv

# versão do LurkQVD: a tag do release (vX.Y.Z) tem de ser igual a esta
__version__ = "0.1.0"

load_dotenv()
