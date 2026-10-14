"""Contrato de cada adapter com os dados reais da máquina + isolamento de erro."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chats_lib import registry  # noqa: E402
from chats_lib.adapters import agy, codex, devin, freebuff, gemini, opencode  # noqa: E402

TODOS = [opencode, codex, agy, devin, freebuff, gemini]


class TestContrato(unittest.TestCase):
    def test_cada_adapter_lista_e_expor_como_retomar(self):
        for ad in TODOS:
            with self.subTest(cli=ad.CLI):
                registros = ad.scan()
                self.assertGreater(len(registros), 0, f"{ad.CLI} sem conversas")
                reg = registros[0]
                self.assertEqual(reg.cli, ad.CLI)
                self.assertTrue(reg.key.startswith(ad.CLI + ":"))
                self.assertTrue(reg.title)
                # sem comando de retomada, precisa haver um aviso (gemini inativo)
                self.assertTrue(reg.native_resume or reg.meta.get("aviso"))
                self.assertFalse(
                    any("\t" in r.title or "\n" in r.title for r in registros),
                    f"{ad.CLI} com título multiline/táb quebraria a linha do fzf",
                )

    def test_key_e_estavel_entre_execucoes(self):
        for ad in TODOS:
            with self.subTest(cli=ad.CLI):
                primeira = {r.key for r in ad.scan()}
                segunda = {r.key for r in ad.scan()}
                self.assertEqual(primeira, segunda)

    def test_todos_tem_fonte_declarada(self):
        for ad in TODOS:
            with self.subTest(cli=ad.CLI):
                self.assertTrue(getattr(ad, "FONTES", None), f"{ad.CLI} sem FONTES")


class TestConteudo(unittest.TestCase):
    def test_le_mensagem_de_quem_tem_conteudo(self):
        for ad in (opencode, codex, devin, freebuff, gemini):
            with self.subTest(cli=ad.CLI):
                lidos = [ad.carregar(r) for r in ad.scan()[:8]]
                lidos = [m for m in lidos if m]
                self.assertTrue(lidos, f"{ad.CLI} não leu nada em 8 tentativas")
                # `system` pode vir primeiro (contexto injetado); exige fala real
                self.assertTrue(
                    any(m.role in ("user", "assistant") for msgs in lidos for m in msgs),
                    f"{ad.CLI} só devolveu system",
                )
                self.assertTrue(lidos[0][0].text.strip())

    def test_agy_devolve_vazio_e_usa_o_preview_da_linha(self):
        """protobuf sem schema: o fallback da prévia é a coluna `preview`."""
        regs = agy.scan()
        self.assertEqual(agy.carregar(regs[0]), [])
        self.assertTrue(regs[0].preview)


class TestIsolamento(unittest.TestCase):
    def test_fonte_sumida_vira_erro_e_nao_derruba_a_cli(self):
        original = opencode.DB
        try:
            opencode.DB = Path("/nao/existe/banco.db")
            registros, erros = registry.scan()
        finally:
            opencode.DB = original

        self.assertTrue(any(cli == "opencode" for cli, _ in erros), erros)
        # os outros cinco continuam de pé
        self.assertGreater(len(registros), 500)
        self.assertIn("FileNotFoundError", erros[0][1])

    def test_dedupe_devin_real_bate_com_o_opencode(self):
        registros, _ = registry.scan()
        devins = [r for r in registros if r.cli == "devin"]
        marcados = [r for r in devins if r.imported_in_opencode]
        self.assertEqual(len(devins), 39)
        self.assertGreaterEqual(len(marcados), 30, "dedupe (título, dir) regrediu")
        for r in marcados:
            self.assertTrue(r.imported_in_opencode.startswith("ses_devin"))


if __name__ == "__main__":
    unittest.main()
