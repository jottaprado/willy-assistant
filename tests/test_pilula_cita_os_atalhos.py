"""
As mensagens da pílula citam os atalhos configurados, não os padrões.

"Willy acordou! (Ctrl + Espaço)", "Willy foi dormir (Ctrl+Shift+Espaço)" e "Ctrl+Alt+S p/
parar" eram fixos: quem trocou os atalhos lia uma tecla que não faz mais nada.
"""

import ast
import os
import tkinter as tk
import unittest
from typing import ClassVar
from unittest.mock import MagicMock

from ui.overlays.pill import FloatingPill, rotulo_do_atalho

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestRotulo(unittest.TestCase):
    def test_como_no_teclado(self):
        self.assertEqual("Ctrl+Shift+Espaço", rotulo_do_atalho("ctrl+shift+space"))
        self.assertEqual("Ctrl+Alt+S", rotulo_do_atalho("ctrl+alt+s"))
        self.assertEqual("Ctrl+F9", rotulo_do_atalho("CTRL+F9"))
        self.assertEqual("Ctrl+Espaço", rotulo_do_atalho("ctrl+espaço"))
        self.assertEqual("", rotulo_do_atalho(""))


class TestMensagens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _texto(self, estado, atalhos=None):
        pill = FloatingPill(self.root, atalho_getter=None if atalhos is None else atalhos.get)
        self.addCleanup(pill.destroy)
        pill.root.deiconify = MagicMock()
        pill.show_state(estado)
        return pill.canvas.itemcget(pill.text, "text")

    CONFIGURADOS: ClassVar[dict] = {"hotkey": "ctrl+alt+d", "master_hotkey": "ctrl+alt+w", "speak_hotkey": "ctrl+alt+y"}

    def test_citam_os_atalhos_configurados(self):
        esperados = {
            "app_enabled": "Willy acordou! (Ctrl+Alt+D)",
            "app_disabled": "Willy foi dormir (Ctrl+Alt+W)",
            "sleeping_hint": "Willy dormindo! Acorde com Ctrl+Alt+W",
            "speaking": "Lendo texto selecionado... (Ctrl+Alt+Y p/ parar)",
        }
        for estado, texto in esperados.items():
            with self.subTest(estado=estado):
                self.assertEqual(texto, self._texto(estado, self.CONFIGURADOS))

    def test_sem_atalho_configurado_nao_cita_tecla_nenhuma(self):
        vazios = {"hotkey": "", "master_hotkey": "", "speak_hotkey": ""}
        esperados = {
            "app_enabled": "Willy acordou!",
            "app_disabled": "Willy foi dormir",
            "sleeping_hint": "Willy dormindo! Acorde pelo ícone da bandeja",
            "speaking": "Lendo texto selecionado...",
        }
        for estado, texto in esperados.items():
            with self.subTest(estado=estado):
                self.assertEqual(texto, self._texto(estado, vazios))

    def test_sem_config_ficam_os_padroes(self):
        self.assertEqual("Willy acordou! (Ctrl+Espaço)", self._texto("app_enabled"))
        self.assertEqual("Willy dormindo! Acorde com Ctrl+Shift+Espaço", self._texto("sleeping_hint"))


class TestWillyLigaAPilulaNaConfig(unittest.TestCase):
    def test_atalho_getter_le_o_config_mgr(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        (chamada,) = [n for n in ast.walk(arvore)
                      if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "FloatingPill"]
        getter = {k.arg: k.value for k in chamada.keywords}.get("atalho_getter")
        self.assertIsNotNone(getter, "sem atalho_getter a pílula cita os padrões")
        config_mgr = MagicMock(hotkey="ctrl+alt+d")
        resultado = eval(compile(ast.Expression(getter), "willy.py", "eval"), {"getattr": getattr, "config_mgr": config_mgr})
        self.assertEqual("ctrl+alt+d", resultado("hotkey"))


if __name__ == "__main__":
    unittest.main()
