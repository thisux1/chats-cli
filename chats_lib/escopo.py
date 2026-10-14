"""Regra de escopo: decide quais conversas pertencem ao diretório atual.

- home (`~`)  → tudo o que estiver sob `$HOME`, agrupado por pasta
- projeto git → só a raiz do repositório e os descendentes
- pasta comum → só o `cwd` exato
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterable

from .models import Registro

HOME = Path.home()

TODOS = "all"  # --all: ignora escopo
CASA = "home"
PROJETO = "project"
ARVORE = "tree"  # --tree: raiz + descendentes mesmo fora de casa


def resolver_raiz(pwd: Path) -> Path:
    """Raiz do escopo: raiz do git quando houver, senão o próprio diretório."""
    pwd = pwd.resolve()
    try:
        out = subprocess.run(
            ["git", "-C", str(pwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except Exception:
        pass
    return pwd


def modo(raiz: Path, forcar: str | None = None) -> str:
    if forcar:
        return forcar
    if raiz == HOME or raiz == Path("/"):
        return CASA
    return PROJETO


def seletor(raiz: Path, escopo: str) -> Callable[[Registro], bool]:
    if escopo == TODOS:
        return lambda r: True

    base = str(HOME) + "/" if escopo == CASA else str(raiz) + "/"
    alvo = str(HOME) if escopo == CASA else str(raiz)
    return lambda r: bool(r.cwd) and (r.cwd == alvo or r.cwd.startswith(base))


def aplicar(
    registros: Iterable[Registro],
    raiz: Path,
    escopo: str,
    exato: bool = False,
) -> list[Registro]:
    sel = seletor(raiz, escopo)
    fora = [r for r in registros if sel(r)]
    if exato:
        fora = [r for r in fora if r.cwd == str(raiz)]
    return fora


def descrever(raiz: Path, escopo: str) -> str:
    if escopo == TODOS:
        return "todas as conversas de todas as pastas (--all)"
    if escopo == CASA:
        return f"tudo sob {HOME} (agrupado por pasta)"
    if escopo == ARVORE:
        return f"{raiz} e subpastas"
    return f"só {raiz} (cwd exato + descendentes)"
