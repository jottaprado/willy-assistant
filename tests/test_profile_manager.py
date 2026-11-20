"""
Testes unitários para o módulo core.storage.profile_manager.ProfileManager.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from core.storage.profile_manager import ProfileManager
from versao import __version__


class TestProfileManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_file = os.path.join(self.temp_dir.name, "perfil_backup.json")
        self.mock_config = MagicMock()
        self.mock_config.groq_api_key = "gsk_teste"
        self.mock_config.hotkey = "ctrl+space"
        self.mock_config.translate_hotkey = "ctrl+alt+t"
        self.mock_config.translate_es_hotkey = "ctrl+alt+n"
        self.mock_config.master_hotkey = "ctrl+alt+w"
        self.mock_config.meeting_hotkey = "ctrl+alt+m"
        self.mock_config.prompt_hotkey = "ctrl+alt+p"
        self.mock_config.history_hotkey = "ctrl+alt+h"
        self.mock_config.speak_hotkey = "ctrl+alt+s"
        self.mock_config.sticky_hotkey = "ctrl+alt+k"
        self.mock_config.captions_hotkey = "ctrl+alt+l"
        self.mock_config.transform_hotkey = "ctrl+shift+t"
        self.mock_config.profile_hotkey = "ctrl+alt+o"
        self.mock_config.model = "whisper-large-v3-turbo"
        self.mock_config.translate_model = "whisper-large-v3"
        self.mock_config.llm_model = "llama-3.3-70b-versatile"
        self.mock_config.processing_profile = "dev"
        self.mock_config.refine_prompt = "Refine..."
        self.mock_config.silent_mode = False
        self.mock_config.whisper_mode = False
        self.mock_config.pill_position = "top-right"
        self.mock_config.auto_silence = True
        self.mock_config.silence_seconds = 1.8
        self.mock_config.silence_threshold = 0.005
        self.mock_config.speech_threshold = 0.009
        self.mock_config.mic_gain = 1.0
        self.mock_config.audio_device = None
        self.mock_config.system_audio_device = None
        self.mock_config.private_mode = False
        self.mock_config.outputs_dir = "C:\\Users\\test\\Documents\\Willy"
        self.mock_config.clean_fillers = True
        self.mock_config.clipboard_only = False
        self.mock_config.output_tone = "natural"
        self.mock_config.input_language = "auto"
        self.mock_config.undo_hotkey = "ctrl+alt+z"
        self.mock_config.send_hotkey = "ctrl+shift+enter"
        self.mock_config.smart_paragraphing = True
        self.mock_config.save_audio_files = False
        self.mock_config.silero_vad = True
        self.mock_config.wake_word_enabled = False

        self.mock_config.load_vocab_text.return_value = "Python, TypeScript, Docker"
        self.mock_config.load_history.return_value = [{"text": "Primeiro teste", "timestamp": "2026-09-29 02:00:00"}]
        self.mock_config.load_replacements.return_value = {"dockers": "Docker"}
        self.mock_config.get_app_context_rules.return_value = [
            {"app_exe": "slack.exe", "title_contains": "", "tone": "concise", "action_mode": "default",
             "custom_instruction": ""}]

        self.mock_snippet_mgr = MagicMock()
        self.mock_snippet_mgr.get_snippets.return_value = [{"trigger": ";email", "title": "Email", "content": "Olá!"}]

        self.manager = ProfileManager(self.mock_config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_profile_creates_valid_json(self):
        sucesso = self.manager.export_profile(self.target_file, snippet_mgr=self.mock_snippet_mgr)
        self.assertTrue(sucesso)
        self.assertTrue(os.path.exists(self.target_file))

        with open(self.target_file, "r", encoding="utf-8") as f:
            dados = json.load(f)

        self.assertEqual(dados["willy_version"], __version__)
        # A chave só sai com include_api_key=True (ver test_perfil_seguro).
        self.assertNotIn("GROQ_API_KEY", dados["settings"])
        self.assertIs(True, dados["settings"]["SILERO_VAD"])
        self.assertEqual(dados["vocabulary"], "Python, TypeScript, Docker")
        self.assertEqual(len(dados["snippets"]), 1)
        self.assertEqual(dados["snippets"][0]["trigger"], ";email")
        self.assertEqual(dados["replacements"]["dockers"], "Docker")
        self.assertEqual("concise", dados["app_rules"][0]["tone"])
        # O histórico só sai com include_history=True (ver test_perfil_seguro).
        self.assertNotIn("history", dados)
        self.mock_config.load_history.assert_not_called()

    def test_import_profile_restores_all_stores(self):
        # Primeiro exporta (completo, para restaurar todos os stores)
        self.manager.export_profile(self.target_file, snippet_mgr=self.mock_snippet_mgr, include_history=True)

        # Agora simula import
        mock_novo_config = MagicMock()
        mock_novo_snippet_mgr = MagicMock()
        manager_import = ProfileManager(mock_novo_config)

        sucesso = manager_import.import_profile(self.target_file, snippet_mgr=mock_novo_snippet_mgr)
        self.assertTrue(sucesso)

        mock_novo_config.save_settings.assert_called_once()
        mock_novo_config.save_vocab_text.assert_called_once_with("Python, TypeScript, Docker")
        mock_novo_config.save_replacements.assert_called_once_with({"dockers": "Docker"})
        mock_novo_snippet_mgr.replace_snippets.assert_called_once_with(
            [{"trigger": ";email", "title": "Email", "content": "Olá!"}]
        )
        mock_novo_config.history_store.save_history.assert_called_once()
        mock_novo_config.save_app_context_rules.assert_called_once_with(
            self.mock_config.get_app_context_rules.return_value)

    def test_import_profile_missing_file_returns_false(self):
        self.assertFalse(self.manager.import_profile("caminho_inexistente.json"))


if __name__ == "__main__":
    unittest.main()
