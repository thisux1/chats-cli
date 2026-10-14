"""Picker: comando do fzf, fallback numerado e sobrevivência a fzf quebrado."""
import contextlib
import io
import shutil
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chats_lib import picker, render  # noqa: E402
from chats_lib.models import Registro  # noqa: E402

HOME = str(Path.home())
CHATS = "/home/thiago/Documentos/codesnippets/chats-cli/chats"


class _StdinFalso:
    """stdin que finge ser TTY — o fzf só entra com TTY."""

    def isatty(self) -> bool:
        return True


def lista(n=3):
    return [
        Registro(id=f"conv{i}", cli="codex", title=f"Conversa {i}",
                 cwd=f"{HOME}/pasta{i}", updated_at=1000 + i)
        for i in range(n)
    ]


class TestComandoFzf(unittest.TestCase):
    def test_argumentos_basicos(self):
        cmd = picker.comando_fzf(CHATS)
        self.assertEqual(cmd[0], "fzf")
        self.assertIn("--ansi", cmd)          # cores na linha
        self.assertIn("--delimiter=\t", cmd)  # campos separados por tab
        self.assertIn("--with-nth=1,2,3,4", cmd)  # esconde a key
        self.assertIn("--cycle", cmd)

    def test_nao_usa_opcao_que_o_fzf_daqui_nao_tem(self):
        # `--header-lines-position` não existe no fzf 0.74.3: derrubava
        # o fzf (rc=2) e o EPIPE em seguida matava a CLI com rc 141
        self.assertNotIn("--header-lines-position", picker.comando_fzf(CHATS))
        self.assertIn("--header-first", picker.comando_fzf(CHATS))

    @unittest.skipUnless(shutil.which("fzf"), "fzf ausente")
    def test_opcoes_passam_na_validacao_do_fzf_instalado(self):
        """Toda opção precisa existir no fzf desta máquina.

        `--filter` faz o fzf validar o argv sem precisar de TTY e sem
        desenhar nada. rc=1 aqui seria "sem match", não opção inválida,
        por isso o filtro casa com a linha.
        """
        cmd = picker.comando_fzf(CHATS) + ["--filter=a"]
        proc = subprocess.run(
            cmd, input="a\tb\tc\td\te\n", text=True, capture_output=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_preview_aponta_pra_o_chats_e_usa_o_quinto_campo(self):
        cmd = picker.comando_fzf(CHATS)
        i = cmd.index("--preview")
        self.assertEqual(cmd[i + 1], f"{CHATS} preview '{{5}}'")
        # a key é o 5º campo da linha
        campos = render.linha(lista()[0], ligado=False).split("\t")
        self.assertEqual(len(campos), 5)
        self.assertEqual(campos[-1], "codex:conv0")


class TestFallbackNumerado(unittest.TestCase):
    def _com_stdin(self, texto: str, registros):
        original = sys.stdin
        sys.stdin = io.StringIO(texto)
        try:
            return picker._numerado(registros, ligado=False)
        finally:
            sys.stdin = original

    def test_escolhe_pelo_numero(self):
        self.assertEqual(self._com_stdin("2\n", lista()), ["codex:conv1"])

    def test_aceita_lista_separada_por_virgula(self):
        self.assertEqual(self._com_stdin("1, 3\n", lista()),
                         ["codex:conv0", "codex:conv2"])

    def test_enter_vazio_sai(self):
        self.assertIsNone(self._com_stdin("\n", lista()))

    def test_numero_fora_da_faixa_sai(self):
        self.assertIsNone(self._com_stdin("99\n", lista()))

    def test_leitura_interrompida_sai(self):
        self.assertIsNone(self._com_stdin("", lista()))  # EOF


class TestEscolher(unittest.TestCase):
    def test_lista_vazia_nao_abre_nada(self):
        self.assertIsNone(picker.escolher([], CHATS))


class TestEscolherComFzf(unittest.TestCase):
    """O caminho do fzf precisa sobreviver a um fzf quebrado.

    Regressão: com `capture_output=True` o erro do fzf ficava invisível e
    o EPIPE de um fzf que morreu cedo matava a CLI com rc 141, sem
    listar nada (relato "not working" de 2026-10-06).
    """

    def _roda(self, retorno, numerado=None):
        """Roda `escolher` com fzf disponível e TTY falso."""
        rodou = mock.MagicMock()
        rodou.return_value = retorno
        saida = io.StringIO()
        with mock.patch.object(picker.shutil, "which", return_value="/usr/bin/fzf"), \
                mock.patch.object(picker.sys, "stdin", _StdinFalso()), \
                mock.patch.object(picker.subprocess, "run", rodou), \
                mock.patch.object(picker, "_numerado",
                                  numerado or mock.Mock(return_value=["codex:conv0"])), \
                contextlib.redirect_stderr(saida) as _:
            chaves = picker.escolher(lista(), CHATS)
            numerado_chamado = picker._numerado
        return chaves, rodou, numerado_chamado, saida.getvalue()

    def test_stderr_do_fzf_vai_pro_terminal_e_sigpipe_restaurado(self):
        antes = signal.getsignal(signal.SIGPIPE)
        chaves, rodou, _, _ = self._roda(mock.Mock(returncode=1, stdout=""))

        kwargs = rodou.call_args.kwargs
        self.assertNotIn("capture_output", kwargs)  # engolia o erro do fzf
        self.assertNotIn("stderr", kwargs)          # UI/erros precisam aparecer
        self.assertIsNotNone(kwargs.get("stdout"))  # só a seleção vem por pipe
        self.assertIsNone(chaves)                   # rc=1 é o usuário saindo
        self.assertEqual(signal.getsignal(signal.SIGPIPE), antes)

    def test_fzf_morrido_cai_na_lista_numerada_e_avisa(self):
        for rc in (2, 127):  # 2 = opção desconhecida, 127 = comando ausente
            with self.subTest(rc=rc):
                chaves, _, numerado, saida = self._roda(
                    mock.Mock(returncode=rc, stdout="")
                )
                numerado.assert_called_once()
                self.assertEqual(chaves, ["codex:conv0"])
                self.assertIn(f"rc={rc}", saida)

    def test_esc_e_sem_match_sao_desistencia_do_usuario(self):
        for rc in picker.SAIDAS_DO_USUARIO:
            with self.subTest(rc=rc):
                chaves, _, numerado, saida = self._roda(
                    mock.Mock(returncode=rc, stdout="")
                )
                self.assertIsNone(chaves)
                numerado.assert_not_called()
                self.assertEqual(saida, "")

    def test_erro_de_pipe_vai_pra_lista_numerada(self):
        """SIGPIPE dentro do spawn vira OSError e não morte silenciosa."""
        rodou = mock.MagicMock(side_effect=BrokenPipeError("fzf morreu"))
        with mock.patch.object(picker.shutil, "which", return_value="/usr/bin/fzf"), \
                mock.patch.object(picker.sys, "stdin", _StdinFalso()), \
                mock.patch.object(picker.subprocess, "run", rodou), \
                mock.patch.object(picker, "_numerado",
                                  mock.Mock(return_value=["codex:conv0"])) as numerado:
            chaves = picker.escolher(lista(), CHATS)
        numerado.assert_called_once()
        self.assertEqual(chaves, ["codex:conv0"])


if __name__ == "__main__":
    unittest.main()
