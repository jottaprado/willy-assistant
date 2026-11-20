"""
Teleprompter: destroy() existe, e o arraste segue o ponteiro na tela.

- O willy.py chamava teleprompter.destroy() ao sair e o método não existia: o AttributeError
  era engolido (a janela fechava junto com a raiz, logo depois).
- O arraste somava o event.x (relativo ao widget, que anda com a janela) ao winfo_x (que
  ainda não tem a posição do último geometry() numa rajada de movimentos): ia aos saltos.
"""

import time
import unittest
from types import SimpleNamespace

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.overlays.teleprompter import LiveTeleprompter


class TestTeleprompter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        fim = time.time() + 0.3  # os afters do CTkToplevel rodam com a raiz viva
        while time.time() < fim:
            cls.root.update()
            time.sleep(0.01)
        destruir_tk(cls.root)

    def setUp(self):
        self.tp = LiveTeleprompter(self.root)
        self.addCleanup(self.tp.destroy)
        self.tp.mostrar()
        self.tp.window.geometry("540x220+300+400")
        self.tp.window.update()

    def _posicao(self):
        _, x, y = self.tp.window.geometry().split("+")
        return int(x), int(y)

    def test_destroy_fecha_a_janela(self):
        janela = self.tp.window
        self.tp.destroy()
        self.assertFalse(janela.winfo_exists())
        self.assertIsNone(self.tp.window)
        self.assertFalse(self.tp.is_visible)

    def test_destroy_duas_vezes_nao_quebra(self):
        self.tp.destroy()
        self.tp.destroy()

    def test_mostrar_depois_do_destroy_abre_de_novo(self):
        self.tp.destroy()
        self.tp.mostrar()
        self.assertTrue(self.tp.window.winfo_exists())

    def test_arraste_segue_o_ponteiro_numa_rajada(self):
        # Pegou o cabeçalho 10 px à direita e 5 abaixo do canto. Dois movimentos sem a janela
        # ter sido redesenhada entre eles; o x/y relativo do widget não vale nada aqui.
        def ev(x_root, y_root):
            return SimpleNamespace(x_root=x_root, y_root=y_root, x=0, y=0)

        self.tp._start_drag(ev(310, 405))
        self.tp._on_drag(ev(410, 455))
        self.tp._on_drag(ev(510, 505))
        self.tp.window.update_idletasks()
        self.assertEqual((500, 500), self._posicao())

    def test_arraste_para_o_monitor_da_esquerda(self):
        def ev(x_root, y_root):
            return SimpleNamespace(x_root=x_root, y_root=y_root, x=0, y=0)

        self.tp._start_drag(ev(310, 405))
        self.tp._on_drag(ev(-1000, 405))
        self.tp.window.update_idletasks()
        self.assertEqual((-1010, 400), self._posicao())

    def test_adicionar_legenda_insere_texto_no_widget(self):
        self.tp.adicionar_legenda("Olá equipe, reunião às dez", prefixo="Ditado")
        self.tp.window.update()
        conteudo = self.tp.txt_captions.get("1.0", "end")
        self.assertIn("Ditado", conteudo)
        self.assertIn("Olá equipe, reunião às dez", conteudo)


if __name__ == "__main__":
    unittest.main()
