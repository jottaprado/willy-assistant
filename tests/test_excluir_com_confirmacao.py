"""
Excluir um template ou uma substituição pede confirmação, como no Histórico.

Os dois excluíam no primeiro clique, sem confirmar nem desfazer: um clique fora do lugar
apagava um template que a pessoa tinha escrito à mão.
"""

import unittest
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.tabs.tab_history import HistoryTab
from ui.tabs.tab_templates import build_tab_templates
from ui.tabs.tab_vocabulary import build_tab_vocabulary


def _botoes(widget, texto):
    achados = []
    for filho in widget.winfo_children():
        if isinstance(filho, ctk.CTkButton) and filho.cget("text") == texto:
            achados.append(filho)
        achados += _botoes(filho, texto)
    return achados


def _modais(widget):
    achados = []
    for filho in widget.winfo_children():
        if isinstance(filho, ctk.CTkToplevel):
            achados.append(filho)
        achados += _modais(filho)
    return achados


class _BaseTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def tearDown(self):
        destruir_tk(*self.root.winfo_children())


class TestTemplates(_BaseTk):
    def _aba(self):
        self.excluir = MagicMock(return_value=True)
        return build_tab_templates(self.root, callbacks={
            "get_snippets": lambda: [{"trigger": "meu pix", "title": "Pix", "content": "chave"}],
            "on_delete_snippet": self.excluir,
        })

    def test_o_botao_excluir_so_abre_a_confirmacao(self):
        aba = self._aba()
        (botao,) = _botoes(aba, "Excluir")
        botao.invoke()
        self.excluir.assert_not_called()
        self.assertEqual(1, len(_modais(aba)))

    def test_confirmar_exclui_e_cancelar_nao(self):
        aba = self._aba()
        aba.confirmar_excluir_snippet("meu pix").btn_cancelar.invoke()
        self.excluir.assert_not_called()
        aba.confirmar_excluir_snippet("meu pix").btn_excluir.invoke()
        self.excluir.assert_called_once_with("meu pix")

    def test_atalhos_escape_e_return_no_modal(self):
        aba = self._aba()
        modal_esc = aba.confirmar_excluir_snippet("meu pix")
        self.assertTrue(modal_esc.bind("<Escape>"), "Modal confirmar_exclusao deve vincular <Escape>")
        self.assertTrue(modal_esc.bind("<Return>"), "Modal confirmar_exclusao deve vincular <Return>")
        modal_esc.cancelar()
        self.assertFalse(modal_esc.winfo_exists())
        self.excluir.assert_not_called()

        modal_ret = aba.confirmar_excluir_snippet("meu pix")
        modal_ret.confirmar()
        self.assertFalse(modal_ret.winfo_exists())
        self.excluir.assert_called_once_with("meu pix")


class TestSubstituicoes(_BaseTk):
    def _aba(self):
        self.excluir = MagicMock(return_value=True)
        return build_tab_vocabulary(self.root, callbacks={
            "get_replacements": lambda: {"postgre": "PostgreSQL"},
            "on_delete_replacement": self.excluir,
        })

    def test_o_botao_excluir_so_abre_a_confirmacao(self):
        aba = self._aba()
        (botao,) = _botoes(aba, "Excluir")
        botao.invoke()
        self.excluir.assert_not_called()
        self.assertEqual(1, len(_modais(aba)))

    def test_confirmar_exclui_e_cancelar_nao(self):
        aba = self._aba()
        aba.confirmar_excluir_replacement("postgre", "PostgreSQL").btn_cancelar.invoke()
        self.excluir.assert_not_called()
        aba.confirmar_excluir_replacement("postgre", "PostgreSQL").btn_excluir.invoke()
        self.excluir.assert_called_once_with("postgre")


class TestHistoricoUsaOMesmoModal(unittest.TestCase):
    def test_confirmar_chama_a_exclusao_do_item(self):
        aba, item = MagicMock(), {"id": 7, "text": "x"}
        with patch("ui.tabs.tab_history.confirmar_exclusao") as confirmar:
            HistoryTab._confirmar_excluir_item(aba, item)
        _, titulo, _, ao_confirmar = confirmar.call_args.args
        self.assertEqual("Excluir Transcrição", titulo)
        aba._excluir_item.assert_not_called()
        ao_confirmar()
        aba._excluir_item.assert_called_once_with(item)

    def test_limpar_historico_reutiliza_confirmar_exclusao(self):
        aba = MagicMock()
        with patch("ui.tabs.tab_history.confirmar_exclusao") as confirmar, \
             patch("ui.tabs.tab_history.ctk.CTkToplevel", side_effect=AssertionError("Deve reutilizar confirmar_exclusao")):
            HistoryTab._abrir_modal_confirmar_limpeza(aba)
        confirmar.assert_called_once()
        _, titulo, _, ao_confirmar = confirmar.call_args.args
        self.assertEqual("Limpar Todo o Histórico", titulo)
        self.assertEqual("Limpar Tudo", confirmar.call_args.kwargs.get("rotulo_confirmar"))
        aba._confirmar_limpar_historico.assert_not_called()
        ao_confirmar()
        aba._confirmar_limpar_historico.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
