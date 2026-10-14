"""`chats doctor` — saúde de cada adapter: fonte, contagem, erro."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from . import store
from .picker import comando_fzf
from .registry import ADAPTERS
from .render import CORES, pintar


def rodar(ligado: bool = True) -> int:
    falhas = 0
    print("fontes:\n")
    for ad in ADAPTERS:
        cor = CORES.get(ad.CLI, "")
        nome = pintar(f"{ad.CLI:<10}", cor, ligado)
        fontes = getattr(ad, "FONTES", [])
        detalhes = []
        for caminho in fontes:
            caminho = Path(caminho)
            if caminho.exists():
                if caminho.is_dir():
                    n = sum(1 for _ in caminho.rglob("*") if _.is_file())
                    detalhes.append(f"{_curto(caminho)} ({n} arqs)")
                else:
                    mb = caminho.stat().st_size / 1e6
                    detalhes.append(f"{_curto(caminho)} ({mb:.1f} MB)")
            else:
                detalhes.append(f"{_curto(caminho)} AUSENTE")

        inicio = time.time()
        try:
            regs = ad.scan()
            ms = (time.time() - inicio) * 1000
            print(f"  {nome} ✓ {len(regs):>4} conversas  {ms:6.0f} ms")
            for d in detalhes:
                print(f"             {d}")
        except Exception as exc:
            falhas += 1
            print(f"  {nome} ✗ {type(exc).__name__}: {exc}")
            for d in detalhes:
                print(f"             {d}")

    print()
    falhas += status_fzf()
    print()
    print("  ⇄  conversa já importada pro OpenCode (dedupe devin)")
    print("  ≡  mesma conversa em 2+ CLIs — pasta, 1ª frase e dia iguais")
    _status_indice()
    return 1 if falhas else 0


def status_fzf() -> int:
    """Confere se o fzf instalado aceita todas as opções do picker (0 = ok).

    Uma opção que essa versão não tem derruba o fzf na hora — e sem
    isso aqui o sintoma é só uma tela em branco.
    """
    bin_fzf = shutil.which("fzf")
    if not bin_fzf:
        print("  fzf      ausente — a lista numerada assume")
        return 0
    proc = subprocess.run(
        comando_fzf("<chats>") + ["--filter=a"],
        input="a\tb\tc\td\te\n",
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        versao = subprocess.run([bin_fzf, "--version"], capture_output=True, text=True)
        nome = (versao.stdout or "").strip() or "fzf"
        print(f"  fzf      ✓ {nome} · opções compatíveis com o picker")
        return 0
    erro = proc.stderr.strip() or f"rc={proc.returncode}"
    print(f"  fzf      ✗ {erro}")
    print("             o picker cai na lista numerada até isso mudar")
    return 1


def _status_indice() -> None:
    st = store.status()
    if not st["existe"]:
        print(f"\n  índice  ausente — o primeiro `chats` cria {store.DB}")
        return
    quando = ""
    if st["quando"]:
        idade = int(time.time()) - st["quando"]
        quando = f" · escrito há {_tempo(idade)}"
    print(f"\n  índice  {store.DB}")
    print(f"          {st['registros']} registros em {st['fontes']} fontes{quando}")


def _tempo(segundos: int) -> str:
    if segundos < 60:
        return f"{segundos} s"
    if segundos < 3600:
        return f"{segundos // 60} min"
    if segundos < 86400:
        return f"{segundos // 3600} h"
    return f"{segundos // 86400} d"


def _curto(caminho: Path) -> str:
    return str(caminho).replace(str(Path.home()), "~")
