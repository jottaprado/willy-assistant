"""
Busca na aba Atalhos: o que aparece fica na ordem original e seção sem resultado some.

As linhas ficavam soltas no frame da aba. Cada uma que reaparecia na busca era
reempacotada no FIM da aba (um pack() avulso põe o widget no fim), depois da seção de
Pontuação, e os títulos das seções ficavam na tela mesmo sem nenhum item.
"""

import unittest

import customtkinter as ctk

from ui.tabs.tab_shortcuts import build_tab_shortcuts

ORDEM_DAS_SECOES = ["DITADO", "TRANSFORMAÇÃO COM IA", "FERRAMENTAS", "SISTEMA", "COMANDOS DE VOZ PARA PONTUAÇÃO"]


class TestBuscaAtalhos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.aba = build_tab_shortcuts(self.root)
        self.addCleanup(self.aba.destroy)
        self.por_titulo = {s["titulo"]: s for s in self.aba.secoes}
        self.ordem_das_linhas = {s["titulo"]: [i["widget"] for i in s["itens"]] for s in self.aba.secoes}

    def _secoes_na_tela(self):
        frames = {s["frame"]: s["titulo"] for s in self.aba.secoes}
        return [frames[w] for w in self.aba.pack_slaves() if w in frames]

    def _linhas_na_tela(self, titulo):
        secao = self.por_titulo[titulo]
        linhas = {i["widget"] for i in secao["itens"]}
        return [w for w in secao["frame"].pack_slaves() if w in linhas]

    def test_as_secoes_comecam_na_ordem(self):
        self.assertEqual(ORDEM_DAS_SECOES, self._secoes_na_tela())

    def test_buscar_e_limpar_volta_a_ordem_original(self):
        self.aba.filtrar("vírgula")      # só a Pontuação fica: as outras seções saem
        self.aba.filtrar("tradução")     # só a Tradução, no meio do DITADO
        self.aba.filtrar("")
        self.assertEqual(ORDEM_DAS_SECOES, self._secoes_na_tela())
        self.assertEqual(self.ordem_das_linhas["DITADO"], self._linhas_na_tela("DITADO"))

    def test_secao_sem_resultado_some(self):
        self.aba.filtrar("reunião")
        self.assertEqual(["DITADO"], self._secoes_na_tela())

    def test_resultado_fica_dentro_da_secao_dele(self):
        self.aba.filtrar("desfazer")
        self.assertEqual(["FERRAMENTAS"], self._secoes_na_tela())
        (linha,) = self._linhas_na_tela("FERRAMENTAS")
        self.assertIs(self.ordem_das_linhas["FERRAMENTAS"][1], linha)

    def test_pontuacao_tambem_filtra(self):
        self.aba.filtrar("vírgula")
        self.assertEqual(["COMANDOS DE VOZ PARA PONTUAÇÃO"], self._secoes_na_tela())


if __name__ == "__main__":
    unittest.main()
