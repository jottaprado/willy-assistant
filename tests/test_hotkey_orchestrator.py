"""
Testes unitários para o módulo core.system.hotkey_orchestrator.
"""

import unittest
from unittest.mock import MagicMock

from core.config import ConfigManager
from core.system.hotkey_orchestrator import HotkeyOrchestrator


class TestHotkeyOrchestrator(unittest.TestCase):
    def setUp(self):
        self.mock_hotkey_mgr = MagicMock()
        self.mock_config = MagicMock(spec=ConfigManager)
        self.mock_config.master_hotkey = "ctrl+alt+w"
        self.mock_config.translate_hotkey = "ctrl+alt+t"
        self.mock_config.translate_es_hotkey = "ctrl+alt+y"
        self.mock_config.meeting_hotkey = "ctrl+alt+m"
        self.mock_config.prompt_hotkey = "ctrl+alt+p"
        self.mock_config.transform_hotkey = "ctrl+shift+t"
        self.mock_config.profile_hotkey = "ctrl+alt+o"
        self.mock_config.history_hotkey = "ctrl+alt+h"
        self.mock_config.undo_hotkey = "ctrl+alt+z"
        self.mock_config.send_hotkey = "ctrl+shift+enter"
        self.mock_config.speak_hotkey = "ctrl+alt+s"
        self.mock_config.sticky_hotkey = "ctrl+alt+k"
        self.mock_config.captions_hotkey = "ctrl+alt+l"
        self.mock_config.hotkey = "ctrl+space"

        self.handlers = {
            "master": MagicMock(),
            "translate": MagicMock(),
            "translate_es": MagicMock(),
            "meeting": MagicMock(),
            "prompt": MagicMock(),
            "transform": MagicMock(),
            "profile": MagicMock(),
            "history": MagicMock(),
            "undo": MagicMock(),
            "send": MagicMock(),
            "speak": MagicMock(),
            "sticky": MagicMock(),
            "captions": MagicMock(),
            "voice": MagicMock(),
        }

        self.orchestrator = HotkeyOrchestrator(
            self.mock_hotkey_mgr,
            self.mock_config,
            self.handlers,
        )

    def test_registrar_todos_registers_all_configured_hotkeys(self):
        self.orchestrator.registrar_todos()

        self.mock_hotkey_mgr.stop.assert_called_once()
        self.mock_hotkey_mgr.clear.assert_called_once()
        self.assertEqual(self.mock_hotkey_mgr.register.call_count, 14)
        self.mock_hotkey_mgr.start.assert_called_once()

    def test_registrar_todos_skips_empty_optional_hotkey(self):
        self.mock_config.translate_es_hotkey = ""
        self.orchestrator.registrar_todos()
        self.assertEqual(self.mock_hotkey_mgr.register.call_count, 13)

    def test_recarregar_se_necessario_triggers_when_hotkey_field_present(self):
        self.orchestrator.recarregar_se_necessario({"VOICE_HOTKEY": "ctrl+shift+w"})
        self.assertEqual(self.mock_hotkey_mgr.register.call_count, 14)

    def test_recarregar_se_necessario_does_not_trigger_for_unrelated_field(self):
        self.orchestrator.recarregar_se_necessario({"OUTPUT_TONE": "formal"})
        self.mock_hotkey_mgr.register.assert_not_called()


if __name__ == "__main__":
    unittest.main()
