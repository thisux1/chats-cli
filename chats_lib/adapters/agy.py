"""Adapter agy (Antigravity) — `~/.gemini/antigravity-cli/conversation_summaries.db`.

Uma linha por conversa; `workspace_uris` traz o diretório como `file:///...`.
O conteúdo passo a passo fica em `conversations/<uuid>.db`, mas em protobuf —
a leitura completa não está implementada (a prévia cai no `preview` da linha).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .. import store
from ..models import Mensagem, Registro

CLI = "agy"
DB = Path.home() / ".gemini/antigravity-cli/conversation_summaries.db"
FONTES = [DB, Path.home() / ".gemini/antigravity-cli/cache/conversation_metadata.json"]


def _con() -> sqlite3.Connection:
    if not DB.exists():
        raise FileNotFoundError(f"banco não encontrado: {DB}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _epoch(valor: object) -> int | None:
    """`2026-09-11 02:33:28.026513155+00:00` → epoch ms (nanos descartados)."""
    if not valor or not isinstance(valor, str):
        return None
    texto = valor.strip()
    if len(texto) < 26:
        return None
    try:
        dt = datetime.fromisoformat(texto[:19] + texto[-6:])
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _cwd(uris: str | None) -> str | None:
    if not uris:
        return None
    try:
        lista = json.loads(uris)
    except Exception:
        return None
    if not isinstance(lista, list) or not lista:
        return None
    primeiro = lista[0]
    if not isinstance(primeiro, str):
        return None
    return primeiro[7:] if primeiro.startswith("file://") else primeiro


def resolver(sid: str) -> Registro | None:
    if not DB.exists():
        return None
    return Registro(id=sid, cli=CLI, title="", source_path=str(DB),
                    native_resume=["agy", "--conversation", sid])


def fingerprint() -> str:
    """Contagem de conversas + última entrada de usuário (ISO ordena lexicograficamente)."""
    con = _con()
    try:
        return store.fingerprint_consulta(
            con,
            "SELECT COUNT(*), MAX(last_user_input_time) FROM conversation_summaries",
        )
    finally:
        con.close()


def scan() -> list[Registro]:
    con = _con()
    try:
        linhas = con.execute(
            "SELECT conversation_id, title, preview, workspace_uris,"
            " last_modified_time, last_user_input_time, step_count, agent_name"
            " FROM conversation_summaries"
        ).fetchall()
    finally:
        con.close()

    registros: list[Registro] = []
    for cid, titulo, preview, uris, modificado, ultimo, passos, agente in linhas:
        primeira = " ".join((preview or "").split())
        registros.append(
            Registro(
                id=cid,
                cli=CLI,
                title=(titulo or "").strip() or primeira[:80] or cid[:8],
                cwd=_cwd(uris),
                created_at=_epoch(modificado),
                updated_at=_epoch(ultimo) or _epoch(modificado),
                preview=primeira[:200],
                n_msgs=passos,
                native_resume=["agy", "--conversation", cid],
                source_path=str(DB),
                meta={k: v for k, v in (("agent", agente),) if v},
            )
        )
    registros.sort(key=lambda r: r.updated_at or 0, reverse=True)
    return registros


def carregar(reg: Registro) -> list[Mensagem]:
    """Protobuf sem schema — devolve vazio e a CLI mostra o `preview` da linha."""
    return []
