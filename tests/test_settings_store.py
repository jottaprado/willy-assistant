"""
Testes unitários para o módulo core.storage.settings_store.
"""

import os
import tempfile
import unittest

from core.storage.settings_store import SettingsStore


class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = os.path.join(self.temp_dir.name, ".test.env")
        self.store = SettingsStore(env_file=self.env_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_missing(self):
        self.assertEqual(self.store.load_lines(), [])

    def test_save_new_file(self):
        mapping = {"GROQ_API_KEY": "gsk_test123", "VOICE_HOTKEY": "ctrl+space"}
        self.assertTrue(self.store.save_settings(mapping))

        linhas = self.store.load_lines()
        self.assertIn("GROQ_API_KEY=gsk_test123\n", linhas)
        self.assertIn("VOICE_HOTKEY=ctrl+space\n", linhas)

    def test_preserve_comments_and_order(self):
        initial = (
            "# Configurações do Willy\n"
            "\n"
            "# Chave de API\n"
            "GROQ_API_KEY=antiga\n"
            "# Outra chave customizada\n"
            "CUSTOM_VAR=manter_isto\n"
            "SILENCE_SECONDS=1.5\n"
        )
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(initial)

        self.assertTrue(self.store.save_settings({"GROQ_API_KEY": "nova_chave", "NOVA_VAR": "valor"}))

        conteudo = "".join(self.store.load_lines())
        self.assertIn("# Configurações do Willy\n", conteudo)
        self.assertIn("# Chave de API\n", conteudo)
        self.assertIn("GROQ_API_KEY=nova_chave\n", conteudo)
        self.assertNotIn("GROQ_API_KEY=antiga\n", conteudo)
        self.assertIn("CUSTOM_VAR=manter_isto\n", conteudo)
        self.assertIn("SILENCE_SECONDS=1.5\n", conteudo)
        self.assertIn("NOVA_VAR=valor\n", conteudo)


if __name__ == "__main__":
    unittest.main()
