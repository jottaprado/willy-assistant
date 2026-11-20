"""
A aba Vocabulário só diz "Salvo" quando gravou.

save_vocab_text e as regras de substituição já devolviam se a gravação atômica deu certo,
mas a aba ignorava o retorno: com o arquivo bloqueado (antivírus, OneDrive, sem permissão),
mostrava "Salvo" e limpava os campos da regra, e a pessoa achava que os termos valiam no
próximo ditado.
"""

import os
import unittest
from unittest.mock import patch

import customtkinter as ctk

from core.config import ConfigManager
from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.tabs.tab_vocabulary import build_tab_vocabulary


class _BaseAba(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _aba(self, **callbacks):
        aba = build_tab_vocabulary(self.root, callbacks=callbacks)
        self.addCleanup(aba.destroy)
        return aba

    def _aviso_das_regras(self, aba):
        aba.update_idletasks()
        if aba.lbl_status_reps.winfo_manager() != "pack":
            return ""
        return aba.lbl_status_reps.cget("text")


class TestVocabulario(_BaseAba):
    def test_gravacao_que_falha_nao_diz_salvo(self):
        aba = self._aba(on_save_vocab=lambda _texto: False)
        aba.salvar_vocabulario()
        self.assertEqual("Não salvei. Tente de novo", aba.lbl_status_salvo.cget("text"))
        self.assertEqual("Salvar Vocabulário", aba.btn_salvar_vocab.cget("text"))

    def test_gravacao_que_funciona_diz_salvo(self):
        aba = self._aba(on_save_vocab=lambda _texto: True)
        aba.salvar_vocabulario()
        self.assertEqual("Salvo", aba.lbl_status_salvo.cget("text"))
        self.assertEqual("Salvo", aba.btn_salvar_vocab.cget("text"))

    def test_depois_de_uma_falha_o_proximo_salvar_volta_ao_normal(self):
        resultados = [False, True]
        aba = self._aba(on_save_vocab=lambda _texto: resultados.pop(0))
        aba.salvar_vocabulario()
        aba.salvar_vocabulario()
        self.assertEqual("Salvo", aba.lbl_status_salvo.cget("text"))


class TestRegras(_BaseAba):
    def _preencher(self, aba, de="postgre", para="PostgreSQL"):
        aba.entry_rep_de.insert(0, de)
        aba.entry_rep_para.insert(0, para)

    def test_regra_que_nao_grava_avisa_e_mantem_o_que_foi_digitado(self):
        aba = self._aba(on_save_replacement=lambda de, para: False, get_replacements=dict)
        self._preencher(aba)
        aba.adicionar_replacement()
        self.assertEqual('Não salvei a regra "postgre". Tente de novo', self._aviso_das_regras(aba))
        self.assertEqual("postgre", aba.entry_rep_de.get())
        self.assertEqual("PostgreSQL", aba.entry_rep_para.get())

    def test_regra_gravada_limpa_os_campos_e_o_aviso(self):
        resultados = [False, True]
        aba = self._aba(on_save_replacement=lambda de, para: resultados.pop(0), get_replacements=dict)
        self._preencher(aba)
        aba.adicionar_replacement()
        aba.adicionar_replacement()
        self.assertEqual("", self._aviso_das_regras(aba))
        self.assertEqual("", aba.entry_rep_de.get())

    def test_exclusao_que_falha_avisa(self):
        regras = {"postgre": "PostgreSQL"}
        aba = self._aba(on_delete_replacement=lambda de: False, get_replacements=lambda: dict(regras))
        aba.deletar_replacement("postgre")
        self.assertEqual('Não excluí a regra "postgre". Tente de novo', self._aviso_das_regras(aba))

    def test_regra_que_ja_nao_existia_nao_avisa(self):
        # O store devolve False também quando a regra não existe mais (apagada em outra janela).
        aba = self._aba(on_delete_replacement=lambda de: False, get_replacements=dict)
        aba.deletar_replacement("postgre")
        self.assertEqual("", self._aviso_das_regras(aba))

    def test_presets_que_nao_gravam_dizem_quantos(self):
        aba = self._aba(on_save_replacement=lambda de, para: de != "k8s", get_replacements=dict)
        aba.carregar_termos_tech_comuns()
        self.assertRegex(self._aviso_das_regras(aba), r"^1 de \d+ presets não foram salvos")
        self.assertEqual("Presets Tech", aba.btn_preset_tech.cget("text"))

    def test_presets_gravados(self):
        aba = self._aba(on_save_replacement=lambda de, para: True, get_replacements=dict)
        aba.carregar_termos_tech_comuns()
        self.assertEqual("", self._aviso_das_regras(aba))
        self.assertEqual("Presets carregados", aba.btn_preset_tech.cget("text"))


class TestComOConfigManagerDeVerdade(_BaseAba):
    """Os callbacks do willy.py são os métodos do ConfigManager; o disco recusa a gravação."""

    def setUp(self):
        isolar_config(self)
        os.environ["GROQ_API_KEY"] = "gsk_teste"
        self.config = ConfigManager()

    def _aba_do_willy(self):
        return self._aba(on_save_vocab=self.config.save_vocab_text,
                         on_save_replacement=self.config.add_replacement,
                         on_delete_replacement=self.config.delete_replacement,
                         get_replacements=self.config.load_replacements)

    def test_arquivo_bloqueado_nao_diz_salvo(self):
        aba = self._aba_do_willy()
        with patch("core.storage.vocabulary_store._atomic_write_text", side_effect=PermissionError("bloqueado")):
            aba.salvar_vocabulario()
        self.assertEqual("Não salvei. Tente de novo", aba.lbl_status_salvo.cget("text"))

    def test_regra_com_arquivo_bloqueado_avisa(self):
        aba = self._aba_do_willy()
        aba.entry_rep_de.insert(0, "jota")
        aba.entry_rep_para.insert(0, "Jotta Prado")
        with patch("core.storage.vocabulary_store._atomic_write_json", side_effect=PermissionError("bloqueado")):
            aba.adicionar_replacement()
        self.assertIn("Não salvei a regra", self._aviso_das_regras(aba))
        self.assertEqual({}, self.config.load_replacements())

    def test_disco_normal_diz_salvo(self):
        aba = self._aba_do_willy()
        aba.txt_vocab.insert("1.0", "Kubernetes")
        aba.salvar_vocabulario()
        self.assertEqual("Salvo", aba.lbl_status_salvo.cget("text"))
        self.assertIn("Kubernetes", self.config.load_vocab_text())


if __name__ == "__main__":
    unittest.main()
