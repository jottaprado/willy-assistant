"""
O modo preferido conta o ditado enviado com Enter ("send") como ditado.

Contado à parte, quem dita e envia via "Tradução EN" (ou "Reunião") com um item a mais.
"""

import unittest

from core.analytics.metrics import calculate_analytics_metrics


def _historico(**modos):
    return [{"text": "x", "words": 1, "timestamp": "01/01/2026 10:00:00", "mode": modo}
            for modo, quantos in modos.items() for _ in range(quantos)]


class TestModoPreferidoContaOEnvio(unittest.TestCase):
    def test_ditado_com_enter_conta_como_ditado(self):
        for outro, nome in (("translate", "traduções"), ("meeting", "reuniões")):
            with self.subTest(contra=nome):
                metricas = calculate_analytics_metrics(_historico(send=3, transcribe=1, **{outro: 2}))
                self.assertEqual("Ditado PT", metricas["favorite_mode"])

    def test_so_enviando_tambem_e_ditado(self):
        self.assertEqual("Ditado PT", calculate_analytics_metrics(_historico(send=2, translate=1))["favorite_mode"])

    def test_mais_traducao_que_ditado_somado(self):
        self.assertEqual("Tradução EN",
                         calculate_analytics_metrics(_historico(send=1, transcribe=1, translate=3))["favorite_mode"])

    def test_mais_reuniao_que_ditado_somado(self):
        self.assertEqual("Reunião",
                         calculate_analytics_metrics(_historico(send=1, transcribe=1, meeting=3))["favorite_mode"])


if __name__ == "__main__":
    unittest.main()
