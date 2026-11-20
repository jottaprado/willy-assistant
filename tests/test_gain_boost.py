"""
Testes unitários para ganho de microfone por software (Modo Sussurro) e gravação de reunião.
"""

import unittest
from unittest.mock import MagicMock

import numpy as np

from core.audio import AudioManager


class TestGainBoost(unittest.TestCase):

    def setUp(self):
        self.audio_mgr = AudioManager(sample_rate=16000, channels=1, gain_boost=1.0)
        # start_recording exige microfone aberto (sem ele era a gravação fantasma).
        self.audio_mgr.stream = MagicMock(active=True)

    def test_gain_boost_amplification(self):
        self.audio_mgr.set_gain_boost(2.0)
        self.assertEqual(self.audio_mgr.gain_boost, 2.0)

        self.audio_mgr.start_recording("transcribe")
        sample_chunk = np.full((100, 1), 0.2, dtype=np.float32)
        self.audio_mgr.append_audio(sample_chunk)

        res = self.audio_mgr.stop_recording()
        self.assertIsNotNone(res)
        audio_out, _modo = res

        # Com ganho de 2.0x, amplitude 0.2 vira 0.4
        self.assertAlmostEqual(float(audio_out[0][0]), 0.4, places=4)

    def test_gain_boost_clipping_protection(self):
        self.audio_mgr.set_gain_boost(3.0)
        self.audio_mgr.start_recording("transcribe")
        loud_chunk = np.full((100, 1), 0.8, dtype=np.float32)
        self.audio_mgr.append_audio(loud_chunk)

        res = self.audio_mgr.stop_recording()
        self.assertIsNotNone(res)
        audio_out, _modo = res

        # 0.8 * 3.0 = 2.4, deve ser limitado (clipped) a no máximo 1.0
        self.assertLessEqual(np.max(audio_out), 1.0)
        self.assertGreaterEqual(np.min(audio_out), -1.0)

    def test_set_system_device(self):
        self.audio_mgr.set_system_device(3)
        self.assertEqual(self.audio_mgr.system_device_index, 3)
        self.audio_mgr.set_system_device(None)
        self.assertIsNone(self.audio_mgr.system_device_index)


if __name__ == "__main__":
    unittest.main()

