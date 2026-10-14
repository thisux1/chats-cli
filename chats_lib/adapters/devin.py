"""Adapter Devin — `~/.local/share/devin/cli/sessions.db`.

A tabela `sessions` (39 linhas) já traz `working_directory` e `title`.
A prévia lê só os 8 primeiros nós por `rowid` (~1 ms/sessão — 40 ms no
total); o conteúdo completo continua saindo sob demanda, seguindo
`main_chain_id` até a raiz. A tabela `message_nodes` (167 mil linhas num
banco de 4,6 GB) nunca é varrida: ordenar por `created_at` ali custaria
segundos, porque não há índice de (session_id, created_at) e a ordenação
tocaria os blobs gigantes de `chat_response`.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .. import store
from ..models import Mensagem, Registro

CLI = "devin"
DB = Path.home() / ".local/share/devin/cli/sessions.db"
FONTES = [DB]

# papéis que interessam numa leitura (tool/compaction ficam de fora)
PAPEIS = ("user", "assistant", "system")


def _con() -> sqlite3.Connection:
    if not DB.exists():
        raise FileNotFoundError(f"banco não encontrado: {DB}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout=3000")
    return con


def resolver(sid: str) -> Registro | None:
    if not DB.exists():
        return None
    return Registro(id=sid, cli=CLI, title="", source_path=str(DB),
                    native_resume=["devin", "-r", sid])


def fingerprint() -> str:
    """Contagem de sessões + última atividade (a `sessions` tem 39 linhas)."""
    con = _con()
    try:
        return store.fingerprint_consulta(
            con, "SELECT COUNT(*), MAX(last_activity_at) FROM sessions"
        )
    finally:
        con.close()


def _primeiro_prompt(con: sqlite3.Connection, sid: str) -> str:
    """1ª fala do usuário da sessão, lida por `rowid` (ordem de inserção)."""
    for (blob,) in con.execute(
        "SELECT chat_message FROM message_nodes WHERE session_id=?"
        " ORDER BY rowid LIMIT 8",
        (sid,),
    ):
        try:
            msg = json.loads(blob)
        except Exception:
            continue
        if msg.get("role") != "user":
            continue
        conteudo = msg.get("content")
        texto = conteudo if isinstance(conteudo, str) else ""
        if isinstance(conteudo, list):
            texto = "\n".join(
                bloco.get("text", "")
                for bloco in conteudo
                if isinstance(bloco, dict) and isinstance(bloco.get("text"), str)
            )
        if texto.strip():
            return " ".join(texto.split())[:200]
    return ""


def scan() -> list[Registro]:
    con = _con()
    try:
        linhas = con.execute(
            "SELECT id, working_directory, title, created_at, last_activity_at,"
            " model, agent_mode, hidden FROM sessions ORDER BY last_activity_at DESC"
        ).fetchall()
        try:
            prompts = {
                linha[0]: _primeiro_prompt(con, linha[0])
                for linha in linhas
                if not linha[7]
            }
        except sqlite3.Error:
            prompts = {}  # prévia é bônus: sem ela o scan continua de pé
    finally:
        con.close()

    registros: list[Registro] = []
    for sid, dir_, titulo, criado, ativo, model, modo, escondido in linhas:
        if escondido:
            continue
        registros.append(
            Registro(
                id=sid,
                cli=CLI,
                title=(titulo or "").strip() or sid,
                cwd=dir_ or None,
                created_at=(criado or 0) * 1000 or None,
                updated_at=(ativo or 0) * 1000 or None,
                preview=prompts.get(sid, ""),
                native_resume=["devin", "-r", sid],
                source_path=str(DB),
                meta={k: v for k, v in (("model", model), ("agent", modo)) if v},
            )
        )
    return registros


def carregar(reg: Registro) -> list[Mensagem]:
    con = _con()
    try:
        cabeca = con.execute(
            "SELECT main_chain_id FROM sessions WHERE id=?", (reg.id,)
        ).fetchone()
        if not cabeca or cabeca[0] is None:
            return []
        nos = {
            row[0]: (row[1], row[2])
            for row in con.execute(
                "SELECT node_id, parent_node_id, chat_message"
                " FROM message_nodes WHERE session_id=?",
                (reg.id,),
            )
        }
    finally:
        con.close()

    # caminha da cabeça até a raiz e inverte → ordem cronológica da conversa
    cadeia: list[int] = []
    atual, visto = cabeca[0], set()
    while atual is not None and atual in nos and atual not in visto:
        visto.add(atual)
        cadeia.append(atual)
        atual = nos[atual][0]
    cadeia.reverse()

    mensagens: list[Mensagem] = []
    for no in cadeia:
        try:
            msg = json.loads(nos[no][1])
        except Exception:
            continue
        papel = msg.get("role")
        if papel not in PAPEIS:
            continue
        conteudo = msg.get("content")
        texto = conteudo if isinstance(conteudo, str) else ""
        if isinstance(conteudo, list):
            texto = "\n".join(
                b.get("text", "")
                for b in conteudo
                if isinstance(b, dict) and isinstance(b.get("text"), str)
            )
        if not texto or not texto.strip():
            continue
        mensagens.append(Mensagem(role=papel, text=texto.strip()))
    return mensagens
