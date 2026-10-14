"""Opener: o que fazer depois que uma conversa foi escolhida."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import registry
from .models import Registro

DIAS = {
    "opencode": "abre no seu projeto atual (opencode -s <id>)",
    "codex": "retoma a conversa no terminal (codex resume <id>)",
    "agy": "retoma a conversa (agy --conversation <id>)",
    "devin": "retoma a conversa (devin -r <id>)",
    "freebuff": "retoma a conversa (freebuff --continue <id>)",
    "gemini": "retoma a conversa (gemini)",
}


def menu(reg: Registro, binpath: str) -> int:
    print(f"\n\033[1m{reg.title}\033[0m")
    print(f"  {reg.cli} · {reg.key}")
    print(f"  {reg.cwd or '(diretório desconhecido)'}"
          f" · {reg.n_msgs or '?'} msgs · {origem(reg)}")
    print()
    if reg.native_resume:
        print("  1  ▶  Abrir no nativo        " + " ".join(reg.native_resume))
        retomar = "1"
    else:
        print(f"  1  ▶  Abrir no nativo        (indisponível: "
              f"{reg.meta.get('aviso') or 'sem comando pro ' + reg.cli})")
        retomar = ""
    print("  2  ⇄  Abrir no OpenCode")
    print("  3  👁  Ler no pager")
    print("  4  ⧉  Copiar id / comando")
    print("  0  ⬅  Voltar")
    print()
    try:
        opcao = input("opção: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if opcao == retomar and retomar:
        return abrir_native(reg)
    if opcao == "2":
        return abrir_opencode(reg)
    if opcao == "3":
        return ler(reg, binpath)
    if opcao == "4":
        return copiar(" ".join(reg.native_resume) or reg.key)
    return 0


def plano_native(reg: Registro) -> tuple[list[str], str]:
    """(argv, cwd) que a conversa pede — testável sem dar exec."""
    argv = list(reg.native_resume)
    cwd = reg.cwd if reg.cwd and Path(reg.cwd).is_dir() else str(Path.home())
    return argv, cwd


def abrir_native(reg: Registro) -> int:
    argv, cwd = plano_native(reg)
    if not argv:
        print(f"não sei retomar conversas do {reg.cli} ainda", file=sys.stderr)
        return 1

    print(f"$ {' '.join(argv)}", file=sys.stderr)
    print(f"  cwd: {cwd}", file=sys.stderr)
    os.chdir(cwd)
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        print(f"comando não encontrado: {argv[0]}", file=sys.stderr)
        return 127
    return 0


def abrir_opencode(reg: Registro, diretorio: str | None = None) -> int:
    """Fase 3: importa pro OpenCode e abre lá."""
    from . import import_opencode

    if diretorio is None and (not reg.cwd or not Path(reg.cwd).is_dir()):
        try:
            resposta = input("diretório do projeto no opencode: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        diretorio = resposta or None
    return import_opencode.abrir(reg, diretorio)


def ler(reg: Registro, binpath: str) -> int:
    mensagens = registry.carregar_id(reg.cli, reg.id)
    if not mensagens:
        print("não consegui ler o conteúdo desta conversa", file=sys.stderr)
        return 1

    texto = [f"# {reg.title}", "", f"- cli: {reg.cli}", f"- id: {reg.id}",
             f"- pasta: {reg.cwd or '?'}", ""]
    for msg in mensagens:
        texto.append(f"### {msg.role}")
        texto.append("")
        texto.append(msg.text)
        texto.append("")

    conteudo = "\n".join(texto)
    paginador = os.environ.get("PAGER") or ("bat --paging=always" if shutil.which("bat") else "less -R")
    if not sys.stdout.isatty():
        print(conteudo)
        return 0
    try:
        return subprocess.run(paginador, shell=True, input=conteudo.encode()).returncode
    except KeyboardInterrupt:
        return 0


def copiar(texto: str) -> int:
    for comando in ("wl-copy", "xclip -selection clipboard", "xsel --clipboard --input"):
        if shutil.which(comando.split()[0]):
            subprocess.run(comando, shell=True, input=texto.encode())
            print(f"copiado: {texto}")
            return 0
    print(texto)
    print("(sem wl-copy/xclip/xsel — só imprimi)", file=sys.stderr)
    return 1


def origem(reg: Registro) -> str:
    if not reg.source_path:
        return "?"
    caminho = Path(reg.source_path)
    home = str(Path.home())
    return str(caminho).replace(home, "~")
