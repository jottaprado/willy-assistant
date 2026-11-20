"""
Testes unitários para o módulo core.sound.SoundManager.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from core.sound import SoundManager


class TestSoundManager(unittest.TestCase):

    def test_sound_calls_do_not_crash(self):
        # Modo silencioso ativado
        mgr = SoundManager(is_silent_func=lambda: True)
        # Nenhuma chamada deve lançar exceção
        mgr.sound_start()
        mgr.sound_stop()
        mgr.sound_success()
        mgr.sound_error()
        mgr.sound_sleep()
        mgr.sound_wake()

    def test_silent_checker_toggle(self):
        silent = False
        mgr = SoundManager(is_silent_func=lambda: silent)
        self.assertFalse(mgr._is_silent())

        silent = True
        self.assertTrue(mgr._is_silent())

        mgr.set_silent_checker(lambda: False)
        self.assertFalse(mgr._is_silent())

    def test_play_wav_file_respeita_modo_silencioso_e_loga_erro_no_stderr(self):
        """AUD-038 e AUD-205: play_wav_file deve respeitar _is_silent() e logar falhas em sys.stderr."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        try:
            mgr_silencioso = SoundManager(is_silent_func=lambda: True)
            with patch("core.sound.winsound") as mock_ws:
                self.assertFalse(mgr_silencioso.play_wav_file(wav_path))
                mock_ws.PlaySound.assert_not_called()

            mgr_ativo = SoundManager(is_silent_func=lambda: False)
            buf = io.StringIO()
            with patch("core.sound.winsound") as mock_ws, redirect_stderr(buf):
                mock_ws.SND_FILENAME = 1
                mock_ws.SND_ASYNC = 2
                mock_ws.PlaySound.side_effect = RuntimeError("Dispositivo de áudio ocupado")
                self.assertFalse(mgr_ativo.play_wav_file(wav_path))
            self.assertIn("[SoundManager]", buf.getvalue())
            self.assertIn("Dispositivo de áudio ocupado", buf.getvalue())
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)


if __name__ == "__main__":
    unittest.main()
