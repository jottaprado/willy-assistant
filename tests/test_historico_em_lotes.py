"""
A página do Histórico sai em lotes: os primeiros cartões na hora, o resto entre voltas do laço
de eventos.

Os 20 cartões de uma página levavam ~1,6 s seguidos na thread da interface (medido no Bloco
5). Agora o que aparece sem rolar sai na hora e o resto vem em lotes curtos, sem mudar o
resultado final, e um lote pendente não sobrevive à lista refeita nem à aba destruída.
"""

import datetime
import time
import unittest

import customtkinter as ctk

from tests.willy_isolado import _widgets, destruir_tk
from ui.tabs import tab_history
from ui.tabs.tab_history import CARTOES_NA_HORA, PAGINA_DE_CARTOES, HistoryTab


def _itens(n, datas=("23/10/2026 10:00",)):
    return [{"id": str(i), "timestamp": datas[i * len(datas) // n], "mode": "transcribe", "words": 4,
             "text": f"Item {i}: um ditado de teste"} for i in range(n)]


class TestPaginaEmLotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.geometry("900x700+-4000+-4000")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        fim = time.time() + 0.3
        while time.time() < fim:
            cls.root.update()
            time.sleep(0.01)
        destruir_tk(cls.root)

    def _aba(self, itens):
        aba = HistoryTab(self.root, callbacks={}, history_items=itens)
        self.addCleanup(aba.destroy)
        aba.pack(fill="both", expand=True)
        return aba

    def _terminar(self, aba):
        fim = time.time() + 10
        while aba._lote_agendado is not None and time.time() < fim:
            self.root.update()
            time.sleep(0.005)
        self.root.update()

    def _textos(self, aba):
        return [l.cget("text") for l in _widgets(aba.scroll_historico, ctk.CTkLabel)
                if l.cget("text").startswith("Item ")]

    def _mais(self, aba):
        return [b for b in _widgets(aba.scroll_historico, ctk.CTkButton) if b.cget("text").startswith("Mostrar mais")]

    def test_os_primeiros_cartoes_saem_na_hora_e_o_resto_depois(self):
        aba = self._aba(_itens(PAGINA_DE_CARTOES + 10))
        aba.atualizar_lista_historico()
        self.assertEqual(CARTOES_NA_HORA, len(self._textos(aba)), "a página inteira saiu de uma vez")
        self.assertEqual([], self._mais(aba), "o botão vem só com a página completa")
        self._terminar(aba)
        self.assertEqual(PAGINA_DE_CARTOES, len(self._textos(aba)))
        self.assertEqual(["Mostrar mais (10)"], [b.cget("text") for b in self._mais(aba)])

    def test_mesma_lista_e_mesmos_grupos_de_data_que_de_uma_vez(self):
        # Os quatro grupos de data na mesma página, com as trocas de grupo caindo dentro e na
        # borda dos lotes: cada cabeçalho aparece uma vez, na ordem.
        agora = datetime.datetime.now()
        datas = tuple((agora - datetime.timedelta(days=d)).strftime("%d/%m/%Y %H:%M") for d in (400, 3, 1, 0))
        itens = _itens(PAGINA_DE_CARTOES, datas)  # do mais antigo ao de hoje; a lista mostra ao contrário
        aba = self._aba(itens)
        aba.atualizar_lista_historico()
        self._terminar(aba)
        self.assertEqual([it["text"] for it in reversed(itens)], self._textos(aba))
        cabecalhos = [l.cget("text") for l in _widgets(aba.scroll_historico, ctk.CTkLabel)
                      if l.cget("text") in ("HOJE", "ONTEM", "ESTA SEMANA", "ANTERIORES")]
        self.assertEqual(["HOJE", "ONTEM", "ESTA SEMANA", "ANTERIORES"], cabecalhos)

    def test_lista_curta_refeita_no_meio_da_pagina_mostra_so_a_nova(self):
        # O cancelamento em si é provado pelos dois testes seguintes: aqui, o lote órfão não
        # teria o que desenhar (a lista nova cabe nos primeiros cartões).
        aba = self._aba(_itens(PAGINA_DE_CARTOES + 10))
        aba.atualizar_lista_historico()  # 6 na tela, lote pendente
        aba.history_items = _itens(3)
        aba.atualizar_lista_historico()
        self._terminar(aba)
        self.assertEqual(["Item 2: um ditado de teste", "Item 1: um ditado de teste", "Item 0: um ditado de teste"],
                         self._textos(aba), "sobrou cartão da lista de antes")

    def test_lista_longa_refeita_no_meio_fica_com_um_botao_so(self):
        # Sem cancelar, o lote de antes seguia junto com o da lista nova: duas correntes de
        # lotes, e o "Mostrar mais" saía duas vezes.
        aba = self._aba(_itens(PAGINA_DE_CARTOES + 10))
        aba.atualizar_lista_historico()
        aba.history_items = _itens(PAGINA_DE_CARTOES + 5)
        aba.atualizar_lista_historico()
        self._terminar(aba)
        fim = time.time() + 0.3  # a corrente órfã, se houver, também termina
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(PAGINA_DE_CARTOES, len(self._textos(aba)))
        self.assertEqual(["Mostrar mais (5)"], [b.cget("text") for b in self._mais(aba)])

    def test_busca_sem_resultado_no_meio_da_pagina_nao_traz_cartao_velho(self):
        # A lista vazia sai antes de começar página nova: só o cancelamento no começo do
        # atualizar impede o lote pendente de desenhar a lista de antes debaixo do aviso.
        aba = self._aba(_itens(PAGINA_DE_CARTOES + 10))
        aba.atualizar_lista_historico()
        aba.entry_busca.insert(0, "nada casa com isto")
        aba.atualizar_lista_historico()
        fim = time.time() + 0.3
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual([], self._textos(aba))

    def _rolagem(self, aba):
        return aba.scroll_historico._parent_canvas.canvasy(0)

    def test_lista_refeita_mantem_a_rolagem(self):
        # Achado do juiz: rolado na metade, refazer a lista (excluir um item, chegar um ditado)
        # mandava a rolagem para cima, porque a lista encolhia para os 6 primeiros cartões.
        aba = self._aba(_itens(PAGINA_DE_CARTOES + 10))
        aba.atualizar_lista_historico()
        self._terminar(aba)
        aba.scroll_historico._parent_canvas.yview_moveto(0.5)
        self.root.update()
        antes = self._rolagem(aba)
        self.assertGreater(antes, 0)
        aba.atualizar_lista_historico()
        self._terminar(aba)
        self.assertEqual(antes, self._rolagem(aba))

    def test_lista_no_topo_continua_saindo_em_lotes(self):
        aba = self._aba(_itens(PAGINA_DE_CARTOES + 10))
        aba.atualizar_lista_historico()
        self._terminar(aba)
        aba.atualizar_lista_historico()  # no topo: nada a cobrir
        self.assertEqual(CARTOES_NA_HORA, len(self._textos(aba)))

    def test_aba_destruida_no_meio_da_pagina_nao_deixa_lote(self):
        erros = []
        self.root.tk.createcommand("bgerror", lambda *msg: erros.append(msg))
        self.addCleanup(self.root.tk.deletecommand, "bgerror")
        aba = HistoryTab(self.root, callbacks={}, history_items=_itens(PAGINA_DE_CARTOES))
        aba.pack()
        aba.atualizar_lista_historico()
        aba.destroy()
        fim = time.time() + 0.3
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual([], erros)

    def test_o_bloqueio_inicial_e_uma_fracao_da_pagina(self):
        # O que fica na thread da interface de uma vez: CARTOES_NA_HORA de PAGINA_DE_CARTOES.
        self.assertLessEqual(CARTOES_NA_HORA * 3, PAGINA_DE_CARTOES)
        self.assertGreater(tab_history.CARTOES_POR_LOTE, 0)


if __name__ == "__main__":
    unittest.main()
