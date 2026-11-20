"""
A aba Histórico não trava a interface.

Medido em 23/10/2026 nesta máquina, com 100 itens: refazer a lista levava de 13 a 14 s na
thread da interface. E ela era refeita depois de cada ditado mesmo com a janela escondida
(com a pílula esperando), a cada clique para expandir um cartão e duas vezes a cada tecla da
busca. Agora: uma página de 20 cartões por vez (cerca de 1,6 s), botões de ação criados no
primeiro hover, expandir troca só o texto do cartão, a busca espera a pessoa parar de digitar
e o dashboard escondido não refaz a lista.
"""

import time
import unittest
from unittest.mock import patch

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import _widgets, destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs import tab_history
from ui.tabs.tab_history import PAGINA_DE_CARTOES, HistoryTab


def _itens(n):
    return [{"id": str(i), "timestamp": "23/10/2026 10:00", "mode": "transcribe", "words": 40,
             "text": f"Item {i}: " + "refatorar o módulo de áudio para usar a taxa de 16 kHz " * 6}
            for i in range(n)]


def _bombear(root, segundos):
    fim = time.time() + segundos
    while time.time() < fim:
        root.update()
        time.sleep(0.01)


class _BaseAba(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Fora da tela, mas mapeada: o Tk não entrega eventos de mouse e teclado a uma janela
        # escondida, e os testes de hover, clique e tecla não provariam nada.
        cls.root = ctk.CTk()
        cls.root.geometry("900x700+-4000+-4000")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _aba(self, n):
        aba = HistoryTab(self.root, callbacks={}, history_items=_itens(n))
        self.addCleanup(aba.destroy)
        aba.pack(fill="both", expand=True)
        aba.atualizar_lista_historico()
        self._terminar_pagina(aba)
        return aba

    def _terminar_pagina(self, aba):
        """A página sai em lotes (ver CARTOES_NA_HORA): espera o último."""
        fim = time.time() + 10
        while aba._lote_agendado is not None and time.time() < fim:
            self.root.update()
            time.sleep(0.005)
        self.root.update()

    @staticmethod
    def _evento(rotulo, sequencia):
        # O CTkLabel liga os binds no tk.Label de dentro dele.
        rotulo._label.event_generate(sequencia, when="now")

    def _textos(self, aba):
        return [l for l in _widgets(aba.scroll_historico, ctk.CTkLabel) if l.cget("text").startswith("Item ")]

    def _mais(self, aba):
        return [b for b in _widgets(aba.scroll_historico, ctk.CTkButton) if b.cget("text").startswith("Mostrar mais")]


class TestPaginas(_BaseAba):
    def test_uma_pagina_por_vez_ate_acabar(self):
        aba = self._aba(PAGINA_DE_CARTOES * 2 + 5)
        self.assertEqual(PAGINA_DE_CARTOES, len(self._textos(aba)))
        (mais,) = self._mais(aba)
        self.assertEqual(f"Mostrar mais ({PAGINA_DE_CARTOES + 5})", mais.cget("text"))

        mais.invoke()
        self._terminar_pagina(aba)
        self.assertEqual(PAGINA_DE_CARTOES * 2, len(self._textos(aba)))
        self._mais(aba)[0].invoke()
        self._terminar_pagina(aba)
        self.assertEqual(PAGINA_DE_CARTOES * 2 + 5, len(self._textos(aba)))
        self.assertEqual([], self._mais(aba))

    def test_mostrar_mais_nao_refaz_os_cartoes_ja_desenhados(self):
        aba = self._aba(PAGINA_DE_CARTOES + 3)
        primeiro = self._textos(aba)[0]
        self._mais(aba)[0].invoke()
        self._terminar_pagina(aba)
        self.assertIs(primeiro, self._textos(aba)[0])

    def test_lista_curta_sem_botao(self):
        self.assertEqual([], self._mais(self._aba(3)))


class TestCartao(_BaseAba):
    def test_botoes_de_acao_nascem_no_primeiro_hover(self):
        # O Copiar, sempre à vista desde o Bloco 11, é um CTkLabel: os CTkButton nascem no 1º hover.
        aba = self._aba(2)
        icones = lambda: [b for b in _widgets(aba.scroll_historico, ctk.CTkButton) if not b.cget("text")]
        self.assertEqual([], icones(), "os botões de ação eram criados para todo cartão desenhado")
        self._evento(self._textos(aba)[0], "<Enter>")
        self.assertEqual(4, len(icones()))  # Reusar, Abrir .md, Reformatar e Mais (sem áudio, sem Ouvir)

    def test_expandir_troca_so_o_texto_do_cartao(self):
        aba = self._aba(2)
        rotulo = self._textos(aba)[0]  # a lista é do mais novo para o mais antigo
        self.assertTrue(rotulo.cget("text").endswith("..."))
        (ver_mais,) = [l for l in _widgets(rotulo.master, ctk.CTkLabel) if l.cget("text") == "Ver mais"]
        with patch.object(aba, "atualizar_lista_historico") as refazer:
            self._evento(ver_mais, "<ButtonPress-1>")
        refazer.assert_not_called()
        self.assertEqual(_itens(2)[1]["text"], rotulo.cget("text"))
        self.assertIs(rotulo, self._textos(aba)[0])

    def test_duplo_clique_copia_mesmo_antes_do_hover(self):
        aba = self._aba(1)
        rotulo = self._textos(aba)[0]
        with patch.object(aba, "_copiar_com_feedback") as copiar:
            rotulo._label.event_generate("<ButtonPress-1>", when="now")
            rotulo._label.event_generate("<ButtonRelease-1>", when="now")
            self.assertEqual(1, copiar.call_count)
            self.assertEqual(_itens(1)[0]["text"], copiar.call_args.args[0])
            self.assertIsInstance(copiar.call_args.args[1], ctk.CTkLabel)
            rotulo._label.event_generate("<ButtonPress-1>", when="now")
            self.assertEqual(2, copiar.call_count)
            self.assertEqual(_itens(1)[0]["text"], copiar.call_args.args[0])


class TestBusca(_BaseAba):
    def test_varias_teclas_viram_uma_busca_so(self):
        aba = self._aba(3)
        with patch.object(aba, "atualizar_lista_historico") as refazer:
            for _ in range(5):
                aba.search_field._on_key_release(None)  # o que o SearchField faz a cada tecla
            refazer.assert_not_called()
            _bombear(self.root, tab_history.ESPERA_DA_BUSCA_MS / 1000 + 0.2)
        refazer.assert_called_once_with()

    def test_a_tecla_tem_um_dono_so(self):
        # O <KeyRelease> próprio da aba somava uma segunda reconstrução a cada tecla.
        script = self._aba(1).entry_busca._entry.bind("<KeyRelease>")
        handlers = [linha for linha in script.splitlines() if linha.strip().startswith("if {")]
        self.assertEqual(1, len(handlers), script)


class TestDashboardEscondido(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls.dash = WillyDashboard(callbacks={"get_history": lambda: _itens(5), "get_app_rules": list})
        cls.dash.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def test_depois_de_um_ditado_com_a_janela_escondida_nao_refaz_a_lista(self):
        with patch.object(self.dash, "atualizar_lista_historico") as refazer:
            self.dash.recarregar_dados()
        refazer.assert_not_called()
        self.assertEqual(5, len(self.dash.history_items), "os itens novos ficam guardados para quando abrir")

    def test_com_a_janela_aberta_refaz(self):
        with patch.object(self.dash, "atualizar_lista_historico") as refazer, \
             patch.object(self.dash, "state", return_value="normal"):
            self.dash.recarregar_dados()
        refazer.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
