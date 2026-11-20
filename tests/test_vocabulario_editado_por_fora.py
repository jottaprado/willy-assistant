"""
Vocabulário editado por fora (a bandeja abre o arquivo no Bloco de Notas).

Com a janela voltando da bandeja sem reler, a aba mostrava o texto velho e o próximo
auto-save gravava por cima, apagando o que foi editado no Bloco de Notas. Reler não pode
apagar o que a pessoa digitou na aba e o auto-save ainda não gravou.
"""

import unittest
from unittest.mock import patch

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.tabs.tab_vocabulary import build_tab_vocabulary


class TestVocabularioEditadoPorFora(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def setUp(self):
        self.disco = {"vocab": "Groq\nWhisper", "grava": True}

        def _salvar(texto):
            if self.disco["grava"]:
                self.disco["vocab"] = texto
            return self.disco["grava"]

        self.aba = build_tab_vocabulary(self.root, callbacks={
            "get_vocab": lambda: self.disco["vocab"],
            "on_save_vocab": _salvar,
        })
        self.addCleanup(self.aba.destroy)

    def _na_tela(self):
        return self.aba.txt_vocab.get("1.0", "end").strip()

    def _digitar(self, texto):
        self.aba.txt_vocab.insert("end", texto)
        self.aba._on_vocab_keyrelease()

    def test_rele_o_que_mudou_no_disco(self):
        self.disco["vocab"] = "Groq\nWhisper\nKubernetes"  # o Bloco de Notas
        self.aba.recarregar_se_nao_editado()
        self.assertEqual("Groq\nWhisper\nKubernetes", self._na_tela())

    def test_nao_apaga_o_que_o_auto_save_ainda_nao_gravou(self):
        self._digitar("\nDocker")
        self.disco["vocab"] = "outra coisa"
        self.aba.recarregar_se_nao_editado()
        self.assertIn("Docker", self._na_tela())

    def test_depois_de_gravado_volta_a_reler(self):
        self._digitar("\nDocker")
        self.aba.salvar_vocabulario()  # o que o auto-save chama
        self.disco["vocab"] = "Groq\nWhisper\nDocker\nKubernetes"
        self.aba.recarregar_se_nao_editado()
        self.assertEqual("Groq\nWhisper\nDocker\nKubernetes", self._na_tela())

    def test_gravacao_falha_mantem_o_texto_da_tela(self):
        self.disco["grava"] = False
        self._digitar("\nDocker")
        self.aba.salvar_vocabulario()
        self.aba.recarregar_se_nao_editado()
        self.assertIn("Docker", self._na_tela())

    def test_importado_que_nao_gravou_nao_e_apagado(self):
        self.disco["grava"] = False
        with patch("tkinter.filedialog.askopenfilename", return_value="importado.txt"), \
             patch("builtins.open", unittest.mock.mock_open(read_data="Importado")):
            self.aba._importar_vocabulario()
        self.aba.recarregar_se_nao_editado()
        self.assertEqual("Importado", self._na_tela())


if __name__ == "__main__":
    unittest.main()
