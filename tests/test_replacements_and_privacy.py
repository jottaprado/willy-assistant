"""
Testes unitários para Dicionário de Auto-Correção Fonética e Modo Privado (Zero-Retention).
"""

import os
import unittest

from core.config import ConfigManager
from core.text_processing import TextProcessor
from tests.config_isolada import isolar_config


class TestReplacementsAndPrivacy(unittest.TestCase):

    def setUp(self):
        # O import_profile grava o vocabulário: sem isolar o VOCAB_FILE, ele regravava o
        # vocabulario.txt da raiz do repositório (achado do 2º juiz do 7A).
        self.tmp_dir_name = isolar_config(self)

    def test_apply_replacements_word_boundaries(self):
        regras = {
            "jota": "Jotta Prado",
            "k8s": "Kubernetes",
            "pr": "Pull Request"
        }

        texto = "Eu conversei com o jota sobre o novo pr no cluster k8s."
        resultado = TextProcessor.apply_replacements(texto, regras)
        self.assertEqual(resultado, "Eu conversei com o Jotta Prado sobre o novo Pull Request no cluster Kubernetes.")

        # Teste de proteção contra substituição indevida em substrings
        texto_preservado = "A lojota da calçada precisa ser reparada antes de projetar o prédio."
        resultado_preservado = TextProcessor.apply_replacements(texto_preservado, regras)
        self.assertEqual(resultado_preservado, texto_preservado)

    def test_apply_replacements_case_insensitive(self):
        regras = {"react": "React.js"}
        texto = "Eu adoro REACT e desenvolvo em react diariamente."
        resultado = TextProcessor.apply_replacements(texto, regras)
        self.assertEqual(resultado, "Eu adoro React.js e desenvolvo em React.js diariamente.")

    def test_apply_replacements_empty_or_none(self):
        self.assertEqual(TextProcessor.apply_replacements("teste", {}), "teste")
        self.assertEqual(TextProcessor.apply_replacements("teste", None), "teste")
        self.assertEqual(TextProcessor.apply_replacements("", {"a": "b"}), "")

    def test_config_manager_replacements_crud(self):
        cfg = ConfigManager()

        # Inicialmente vazio
        self.assertEqual(cfg.load_replacements(), {})

        # Adiciona regra
        cfg.add_replacement("willi", "Willy")
        reps = cfg.load_replacements()
        self.assertIn("willi", reps)
        self.assertEqual(reps["willi"], "Willy")

        # Adiciona segunda regra
        cfg.add_replacement("ia", "Inteligência Artificial")
        reps = cfg.load_replacements()
        self.assertEqual(len(reps), 2)

        # Deleta regra
        cfg.delete_replacement("willi")
        reps_after = cfg.load_replacements()
        self.assertNotIn("willi", reps_after)
        self.assertIn("ia", reps_after)

    def test_config_manager_private_mode_and_export_profile(self):
        cfg = ConfigManager()

        # Padrão é False
        self.assertFalse(cfg.private_mode)

        # Ativa private_mode
        cfg.save_settings({"PRIVATE_MODE": True})
        self.assertTrue(cfg.private_mode)

        cfg.add_replacement("de_teste", "para_teste")

        # Exporta perfil
        export_path = os.path.join(self.tmp_dir_name, "perfil_exportado.json")
        ok_exp = cfg.export_profile(export_path)
        self.assertTrue(ok_exp)

        # Reinicializa configurações em outro objeto
        cfg2 = ConfigManager()
        cfg2.private_mode = False
        cfg2.save_replacements({})

        # Importa perfil
        ok_imp = cfg2.import_profile(export_path)
        self.assertTrue(ok_imp)
        self.assertTrue(cfg2.private_mode)
        reps_importadas = cfg2.load_replacements()
        self.assertEqual(reps_importadas.get("de_teste"), "para_teste")


if __name__ == "__main__":
    unittest.main()
