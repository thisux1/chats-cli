"""Índice local (Fase 4): evita reler as 6 fontes a cada execução.

Regra: a fonte só é relida quando a `fingerprint` dela muda. A
`fingerprint` é barata — contagem + mtime (arquivos) ou contagem +
MAX(coluna) (SQLite) — e sai por ~10 ms no total; a fonte inteira sai
por ~230 ms.

Banco próprio em `~/.local/share/chats/index.db`: gravável, ao
contrário dos bancos de terceiros, que só são abertos em modo leitura.
Se o índice falhar por qualquer motivo, o scan cai na fonte direta —
ele é aceleração, nunca parte do contrato.
"""
from __future__ import annotations

import json
import sqlite3
import stat as stat_mod
import time
from contextlib import contextmanager
from pathlib import Path

from .models import Registro

DIR = Path.home() / ".local/share/chats"
DB = DIR / "index.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS registro(
    key TEXT PRIMARY KEY,
    cli TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    cwd TEXT,
    created_at INTEGER,
    updated_at INTEGER,
    preview TEXT,
    n_msgs INTEGER,
    native_resume TEXT,
    source_path TEXT,
    imported_in_opencode TEXT,
    meta TEXT
);
CREATE TABLE IF NOT EXISTS fonte(
    cli TEXT PRIMARY KEY,
    fingerprint TEXT,
    quando INTEGER
);
"""

_COLUNAS = (
    "key, cli, id, title, cwd, created_at, updated_at, preview, n_msgs, "
    "native_resume, source_path, imported_in_opencode, meta"
)


@contextmanager
def _abrir():
    DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    try:
        con.execute("PRAGMA busy_timeout=3000")
        con.executescript(_ESQUEMA)
        yield con
        con.commit()
    finally:
        con.close()


def fingerprint(cli: str) -> str | None:
    """Fingerprint guardada da fonte — None quando nunca indexada.

    Qualquer falha aqui (permissão, disco cheio, schema corrompido)
    devolve None e manda o scan ler a fonte direto: o índice não pode
    derrubar a CLI.
    """
    try:
        with _abrir() as con:
            linha = con.execute(
                "SELECT fingerprint FROM fonte WHERE cli=?", (cli,)
            ).fetchone()
    except Exception:
        return None
    return linha[0] if linha else None


def ler(cli: str) -> list[Registro] | None:
    """Registros guardados da fonte; None = sem índice utilizável."""
    try:
        with _abrir() as con:
            if (
                con.execute("SELECT 1 FROM fonte WHERE cli=?", (cli,)).fetchone()
                is None
            ):
                return None  # fonte nunca indexada
            linhas = con.execute(
                f"SELECT {_COLUNAS} FROM registro WHERE cli=?", (cli,)
            ).fetchall()
    except Exception:
        return None
    registros: list[Registro] = []
    try:
        for linha in linhas:
            registros.append(
                Registro(
                    id=linha[2],
                    cli=linha[1],
                    title=linha[3],
                    cwd=linha[4],
                    created_at=linha[5],
                    updated_at=linha[6],
                    preview=linha[7] or "",
                    n_msgs=linha[8],
                    native_resume=json.loads(linha[9]) if linha[9] else [],
                    source_path=linha[10] or "",
                    imported_in_opencode=linha[11],
                    meta=json.loads(linha[12]) if linha[12] else {},
                )
            )
    except (ValueError, TypeError, json.JSONDecodeError):
        return None  # linha corrompida → rescan, não dado pela metade
    return registros


def salvar(cli: str, fingerprint: str, registros: list[Registro]) -> None:
    """(Re)escreve a fonte inteira num transação só."""
    with _abrir() as con:
        con.execute("DELETE FROM registro WHERE cli=?", (cli,))
        con.executemany(
            f"INSERT OR REPLACE INTO registro({_COLUNAS}) VALUES"
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r.key,
                    r.cli,
                    r.id,
                    r.title,
                    r.cwd,
                    r.created_at,
                    r.updated_at,
                    r.preview,
                    r.n_msgs,
                    json.dumps(r.native_resume, ensure_ascii=False),
                    r.source_path,
                    r.imported_in_opencode,
                    json.dumps(r.meta, ensure_ascii=False),
                )
                for r in registros
            ],
        )
        con.execute(
            "INSERT OR REPLACE INTO fonte(cli, fingerprint, quando) VALUES(?, ?, ?)",
            (cli, fingerprint, int(time.time())),
        )


def fingerprint_arquivos(*caminhos: Path) -> str:
    """Contagem de arquivos + mtime máximo — muda quando a fonte muda."""
    total, maximo = 0, 0
    for caminho in caminhos:
        raiz = Path(caminho)
        try:
            itens = [raiz] if raiz.is_file() else list(raiz.rglob("*"))
        except OSError:
            continue
        for item in itens:
            try:
                st = item.stat()
            except OSError:
                continue
            if stat_mod.S_ISREG(st.st_mode):
                total += 1
                maximo = max(maximo, st.st_mtime_ns)
    return f"v1:{total}:{maximo}"


def fingerprint_consulta(con: sqlite3.Connection, sql: str, params=()) -> str:
    """Para SQL que devolve (COUNT(*), MAX(coluna))."""
    total, maximo = con.execute(sql, params).fetchone()
    return f"v1:{total or 0}:{maximo}"


def status() -> dict:
    """Resumo do índice pro `doctor`/`sync`: registros, fontes, última escrita."""
    if not DB.exists():
        return {"existe": False, "registros": 0, "fontes": 0, "quando": None}
    try:
        with _abrir() as con:
            registros = con.execute("SELECT COUNT(*) FROM registro").fetchone()[0]
            fontes, quando = con.execute(
                "SELECT COUNT(*), MAX(quando) FROM fonte"
            ).fetchone()
    except sqlite3.Error:
        return {"existe": True, "registros": 0, "fontes": 0, "quando": None}
    return {"existe": True, "registros": registros, "fontes": fontes or 0,
            "quando": quando}


def limpar() -> None:
    """Apaga o índice (usado por teste e por quem quiser recomeçar)."""
    for caminho in (DB, Path(str(DB) + "-wal"), Path(str(DB) + "-shm")):
        try:
            caminho.unlink()
        except OSError:
            pass
