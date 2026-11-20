"""
A largura da pílula acompanha a escala em que o Tk desenha a fonte (125%, 150%).

A 100% as mensagens longas cabem (medido no Bloco 6B: a mais longa ocupa 401 px de texto
numa pílula de 520). Com a escala maior a fonte cresce e a pílula ficava nos 340–520 de 100%:
o fim da mensagem ("…Clique p/ reenviar") passava da borda.
"""

import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import patch

from ui.overlays import pill as pill_mod
from ui.overlays.pill import LARGURA_MAX, LARGURA_MIN, FloatingPill, largura_para

LONGAS = (
    "Nada para colar nesse áudio. Áudios salvos: 2. Clique p/ reenviar",
    "Copiado: cole onde quiser. Áudios salvos: 12. Clique p/ reenviar",
    "Transcrito, mas não consegui copiar. O texto ficou no histórico",
)
X_DO_TEXTO = 52  # onde o texto começa no canvas da pílula


class TestLarguraPara(unittest.TestCase):
    def test_a_100_porcento_nada_muda(self):
        self.assertEqual(LARGURA_MIN, largura_para("ok"))
        self.assertEqual(LARGURA_MAX, largura_para("x" * 200))
        self.assertEqual(largura_para(LONGAS[0]), largura_para(LONGAS[0], 1.0))

    def test_limites_crescem_com_a_escala(self):
        self.assertEqual(round(LARGURA_MIN * 1.5), largura_para("ok", 1.5))
        self.assertEqual(round(LARGURA_MAX * 1.5), largura_para("x" * 200, 1.5))
        self.assertEqual(round((70 + 50 * 7) * 1.25), largura_para("x" * 50, 1.25))

    def test_abaixo_de_100_porcento_fica_nos_limites_de_100(self):
        # Só cresce acima de 1.0; o Tk desta máquina dá 0,999 (95,9 ppp) e não pode encolher.
        self.assertEqual(LARGURA_MIN, largura_para("ok", 0.8))
        self.assertEqual(LARGURA_MAX, largura_para("x" * 200, 0.8))
        self.assertEqual(largura_para("x" * 40), largura_para("x" * 40, 0.8))

    def test_nunca_passa_da_largura_util_do_monitor(self):
        self.assertEqual(600, largura_para("x" * 200, 1.5, largura_util=600))
        self.assertEqual(300, largura_para("ok", 1.5, largura_util=300), "nem o mínimo passa da tela")


class _PilulaNaEscala(unittest.TestCase):
    """Uma raiz com o `tk scaling` da escala pedida: é por ele que o Tk mede a fonte."""

    escala = 1.0

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        # O `tk scaling` vale para o display, não só para esta raiz: os testes seguintes do
        # mesmo processo o herdariam (medido). Volta ao de antes no fim.
        antes = self.root.tk.call("tk", "scaling")
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", antes))
        self.root.tk.call("tk", "scaling", self.escala * 96 / 72)
        self.pill = FloatingPill(self.root)
        self.addCleanup(self.pill.destroy)
        self.fonte = tkfont.Font(root=self.root, family="Segoe UI", size=10, weight="bold")

    def _cabe(self, msg):
        with patch.object(self.pill, "_largura_util", return_value=None):
            self.pill.show_state("offline_retry", msg)
        return X_DO_TEXTO + self.fonte.measure(msg) <= self.pill.width, (self.fonte.measure(msg), self.pill.width)


class TestMensagemLongaCabeA125(_PilulaNaEscala):
    escala = 1.25

    def test_cabe(self):
        self.assertAlmostEqual(1.25, self.pill._escala(), places=2)
        for msg in LONGAS:
            with self.subTest(msg=msg):
                cabe, medidas = self._cabe(msg)
                self.assertTrue(cabe, f"texto e pílula: {medidas}")


class TestMensagemLongaCabeA150(_PilulaNaEscala):
    escala = 1.5

    def test_cabe(self):
        for msg in LONGAS:
            with self.subTest(msg=msg):
                cabe, medidas = self._cabe(msg)
                self.assertTrue(cabe, f"texto e pílula: {medidas}")

    def test_monitor_estreito_e_o_teto(self):
        with patch.object(self.pill, "_largura_util", return_value=450):
            self.pill.show_state("offline_retry", LONGAS[0])
        self.assertEqual(450, self.pill.width)


class TestTrocaDeTelaDepoisDeCriada(_PilulaNaEscala):
    """Achado do verificador: uma troca de tela faz o Tk reler o DPI, mas a fonte já criada da
    pílula não cresce. A largura tem de seguir a escala da fonte, não a nova."""

    def test_escala_que_muda_depois_nao_alarga_a_pilula(self):
        self.root.tk.call("tk", "scaling", 2.0 * 96 / 72)  # o Tk agora diz 200%
        with patch.object(self.pill, "_largura_util", return_value=None):
            self.pill.show_state("offline_retry", LONGAS[0])
        self.assertEqual(largura_para(LONGAS[0], 1.0), self.pill.width)


class TestLarguraUtilDoMonitor(_PilulaNaEscala):
    def test_escondida_usa_o_monitor_onde_vai_aparecer(self):
        with patch.object(self.pill, "_area_de_trabalho", return_value=(-1920, 0, 0, 1040)) as area, \
             patch.object(self.pill.root, "winfo_viewable", return_value=0):
            self.assertEqual(1920 - 2 * pill_mod.MARGEM_LATERAL_CURSOR, self.pill._largura_util())
        self.assertEqual(self.pill._get_position(), area.call_args.args[0])

    def test_visivel_usa_o_monitor_em_que_esta(self):
        self.pill.root.geometry("340x48+-1500+600")
        self.pill.root.update_idletasks()
        with patch.object(self.pill, "_area_de_trabalho", return_value=(-1920, 371, 0, 1403)) as area, \
             patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.assertEqual(1920 - 2 * pill_mod.MARGEM_LATERAL_CURSOR, self.pill._largura_util())
        modo, ponto = area.call_args.args
        self.assertEqual("seguir_cursor", modo)  # o monitor de um ponto: o centro da pílula
        self.assertEqual((-1500 + 340 // 2, 600 + 48 // 2), ponto)


if __name__ == "__main__":
    unittest.main()
