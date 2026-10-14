"""Casos-limite da regra de escopo, render e dedupe.

Roda com a stdlib:  python3 -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chats_lib import escopo as esc  # noqa: E402
from chats_lib import render  # noqa: E402
from chats_lib.cli import _desde  # noqa: E402
from chats_lib.models import Registro  # noqa: E402
from chats_lib.openers import plano_native  # noqa: E402
from chats_lib.registry import _marca_importadas  # noqa: E402

HOME = str(esc.HOME)


def reg(cwd, cli="codex", sid="x", quando=1000):
    return Registro(id=sid, cli=cli, title="t", cwd=cwd, updated_at=quando)


class TestResolverRaiz(unittest.TestCase):
    def test_pasta_comum_devolve_a_propria(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(esc.resolver_raiz(Path(d)), Path(d).resolve())

    def test_pasta_dentro_de_repo_devolve_a_raiz_do_git(self):
        import subprocess

        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            subprocess.run(["git", "init", "-q", str(raiz)], check=True)
            filho = raiz / "a" / "b"
            filho.mkdir(parents=True)
            self.assertEqual(esc.resolver_raiz(filho), raiz.resolve())

    def test_caminho_relativo_e_normalizado(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "sub").mkdir()
            self.assertEqual(esc.resolver_raiz(raiz / "sub" / ".."), raiz.resolve())


class TestModo(unittest.TestCase):
    def test_home_vira_modo_casa(self):
        self.assertEqual(esc.modo(esc.HOME), esc.CASA)

    def test_raiz_fica_casa(self):
        self.assertEqual(esc.modo(Path("/")), esc.CASA)

    def test_qualquer_pasta_vira_projeto(self):
        self.assertEqual(esc.modo(Path("/opt/coisa")), esc.PROJETO)

    def test_forcar_vence_o_padrao(self):
        self.assertEqual(esc.modo(esc.HOME, esc.TODOS), esc.TODOS)


class TestSeletor(unittest.TestCase):
    def test_casa_aceita_subpasta_do_home(self):
        sel = esc.seletor(esc.HOME, esc.CASA)
        self.assertTrue(sel(reg(f"{HOME}/projetos/x")))

    def test_casa_aceita_o_proprio_home(self):
        self.assertTrue(esc.seletor(esc.HOME, esc.CASA)(reg(HOME)))

    def test_casa_recusa_fora_do_home(self):
        self.assertFalse(esc.seletor(esc.HOME, esc.CASA)(reg("/tmp/opencode")))

    def test_casa_recusa_cwd_desconhecido(self):
        self.assertFalse(esc.seletor(esc.HOME, esc.CASA)(reg(None)))

    def test_casa_recusa_prefixo_parecido(self):
        """`/home/thiago2` não pode entrar no escopo de `/home/thiago`."""
        self.assertFalse(esc.seletor(esc.HOME, esc.CASA)(reg(f"{HOME}2/x")))

    def test_all_aceita_tudo(self):
        sel = esc.seletor(esc.HOME, esc.TODOS)
        self.assertTrue(sel(reg(None)))
        self.assertTrue(sel(reg("/tmp")))

    def test_projeto_aceita_raiz_e_descendente(self):
        alvo = f"{HOME}/repo"
        sel = esc.seletor(Path(alvo), esc.PROJETO)
        self.assertTrue(sel(reg(alvo)))
        self.assertTrue(sel(reg(f"{alvo}/sub/deep")))

    def test_projeto_recusa_irmao_e_ascendente(self):
        alvo = f"{HOME}/repo"
        sel = esc.seletor(Path(alvo), esc.PROJETO)
        self.assertFalse(sel(reg(f"{HOME}/repo-outra")))
        self.assertFalse(sel(reg(HOME)))

    def test_arvore_comporta_como_projeto(self):
        alvo = f"{HOME}/repo"
        sel = esc.seletor(Path(alvo), esc.ARVORE)
        self.assertTrue(sel(reg(f"{alvo}/x")))
        self.assertFalse(sel(reg("/tmp")))

    def test_exato_remove_descendentes(self):
        alvo = Path(f"{HOME}/repo")
        dentro = [reg(str(alvo)), reg(f"{alvo}/sub"), reg(HOME)]
        fora = esc.aplicar(dentro, alvo, esc.PROJETO, exato=True)
        self.assertEqual([r.cwd for r in fora], [str(alvo)])


class TestRegistro(unittest.TestCase):
    def test_key_e_cli_dois_pontos_id(self):
        self.assertEqual(reg(HOME, "opencode", "ses_abc").key, "opencode:ses_abc")

    def test_as_dict_carrega_a_key(self):
        self.assertEqual(reg(HOME).as_dict()["key"], "codex:x")

    def test_dedupe_devin_marcado_quando_importado(self):
        """O importador gerou `ses_devin<hash>` — a identidade é (título, dir)."""
        op = Registro(id="ses_devin1a2b3c", cli="opencode",
                      title="Auditar 3 repos", cwd=f"{HOME}/x")
        igual = Registro(id="modern-jacket", cli="devin",
                         title="Auditar 3 repos", cwd=f"{HOME}/x")
        dir_divergente = Registro(id="outro", cli="devin",
                                  title="Auditar 3 repos", cwd=f"{HOME}/y")
        titulo_outro = Registro(id="terceiro", cli="devin",
                                title="outro título", cwd=f"{HOME}/x")
        registros = [op, igual, dir_divergente, titulo_outro]

        _marca_importadas(registros)

        self.assertEqual(igual.imported_in_opencode, "ses_devin1a2b3c")
        # sem o par exato, cai no título puro
        self.assertEqual(dir_divergente.imported_in_opencode, "ses_devin1a2b3c")
        self.assertIsNone(titulo_outro.imported_in_opencode)
        # registro do próprio opencode não é tocado
        self.assertIsNone(op.imported_in_opencode)


class TestRender(unittest.TestCase):
    def test_linha_tem_cinco_campos_e_key_no_fim(self):
        campos = render.linha(reg(HOME, "codex", "abc"), ligado=False).split("\t")
        self.assertEqual(len(campos), 5)
        self.assertEqual(campos[-1], "codex:abc")

    def test_linha_aceita_ansi_sem_quebrar_campos(self):
        campos = render.linha(reg(HOME, "codex", "abc"), ligado=True).split("\t")
        self.assertEqual(len(campos), 5)
        self.assertEqual(campos[-1], "codex:abc")

    def test_pasta_encurta_o_home(self):
        self.assertEqual(render.pasta(f"{HOME}/x"), "~/x")
        self.assertEqual(render.pasta(HOME), "~")
        self.assertEqual(render.pasta(None), "?")
        self.assertEqual(render.pasta("/opt/x"), "/opt/x")

    def test_cortar_respeita_o_limite(self):
        self.assertTrue(len(render.cortar("x" * 100, 10)) <= 10)

    def test_ordenar_e_por_recencia(self):
        regs = [reg(HOME, quando=5), reg(HOME, quando=9), reg(HOME, quando=1)]
        self.assertEqual([r.updated_at for r in render.ordenar(regs)], [9, 5, 1])

    def test_agrupar_ordina_pasta_pela_mais_recente(self):
        regs = [
            reg(f"{HOME}/velho", quando=1),
            reg(f"{HOME}/novo", quando=10),
            reg(f"{HOME}/novo", quando=3),
        ]
        grupos = dict(render.agrupar(regs))
        self.assertEqual(list(grupos), ["~/novo", "~/velho"])
        self.assertEqual([r.updated_at for r in grupos["~/novo"]], [10, 3])

    def test_json_e_tsv_sao_parseaveis(self):
        import json

        registros = [reg(HOME, quando=7)]
        self.assertEqual(json.loads(render.como_json(registros))[0]["key"], "codex:x")
        self.assertEqual(render.como_tsv(registros).splitlines()[1].split("\t")[0], "codex:x")


class TestPlanoNative(unittest.TestCase):
    def test_argv_do_codex_e_cwd_da_conversa(self):
        r = Registro(id="abc", cli="codex", title="t", cwd="/tmp",
                     native_resume=["codex", "resume", "abc"])
        self.assertEqual(plano_native(r), (["codex", "resume", "abc"], "/tmp"))

    def test_cwd_inexistente_cai_na_home(self):
        r = Registro(id="abc", cli="codex", title="t", cwd="/nao/existe/xyz",
                     native_resume=["codex", "resume", "abc"])
        _, cwd = plano_native(r)
        self.assertEqual(cwd, HOME)


class TestDesde(unittest.TestCase):
    def test_dias_horas_e_semanas(self):
        """corte mais apertado (1h) é mais recente que 1d, que é mais que 1w."""
        self.assertGreater(_desde("1h"), _desde("1d"))
        self.assertGreater(_desde("1d"), _desde("1w"))

    def test_hoje_e_ano_mes(self):
        self.assertIsInstance(_desde("hoje"), int)
        self.assertLess(_desde("2026-09"), _desde("hoje"))

    def test_invalido_sai_com_erro(self):
        with self.assertRaises(SystemExit):
            _desde("qualquercoisa")


if __name__ == "__main__":
    unittest.main()
