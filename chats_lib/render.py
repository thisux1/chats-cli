"""Formatação: linha do fzf, tabela simples, JSON, agrupamento por pasta."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .models import Registro

HOME = str(Path.home())

# paleta fixa por CLI — usada com --ansi no fzf
CORES = {
    "opencode": "36",   # ciano
    "codex": "32",      # verde
    "agy": "35",        # magenta
    "devin": "33",      # âmbar
    "freebuff": "91",   # rosa
    "gemini": "34",     # azul
}
RESET = "\033[0m"


def cor_ativa(desligada: bool) -> bool:
    return (not desligada) and sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def pintar(texto: str, codigo: str, ligado: bool) -> str:
    if not ligado or not codigo:
        return texto
    return f"\033[{codigo}m{texto}{RESET}"


def hora(ms: int | None) -> str:
    if not ms:
        return "  --"
    d = datetime.fromtimestamp(ms / 1000)
    if d.date() == datetime.now().date():
        return d.strftime("%H:%M")
    return d.strftime("%d/%m")


def pasta(cwd: str | None) -> str:
    if not cwd:
        return "?"
    if cwd == HOME:
        return "~"
    if cwd.startswith(HOME + os.sep):
        return "~" + cwd[len(HOME):]
    return cwd


def cortar(texto: str, limite: int) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def linha(reg: Registro, ligado: bool = True, largo: bool = False) -> str:
    """Uma linha TSV pro fzf: hora · cli · título · pasta · (key escondida)."""
    cli = pintar(f"{reg.cli:<9}", CORES.get(reg.cli, ""), ligado)
    titulo = cortar(reg.title, 78 if largo else 58)
    caminho = pintar(pasta(reg.cwd), "2", ligado)
    selo = " ⇄" if reg.imported_in_opencode and reg.cli != "opencode" else ""
    if reg.duplicada:
        selo += " ≡"
    return "\t".join([hora(reg.updated_at), cli, titulo + selo, caminho, reg.key])


def ordenar(registros: list[Registro]) -> list[Registro]:
    return sorted(registros, key=lambda r: r.updated_at or 0, reverse=True)


def agrupar(registros: list[Registro]) -> list[tuple[str, list[Registro]]]:
    """Agrupa por pasta; pastas ordenadas pela conversa mais recente."""
    grupos: dict[str, list[Registro]] = {}
    for reg in registros:
        grupos.setdefault(pasta(reg.cwd), []).append(reg)
    itens = []
    for nome, regs in grupos.items():
        regs.sort(key=lambda r: r.updated_at or 0, reverse=True)
        itens.append((nome, regs))
    itens.sort(key=lambda item: item[1][0].updated_at or 0, reverse=True)
    return itens


def tabela(registros: list[Registro], ligado: bool, agrupado: bool, largo: bool) -> str:
    saida: list[str] = []
    blocos = agrupar(registros) if agrupado else [("", registros)]
    for nome, regs in blocos:
        if agrupado:
            cab = f"── {nome} ({len(regs)}) "
            saida.append(pintar(cab + "─" * max(4, 60 - len(cab)), "1;2", ligado))
        for reg in regs:
            selo = " ⇄" if reg.imported_in_opencode and reg.cli != "opencode" else ""
            if reg.duplicada:
                selo += " ≡"
            selo = pintar(selo, "33", ligado)
            meta = []
            if reg.n_msgs:
                meta.append(f"{reg.n_msgs} msgs")
            if reg.meta.get("agent"):
                meta.append(str(reg.meta["agent"]))
            extra = pintar(" · " + " · ".join(meta), "2", ligado) if meta else ""
            saida.append(
                "\t".join(
                    [
                        pintar(hora(reg.updated_at), "2", ligado),
                        pintar(f"{reg.cli:<9}", CORES.get(reg.cli, ""), ligado),
                        cortar(reg.title, 78 if largo else 58) + selo + extra,
                        pintar(pasta(reg.cwd), "2", ligado),
                    ]
                )
            )
    return "\n".join(saida)


def como_json(registros: list[Registro]) -> str:
    return json.dumps([r.as_dict() for r in registros], ensure_ascii=False, indent=2)


def como_tsv(registros: list[Registro]) -> str:
    linhas = ["\t".join(["key", "cli", "updated_at", "cwd", "n_msgs", "title"])]
    for reg in registros:
        linhas.append(
            "\t".join(
                [
                    reg.key,
                    reg.cli,
                    str(reg.updated_at or ""),
                    reg.cwd or "",
                    str(reg.n_msgs if reg.n_msgs is not None else ""),
                    " ".join(reg.title.split()),
                ]
            )
        )
    return "\n".join(linhas)
