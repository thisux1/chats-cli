"""CLI: lista (com escopo), preview, open, export, doctor, which."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from . import escopo as esc
from . import picker, registry, render, store
from .doctor import rodar as doctor_rodar
from .models import Registro
from .openers import menu

SUBCOMANDOS = {"preview", "open", "export", "doctor", "which", "sync"}
SEM_KEY = 2  # nenhum resultado no escopo atual
FALHA = 1


def _binpath() -> str:
    return os.path.realpath(sys.argv[0])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in SUBCOMANDOS:
        return _sub(argv)
    return _lista(argv)


# ─────────────────────────────── lista ───────────────────────────────


def _parser_lista() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chats",
        description="Lista conversas de opencode, codex, agy, devin, freebuff e gemini "
        "escopadas ao diretório atual.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="ignora o escopo do diretório")
    g.add_argument("--tree", action="store_true", help="raiz + subpastas, agrupado por pasta")
    g.add_argument("--flat", action="store_true", help="lista plana (sem grupos)")
    p.add_argument("--exact", action="store_true", help="só o cwd exato, sem descendentes")
    p.add_argument("--cli", metavar="A,B", help="só estas fontes (ex.: codex,devin)")
    p.add_argument("--since", metavar="7d|30d|hoje|2026-09", help="janela temporal")
    p.add_argument("--limit", type=int, metavar="N")
    p.add_argument("--format", choices=["table", "json", "tsv"], default="table")
    p.add_argument("--long", action="store_true", help="título e caminho mais largos")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--no-pick", action="store_true", help="só imprime, não abre o fzf")
    p.add_argument("query", nargs="*", help="termos de busca")
    return p


def _desde(texto: str) -> int:
    t = texto.strip().lower()
    agora = time.time()
    m = re.fullmatch(r"(\d+)([hdw])", t)
    if m:
        mult = {"h": 3600, "d": 86400, "w": 604800}[m.group(2)]
        return int((agora - int(m.group(1)) * mult) * 1000)
    if t in ("hoje", "today"):
        ini = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return int(ini.timestamp() * 1000)
    m = re.fullmatch(r"(\d{4})-(\d{2})", t)
    if m:
        return int(datetime(int(m.group(1)), int(m.group(2)), 1).timestamp() * 1000)
    raise SystemExit(f"--since inválido: {texto}  (use 7d, 12h, 30d, hoje, 2026-09)")


def _bate(reg: Registro, tokens: list[str]) -> bool:
    alvo = " ".join(
        [reg.title, reg.preview, reg.cwd or "", reg.cli]
        + [str(v) for v in reg.meta.values() if isinstance(v, str)]
    ).lower()
    return all(t in alvo for t in tokens)


def _lista(argv: list[str]) -> int:
    args = _parser_lista().parse_args(argv)
    ligado = render.cor_ativa(args.no_color)

    clis = {c.strip() for c in args.cli.split(",") if c.strip()} if args.cli else None
    registros, erros = registry.scan(clis)
    for cli, erro in erros:
        print(f"aviso: {cli}: {erro}", file=sys.stderr)

    pwd = Path.cwd()
    raiz = esc.resolver_raiz(pwd)
    if args.all:
        escopo = esc.TODOS
    elif args.tree:
        escopo = esc.ARVORE
    else:
        escopo = esc.modo(raiz)

    no_escopo = esc.aplicar(registros, raiz, escopo, exato=args.exact)
    no_escopo = render.ordenar(no_escopo)

    if args.since:
        corte = _desde(args.since)
        no_escopo = [r for r in no_escopo if (r.updated_at or 0) >= corte]
    if args.query:
        tokens = [t.lower() for t in args.query]
        no_escopo = [r for r in no_escopo if _bate(r, tokens)]
    if args.limit:
        no_escopo = no_escopo[: args.limit]

    agrupado = (not args.flat) and (args.tree or escopo == esc.CASA)

    if args.format == "json":
        print(render.como_json(no_escopo))
        return 0 if no_escopo else SEM_KEY
    if args.format == "tsv":
        print(render.como_tsv(no_escopo))
        return 0 if no_escopo else SEM_KEY

    if not no_escopo:
        print(f"nenhuma conversa em {esc.descrever(raiz, escopo)}", file=sys.stderr)
        if escopo != esc.TODOS:
            print("dica: `chats --all` ignora o escopo · `chats which` mostra a regra",
                  file=sys.stderr)
        return SEM_KEY

    if args.no_pick or not sys.stdout.isatty():
        ordem = render.agrupar(no_escopo) if agrupado else [("", no_escopo)]
        planos = [r for _, regs in ordem for r in regs]
        print(render.tabela(planos, ligado, agrupado, args.long))
        return 0

    # ordem no fzf: agrupada quando o escopo é a home, senão por recência
    if agrupado:
        ordem = [r for _, regs in render.agrupar(no_escopo) for r in regs]
    else:
        ordem = no_escopo

    escolhidas = picker.escolher(ordem, _binpath(), ligado, args.long)
    if not escolhidas:
        return 0

    por_key = {r.key: r for r in registros}
    for key in escolhidas:
        reg = por_key.get(key)
        if reg is None:
            print(f"não achei {key}", file=sys.stderr)
            continue
        if menu(reg, _binpath()) != 0:
            return FALHA
    return 0


# ─────────────────────────────── subs ───────────────────────────────


def _sub(argv: list[str]) -> int:
    cmd, resto = argv[0], argv[1:]

    if cmd == "doctor":
        p = argparse.ArgumentParser(prog="chats doctor")
        p.add_argument("--no-color", action="store_true")
        return doctor_rodar(not p.parse_args(resto).no_color)

    if cmd == "which":
        return _which()

    if cmd == "preview":
        p = argparse.ArgumentParser(prog="chats preview")
        p.add_argument("key")
        p.add_argument("--lines", type=int, default=40)
        ns = p.parse_args(resto)
        return _preview(ns.key, ns.lines)

    if cmd == "open":
        p = argparse.ArgumentParser(prog="chats open")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--native", action="store_true")
        g.add_argument("--opencode", action="store_true")
        g.add_argument("--ask", action="store_true")
        p.add_argument("--dir", metavar="PATH",
                       help="diretório do projeto no OpenCode (obrigatório se "
                            "a conversa não tiver cwd válido)")
        p.add_argument("key")
        ns = p.parse_args(resto)
        return _open(ns.key, ns)

    if cmd == "export":
        p = argparse.ArgumentParser(prog="chats export")
        p.add_argument("--to", choices=["md", "json"], default="md")
        p.add_argument("-o", "--out")
        p.add_argument("key")
        ns = p.parse_args(resto)
        return _export(ns.key, ns.to, ns.out)

    if cmd == "sync":
        p = argparse.ArgumentParser(prog="chats sync")
        p.add_argument("--force", action="store_true",
                       help="reescreve o índice mesmo sem mudança na fonte")
        p.add_argument("--cli", metavar="A,B", help="só estas fontes")
        p.add_argument("--no-color", action="store_true")
        return _sync(p.parse_args(resto))

    return FALHA


def _acha(key: str) -> Registro:
    reg = registry.buscar(key)
    if reg is None:
        raise SystemExit(f"conversa não encontrada: {key}")
    return reg


def _preview(key: str, linhas: int) -> int:
    cli, _, sid = key.partition(":")
    reg = registry.buscar(key)
    mensagens = registry.carregar_id(cli, sid)

    if not mensagens:
        # sem conteúdo (agy em protobuf, conversa vazia) → usa a linha
        if reg is None:
            return FALHA
        print(f"▌{reg.title}")
        print(f"▌{render.pasta(reg.cwd)} · {reg.n_msgs or '?'} msgs"
              " · conteúdo completo indisponível")
        if reg.preview:
            print()
            print("› " + " ".join(reg.preview.split()))
        return 0

    titulo = reg.title if reg else key
    print(f"▌{titulo}")
    if reg:
        print(f"▌{render.pasta(reg.cwd)} · {reg.n_msgs or len(mensagens)} msgs")
    print()
    for msg in mensagens[:linhas]:
        if msg.role == "system":
            continue  # contexto injetado polui a prévia
        marca = "›" if msg.role == "user" else "‹"
        corpo = " ".join(msg.text.split())
        if len(corpo) > 400:
            corpo = corpo[:399] + "…"
        print(f"{marca} {corpo}")
    return 0


def _open(key: str, ns: argparse.Namespace) -> int:
    reg = _acha(key)
    if ns.native:
        from .openers import abrir_native

        return abrir_native(reg)
    if ns.opencode:
        from .import_opencode import abrir

        return abrir(reg, getattr(ns, "dir", None))
    return menu(reg, _binpath())


def _export(key: str, para: str, destino: str | None) -> int:
    reg = _acha(key)
    mensagens = registry.carregar_id(reg.cli, reg.id)
    if not mensagens:
        return FALHA

    if para == "json":
        dados = {
            "registro": reg.as_dict(),
            "mensagens": [{"role": m.role, "text": m.text, "time": m.time} for m in mensagens],
        }
        conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    else:
        linhas = [f"# {reg.title}", "", f"- cli: {reg.cli}", f"- id: {reg.id}",
                  f"- pasta: {reg.cwd or '?'}", f"- mensagens: {len(mensagens)}", ""]
        for m in mensagens:
            linhas += [f"### {m.role}", "", m.text, ""]
        conteudo = "\n".join(linhas)

    if destino:
        Path(destino).write_text(conteudo, encoding="utf-8")
        print(destino)
        return 0
    print(conteudo)
    return 0


def _which() -> int:
    pwd = Path.cwd()
    raiz = esc.resolver_raiz(pwd)
    escopo = esc.modo(raiz)
    registros, _ = registry.scan()

    print(f"pwd      {pwd}")
    print(f"raiz     {raiz}"
          + ("" if raiz == pwd.resolve() else "   (raiz do git)"))
    print(f"escopo   {escopo} — {esc.descrever(raiz, escopo)}")
    print(f"regra    cwd == raiz ou cwd começa com {raiz}/")
    print()
    dentro = esc.aplicar(registros, raiz, escopo)
    if not dentro:
        print("  (nenhuma conversa neste escopo)")
    else:
        grupos = render.agrupar(dentro)
        for nome, regs in grupos:
            print(f"  {len(regs):>4}  {nome}")
        print(f"  ─────")
        print(f"  {len(dentro):>4}  total")
    print()
    print(f"  {len(registros):>4}  total com --all")
    return 0


def _sync(ns: argparse.Namespace) -> int:
    """Revalida cada fonte e reescreve só o que mudou no índice local."""
    clis = {c.strip() for c in ns.cli.split(",") if c.strip()} if ns.cli else None
    ligado = render.cor_ativa(ns.no_color)
    falhas = 0
    fonte_ms = 0.0

    print(f"{'fonte':<10} {'estado':<12} {'registros':>9} {'ms':>7}")
    for ad in registry.ADAPTERS:
        if clis and ad.CLI not in clis:
            continue
        inicio = time.time()
        try:
            guardada = store.fingerprint(ad.CLI)
            fp = ad.fingerprint()
            mudou = fp != guardada
            if ns.force or mudou:
                regs = ad.scan()
                store.salvar(ad.CLI, fp, regs)
                estado = "atualizado" if mudou else "reescrevido"
            else:
                regs = store.ler(ad.CLI) or []
                estado = "sem mudar"
        except Exception as exc:
            falhas += 1
            print(f"{ad.CLI:<10} {'erro':<12} {'-':>9} {'-':>7}"
                  f"  {type(exc).__name__}: {exc}")
            continue
        ms = (time.time() - inicio) * 1000
        fonte_ms += ms
        nome = render.pintar(f"{ad.CLI:<10}", render.CORES.get(ad.CLI, ""), ligado)
        print(f"{nome}{estado:<12} {len(regs):>9} {ms:>7.0f}")

    registros, _ = registry.scan(clis)
    print()
    print(f"  índice  {store.DB}")
    escopo = f" · só {','.join(sorted(clis))}" if clis else ""
    print(f"  {len(registros):>4} conversas{escopo}  ·  "
          f"{registry.contar_duplicadas(registros)} marcadas ≡  ·  "
          f"{fonte_ms:.0f} ms de fonte")
    if falhas:
        print(f"  {falhas} fonte(s) com erro", file=sys.stderr)
    return 1 if falhas else 0
