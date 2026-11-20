"""
Testes de integração do Willy.
Verifica a interoperabilidade entre os módulos core, dashboard e orquestrador.
"""

import unittest

from core import (
    DEV_PROMPT_CONTEXT,
    AudioManager,
    ConfigManager,
    GroqService,
    SingleInstanceManager,
    SoundManager,
    TextProcessor,
)
from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.overlays import TrayManager


class TestIntegration(unittest.TestCase):

    def test_all_exports_available(self):
        self.assertIsNotNone(ConfigManager)
        self.assertIsNotNone(SoundManager)
        self.assertIsNotNone(TextProcessor)
        self.assertIsNotNone(GroqService)
        self.assertIsNotNone(AudioManager)
        self.assertIsNotNone(TrayManager)
        self.assertIsNotNone(SingleInstanceManager)
        self.assertIsNotNone(DEV_PROMPT_CONTEXT)

    def test_manager_instantiations(self):
        isolar_config(self)
        cfg = ConfigManager()
        SoundManager()
        GroqService(api_key=cfg.groq_api_key)
        audio = AudioManager()
        SingleInstanceManager()

        self.assertFalse(audio.is_recording)
        self.assertTrue(audio.is_awake)
        self.assertEqual(cfg.hotkey, "ctrl+space")

    def test_tray_menu_generation(self):
        tray = TrayManager(callbacks={}, base_dir=".")
        menu = tray.build_menu(
            is_awake=True,
            refine_enabled=True,
            silent_mode=False,
            pill_pos="centro_inferior",
            hotkey="ctrl+space",
            trans_hotkey="ctrl+alt+space",
            master_hotkey="ctrl+shift+space",
            meeting_hotkey="ctrl+alt+r",
            llm_model="llama-3.3-70b-versatile",
            history_items=[{"text": "Prompt de teste", "mode": "transcribe"}],
            prompt_hotkey="ctrl+alt+p"
        )
        self.assertIsNotNone(menu)

    def test_pill_offline_retry_callback(self):
        import tkinter as tk

        from ui.overlays.pill import FloatingPill

        root = tk.Tk()
        root.withdraw()
        try:
            pill = FloatingPill(root)
            called = []
            pill.set_retry_callback(lambda: called.append(True))
            pill.show_state("offline_retry", "Teste offline")
            self.assertEqual(pill.current_state, "offline_retry")

            # Ao clicar em estado offline_retry, deve disparar o callback
            pill._on_click()
            self.assertEqual(called, [True])
            self.assertIsNone(pill.current_state)
            pill.destroy()
        finally:
            destruir_tk(root)

    def test_dashboard_history_filtering(self):
        from tests.config_isolada import isolar_config
        from ui.dashboard import WillyDashboard
        isolar_config(self)

        test_history = [
            {"text": "Ditar texto simples", "mode": "transcribe", "timestamp": "16/09/2026 20:00"},
            {"text": "Translate this sentence to English", "mode": "translate", "timestamp": "16/09/2026 20:01"},
            {"text": '/goal "Criar tela de login" /loop /maestro:maestro', "mode": "prompt", "timestamp": "16/09/2026 20:02"},
            {"text": "Resumir tópicos selecionados", "mode": "action", "timestamp": "16/09/2026 20:03"},
        ]

        dash = WillyDashboard(callbacks={"get_history": lambda: test_history, "get_app_rules": list})
        dash.withdraw()
        try:
            # Verifica se o segmented button de filtros foi criado
            self.assertTrue(hasattr(dash, "seg_filtro_historico"))
            self.assertEqual(dash.seg_filtro_historico.get(), "Todos")

            # Testa filtro de prompts de agente
            dash.seg_filtro_historico.set("🎯 Prompts de Agente")
            dash.atualizar_lista_historico()
            # 1 de 4
            self.assertIn("1 de 4", dash.lbl_total_prompts.cget("text"))

            # Testa filtro de ações
            dash.seg_filtro_historico.set("⚡ Ações")
            dash.atualizar_lista_historico()
            self.assertIn("1 de 4", dash.lbl_total_prompts.cget("text"))

            # Restaura todos
            dash.seg_filtro_historico.set("Todos")
            dash.atualizar_lista_historico()
            self.assertIn("4 de 4", dash.lbl_total_prompts.cget("text"))
        finally:
            destruir_tk(dash)


if __name__ == "__main__":
    unittest.main()


