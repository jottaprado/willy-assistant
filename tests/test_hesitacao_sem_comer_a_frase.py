"""
Tirar hesitações não come o ponto final da frase nem a palavra "hum".

- A pontuação de pausa em volta de "ééé" saía junto, e com ela o ponto que fechava a frase:
  "Terminei. Ééé, vamos" virava "Terminei vamos".
- "hum" com um m só saía como hesitação, mas em inglês é palavra: "I hum a song" virava
  "I a song".
"""

import unittest

from core.text_processing import TextProcessor


class TestHesitacaoSemComerAFrase(unittest.TestCase):
    def test_ponto_final_da_frase_fica(self):
        casos = {
            "Terminei. Ééé, vamos para o próximo": "Terminei. Vamos para o próximo",
            "Fechou, ééé. Vamos para o próximo": "Fechou. Vamos para o próximo",
            "Vamos começar, ééé.": "Vamos começar.",
            "Terminei. Humm": "Terminei.",
        }
        for entrada, saida in casos.items():
            with self.subTest(entrada):
                self.assertEqual(saida, TextProcessor.clean_filler_words(entrada))

    def test_reticencias_de_pausa_ainda_saem(self):
        self.assertEqual("Então vamos começar o projeto",
                         TextProcessor.clean_filler_words("então... ééé... vamos começar o projeto"))

    def test_hesitacao_no_comeco_nao_deixa_ponto_solto(self):
        self.assertEqual("Vamos lá", TextProcessor.clean_filler_words("Ééé. Vamos lá"))

    def test_hum_com_um_m_fica(self):
        self.assertEqual("I hum a song while I work", TextProcessor.clean_filler_words("I hum a song while I work"))

    def test_humm_ainda_sai(self):
        self.assertEqual("Precisamos analisar", TextProcessor.clean_filler_words("humm, precisamos analisar"))


if __name__ == "__main__":
    unittest.main()
