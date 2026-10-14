"""Payload do import: formato conferido num export real + ledger de idempotência."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chats_lib import import_opencode as io  # noqa: E402
from chats_lib.models import Mensagem, Registro  # noqa: E402

HOME = str(Path.home())


def conversa():
    reg = Registro(id="conv-1", cli="freebuff", title="Título da conversa",
                   cwd=f"{HOME}/projetos/x", created_at=1000, updated_at=2000)
    mensagens = [
        Mensagem(role="user", text="oi, tudo bem?", time=1000),
        Mensagem(role="assistant", text="tudo ótimo", time=1100),
    ]
    return reg, mensagens


class TestPayload(unittest.TestCase):
    def test_estrutura_exigida_pelo_endpoint(self):
        reg, msgs = conversa()
        p = io.monta_payload(reg, msgs, f"{HOME}/projetos/x", "proj_abc")

        self.assertEqual(p["info"]["projectID"], "proj_abc")
        self.assertEqual(p["location"], {"directory": f"{HOME}/projetos/x"})
        self.assertEqual(p["info"]["location"], {"directory": f"{HOME}/projetos/x"})
        self.assertTrue(p["info"]["id"].startswith("ses_"))
        self.assertEqual(p["info"]["title"], "Título da conversa")
        self.assertEqual(p["info"]["time"], {"created": 1000, "updated": 2000})

    def test_projecao_das_mensagens(self):
        reg, msgs = conversa()
        p = io.monta_payload(reg, msgs, f"{HOME}/projetos/x", "proj_abc")
        user, bot = p["messages"]

        self.assertEqual(user["type"], "user")
        self.assertEqual(user["text"], "oi, tudo bem?")
        self.assertEqual(user["time"]["created"], 1000)

        self.assertEqual(bot["type"], "assistant")
        self.assertEqual(bot["content"], [{"type": "text", "text": "tudo ótimo"}])
        self.assertIn("tokens", bot)
        self.assertIn("model", bot)

    def test_ids_sao_unicos(self):
        reg, msgs = conversa()
        p = io.monta_payload(reg, msgs * 20, f"{HOME}/x", "proj")
        ids = [m["id"] for m in p["messages"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotEqual(p["info"]["id"], ids[0])

    def test_titulo_truncado(self):
        reg, msgs = conversa()
        reg.title = "x" * 900
        p = io.monta_payload(reg, msgs, f"{HOME}/x", "proj")
        self.assertEqual(len(p["info"]["title"]), io.MAX_TITULO)

    def test_subpath_relativo_ao_home(self):
        self.assertEqual(io._subpath(f"{HOME}/a/b"), "a/b")
        self.assertEqual(io._subpath("/opt/coisa"), "/opt/coisa")


class TestLedger(unittest.TestCase):
    def setUp(self):
        self._original = io.LEDGER
        self.pasta = tempfile.TemporaryDirectory()
        io.LEDGER = Path(self.pasta.name) / "imports.json"

    def tearDown(self):
        io.LEDGER = self._original
        self.pasta.cleanup()

    def test_roundtrip(self):
        io._gravar_ledger("freebuff:pasta/1", "ses_abc")
        io._gravar_ledger("codex:xyz", "ses_def")
        self.assertEqual(io._ler_ledger(),
                         {"freebuff:pasta/1": "ses_abc", "codex:xyz": "ses_def"})

    def test_ledger_corrompido_nao_derruba(self):
        io.LEDGER.write_text("{sem json", encoding="utf-8")
        self.assertEqual(io._ler_ledger(), {})

    def test_diretorio_criado_na_primeira_escrita(self):
        io.LEDGER = Path(self.pasta.name) / "sub" / "dir" / "imports.json"
        self.assertFalse(io.LEDGER.parent.exists())
        io._gravar_ledger("k", "ses_1")
        self.assertTrue(io.LEDGER.exists())

    def test_ja_importada_respeita_o_marcador_do_dedupe(self):
        reg = Registro(id="modern-jacket", cli="devin", title="t", cwd=HOME,
                       imported_in_opencode="ses_devinXXX")
        self.assertEqual(io.ja_importada(reg), "ses_devinXXX")


if __name__ == "__main__":
    unittest.main()
