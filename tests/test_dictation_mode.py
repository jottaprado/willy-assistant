"""
Testes unitários para o Modo de Ditado: Automático (Silêncio) vs Manual (Toggle / Pressione para Parar).
"""

import json
import os
import unittest

from core.config import ConfigManager
from tests.config_isolada import isolar_config


class TestDictationMode(unittest.TestCase):

    def setUp(self):
        self.test_dir = isolar_config(self)

    def test_default_auto_silence_is_true(self):
        cfg = ConfigManager()
        self.assertTrue(cfg.auto_silence)

    def test_save_and_reload_auto_silence_false(self):
        cfg = ConfigManager()
        cfg.save_settings({"AUTO_SILENCE": False})
        self.assertFalse(cfg.auto_silence)

        # Recarrega a partir do .env
        cfg2 = ConfigManager()
        self.assertFalse(cfg2.auto_silence)

        # Reativa modo automático
        cfg2.save_settings({"AUTO_SILENCE": True})
        self.assertTrue(cfg2.auto_silence)
        cfg3 = ConfigManager()
        self.assertTrue(cfg3.auto_silence)

    def test_toggle_auto_silence_method(self):
        cfg = ConfigManager()
        self.assertTrue(cfg.auto_silence)

        novo = cfg.toggle_auto_silence()
        self.assertFalse(novo)
        self.assertFalse(cfg.auto_silence)

        novo2 = cfg.toggle_auto_silence()
        self.assertTrue(novo2)
        self.assertTrue(cfg.auto_silence)

    def test_export_import_profile_preserves_auto_silence(self):
        cfg = ConfigManager()
        cfg.save_settings({"AUTO_SILENCE": False})

        export_file = os.path.join(self.test_dir, "perfil_manual.json")
        self.assertTrue(cfg.export_profile(export_file))

        with open(export_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("AUTO_SILENCE", data["settings"])
        self.assertFalse(data["settings"]["AUTO_SILENCE"])

        # Muda para True e depois restaura via import
        cfg.save_settings({"AUTO_SILENCE": True})
        self.assertTrue(cfg.auto_silence)

        self.assertTrue(cfg.import_profile(export_file))
        self.assertFalse(cfg.auto_silence)

    def test_pill_show_state_custom_message(self):
        # Testa se a pílula aceita e exibe a mensagem customizada de modo manual
        import tkinter as tk

        from ui.overlays.pill import FloatingPill

        root = tk.Tk()
        root.withdraw()
        try:
            pill = FloatingPill(root)
            msg_custom = "🎙️ Modo Manual (Pressione atalho p/ enviar)"
            pill.show_state("listening", msg=msg_custom, mode="transcribe")
            texto_atual = pill.canvas.itemcget(pill.text, "text")
            self.assertEqual(texto_atual, msg_custom)
            pill.root.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
