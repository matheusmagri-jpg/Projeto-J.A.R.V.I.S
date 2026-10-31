import os
import unittest
from unittest import mock

from nexo import ferramentas
from nexo.ferramentas import tela
from nexo.interface import tecla


class TestAtalhoGlobal(unittest.TestCase):
    def test_interpretar(self):
        self.assertEqual(tecla.interpretar("ctrl+alt+j"), (0x2 | 0x1 | tecla.SEM_REPETIR, ord("J")))
        self.assertEqual(tecla.interpretar("Win + Shift + F9")[1], 0x78)
        for ruim in ("j", "ctrl+alt", "ctrl+çç"):
            with self.assertRaises(ValueError):
                tecla.interpretar(ruim)
        self.assertEqual(tecla.legivel("ctrl+alt+j"), "Ctrl+Alt+J")


@unittest.skipUnless(os.name == "nt", "agir na tela só existe no Windows")
class TestAgirNaTela(unittest.TestCase):
    """Nada aqui chega ao teclado ou ao mouse de verdade: o SendInput e a janela são simulados."""

    def setUp(self):
        self.enviado = []
        for alvo, valor in (("_enviar", lambda *e: self.enviado.extend(e)), ("_sair_da_frente", lambda: None),
                            ("_janela_em_uso", lambda: "Bloco de Notas"), ("_clique", lambda **k: self.enviado.append("clique"))):
            p = mock.patch.object(tela, alvo, side_effect=valor)
            p.start()
            self.addCleanup(p.stop)

    def test_todas_pedem_confirmacao(self):
        todas = ferramentas.carregar()
        for nome in ("clicar_na_tela", "digitar_texto", "apertar_teclas"):
            self.assertTrue(todas[nome].confirmar, nome)

    def test_teclas(self):
        self.assertEqual(tela.interpretar_teclas("ctrl+shift+t"), [0x11, 0x10, ord("T")])
        self.assertEqual(tela.interpretar_teclas("f5"), [0x74])
        self.assertIn("Apertei ctrl+s em 'Bloco de Notas'", tela.apertar_teclas("ctrl+s"))
        self.assertEqual(len(self.enviado), 4)   # ctrl e s descem, depois sobem
        self.assertIn("desconhecida", tela.apertar_teclas("ctrl+banana"))

    def test_digitar_acentos(self):
        self.assertIn("em 'Bloco de Notas'", tela.digitar_texto("Ação ✓", enter=True))
        unicode = [e.u.ki.wScan for e in self.enviado if e.u.ki.dwFlags & 0x0004 and not e.u.ki.dwFlags & 0x0002]
        self.assertEqual("".join(map(chr, unicode)), "Ação ✓")

    def test_nao_age_no_proprio_painel(self):
        with mock.patch.object(tela, "_janela_em_uso", return_value=None):
            self.assertIn("não digitei", tela.digitar_texto("oi"))
            self.assertIn("não apertei", tela.apertar_teclas("enter"))
        self.assertEqual(self.enviado, [])

    def test_clicar(self):
        with mock.patch.object(tela, "localizar", return_value=None):
            self.assertIn("Nada foi clicado", tela.clicar_na_tela("botão roxo"))
        self.assertEqual(self.enviado, [])
        with mock.patch.object(tela, "localizar", return_value=(100, 200, "botão Salvar")), \
                mock.patch("ctypes.windll.user32.SetCursorPos") as cursor:
            self.assertIn("Cliquei em botão Salvar", tela.clicar_na_tela("Salvar"))
        cursor.assert_called_once_with(100, 200)
        self.assertEqual(self.enviado, ["clique"])


class TestIconeAdministrador(unittest.TestCase):
    def test_liga_so_o_bit_de_administrador(self):
        import tempfile
        from pathlib import Path
        from nexo import inicializacao
        with tempfile.TemporaryDirectory() as pasta:
            lnk = Path(pasta) / "x.lnk"
            original = bytes(range(0x30))
            lnk.write_bytes(original)
            inicializacao.marcar_como_administrador(lnk)
            novo = lnk.read_bytes()
        self.assertEqual(novo[0x15], original[0x15] | 0x20)
        self.assertEqual(novo[:0x15] + novo[0x16:], original[:0x15] + original[0x16:])


if __name__ == "__main__":
    unittest.main()
