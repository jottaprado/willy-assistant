"""
Testes unitários para exportação e importação de perfil completo do Willy.
"""

import json
import os
import unittest
from unittest.mock import MagicMock

from core.config import ConfigManager
from tests.config_isolada import isolar_config


class TestProfileBackup(unittest.TestCase):

    def setUp(self):
        self.temp_dir = isolar_config(self)
        self.cfg_mgr = ConfigManager()

    def test_export_and_import_profile(self):
        # 1. Popula dados de teste
        self.cfg_mgr.save_settings({
            "GROQ_API_KEY": "gsk_perfil_test",
            "VOICE_HOTKEY": "ctrl+alt+z",
            "MIC_GAIN": "2.0",
            "HISTORY_HOTKEY": "ctrl+shift+h"
        })
        self.cfg_mgr.save_vocab_text("Kubernetes\nTerraform\nLangChain")
        self.cfg_mgr.save_history_item("Teste ditado de perfil 1", modo="transcribe")
        self.cfg_mgr.save_history_item("Teste ditado de perfil 2", modo="prompt")

        mock_snippet_mgr = MagicMock()
        mock_snippet_mgr.get_snippets.return_value = [
            {"trigger": "pix", "title": "Chave PIX", "content": "123.456.789-00"},
            {"trigger": "email", "title": "Email Comercial", "content": "teste@willy.ai"}
        ]

        export_path = os.path.join(self.temp_dir, "perfil_exportado.json")

        # 2. Exporta
        # Backup completo para a própria máquina: o histórico só vai quando pedido.
        ok = self.cfg_mgr.export_profile(export_path, snippet_mgr=mock_snippet_mgr, include_history=True)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(export_path))

        with open(export_path, "r", encoding="utf-8") as f:
            dados = json.load(f)

        self.assertEqual(dados["settings"]["VOICE_HOTKEY"], "ctrl+alt+z")
        self.assertEqual(dados["settings"]["MIC_GAIN"], 2.0)
        self.assertEqual(dados["settings"]["HISTORY_HOTKEY"], "ctrl+shift+h")
        self.assertIn("Kubernetes", dados["vocabulary"])
        self.assertEqual(len(dados["snippets"]), 2)
        self.assertEqual(len(dados["history"]), 2)

        # 3. Altera os dados locais
        self.cfg_mgr.save_settings({
            "GROQ_API_KEY": "gsk_outro",
            "VOICE_HOTKEY": "ctrl+space",
            "MIC_GAIN": "1.0",
            "HISTORY_HOTKEY": "ctrl+alt+h"
        })
        self.cfg_mgr.save_vocab_text("Outro texto")
        self.cfg_mgr.clear_history()

        # 4. Importa de volta
        mock_snippet_mgr_restore = MagicMock()
        ok_import = self.cfg_mgr.import_profile(export_path, snippet_mgr=mock_snippet_mgr_restore)
        self.assertTrue(ok_import)

        # 5. Valida restauração
        self.assertEqual(self.cfg_mgr.hotkey, "ctrl+alt+z")
        self.assertEqual(self.cfg_mgr.mic_gain, 2.0)
        self.assertEqual(self.cfg_mgr.history_hotkey, "ctrl+shift+h")
        self.assertIn("Kubernetes", self.cfg_mgr.load_vocab_text())
        self.assertEqual(len(self.cfg_mgr.load_history()), 2)
        mock_snippet_mgr_restore.replace_snippets.assert_called_once_with([
            {"trigger": "pix", "title": "Chave PIX", "content": "123.456.789-00"},
            {"trigger": "email", "title": "Email Comercial", "content": "teste@willy.ai"},
        ])

    def test_import_legacy_profile_with_expansion(self):
        legacy_path = os.path.join(self.temp_dir, "perfil_legado.json")
        legacy_data = {
            "settings": {},
            "snippets": [
                {"trigger": "legado", "expansion": "Texto de expansão legado"}
            ]
        }
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        mock_mgr = MagicMock()
        ok = self.cfg_mgr.import_profile(legacy_path, snippet_mgr=mock_mgr)
        self.assertTrue(ok)
        mock_mgr.replace_snippets.assert_called_once_with([
            {"trigger": "legado", "title": "Legado", "content": "Texto de expansão legado"}
        ])

    def test_export_and_import_preserva_limiares_rms_e_substitui_snippets_reais(self):
        """AUD-042 e AUD-043: exporta/importa SILENCE_THRESHOLD e SPEECH_THRESHOLD e substitui a lista de snippets."""
        from core.snippets import SnippetManager

        snippets_file = os.path.join(self.temp_dir, ".snippets.json")
        real_snippets = SnippetManager(file_path=snippets_file)
        self.assertTrue(real_snippets.replace_snippets([
            {"trigger": "atalho um", "title": "Um", "content": "Conteúdo 1"},
            {"trigger": "atalho dois", "title": "Dois", "content": "Conteúdo 2"},
        ]))

        self.cfg_mgr.save_settings({
            "SILENCE_THRESHOLD": 0.015,
            "SPEECH_THRESHOLD": 0.030,
        })

        export_path = os.path.join(self.temp_dir, "perfil_completo.json")
        self.assertTrue(self.cfg_mgr.export_profile(export_path, snippet_mgr=real_snippets))

        with open(export_path, "r", encoding="utf-8") as f:
            exportado = json.load(f)
        self.assertAlmostEqual(exportado["settings"]["SILENCE_THRESHOLD"], 0.015)
        self.assertAlmostEqual(exportado["settings"]["SPEECH_THRESHOLD"], 0.030)

        # Modifica estado local (adiciona snippet extra que não estava no perfil e altera limiares)
        self.cfg_mgr.save_settings({
            "SILENCE_THRESHOLD": 0.005,
            "SPEECH_THRESHOLD": 0.009,
        })
        real_snippets.save_snippet("snippet local extra", "Extra", "Deve sumir no import")
        self.assertEqual(len(real_snippets.get_snippets()), 3)

        # Importa o perfil: o snippet extra deve ser removido e os limiares restaurados
        self.assertTrue(self.cfg_mgr.import_profile(export_path, snippet_mgr=real_snippets))
        self.assertAlmostEqual(self.cfg_mgr.silence_threshold, 0.015)
        self.assertAlmostEqual(self.cfg_mgr.speech_threshold, 0.030)
        gatilhos = [s["trigger"] for s in real_snippets.get_snippets()]
        self.assertEqual(gatilhos, ["atalho um", "atalho dois"])

        # Importar perfil com snippets=[] deve esvaziar a lista de snippets
        vazio_path = os.path.join(self.temp_dir, "perfil_sem_snippets.json")
        with open(vazio_path, "w", encoding="utf-8") as f:
            json.dump({"settings": {}, "snippets": []}, f)
        self.assertTrue(self.cfg_mgr.import_profile(vazio_path, snippet_mgr=real_snippets))
        self.assertEqual(real_snippets.get_snippets(), [])


if __name__ == "__main__":
    unittest.main()
