"""
Testes unitários para as funcionalidades Power de v1.7.0:
1. Gerenciador de Snippets e Templates de Voz com Presets (Pix, Meet, PR).
2. Atalho Global de Desfazer Último Ditado (Ctrl + Alt + Z).
3. Modo Ditar e Enviar (Voice-to-Enter via comando de voz e hotkey).
4. Parágrafos Inteligentes em Pausas Naturais (Smart Paragraphing).
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.config import ConfigManager
from core.groq_service import GroqService
from core.snippets import SnippetManager
from core.text_processing import TextProcessor
from tests.config_isolada import isolar_config


class TestPowerFeaturesV17(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.tmp_snippets_file = os.path.join(self._tmp_dir.name, "tests_tmp_snippets.json")
        self.snippet_mgr = SnippetManager(file_path=self.tmp_snippets_file)

    # -------------------------------------------------------------
    # 1. TESTES DE SNIPPETS & TEMPLATES DE VOZ
    # -------------------------------------------------------------
    def test_default_snippets_presets(self):
        """Verifica se os presets de snippets foram carregados corretamente."""
        triggers = [s["trigger"] for s in self.snippet_mgr.get_snippets()]
        self.assertIn("meu pix", triggers)
        self.assertIn("link da reuniao", triggers)
        self.assertIn("template de pr", triggers)

    def test_snippet_match_and_expand(self):
        """Verifica a expansão de snippet ao falar o gatilho."""
        expanded = self.snippet_mgr.match_and_expand("meu pix")
        self.assertIsNotNone(expanded)
        self.assertIn("Chave PIX", expanded)

        # Snippet inexistente
        no_match = self.snippet_mgr.match_and_expand("frase aleatoria sem gatilho")
        self.assertIsNone(no_match)

    def test_snippet_crud(self):
        """Testa adição, edição e exclusão de snippets."""
        self.snippet_mgr.save_snippet("meu email dev", "Email Dev", "dev@willy.ai")
        expanded = self.snippet_mgr.match_and_expand("meu email dev")
        self.assertEqual(expanded, "dev@willy.ai")

        # Exclusão
        ok = self.snippet_mgr.delete_snippet("meu email dev")
        self.assertTrue(ok)
        self.assertIsNone(self.snippet_mgr.match_and_expand("meu email dev"))

    # -------------------------------------------------------------
    # 2. TESTES DE DETECÇÃO DE COMANDO "DITAR E ENVIAR" (VOICE-TO-ENTER)
    # -------------------------------------------------------------
    def test_detect_send_command_prefixes(self):
        """Testa a extração correta de comandos de envio com Enter por voz."""
        cases = [
            ("Willy enviar: Reunião confirmada para às 15h", "Reunião confirmada para às 15h", True),
            ("Willy mande: Já enviei o pull request", "Já enviei o pull request", True),
            ("willy envie: tudo certo por aqui", "Tudo certo por aqui", True),
            ("Willy enviar Olá pessoal", "Olá pessoal", True),
            ("Willy mande Olá mundo", "Olá mundo", True),
            ("Texto normal sem comando de envio", "Texto normal sem comando de envio", False),
            ("Willy é um excelente copiloto", "Willy é um excelente copiloto", False),
        ]
        for entrada, esperado_texto, esperado_send in cases:
            txt_res, is_send = TextProcessor.detect_send_command(entrada)
            self.assertEqual(txt_res, esperado_texto)
            self.assertEqual(is_send, esperado_send)

    # -------------------------------------------------------------
    # 3. TESTES DE CONFIGURAÇÕES DE ATALHOS E SMART PARAGRAPHING
    # -------------------------------------------------------------
    def test_config_manager_new_settings(self):
        """Verifica se undo_hotkey, send_hotkey e smart_paragraphing têm defaults corretos e salvam no disco."""
        isolar_config(self)
        cfg = ConfigManager()
        self.assertEqual(cfg.undo_hotkey, "ctrl+alt+z")
        self.assertEqual(cfg.send_hotkey, "ctrl+shift+enter")
        self.assertTrue(cfg.smart_paragraphing)

        # AUD-217: Exercita escrita atômica real de SettingsStore em vez de mock_open
        cfg.save_settings({
            "UNDO_HOTKEY": "ctrl+alt+u",
            "SEND_HOTKEY": "ctrl+shift+e",
            "SMART_PARAGRAPHING": False,
        })
        self.assertEqual(cfg.undo_hotkey, "ctrl+alt+u")
        self.assertEqual(cfg.send_hotkey, "ctrl+shift+e")
        self.assertFalse(cfg.smart_paragraphing)

        recarregado = ConfigManager()
        self.assertEqual(recarregado.undo_hotkey, "ctrl+alt+u")
        self.assertEqual(recarregado.send_hotkey, "ctrl+shift+e")
        self.assertFalse(recarregado.smart_paragraphing)

    def test_export_profile_includes_new_features(self):
        """Verifica se o backup do perfil inclui os novos campos."""
        pasta = isolar_config(self)
        cfg = ConfigManager()
        export_path = os.path.join(pasta, "tests_tmp_profile_export.json")
        cfg.export_profile(export_path, snippet_mgr=self.snippet_mgr)
        with open(export_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("UNDO_HOTKEY", data["settings"])
        self.assertIn("SEND_HOTKEY", data["settings"])
        self.assertIn("SMART_PARAGRAPHING", data["settings"])
        self.assertIn("snippets", data)

    # -------------------------------------------------------------
    # 4. TESTES DE SMART PARAGRAPHING NO REFINAMENTO
    # -------------------------------------------------------------
    def test_smart_paragraphing_parameter(self):
        """Verifica se GroqService.refine_text aceita o argumento smart_paragraphing."""
        groq = GroqService(api_key="test_key")
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Texto formatado em parágrafos."
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(groq, "get_client", return_value=mock_client):
            long_text = (
                "Primeiro tópico sobre a arquitetura do sistema com vários detalhes importantes. "
                "Segundo tópico sobre os testes automatizados que garantem estabilidade total."
            )
            res = groq.refine_text(long_text, enabled=True, smart_paragraphing=True)
            self.assertEqual(res, "Texto formatado em parágrafos.")

            # Verifica se o prompt do sistema instruiu parágrafos
            _args, kwargs = mock_client.chat.completions.create.call_args
            messages = kwargs.get("messages", [])
            sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            self.assertIn("parágrafos", sys_msg.lower())


if __name__ == "__main__":
    unittest.main()
