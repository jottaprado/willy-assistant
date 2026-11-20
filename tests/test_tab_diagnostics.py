"""
Testes unitários para o módulo modular ui.tabs.tab_diagnostics.
Verifica a integridade de DiagnosticsTab, build_tab_diagnostics e compatibilidade com WillyDashboard.
"""

import gc
import unittest
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_diagnostics import DiagnosticsTab, build_tab_diagnostics


class TestTabDiagnostics(unittest.TestCase):
    """Testes dos componentes e execução dos testes de microfone e rede."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_diagnostics_tab_componentes(self):
        """Verifica a inicialização de todos os widgets e contratos da aba de diagnóstico."""
        ping_chamado = []
        callbacks = {
            "on_ping_groq": lambda: ping_chamado.append(True) or (True, "OK", 42.5),
            "get_settings": lambda: {"audio_device": None},
            "get_actual_sample_rate": lambda: 48000,
        }
        tab = build_tab_diagnostics(self.root, callbacks=callbacks)
        self.assertIsInstance(tab, DiagnosticsTab)
        self.assertTrue(hasattr(tab, "lbl_mic_info"))
        self.assertTrue(hasattr(tab, "prog_volume"))
        self.assertTrue(hasattr(tab, "btn_test_mic"))
        self.assertTrue(hasattr(tab, "lbl_status_groq"))
        self.assertTrue(hasattr(tab, "btn_test_groq"))

        # Testa ping na Groq
        fila_ui = []
        tab._safe_after = lambda _ms, fn, *a: fila_ui.append((fn, a))
        tab.testar_groq_api()
        # Aguarda thread terminar e callbacks executarem
        import time
        for _ in range(20):
            while fila_ui:
                fn, a = fila_ui.pop(0)
                fn(*a)
            self.root.update()
            if "Conexão ativa" in tab.lbl_status_groq.cget("text"):
                break
            time.sleep(0.05)
        self.assertTrue(ping_chamado)
        self.root.update()
        texto_ping = tab.lbl_status_groq.cget("text")
        self.assertNotIn("Groq Whisper Turbo", texto_ping)
        self.assertIn("Conexão ativa", texto_ping)

    def test_iniciar_teste_mic_negociacao(self):
        """Testa o início do teste de microfone sem levantar exceção em fallback."""
        import threading

        import numpy as np

        callbacks = {
            "get_settings": lambda: {"audio_device": None},
            "get_actual_sample_rate": lambda: 16000,
        }
        tab = build_tab_diagnostics(self.root, callbacks=callbacks)
        started_evt = threading.Event()
        # O lixo dos testes anteriores é coletado aqui, na thread principal. Coletado na thread
        # do teste, o Font.__del__ do tkinter chama o Tcl de fora da thread principal e, sem
        # mainloop, cada um espera ~1 s: a thread passava do prazo (medido no CI do Bloco 6B).
        gc.collect()

        def fake_read(chunk):
            started_evt.set()
            return (np.zeros((chunk, 1), dtype=np.float32), None)

        with patch("sounddevice.InputStream") as mock_stream:
            mock_inst = MagicMock()
            mock_inst.read.side_effect = fake_read
            mock_stream.return_value = mock_inst
            tab.iniciar_teste_mic()
            self.assertTrue(started_evt.wait(timeout=2.0))
            self.assertTrue(tab.mic_test_active)
            tab.mic_test_active = False
            mock_stream.assert_called()

    def test_dashboard_delegacao_diagnosticos(self):
        """Testa a fachada e delegação de WillyDashboard para tab_diagnostics."""
        isolar_config(self)
        dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list})
        dash.withdraw()
        try:
            self.assertIn("diagnostics", dash.frames_abas)
            self.assertIsInstance(dash.frames_abas["diagnostics"], DiagnosticsTab)
            self.assertTrue(hasattr(dash, "tab_diagnostics"))
            self.assertIsNotNone(dash.lbl_mic_info)
            self.assertIsNotNone(dash.btn_test_groq)
        finally:
            destruir_tk(dash)


if __name__ == "__main__":
    unittest.main()
