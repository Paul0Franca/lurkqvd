"""Versão do LurkQVD: uma só, no código, no front e no CHANGELOG (o release confere a tag contra elas)."""

import json
import re
from pathlib import Path

from src.lurkqvd import __version__

RAIZ = Path(__file__).resolve().parent.parent


def test_versao_e_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_front_e_changelog_na_mesma_versao():
    front = json.loads((RAIZ / "front" / "package.json").read_text(encoding="utf-8"))
    assert front["version"] == __version__
    changelog = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(__version__)}\]", changelog, re.M)


def test_health_informa_a_versao(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "versao": __version__}
