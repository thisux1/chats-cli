"""Adapter OpenCode — `~/.local/share/opencode/opencode.db`.

Somente leitura por construção: a URI sempre abre com `mode=ro`, então nenhum
código daqui consegue escrever no banco (lição da incidente de 2026-10-06).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .. import store
from ..models import Mensagem, Registro

CLI = "opencode"
DB = Path.home() / ".local/share/opencode/opencode.db"
FONTES = [DB]


def resolver(sid: str) -> Registro | None:
    """Stub mínimo pra `carregar` sem varrer todas as sessões."""
    if not DB.exists():
        return None
    return Registro(
        id=sid,
        cli=CLI,
        title="",
        source_path=str(DB),
        native_resume=["opencode", "-s", sid],
    )

# mensagens que interessam numa leitura/exportação
PAPEIS = ("user", "assistant", "system")


def _con() -> sqlite3.Connection:
    if not DB.exists():
        raise FileNotFoundError(f"banco não encontrado: {DB}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _texto(raw: object) -> str:
    """Extrai texto de um `data` JSON tolerando variações de formato."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        if not raw.lstrip().startswith("{"):
            return raw
        try:
            raw = json.loads(raw)
        except Exception:
            return raw
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return str(raw)
    for campo in ("text", "content", "message"):
        valor = raw.get(campo)
        if isinstance(valor, str):
            return valor
        if isinstance(valor, list):
            partes = [
                p.get("text", "")
                for p in valor
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            ]
            if partes:
                return "\n".join(partes)
    return ""


def _resumo(texto: str, limite: int = 200) -> str:
    return " ".join(texto.split())[:limite]


def fingerprint() -> str:
    """Contagem de sessões raiz + última atualização (consulta indexada)."""
    con = _con()
    try:
        return store.fingerprint_consulta(
            con,
            "SELECT COUNT(*), MAX(time_updated) FROM session_v2"
            " WHERE parent_id IS NULL",
        )
    finally:
        con.close()


def scan() -> list[Registro]:
    con = _con()
    try:
        sessoes = con.execute(
            "SELECT id, title, directory, time_created, time_updated, agent, model"
            " FROM session_v2 WHERE parent_id IS NULL ORDER BY time_updated DESC"
        ).fetchall()

        # primeira mensagem do usuário de cada sessão (ordem: sessão, tempo)
        primeiras: dict[str, str] = {}
        for sid, data in con.execute(
            "SELECT session_id, data FROM session_message"
            " WHERE type='user' ORDER BY session_id, time_created, id"
        ):
            if sid not in primeiras:
                primeiras[sid] = _texto(data)

        contagens = dict(
            con.execute(
                "SELECT session_id, COUNT(*) FROM session_message GROUP BY session_id"
            )
        )
    finally:
        con.close()

    registros: list[Registro] = []
    for sid, titulo, directory, tc, tu, agent, model in sessoes:
        primeira = _resumo(primeiras.get(sid, ""), 400)
        title = (titulo or "").strip() or primeira[:80] or "(sem título)"
        registros.append(
            Registro(
                id=sid,
                cli=CLI,
                title=title,
                cwd=directory or None,
                created_at=tc,
                updated_at=tu,
                preview=_resumo(primeira),
                n_msgs=contagens.get(sid),
                native_resume=["opencode", "-s", sid],
                source_path=str(DB),
                imported_in_opencode=sid,
                meta={k: v for k, v in (("agent", agent), ("model", model)) if v},
            )
        )
    return registros


def carregar(reg: Registro) -> list[Mensagem]:
    con = _con()
    try:
        linhas = con.execute(
            "SELECT id, type, data, time_created FROM session_message"
            " WHERE session_id=? AND type IN ('user','assistant','system')"
            " ORDER BY time_created, id",
            (reg.id,),
        ).fetchall()

        partes: dict[str, list[str]] = {}
        # `part` não tem coluna `type`: o tipo mora dentro do `data` (JSON)
        for mid, pdata, _ in con.execute(
            "SELECT message_id, data, time_created FROM part"
            " WHERE session_id=? ORDER BY time_created, id",
            (reg.id,),
        ):
            try:
                if json.loads(pdata).get("type") != "text":
                    continue
            except Exception:
                continue
            texto = _texto(pdata)
            if texto:
                partes.setdefault(mid, []).append(texto)
    finally:
        con.close()

    mensagens: list[Mensagem] = []
    for mid, tipo, data, quando in linhas:
        texto = _texto(data).strip() or "\n".join(partes.get(mid, [])).strip()
        if not texto:
            continue
        mensagens.append(Mensagem(role=tipo, text=texto, time=quando))
    return mensagens
