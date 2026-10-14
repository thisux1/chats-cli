"""Picker: fzf quando houver, lista numerada como fallback."""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys

from .models import Registro
from .render import cortar, linha, pintar

CABECALHO = "ENTER abre o menu · / busca · ESC sai"

# fzf devolve 1 quando não há match e 130 em ESC/Ctrl-C — é o usuário
# desistindo, não um defeito. Qualquer outro rc é erro do fzf.
SAIDAS_DO_USUARIO = (1, 130)


def comando_fzf(binpath: str) -> list[str]:
    """Argumentos do fzf — separado pra dar pra testar sem TTY.

    Só opções que o fzf 0.74.3 daqui aceita: `--header-lines-position`
    não existe nessa versão e derrubava tudo (ver `tests/test_picker.py`).
    """
    return [
        "fzf",
        "--ansi",
        "--delimiter=\t",
        "--with-nth=1,2,3,4",
        "--nth=1,2,3,4",
        "--tabstop=2",
        "--layout=default",
        "--cycle",
        "--header",
        CABECALHO,
        "--header-first",
        "--preview",
        f"{binpath} preview '{{5}}'",
        "--preview-window",
        "right:60%:wrap",
    ]


def escolher(
    registros: list[Registro],
    binpath: str,
    ligado: bool = True,
    largo: bool = False,
) -> list[str] | None:
    """Devolve as keys escolhidas, ou None se o usuário desistiu."""
    if not registros:
        return None

    fzf = shutil.which("fzf")
    if not fzf or not sys.stdin.isatty():
        return _numerado(registros, ligado)

    payload = "\n".join(linha(r, ligado, largo) for r in registros) + "\n"
    cmd = [fzf] + comando_fzf(binpath)[1:]
    try:
        proc = _roda_fzf(cmd, payload)
    except OSError:
        return _numerado(registros, ligado)

    if proc.returncode != 0:
        if proc.returncode in SAIDAS_DO_USUARIO:  # 1 = sem match, 130 = ESC/Ctrl-C
            return None
        # fzf quebrou (opção não suportada, versão antiga…) — não é o
        # usuário desistindo, então a lista numerada salva a sessão
        print(
            f"aviso: fzf terminou com rc={proc.returncode}; lista numerada",
            file=sys.stderr,
        )
        return _numerado(registros, ligado)

    keys = []
    for bruta in proc.stdout.splitlines():
        campo = bruta.split("\t")[-1].strip()
        if campo and campo not in keys:
            keys.append(campo)
    return keys or None


def _roda_fzf(cmd: list[str], payload: str):
    """Roda o fzf isolando só o `stdout`; o `stderr` vai pro terminal.

    - não capturar o `stderr` é o que deixa a UI e as mensagens de erro
      do fzf aparecerem (com `capture_output=True` um `unknown option`
      virava morte silenciosa);
    - o SIGPIPE é ignorado só durante o spawn: o entry point instala
      `SIG_DFL` pra `chats … | head` limpo, e nesse estado o EPIPE de um
      fzf que morreu cedo matava a CLI com rc 141 em vez de virar
      `OSError` e cair na lista numerada.
    """
    try:
        antes = signal.getsignal(signal.SIGPIPE)
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    except ValueError:  # fora da thread principal: sinal é global
        antes = None
    try:
        return subprocess.run(cmd, input=payload, text=True, stdout=subprocess.PIPE)
    finally:
        if antes is not None:
            signal.signal(signal.SIGPIPE, antes)


def _numerado(registros: list[Registro], ligado: bool) -> list[str] | None:
    """Fallback sem fzf: lista numerada + input."""
    print(CABECALHO + "\n", file=sys.stderr)
    for i, reg in enumerate(registros, 1):
        print(
            f"{i:>4}  {pintar(f'{reg.cli:<9}', '', ligado)}"
            f"{cortar(reg.title, 70)}  {pintar(pasta_texto(reg), '2', ligado)}",
            file=sys.stderr,
        )
    try:
        resposta = input("\nnúmero (ou vazio pra sair): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not resposta:
        return None
    escolhidas = []
    for parte in resposta.replace(",", " ").split():
        if parte.isdigit() and 1 <= int(parte) <= len(registros):
            escolhidas.append(registros[int(parte) - 1].key)
    return escolhidas or None


def pasta_texto(reg: Registro) -> str:
    from .render import pasta

    return pasta(reg.cwd)
