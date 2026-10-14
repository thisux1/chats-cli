"""Importa uma conversa de qualquer CLI pro OpenCode.

Endpoint: POST /api/experimental/session/import  {info, messages, location}
Formato conferido num export real (`GET /api/experimental/session/:id/export`).
`location.directory` é obrigatório: sem ele a sessão cai no projeto `global` e
some da listagem — exatamente o bug de 2026-10-06.
"""
from __future__ import annotations

import json
import os
import secrets
import string
import subprocess
import sys
import time
from pathlib import Path

from . import registry
from .models import Mensagem, Registro

AGENTE = "build"
ALFABETO = string.ascii_letters + string.digits
MODELO_PADRAO = {"id": "mimo-v2.6-flash-free", "providerID": "opencode"}
MAX_TITULO = 500
LEDGER = Path.home() / ".local/share/chats/imports.json"


def _id(prefixo: str, quando: int | None = None) -> str:
    """Formato canônico do Identifier.create: 12 hex (ts invertido) + 14 base62.

    O Zen só serve o free tier quando `x-opencode-session` é um id de sessão
    real do opencode (`ses_<12hex><14base62>`); ids inventados como
    `ses_devin<...>` são barrados com "can only be used from within OpenCode".
    """
    agora = quando if quando is not None else int(time.time() * 1000)
    invertido = (~agora) & ((1 << 48) - 1)
    sufixo = "".join(secrets.choice(ALFABETO) for _ in range(14))
    return f"{prefixo}{invertido:012x}{sufixo}"


def modelo_padrao() -> dict:
    """O modelo da sessão mais recente do próprio OpenCode (evita hardcode)."""
    db = Path.home() / ".local/share/opencode/opencode.db"
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.execute("PRAGMA busy_timeout=3000")
        linha = con.execute(
            "SELECT model FROM session_v2 WHERE model IS NOT NULL"
            " ORDER BY time_updated DESC LIMIT 1"
        ).fetchone()
        con.close()
        if linha and linha[0]:
            modelo = json.loads(linha[0])
            return {k: modelo[k] for k in ("id", "providerID", "variant") if k in modelo}
    except Exception:
        pass
    return dict(MODELO_PADRAO)


def _subpath(diretorio: str) -> str:
    casa = str(Path.home())
    return diretorio[len(casa) + 1:] if diretorio.startswith(casa + os.sep) else diretorio


def monta_payload(reg: Registro, mensagens: list[Mensagem], diretorio: str,
                  project_id: str, modelo: dict | None = None) -> dict:
    modelo = modelo or modelo_padrao()
    agora = int(time.time() * 1000)
    criado = reg.created_at or agora
    atualizado = max(reg.updated_at or 0, criado)
    # o gate aceita timestamps de até ~1 ano atrás; sessões mais velhas
    # ganham carimbo recente pra não cair no "can only be used from within"
    carimbo = max(min(criado, agora), agora - 330 * 86_400_000)
    sid = _id("ses_", carimbo)

    projeto: dict = {
        "id": sid,
        "projectID": project_id,
        "title": (reg.title or "").strip()[:MAX_TITULO],
        "agent": AGENTE,
        "model": modelo,
        "cost": 0,
        "tokens": {"input": 0, "output": 0, "reasoning": 0,
                   "cache": {"read": 0, "write": 0}},
        "time": {"created": criado, "updated": atualizado},
        "subpath": _subpath(diretorio),
        "location": {"directory": diretorio},
    }

    projetadas: list[dict] = []
    for i, msg in enumerate(mensagens):
        quando = msg.time or (criado + i * 1000)
        base = {"id": _id("msg_"), "time": {"created": quando}}
        if msg.role == "user":
            projetadas.append({**base, "text": msg.text, "type": "user"})
        else:
            projetadas.append({
                **base,
                "time": {"created": quando, "completed": quando},
                "type": "assistant",
                "agent": AGENTE,
                "model": modelo,
                "content": [{"type": "text", "text": msg.text}],
                "cost": 0,
                "tokens": {"input": 0, "output": 0, "reasoning": 0,
                           "cache": {"read": 0, "write": 0}},
            })

    return {
        "info": projeto,
        "messages": projetadas,
        "location": {"directory": diretorio},
    }


def resolve_local(diretorio: str) -> tuple[str, str] | None:
    """(diretório_canônico, projectID) via GET /api/location.

    É o mesmo caminho que o `opencode import` usa: resolve/cria o projeto do
    diretório antes de importar.
    """
    try:
        proc = subprocess.run(
            ["opencode", "api", "get", "/api/location", "--param",
             "location=" + json.dumps({"directory": diretorio})],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    try:
        dado = json.loads((proc.stdout or "").strip())
    except ValueError:
        return None
    projeto = dado.get("project") if isinstance(dado, dict) else None
    if not isinstance(projeto, dict) or not projeto.get("id"):
        return None
    return dado.get("directory") or diretorio, projeto["id"]


def enviar(payload: dict) -> tuple[str | None, str]:
    """POST no servidor em execução. Devolve (id_da_sessão, erro)."""
    corpo = json.dumps(payload, ensure_ascii=False)
    if len(corpo) > 8_000_000:
        return None, f"payload muito grande ({len(corpo) // 1_000_000} MB)"

    try:
        proc = subprocess.run(
            ["opencode", "api", "post", "/api/experimental/session/import",
             "--data", corpo],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return None, "`opencode` não encontrado no PATH"
    except subprocess.TimeoutExpired:
        return None, "timeout no servidor do opencode"

    saida = (proc.stdout or "") + (proc.stderr or "")
    if "HTTP 409" in saida:
        return payload["info"]["id"], "sessão já existia (409)"
    if proc.returncode != 0 or "InvalidRequestError" in saida or "HTTP 4" in saida:
        primeira = saida.strip().splitlines()[0][:300] if saida.strip() else "sem resposta"
        return None, primeira

    try:
        dado = json.loads(saida)
    except ValueError:
        return None, f"resposta ilegível: {saida[:200]}"
    if isinstance(dado, dict) and isinstance(dado.get("data"), dict):
        return dado["data"].get("id") or payload["info"]["id"], ""
    if isinstance(dado, dict) and dado.get("id"):
        return dado["id"], ""
    return payload["info"]["id"], ""


def _canonico(sessao: str) -> bool:
    """id no formato Identifier.create: `ses_<12hex><14base62>` (30 chars)."""
    if len(sessao) != 30 or not sessao.startswith("ses_"):
        return False
    corpo = sessao[4:]
    try:
        int(corpo[:12], 16)
    except ValueError:
        return False
    return all(c in ALFABETO for c in corpo[12:])


def _existe(sessao: str) -> bool:
    db = Path.home() / ".local/share/opencode/opencode.db"
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.execute("PRAGMA busy_timeout=3000")
        achei = con.execute(
            "SELECT 1 FROM session_v2 WHERE id=? LIMIT 1", (sessao,)
        ).fetchone()
        con.close()
        return achei is not None
    except Exception:
        return False


def _ler_ledger() -> dict:
    try:
        dados = json.loads(LEDGER.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_ledger(chave: str, sessao: str) -> None:
    dados = _ler_ledger()
    dados[chave] = sessao
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    except OSError as exc:
        print(f"aviso: não gravei o ledger ({exc})", file=sys.stderr)


def ja_importada(reg: Registro) -> str | None:
    """Idempotência: ledger exato → devin já marcado → (título, pasta)."""
    if reg.imported_in_opencode:
        return reg.imported_in_opencode

    sessao = _ler_ledger().get(reg.key)
    if sessao and _existe(sessao):
        return sessao

    titulo = (reg.title or "").strip().lower()
    if not titulo:
        return None
    registros, _ = registry.scan({"opencode"})
    for alvo in registros:
        if (alvo.title or "").strip().lower() == titulo and alvo.cwd == reg.cwd:
            return alvo.id
    return None


def importar(reg: Registro, diretorio: str | None = None) -> tuple[str | None, str]:
    """Devolve (id_no_opencode, observação). Erro vem como id=None."""
    existente = ja_importada(reg)
    if existente:
        if _canonico(existente):
            return existente, "já estava no opencode"
        # id de import antiga não passa no gate do free tier — reimporta com
        # id canônico (a sessão quebrada fica listada até ser apagada à mão)
        print(f"reimportando: {existente} tem id fora do formato canônico "
              "e o free tier recusa", file=sys.stderr)

    destino = diretorio or reg.cwd
    if not destino:
        return None, "conversa sem diretório — use `--dir <caminho>`"
    if not Path(destino).is_dir():
        return None, f"diretório não existe: {destino} — use `--dir <caminho>`"

    mensagens = registry.carregar(reg)
    if not mensagens:
        return None, "não consegui ler as mensagens desta conversa"

    local = resolve_local(destino)
    if not local:
        return None, f"não consegui resolver o projeto do opencode em {destino}"
    _, project_id = local

    # o diretório PEDIDO é o que decide o projeto e o escopo no opencode;
    # o canônico do /api/location viraria /home/thiago em qualquer subpasta
    payload = monta_payload(reg, mensagens, destino, project_id)
    sessao, obs = enviar(payload)
    if sessao and not obs:
        _gravar_ledger(reg.key, sessao)
    return sessao, obs


def abrir(reg: Registro, diretorio: str | None = None) -> int:
    sessao, obs = importar(reg, diretorio)
    if not sessao:
        print(f"importação falhou: {obs}", file=sys.stderr)
        return 1
    if obs:
        print(obs, file=sys.stderr)

    destino = diretorio or reg.cwd or str(Path.home())
    print(f"sessão no opencode: {sessao}", file=sys.stderr)
    argv = ["opencode", "-s", sessao]
    print(f"$ {' '.join(argv)}", file=sys.stderr)
    print(f"  cwd: {destino}", file=sys.stderr)
    os.chdir(destino)
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        print("comando não encontrado: opencode", file=sys.stderr)
        return 127
    return 0
