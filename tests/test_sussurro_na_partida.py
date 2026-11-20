"""
O Modo Sussurro salvo nos Ajustes vale desde a partida do Willy.

Só o dashboard_save_settings chamava audio_mgr.set_whisper_mode. Na partida, o AudioManager
nascia com o modo desligado e o ganho do slider, e a pessoa que deixou o sussurro ligado
ditava baixo sem o ganho de 3x até salvar os Ajustes de novo.
"""

import unittest

from core.audio import AudioManager
from tests.willy_isolado import rodar_no_willy


class TestAudioManager(unittest.TestCase):
    def test_nasce_com_o_sussurro_ligado(self):
        mgr = AudioManager(gain_boost=1.5, whisper_mode=True)
        self.assertTrue(mgr.whisper_mode)
        self.assertEqual(3.0, mgr.gain_boost)

    def test_sem_sussurro_fica_o_ganho_do_slider(self):
        mgr = AudioManager(gain_boost=1.5)
        self.assertFalse(mgr.whisper_mode)
        self.assertEqual(1.5, mgr.gain_boost)

    def test_desligar_depois_volta_ao_ganho_do_slider(self):
        mgr = AudioManager(gain_boost=1.5, whisper_mode=True)
        mgr.set_whisper_mode(False, 1.5)
        self.assertEqual(1.5, mgr.gain_boost)


# O .env da pasta (no clone de quem desenvolve, o de verdade) não pode decidir o teste: o
# load_dotenv fica mudo, e o modo vem do ambiente que o teste escolhe.
_SCRIPT = r"""
import json, os, sys
os.environ["WHISPER_MODE"] = sys.argv[1]
os.environ["MIC_GAIN"] = "1.5"
import core.config
core.config.load_dotenv = lambda *a, **k: False
import willy
print("RESULTADO=" + json.dumps({"sussurro": willy.audio_mgr.whisper_mode, "ganho": willy.audio_mgr.gain_boost}))
"""


class TestPartidaDoWilly(unittest.TestCase):
    def test_sussurro_salvo_vale_na_partida(self):
        self.assertEqual({"sussurro": True, "ganho": 3.0}, rodar_no_willy(_SCRIPT, "true"))

    def test_sem_sussurro_a_partida_usa_o_ganho_salvo(self):
        self.assertEqual({"sussurro": False, "ganho": 1.5}, rodar_no_willy(_SCRIPT, "false"))


if __name__ == "__main__":
    unittest.main()
