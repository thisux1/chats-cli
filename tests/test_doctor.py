"""`chats doctor`: compatibilidade do fzf com o picker (e a saída geral)."""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chats_lib import doctor, registry  # noqa: E402


class TestStatusFzf(unittest.TestCase):
    def _status(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            codigo = doctor.status_fzf()
        return codigo, buf.getvalue()

    @unittest.skipUnless(shutil.which("fzf"), "fzf ausente")
    def test_fzf_da_maquina_passa_na_validacao(self):
        codigo, saida = self._status()
        self.assertEqual(codigo, 0, saida)
        self.assertIn("✓", saida)

    def test_fzf_ausente_e_so_aviso(self):
        with mock.patch.object(doctor.shutil, "which", return_value=None):
            codigo, saida = self._status()
        self.assertEqual(codigo, 0)
        self.assertIn("ausente", saida)

    def test_opcao_incompativel_vira_falha(self):
        falso = mock.Mock(returncode=2, stderr="unknown option: --qualquer\n")
        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/fzf"), \
                mock.patch.object(doctor.subprocess, "run", return_value=falso):
            codigo, saida = self._status()
        self.assertEqual(codigo, 1)
        self.assertIn("unknown option", saida)
        self.assertIn("lista numerada", saida)


class TestRodar(unittest.TestCase):
    def test_doctor_completo_sai_limpo(self):
        # saída limpa pressupõe todas as fontes saudáveis nesta máquina
        _, erros = registry.scan()
        if erros:
            self.skipTest(f"fonte(s) indisponíveis: {erros}")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            codigo = doctor.rodar(ligado=False)
        saida = buf.getvalue()
        self.assertEqual(codigo, 0, saida)
        self.assertIn("fzf", saida)
        self.assertIn("índice", saida)
        self.assertIn("≡", saida)


if __name__ == "__main__":
    unittest.main()
