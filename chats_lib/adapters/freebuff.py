"""Adapter freebuff — `~/.config/manicode/projects/<proj>/chats/<ts>/`.

O scan lê só o `chat-meta.json` (leve: `firstPrompt` + contagem). O
`chat-messages.json` chega a 19 MB por conversa e NÃO pode entrar no scan.
`cwd` vem do `run-state.json`; quando não existe, cai no `recent-projects.json`
pelo nome da pasta do projeto.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import store
from ..models import Mensagem, Registro

CLI = "freebuff"
ROOT = Path.home() / ".config/manicode/projects"
RECENTES = Path.home() / ".config/manicode/recent-projects.json"
FONTES = [ROOT, RECENTES]

PAPEIS = {"user": "user", "ai": "assistant"}


def _json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _epoch_iso(texto: str) -> int | None:
    try:
        return int(datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _recentes() -> dict[str, str]:
    """nome da pasta do projeto → caminho absoluto."""
    dados = _json(RECENTES) or []
    saida: dict[str, str] = {}
    for item in dados:
        if isinstance(item, dict) and item.get("path"):
            caminho = Path(item["path"])
            saida[caminho.name] = str(caminho)
    return saida


def resolver(sid: str) -> Registro | None:
    projeto, _, pasta = sid.partition("/")
    if not projeto or not pasta:
        return None
    alvo = ROOT / projeto / "chats" / pasta
    if (alvo / "chat-meta.json").exists() or alvo.is_dir():
        if alvo.is_dir():
            return Registro(id=sid, cli=CLI, title="", source_path=str(alvo),
                            native_resume=["freebuff", "--continue", pasta])
    return None


def fingerprint() -> str:
    """Conversas + `recent-projects.json` (é dele que vem o cwd de quem não tem run-state)."""
    return store.fingerprint_arquivos(ROOT, RECENTES)


def scan() -> list[Registro]:
    recentes = _recentes()
    registros: list[Registro] = []
    for pasta in ROOT.glob("*/chats/*"):
        if not pasta.is_dir():
            continue
        meta = _json(pasta / "chat-meta.json") or {}
        run = _json(pasta / "run-state.json") or {}

        cwd = (
            (run.get("sessionState", {}).get("fileContext", {}) or {}).get("cwd")
            or recentes.get(pasta.parent.parent.name)
        )

        primeira = " ".join(str(meta.get("firstPrompt") or "").split())
        mensagens = pasta / "chat-messages.json"
        quando = meta.get("messagesMtimeMs")
        if not quando and mensagens.exists():
            quando = mensagens.stat().st_mtime * 1000
        if not quando:
            quando = pasta.stat().st_mtime * 1000

        registros.append(
            Registro(
                # id = <projeto>/<pasta>: só a pasta colidiria entre projetos
                id=f"{pasta.parent.parent.name}/{pasta.name}",
                cli=CLI,
                title=primeira[:80] or pasta.name,
                cwd=cwd,
                created_at=_epoch_iso(pasta.name),
                updated_at=int(quando),
                preview=primeira[:200],
                n_msgs=meta.get("messageCount"),
                native_resume=["freebuff", "--continue", pasta.name],
                source_path=str(pasta),
                meta={"projeto": pasta.parent.parent.name},
            )
        )
    registros.sort(key=lambda r: r.updated_at or 0, reverse=True)
    return registros


def carregar(reg: Registro) -> list[Mensagem]:
    pasta = Path(reg.source_path)
    mensagens = _json(pasta / "chat-messages.json")
    if not isinstance(mensagens, list):
        return []

    saida: list[Mensagem] = []
    for msg in mensagens:
        if not isinstance(msg, dict):
            continue
        papel = PAPEIS.get(msg.get("variant"))
        if papel is None:
            continue  # dividers, avisos de modo, etc.

        # fala da pessoa vem em `content`; a do agente vem em `blocks[].content`
        texto = msg.get("content")
        if not isinstance(texto, str) or not texto.strip():
            partes = []
            blocos = msg.get("blocks")
            if isinstance(blocos, list):
                for bloco in blocos:
                    if not isinstance(bloco, dict) or bloco.get("type") != "text":
                        continue
                    if bloco.get("textType") == "reasoning":
                        continue  # raciocínio interno polui a leitura
                    t = bloco.get("content") or bloco.get("text")
                    if isinstance(t, str) and t.strip():
                        partes.append(t.strip())
            texto = "\n".join(partes)
        if not texto.strip():
            continue
        saida.append(Mensagem(role=papel, text=texto.strip()))
    return saida
