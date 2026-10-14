"""Adapter gemini — `~/.gemini/tmp/<hash>/chats/session-*.json`.

O diretório do projeto vem do arquivo irmão `.project_root`. O CLI do gemini
está inativo nesta máquina (`IneligibleTierError` — migrou pro Antigravity),
então a conversa só pode ser lida/exportada, não retomada.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import store
from ..models import Mensagem, Registro

CLI = "gemini"
ROOT = Path.home() / ".gemini/tmp"
FONTES = [ROOT]

AVISO = "CLI do gemini inativo (IneligibleTierError — use o agy/Antigravity)"

# no arquivo do gemini o papel vem em `type`, e o assistente é `gemini`
PAPEIS = {"user": "user", "gemini": "assistant", "model": "assistant",
          "assistant": "assistant"}


def _json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _epoch(texto: object) -> int | None:
    if not isinstance(texto, str):
        return None
    try:
        return int(datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def resolver(sid: str) -> Registro | None:
    for caminho in ROOT.glob("*/chats/*.json"):
        dados = _json(caminho)
        if isinstance(dados, dict) and dados.get("sessionId") == sid:
            return Registro(id=sid, cli=CLI, title="", source_path=str(caminho))
    return None


def fingerprint() -> str:
    """Sessões + `.project_root` (é de lá que sai o cwd)."""
    return store.fingerprint_arquivos(ROOT)


def scan() -> list[Registro]:
    registros: list[Registro] = []
    for caminho in ROOT.glob("*/chats/*.json"):
        dados = _json(caminho)
        if not isinstance(dados, dict):
            continue
        raiz = caminho.parent.parent / ".project_root"
        try:
            cwd = raiz.read_text().strip() or None
        except OSError:
            cwd = None
        sid = dados.get("sessionId") or caminho.stem
        resumo = " ".join(str(dados.get("summary") or "").split())
        mensagens = dados.get("messages") or []
        registros.append(
            Registro(
                id=sid,
                cli=CLI,
                title=resumo[:80] or sid,
                cwd=cwd,
                created_at=_epoch(dados.get("startTime")),
                updated_at=_epoch(dados.get("lastUpdated")),
                preview=resumo[:200],
                n_msgs=len(mensagens) if isinstance(mensagens, list) else None,
                native_resume=[],  # CLI inativo — ver AVISO
                source_path=str(caminho),
                meta={"aviso": AVISO},
            )
        )
    registros.sort(key=lambda r: r.updated_at or 0, reverse=True)
    return registros


def carregar(reg: Registro) -> list[Mensagem]:
    dados = _json(Path(reg.source_path))
    if not isinstance(dados, dict):
        return []

    saida: list[Mensagem] = []
    for msg in dados.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        papel = PAPEIS.get(msg.get("role") or msg.get("type") or "")
        if papel is None:
            continue  # erros, checkpoints e afins
        texto = msg.get("content")
        if isinstance(texto, list):
            texto = "\n".join(
                str(b.get("text", ""))
                for b in texto
                if isinstance(b, dict) and b.get("text")
            )
        if not isinstance(texto, str):
            texto = ""
        if not texto.strip():
            partes = msg.get("parts")
            if isinstance(partes, list):
                texto = "\n".join(
                    str(p.get("text", ""))
                    for p in partes
                    if isinstance(p, dict) and p.get("text")
                )
        if not texto.strip():
            continue
        saida.append(Mensagem(role=papel, text=texto.strip(),
                              time=_epoch(msg.get("timestamp"))))
    return saida
