"""
O áudio do sistema da reunião abre em estéreo quando o device recusa mono.

O loopback (Mixagem estéreo, o alto-falante via WASAPI) costuma só abrir com os dois canais
dele. Pedido só em mono, falhava, e a reunião saía sem o lado de lá da chamada.
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from core.audio import AudioManager


class TestAudioDoSistemaEstereo(unittest.TestCase):
    def _reuniao(self, aceita):
        """Abre a reunião com um device de sistema que só aceita os canais em `aceita`."""
        self.mgr = AudioManager()
        self.mgr.stream = MagicMock(active=True)  # start_recording exige microfone aberto
        self.mgr.system_device_index = 7
        self.sistema = MagicMock(name="stream do sistema")

        def _negociar(device, callback, canais, taxa):
            if canais not in aceita:
                raise RuntimeError(f"Invalid number of channels ({canais})")
            return self.sistema, 48000

        with patch("core.audio.negociar_stream", side_effect=_negociar) as negociar:
            self.assertTrue(self.mgr.start_recording("meeting"))
        return negociar

    def test_mono_recusado_abre_em_estereo(self):
        negociar = self._reuniao(aceita={2})
        self.assertIs(self.sistema, self.mgr.system_stream)
        self.assertEqual([1, 2], [c.args[2] for c in negociar.call_args_list])

    def test_mono_aceito_nem_tenta_estereo(self):
        negociar = self._reuniao(aceita={1})
        self.assertIs(self.sistema, self.mgr.system_stream)
        self.assertEqual([1], [c.args[2] for c in negociar.call_args_list])

    def test_nenhum_dos_dois_grava_so_o_microfone(self):
        self._reuniao(aceita=set())
        self.assertIsNone(self.mgr.system_stream)
        self.assertTrue(self.mgr.is_recording)

    def test_estereo_chega_mono_no_buffer(self):
        negociar = self._reuniao(aceita={2})
        callback = negociar.call_args.args[1]
        callback(np.array([[0.2, 0.4], [0.6, 0.8]], dtype=np.float32), 2, None, None)
        (bloco,) = self.mgr.system_buffer
        np.testing.assert_allclose(bloco, [[0.3], [0.7]])


if __name__ == "__main__":
    unittest.main()
