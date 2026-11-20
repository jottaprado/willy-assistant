"""
Testes unitários para a Trilogia de Produtividade do Willy:
1. Limpeza Inteligente de Hesitações e Cacoetes (clean_filler_words)
2. Configuração de Clipboard-Only e Clean-Fillers
3. Persistência de file_path no histórico e helper de abertura de arquivo
"""

import json
import os
import unittest
from unittest.mock import patch

from core.config import ConfigManager
from core.text_processing import TextProcessor
from tests.config_isolada import isolar_config


class TestProductivityFeatures(unittest.TestCase):

    def setUp(self):
        self.test_dir = isolar_config(self)

    def test_clean_filler_words_hesitations(self):
        # 1. Hesitações fonéticas (ééé, humm, uhmm)
        entrada = "então... ééé... vamos começar o projeto"
        saida = TextProcessor.clean_filler_words(entrada)
        self.assertEqual(saida, "Então vamos começar o projeto")

        entrada2 = "humm, precisamos analisar a arquitetura"
        saida2 = TextProcessor.clean_filler_words(entrada2)
        self.assertEqual(saida2, "Precisamos analisar a arquitetura")

    def test_clean_filler_words_verbal_ticks(self):
        # 2. Vícios compostos e interjeições (tipo assim, né)
        entrada = "precisamos tipo assim aprovar o pull request, né?"
        saida = TextProcessor.clean_filler_words(entrada)
        self.assertEqual(saida, "Precisamos aprovar o pull request?")

    def test_clean_filler_words_stutters(self):
        # 3. Gaguejos / repetições consecutivas
        entrada = "eu eu acho que que vai dar certo"
        saida = TextProcessor.clean_filler_words(entrada)
        self.assertEqual(saida, "Eu acho que vai dar certo")

    def test_clean_filler_words_preserves_legitimate_words(self):
        # 4. Preservação estrita de palavras legítimas
        texto_legitimo = "o projeto é muito bom e o néctar da fruta está na tábua"
        saida = TextProcessor.clean_filler_words(texto_legitimo)
        self.assertIn("é muito bom", saida)
        self.assertIn("néctar", saida)
        self.assertIn("tábua", saida)

    def test_config_clean_fillers_and_clipboard_only(self):
        cfg = ConfigManager()
        self.assertTrue(cfg.clean_fillers)
        self.assertFalse(cfg.clipboard_only)

        # Salva novas opções
        cfg.save_settings({
            "CLEAN_FILLERS": False,
            "CLIPBOARD_ONLY": True
        })
        self.assertFalse(cfg.clean_fillers)
        self.assertTrue(cfg.clipboard_only)

        # Recarrega do .env
        cfg2 = ConfigManager()
        self.assertFalse(cfg2.clean_fillers)
        self.assertTrue(cfg2.clipboard_only)

    def test_export_import_profile_preserves_new_settings(self):
        cfg = ConfigManager()
        cfg.save_settings({
            "CLEAN_FILLERS": False,
            "CLIPBOARD_ONLY": True
        })

        export_path = os.path.join(self.test_dir, "perfil_test.json")
        self.assertTrue(cfg.export_profile(export_path))

        with open(export_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("CLEAN_FILLERS", data["settings"])
        self.assertFalse(data["settings"]["CLEAN_FILLERS"])
        self.assertIn("CLIPBOARD_ONLY", data["settings"])
        self.assertTrue(data["settings"]["CLIPBOARD_ONLY"])

        # Restaura
        cfg.save_settings({"CLEAN_FILLERS": True, "CLIPBOARD_ONLY": False})
        self.assertTrue(cfg.clean_fillers)
        self.assertFalse(cfg.clipboard_only)

        self.assertTrue(cfg.import_profile(export_path))
        self.assertFalse(cfg.clean_fillers)
        self.assertTrue(cfg.clipboard_only)

    def test_history_item_stores_file_path(self):
        cfg = ConfigManager()
        caminho_md = os.path.join(self.test_dir, "2026-09-16_teste.md")
        cfg.save_history_item("Texto de ata importante", modo="meeting", file_path=caminho_md)

        hist = cfg.load_history()
        self.assertTrue(len(hist) >= 1)
        ultimo = hist[-1]
        self.assertEqual(ultimo["file_path"], caminho_md)

    def test_open_file_helper(self):
        # Arquivo inexistente deve retornar False
        self.assertFalse(ConfigManager.open_file("caminho_que_nao_existe_123.md"))

        # Arquivo existente deve retornar True (com mock de os.startfile para não abrir janela durante teste)
        arquivo_temp = os.path.join(self.test_dir, "temp_teste.md")
        with open(arquivo_temp, "w", encoding="utf-8") as f:
            f.write("# Teste")

        with patch("os.startfile", return_value=None):
            self.assertTrue(ConfigManager.open_file(arquivo_temp))


if __name__ == "__main__":
    unittest.main()
