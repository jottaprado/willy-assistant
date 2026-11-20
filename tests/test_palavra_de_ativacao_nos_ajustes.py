"""
Ligar ou desligar o "Ei Willy" nos Ajustes vale na hora.

O dashboard_save_settings ignorava WAKE_WORD_ENABLED: ligado, o Willy só passava a ouvir a
palavra depois de reiniciar (o microfone abre na partida); desligado, o microfone seguia
aberto até reiniciar, com o aviso de microfone em uso do Windows aceso.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, create_autospec

from core.audio import AudioManager
from core.config import ConfigManager
from core.groq_service import GroqService
from tests.config_isolada import isolar_config
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy


class TestPalavraDeAtivacaoNosAjustes(unittest.TestCase):
    def setUp(self):
        isolar_config(self)

    def _salvar(self, dados, gravando=False):
        config = ConfigManager()
        config.groq_api_key = "gsk_x"
        config.wake_word_enabled = not dados.get("WAKE_WORD_ENABLED", True)
        self.audio = create_autospec(AudioManager, instance=True)
        self.audio.is_recording = gravando
        self.callback = object()
        _funcao_do_willy(
            "dashboard_save_settings", config_mgr=config,
            groq_service=create_autospec(GroqService, instance=True), audio_mgr=self.audio,
            callback_audio=self.callback, hotkey_orchestrator=None, dashboard=None, pill=None,
            sincronizar_bandeja=MagicMock(), safe_dispatch_ui=MagicMock(), atualizar_ui=MagicMock(),
            transcription_pipeline=SimpleNamespace(fila=[]))(dados)

    def test_ligar_abre_o_microfone_para_ouvir(self):
        self._salvar({"WAKE_WORD_ENABLED": True})
        self.audio.ensure_stream.assert_called_once_with(self.callback)
        self.audio.pause_stream.assert_not_called()

    def test_desligar_fecha_o_microfone(self):
        self._salvar({"WAKE_WORD_ENABLED": False})
        self.audio.pause_stream.assert_called_once_with()
        self.audio.ensure_stream.assert_not_called()

    def test_desligar_no_meio_da_gravacao_nao_corta_o_ditado(self):
        self._salvar({"WAKE_WORD_ENABLED": False}, gravando=True)
        self.audio.pause_stream.assert_not_called()

    def test_salvar_outra_coisa_nao_mexe_no_microfone(self):
        self._salvar({"SILENT_MODE": True})
        self.audio.ensure_stream.assert_not_called()
        self.audio.pause_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
