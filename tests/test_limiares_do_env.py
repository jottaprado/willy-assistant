"""
Os limiares de silêncio e de fala do .env passam pela mesma validação dos outros números.

Liam com float() direto: um valor torto (texto, vírgula decimal) derrubava o ConfigManager e o
Willy não abria; NaN, infinito, zero ou negativo desligavam a detecção de silêncio.
"""

import os
import unittest

from core.config import ConfigManager
from tests.config_isolada import isolar_config


class TestLimiaresDoEnv(unittest.TestCase):
    def setUp(self):
        isolar_config(self)  # inclui um patch.dict(os.environ) até o fim do teste

    def _ler(self, silencio, fala):
        os.environ["SILENCE_THRESHOLD"], os.environ["SPEECH_THRESHOLD"] = silencio, fala
        cfg = ConfigManager()
        return cfg.silence_threshold, cfg.speech_threshold

    def test_valor_valido_vale(self):
        self.assertEqual((0.02, 0.03), self._ler("0.02", "0.03"))
        self.assertEqual((0.0001, 0.5), self._ler("0.0001", "0.5"))

    def test_valor_torto_volta_ao_padrao_sem_derrubar(self):
        for torto in ("abc", "0,02", "nan", "inf", "-0.01", "0", "0.6", ""):
            with self.subTest(torto=torto):
                self.assertEqual((0.005, 0.009), self._ler(torto, torto))


if __name__ == "__main__":
    unittest.main()
