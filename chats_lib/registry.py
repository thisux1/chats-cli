"""Registro de adapters: quem participa, quem falhou, dedupe entre CLIs.

Uma fonte com erro NUNCA derruba a CLI — o adapter é marcado e o resto segue.
O mesmo vale pro índice: se ele falhar, o scan lê a fonte direto.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

from . import store
from .adapters import agy, codex, devin, freebuff, gemini, opencode
from .models import Registro

ADAPTERS = [opencode, codex, agy, devin, freebuff, gemini]

# mínimo de caracteres normalizados na abertura da conversa: abaixo disso
# ("oi", "analisa aqui") o pareamento por 1ª frase geraria falso positivo
FRASE_MINIMA = 30


def modulos() -> dict[str, object]:
    return {ad.CLI: ad for ad in ADAPTERS}


def _indice_ativo() -> bool:
    return not os.environ.get("CHATS_SEM_INDICE")


def scan(
    clis: set[str] | None = None, forcar: bool = False
) -> tuple[list[Registro], list[tuple[str, str]]]:
    """Retorna (registros, erros). `erros` = [(cli, mensagem), ...].

    Cada fonte é relida só quando a `fingerprint` dela mudou; o resto vem
    do índice local. `forcar=True` ignora o índice na leitura (mesmo que
    continue reescrevendo).
    """
    registros: list[Registro] = []
    erros: list[tuple[str, str]] = []
    ativo = _indice_ativo()

    for ad in ADAPTERS:
        if clis and ad.CLI not in clis:
            continue

        fp = None
        if ativo:
            try:
                fp = ad.fingerprint()
            except Exception:  # sem fingerprint não há como validar o cache
                fp = None
            if fp is not None and not forcar:
                try:
                    if fp == store.fingerprint(ad.CLI):
                        guardado = store.ler(ad.CLI)
                        if guardado is not None:
                            registros.extend(guardado)
                            continue
                except Exception:  # índice ilegível → fonte direta
                    pass

        try:
            regs = ad.scan()
        except Exception as exc:  # isolamento por adapter
            erros.append((ad.CLI, f"{type(exc).__name__}: {exc}"))
            continue
        registros.extend(regs)

        if ativo and fp is not None:
            try:
                store.salvar(ad.CLI, fp, regs)
            except Exception:  # aceleração, não contrato
                pass

    _marca_importadas(registros)
    _marca_duplicadas(registros)
    return registros, erros


def buscar(key: str) -> Registro | None:
    registros, _ = scan()
    for reg in registros:
        if reg.key == key:
            return reg
    return None


def carregar(reg: Registro) -> list:
    ad = modulos().get(reg.cli)
    if ad is None:
        raise KeyError(f"adapter desconhecido: {reg.cli}")
    return ad.carregar(reg)


def carregar_id(cli: str, sid: str) -> list:
    """Carrega pelo id só — usado por `preview`/`export`/`ler`, sem escanear tudo."""
    ad = modulos().get(cli)
    if ad is None or not hasattr(ad, "resolver"):
        return []
    stub = ad.resolver(sid)
    if stub is None:
        return []
    return ad.carregar(stub)


def _marca_importadas(registros: list[Registro]) -> None:
    """Devin já importado pro OpenCode.

    O importador gerou `ses_devin<hash>`, não `ses_devin<slug>`, então a
    identidade é (título, diretório) — cai pra título puro se o diretório
    divergir. Serve também pra abrir a sessão já existente em vez de importar.
    """
    opencode_regs = [r for r in registros if r.cli == "opencode"]
    if not opencode_regs:
        return

    por_titulo_dir = {(r.title.strip().lower(), r.cwd): r.id for r in opencode_regs}
    por_titulo = {r.title.strip().lower(): r.id for r in opencode_regs}

    for reg in registros:
        if reg.cli != "devin" or reg.imported_in_opencode:
            continue
        titulo = (reg.title or "").strip().lower()
        if not titulo:
            continue
        achado = por_titulo_dir.get((titulo, reg.cwd)) or por_titulo.get(titulo)
        if achado:
            reg.imported_in_opencode = achado


def primeira_frase(texto: str | None) -> str:
    """Abertura da conversa normalizada (minúsculas, sem pontuação).

    Corta só em fim de frase de verdade (`.`, `!`, `?` seguidos de
    espaço) — senão `revisa o ADR.md` viraria chave `revisa o adr`.
    Volta ``""`` quando não passa de `FRASE_MINIMA` caracteres: a chave
    do dedupe precisa ser específica o bastante pra não marcar duas
    conversas diferentes como a mesma.
    """
    if not texto:
        return ""
    bruto = " ".join(texto.split())
    fim = re.search(r"[.!?](?=\s|$)", bruto)
    frase = bruto[: fim.end()] if fim else bruto
    limpa = re.sub(r"[^0-9a-zÀ-ÿ]+", " ", frase.lower()).strip()
    return limpa if len(limpa) >= FRASE_MINIMA else ""


def _chave_duplicata(reg: Registro) -> tuple[str, str, str] | None:
    """(diretório, 1ª frase, dia de início) — None quando não dá pra comparar."""
    if not reg.cwd or not reg.created_at:
        return None
    frase = primeira_frase(reg.preview)
    if not frase:
        return None
    dia = datetime.fromtimestamp(reg.created_at / 1000).date().isoformat()
    return (reg.cwd, frase, dia)


def _marca_duplicadas(registros: list[Registro]) -> int:
    """Marca a mesma conversa guardada em 2+ CLIs distintos.

    Marcador, nunca colapso: se a heurística errar, o pior caso é uma
    `≡` indevida — a conversa continua listada e abrível.
    """
    grupos: dict[tuple[str, str, str], list[Registro]] = {}
    for reg in registros:
        chave = _chave_duplicata(reg)
        if chave:
            grupos.setdefault(chave, []).append(reg)

    marcadas = 0
    for grupo in grupos.values():
        if len(grupo) < 2 or len({r.cli for r in grupo}) < 2:
            continue  # precisa cruzar CLIs — dentro do mesmo CLI é repetição, não duplicata
        for reg in grupo:
            reg.duplicada = True
            marcadas += 1
    return marcadas


def contar_duplicadas(registros: Iterable[Registro]) -> int:
    return sum(1 for r in registros if r.duplicada)
