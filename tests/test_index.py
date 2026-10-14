"""Fase 4: índice incremental, `sync` e dedupe fino (pasta + 1ª frase + dia).

Todo teste aqui roda com o índice apontado pra um diretório temporário —
nunca escreve no `~/.local/share/chats/index.db` real.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chats_lib import cli, registry, store
from chats_lib.adapters import devin, gemini
from chats_lib.models import Registro

FRASE_LONGA = "revisa o arquivo de arquitetura e diz o que mudar depois disso"


class BaseIndexada(unittest.TestCase):
    """Aponta `store` pra um diretório temporário e restaura no fim."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(store, "DIR", raiz),
            mock.patch.object(store, "DB", raiz / "index.db"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)


class TestRoundtrip(BaseIndexada):
    def test_salvar_e_ler_preserva_os_campos(self):
        origem = Registro(
            id="abc",
            cli="codex",
            title="Título com acento",
            cwd="/home/u/proj",
            created_at=1_700_000_000_000,
            updated_at=1_700_000_100_000,
            preview=FRASE_LONGA,
            n_msgs=12,
            native_resume=["codex", "--resume", "abc"],
            source_path="/x.jsonl",
            meta={"agent": "build", "n": 3},
        )
        store.salvar("codex", "v1:1:2", [origem])

        self.assertEqual(store.fingerprint("codex"), "v1:1:2")
        volta = store.ler("codex")
        self.assertIsNotNone(volta)
        self.assertEqual(len(volta), 1)
        r = volta[0]
        self.assertEqual(r.key, "codex:abc")
        self.assertEqual(r.title, origem.title)
        self.assertEqual(r.preview, FRASE_LONGA)
        self.assertEqual(r.native_resume, origem.native_resume)
        self.assertEqual(r.meta, origem.meta)
        self.assertEqual(r.created_at, origem.created_at)
        self.assertFalse(r.duplicada)  # marca de dedupe nunca é persistida

    def test_fonte_vazia_guarda_como_vazia(self):
        store.salvar("gemini", "v1:0:0", [])
        self.assertEqual(store.ler("gemini"), [])
        self.assertEqual(store.fingerprint("gemini"), "v1:0:0")

    def test_fonte_nunca_indexada_e_none(self):
        self.assertIsNone(store.fingerprint("codex"))
        self.assertIsNone(store.ler("codex"))

    def test_linha_corrompida_devolve_none_e_nao_dado_pela_metade(self):
        store.salvar("codex", "v1:1:1", [
            Registro(id="a", cli="codex", title="ok", meta={"x": 1})
        ])
        con = sqlite3.connect(store.DB)
        try:
            con.execute("UPDATE registro SET meta='{}{invalido' WHERE id='a'")
            con.commit()
        finally:
            con.close()
        self.assertIsNone(store.ler("codex"))


class TestInvalidacao(BaseIndexada):
    def test_fingerprint_correta_usa_o_indice_sem_escanear(self):
        registros = gemini.scan()
        store.salvar("gemini", gemini.fingerprint(), registros)
        with mock.patch.object(
            gemini, "scan", side_effect=AssertionError("escaneou a fonte")
        ):
            saida, erros = registry.scan({"gemini"})
        self.assertEqual(erros, [])
        self.assertEqual(len(saida), len(registros))

    def test_fingerprint_obsoleta_dispara_rescan(self):
        store.salvar("gemini", "v1:0:0", [])
        saida, erros = registry.scan({"gemini"})
        self.assertEqual(erros, [])
        self.assertGreater(len(saida), 0)
        self.assertEqual(store.fingerprint("gemini"), gemini.fingerprint())

    def test_indice_quebrado_cai_na_fonte_sem_erro(self):
        with mock.patch.object(store, "DB", Path(self.tmp.name) / "nao" / "da" / "x.db"):
            saida, erros = registry.scan({"gemini"})
        self.assertEqual(erros, [])
        self.assertGreater(len(saida), 0)

    def test_env_desliga_o_indice(self):
        with mock.patch.dict(os.environ, {"CHATS_SEM_INDICE": "1"}), \
                mock.patch.object(
                    store, "salvar", side_effect=AssertionError("gravou o índice")
                ):
            saida, erros = registry.scan({"gemini"})
        self.assertEqual(erros, [])
        self.assertGreater(len(saida), 0)
        self.assertIsNone(store.fingerprint("gemini"))

    def test_forcar_ignora_o_indice_na_leitura(self):
        registros = gemini.scan()
        store.salvar("gemini", gemini.fingerprint(), registros)
        with mock.patch.object(
            gemini, "scan", side_effect=AssertionError("escaneou a fonte")
        ):
            saida, _ = registry.scan({"gemini"})
        self.assertEqual(len(saida), len(registros))

        with mock.patch.object(gemini, "scan", wraps=gemini.scan) as espião:
            saida, _ = registry.scan({"gemini"}, forcar=True)
        espião.assert_called_once()
        self.assertEqual(len(saida), len(registros))

    def test_todos_os_adapters_tem_fingerprint_barata(self):
        from chats_lib.registry import ADAPTERS

        for ad in ADAPTERS:
            with self.subTest(cli=ad.CLI):
                self.assertTrue(callable(ad.fingerprint))
                fp = ad.fingerprint()
                self.assertIsInstance(fp, str)
                self.assertTrue(fp.startswith("v1:"), fp)


class TestPrimeiraFrase(unittest.TestCase):
    def test_corta_na_pontuacao_e_normaliza(self):
        chave = registry.primeira_frase(
            "Olá, revisa o arquivo de arquitetura e diz o que mudar depois disso!"
            " Depois me avisa"
        )
        self.assertEqual(chave, "olá revisa o arquivo de arquitetura e diz o que mudar depois disso")
        self.assertNotIn("depois me avisa", chave)

    def test_ponto_de_arquivo_nao_encerra_a_frase(self):
        chave = registry.primeira_frase(
            "revisa o ADR.md e diz o que precisa mudar nele por favor"
        )
        self.assertTrue(chave.startswith("revisa o adr md"), chave)
        self.assertGreaterEqual(len(chave), 30)

    def test_frase_curta_nao_vira_chave(self):
        self.assertEqual(registry.primeira_frase("oi, tudo bem?"), "")
        self.assertEqual(registry.primeira_frase(""), "")
        self.assertEqual(registry.primeira_frase(None), "")

    def test_colapsa_quebras_de_linha(self):
        chave = registry.primeira_frase("primeira\nlinha   com     espaços extras")
        self.assertEqual(chave, "primeira linha com espaços extras")


class TestDedupeFino(unittest.TestCase):
    def _reg(self, **kw) -> Registro:
        base = dict(id="x", cli="codex", title="t", cwd="/p",
                    created_at=1_700_000_000_000, preview=FRASE_LONGA)
        base.update(kw)
        return Registro(**base)

    def test_marcas_quando_cruza_clis(self):
        registros = [
            self._reg(id="1", cli="codex"),
            self._reg(id="2", cli="freebuff"),
        ]
        self.assertEqual(registry._marca_duplicadas(registros), 2)
        self.assertTrue(all(r.duplicada for r in registros))

    def test_nao_marca_repeticao_dentro_do_mesmo_cli(self):
        registros = [self._reg(id="1"), self._reg(id="2")]
        self.assertEqual(registry._marca_duplicadas(registros), 0)
        self.assertFalse(any(r.duplicada for r in registros))

    def test_dia_diferente_ou_diretorio_diferente_nao_emparella(self):
        registros = [
            self._reg(id="1", cli="codex"),
            self._reg(id="2", cli="freebuff", created_at=1_700_086_400_000),
            self._reg(id="3", cli="freebuff", cwd="/outro"),
        ]
        self.assertEqual(registry._marca_duplicadas(registros), 0)

    def test_abertura_curta_nao_emparella(self):
        registros = [
            self._reg(id="1", cli="codex"),
            self._reg(id="2", cli="freebuff", preview="oi"),
        ]
        self.assertEqual(registry._marca_duplicadas(registros), 0)

    def test_sem_cwd_nao_emparella(self):
        registros = [
            self._reg(id="1", cli="codex", cwd=None),
            self._reg(id="2", cli="freebuff"),
        ]
        self.assertEqual(registry._marca_duplicadas(registros), 0)

    def test_scan_real_nao_inventa_duplicatas(self):
        """O critério é forte o bastante pra não marcar conversas distintas."""
        registros, erros = registry.scan()
        self.assertEqual(erros, [])
        marcadas = registry.contar_duplicadas(registros)
        self.assertGreater(marcadas, 0)
        grupos = {}
        for r in registros:
            chave = registry._chave_duplicata(r)
            if chave and r.duplicada:
                grupos.setdefault(chave, []).append(r)
        for chave, grupo in grupos.items():
            self.assertGreaterEqual(len({r.cli for r in grupo}), 2, chave)
            # toda marca real desta máquina é devin ↔ opencode importado
            self.assertTrue(
                {r.cli for r in grupo} <= {"devin", "opencode"}, chave
            )


class TestDevin(BaseIndexada):
    @unittest.skipUnless(devin.DB.exists(), "banco do devin ausente")
    def test_preview_vem_da_primeira_fala_do_usuario(self):
        registros = devin.scan()
        self.assertTrue(registros)
        com_preview = [r for r in registros if r.preview]
        self.assertGreaterEqual(len(com_preview), len(registros) - 1)
        self.assertTrue(all(len(r.preview) <= 200 for r in com_preview))


class TestSync(BaseIndexada):
    def test_sync_de_uma_fonte_escreve_o_indice(self):
        captura = {}
        with mock.patch("sys.stdout", _Captura(captura)):
            codigo = cli.main(["sync", "--cli", "gemini", "--no-color"])
        self.assertEqual(codigo, 0)
        saida = captura["texto"]
        self.assertIn("gemini", saida)
        self.assertIn("índice", saida)
        self.assertEqual(store.fingerprint("gemini"), gemini.fingerprint())
        self.assertGreater(len(store.ler("gemini") or []), 0)

    def test_sync_sem_indice_desta_fonte_fica_sem_mudar(self):
        registros = gemini.scan()
        store.salvar("gemini", gemini.fingerprint(), registros)
        with mock.patch.object(
            gemini, "scan", side_effect=AssertionError("escaneou a fonte")
        ), mock.patch("sys.stdout", _Captura({})):
            codigo = cli.main(["sync", "--cli", "gemini", "--no-color"])
        self.assertEqual(codigo, 0)

    def test_fonte_quebrada_no_sync_devolve_falha(self):
        with mock.patch.object(
            gemini, "fingerprint", side_effect=FileNotFoundError("banco sumiu")
        ), mock.patch("sys.stdout", _Captura({})):
            codigo = cli.main(["sync", "--cli", "gemini", "--no-color"])
        self.assertEqual(codigo, 1)

    def test_lista_com_indice_publica_o_campo_duplicada(self):
        captura = {}
        with mock.patch("sys.stdout", _Captura(captura)):
            codigo = cli.main(["--all", "--format", "json", "--no-pick"])
        dados = json.loads(captura["texto"])
        self.assertIn(codigo, (0, cli.SEM_KEY))
        self.assertTrue(dados)
        for linha in dados:
            self.assertIn("duplicada", linha)
            self.assertIsInstance(linha["duplicada"], bool)


class _Captura:
    """stdout falso que também finge ser TTY (o `--format` exige escrita)."""

    def __init__(self, dicionario: dict):
        self.dicionario = dicionario
        self.pedacos: list[str] = []

    def write(self, texto: str) -> int:
        self.pedacos.append(texto)
        self.dicionario["texto"] = "".join(self.pedacos)
        return len(texto)

    def flush(self) -> None:
        self.dicionario["texto"] = "".join(self.pedacos)

    def isatty(self) -> bool:
        return False


if __name__ == "__main__":
    unittest.main()
