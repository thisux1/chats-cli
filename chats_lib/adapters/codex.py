"""Adapter Codex — `~/.codex/sessions/**/*.jsonl` + índices auxiliares.

Não tem listagem nativa, então lemos só a PRIMEIRA linha de cada rollout
(`session_meta` traz `cwd`, `id` e `timestamp`). Ler o arquivo inteiro no scan
seria ~200 arquivos de dezenas de milhares de linhas — fazemos só sob demanda.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from .. import store
from ..models import Mensagem, Registro

CLI = "codex"
ROOT = Path.home() / ".codex"
FONTES = [ROOT / "sessions", ROOT / "session_index.jsonl", ROOT / "history.jsonl"]

# pré-texto que o codex injeta marcando como "user" — não é fala da pessoa
CTX_INJETADA = ("<environment_context>", "The following is the Codex agent history")


def resolver(sid: str) -> Registro | None:
    """O id está no nome do rollout (`rollout-<ts>-<uuid>.jsonl`)."""
    for caminho in ROOT.glob("sessions/**/*.jsonl"):
        if sid in caminho.name:
            return Registro(
                id=sid,
                cli=CLI,
                title="",
                source_path=str(caminho),
                native_resume=["codex", "resume", sid],
            )
    return None


def _epoca(valor: object) -> int | None:
    if not valor:
        return None
    if isinstance(valor, (int, float)):
        v = float(valor)
        return int(v * 1000) if v < 1e12 else int(v)
    if isinstance(valor, str):
        try:
            return int(datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _jsonl(caminho: Path):
    """Itera um JSONL ignorando linhas ilegíveis (arquivos podem estar cortados)."""
    try:
        with caminho.open(encoding="utf-8", errors="replace") as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    yield json.loads(linha)
                except Exception:
                    continue
    except OSError:
        return


def _titulos() -> dict[str, str]:
    """`session_index.jsonl` → id → thread_name (último vencedor)."""
    out: dict[str, str] = {}
    for d in _jsonl(ROOT / "session_index.jsonl"):
        if isinstance(d, dict) and d.get("id") and d.get("thread_name"):
            out[d["id"]] = d["thread_name"]
    return out


def _primeiros_prompts() -> dict[str, str]:
    """`history.jsonl` → session_id → 1º prompt (o arquivo é append-only)."""
    out: dict[str, str] = {}
    for d in _jsonl(ROOT / "history.jsonl"):
        if not isinstance(d, dict):
            continue
        sid = d.get("session_id")
        texto = d.get("text")
        if sid and isinstance(texto, str) and sid not in out:
            out[sid] = texto
    return out


def _meta(caminho: Path) -> dict | None:
    """Lê apenas a primeira linha do rollout."""
    try:
        with caminho.open(encoding="utf-8", errors="replace") as fh:
            primeira = fh.readline()
    except OSError:
        return None
    if not primeira:
        return None
    try:
        dado = json.loads(primeira)
    except Exception:
        return None
    if dado.get("type") != "session_meta":
        return None
    payload = dado.get("payload")
    return payload if isinstance(payload, dict) else None


def fingerprint() -> str:
    """Rollouts + os dois índices: contagem de arquivos e mtime máximo."""
    return store.fingerprint_arquivos(*FONTES)


def scan() -> list[Registro]:
    titulos = _titulos()
    prompts = _primeiros_prompts()
    registros: list[Registro] = []

    for caminho in sorted(ROOT.glob("sessions/**/*.jsonl")):
        meta = _meta(caminho)
        if not meta:
            continue
        sid = meta.get("id") or meta.get("session_id")
        if not sid:
            continue
        quando = _epoca(meta.get("timestamp")) or int(caminho.stat().st_mtime * 1000)
        nome = (titulos.get(sid) or "").strip()
        primeira = " ".join((prompts.get(sid) or "").split())
        title = nome or primeira[:80] or sid[:8]
        registros.append(
            Registro(
                id=sid,
                cli=CLI,
                title=title,
                cwd=meta.get("cwd") or None,
                created_at=quando,
                updated_at=quando,
                preview=primeira[:200],
                native_resume=["codex", "resume", sid],
                source_path=str(caminho),
                meta={
                    k: v
                    for k, v in (
                        ("cli_version", meta.get("cli_version")),
                        ("source", meta.get("source")),
                    )
                    if v
                },
            )
        )
    registros.sort(key=lambda r: r.updated_at or 0, reverse=True)
    return registros


def carregar(reg: Registro) -> list[Mensagem]:
    """Mensagens de fala: `response_item` do tipo `message` (user/assistant)."""
    caminho = Path(reg.source_path)
    if not caminho.exists():
        return []

    mensagens: list[Mensagem] = []
    for d in _jsonl(caminho):
        if d.get("type") != "response_item":
            continue
        payload = d.get("payload") or {}
        if payload.get("type") != "message":
            continue
        papel = payload.get("role")
        if papel not in ("user", "assistant"):
            continue  # ignora `developer` (instruções de sistema)
        blocos = payload.get("content") or []
        texto = "\n".join(
            b.get("text", "")
            for b in blocos
            if isinstance(b, dict) and isinstance(b.get("text"), str)
        ).strip()
        if not texto:
            continue
        # contexto injetado vem marcado como "user", mas é system de verdade
        if papel == "user" and texto.startswith(CTX_INJETADA):
            papel = "system"
        mensagens.append(
            Mensagem(role=papel, text=texto, time=_epoca(d.get("timestamp")))
        )
    return mensagens


def agora_ms() -> int:
    return int(time.time() * 1000)
