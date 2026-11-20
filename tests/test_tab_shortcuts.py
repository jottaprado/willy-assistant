"""
Testes unitários para o módulo modular ui.tabs.tab_shortcuts.
Verifica a integridade de render_keycaps_row, build_tab_shortcuts e compatibilidade com WillyDashboard.
"""

import unittest

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_shortcuts import build_tab_shortcuts, render_keycaps_row


class TestTabShortcuts(unittest.TestCase):
    """Testes da renderização e contratos da aba de atalhos."""

    @classmethod
    def setUpClass(cls):
        # Cria uma janela raiz oculta para os testes de widgets
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_render_keycaps_row_estrutura(self):
        """Testa se render_keycaps_row gera um CTkFrame com os componentes esperados."""
        teclas = ["Ctrl", "+", "Alt", "+", "Espaço"]
        frame = render_keycaps_row(self.root, teclas)
        self.assertIsInstance(frame, ctk.CTkFrame)
        
        # Verifica se os filhos foram gerados
        filhos = frame.winfo_children()
        self.assertGreater(len(filhos), 0)

    def test_build_tab_shortcuts_criacao(self):
        """Testa se build_tab_shortcuts monta com sucesso o frame scrollável."""
        tab_frame = build_tab_shortcuts(self.root)
        self.assertIsInstance(tab_frame, ctk.CTkScrollableFrame)
        
        # Verifica se contém widgets filhos (título, cards, etc.)
        filhos = tab_frame.winfo_children()
        self.assertGreater(len(filhos), 0)

    def test_dashboard_delegacao_atalhos(self):
        """Testa se WillyDashboard inicializa a aba de atalhos via delegação sem erros."""
        isolar_config(self)
        dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list})
        dash.withdraw()
        try:
            self.assertIn("shortcuts", dash.frames_abas)
            self.assertIsInstance(dash.frames_abas["shortcuts"], ctk.CTkScrollableFrame)

            # Testa a fachada legada _criar_keycaps_row
            keycap_frame = dash._criar_keycaps_row(dash, ["Ctrl", "+", "Espaço"])
            self.assertIsNotNone(keycap_frame)
        finally:
            destruir_tk(dash)


if __name__ == "__main__":
    unittest.main()
