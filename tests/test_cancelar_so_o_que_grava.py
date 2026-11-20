"""
O corte por 7 s sem fala só cancela, e só avisa, se ainda há gravação.

Ele chega numa thread. Se a pessoa parou pelo atalho antes, o som de erro e o "cancelado"
saíam por cima do ditado sendo processado, e o microfone era pausado embaixo da gravação
seguinte.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from core.audio import AudioManager
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy


class TestCancelRecording(unittest.TestCase):
    def setUp(self):
        self.mgr = AudioManager()
        self.mgr.stream = MagicMock(active=True)  # start_recording exige microfone aberto

    def test_com_gravacao_cancela_e_devolve_true(self):
        self.mgr.start_recording("transcribe")
        self.mgr.append_audio(np.ones((500, 1), dtype=np.float32))
        self.assertTrue(self.mgr.cancel_recording())
        self.assertFalse(self.mgr.is_recording)
        self.assertEqual([], self.mgr.buffer)

    def test_sem_gravacao_devolve_false_e_nao_mexe_em_nada(self):
        self.mgr.system_stream = sistema = MagicMock()
        self.mgr.buffer = ["do ditado que está sendo parado"]
        self.assertFalse(self.mgr.cancel_recording())
        self.assertIs(sistema, self.mgr.system_stream)
        self.assertEqual(["do ditado que está sendo parado"], self.mgr.buffer)


class TestCancelarGravacao(unittest.TestCase):
    def _cancelar(self, havia_gravacao):
        self.audio = MagicMock()
        self.audio.cancel_recording.return_value = havia_gravacao
        self.som, self.ui, self.soltar_esc = MagicMock(), MagicMock(), MagicMock()
        return _funcao_do_willy("cancelar_gravacao", audio_mgr=self.audio, sound_mgr=self.som,
                                atualizar_ui=self.ui, _soltar_esc=self.soltar_esc,
                                _soltar_esc_sem_gravacao=lambda: None,
                                config_mgr=SimpleNamespace(wake_word_enabled=False))()

    def test_cancelou_avisa(self):
        self.assertTrue(self._cancelar(True))
        self.som.sound_error.assert_called_once_with()
        self.ui.assert_called_once_with("cancelled")
        self.audio.pause_stream.assert_called_once_with()
        self.soltar_esc.assert_called_once_with()

    def test_nada_a_cancelar_fica_quieto(self):
        self.assertFalse(self._cancelar(False))
        # O Esc é solto mesmo assim: sem gravação, ele não pode ficar preso.
        self.soltar_esc.assert_called_once_with()
        self.som.sound_error.assert_not_called()
        self.ui.assert_not_called()
        self.audio.pause_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
