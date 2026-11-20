"""
Restaurar um perfil traz a duração de cada ditado e o vocabulário vazio.

- O histórico restaurado perdia o duration_s: as métricas de palavras por minuto deixavam de
  contar todos os ditados importados.
- Um perfil exportado com o vocabulário vazio não o esvaziava: ficava o vocabulário de agora.
"""

import json
import math
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from core.storage.profile_manager import ProfileManager


class TestPerfilDuracaoEVocabularioVazio(unittest.TestCase):
    def _importar(self, dados):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        caminho = os.path.join(pasta.name, "perfil.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f)
        self.config = MagicMock()
        self.config.outputs_dir = pasta.name
        self.config.chave_configurada.return_value = ""
        self.assertTrue(ProfileManager(self.config).import_profile(caminho))

    def _historico_restaurado(self, duracao):
        self._importar({"history": [{"text": "um ditado", "duration_s": duracao}]})
        (entrada,) = self.config.history_store.save_history.call_args.args[0]
        return entrada

    def test_duracao_valida_fica(self):
        for duracao in (12.5, 3, 0):
            with self.subTest(duracao=duracao):
                entrada = self._historico_restaurado(duracao)
                self.assertEqual(float(duracao), entrada["duration_s"])
                self.assertIsInstance(entrada["duration_s"], float)

    def test_duracao_invalida_sai(self):
        # json.dump grava NaN e Infinity, e o json.load os lê de volta.
        for duracao in (-1, "12", True, None, math.nan, math.inf, [3]):
            with self.subTest(duracao=duracao):
                self.assertNotIn("duration_s", self._historico_restaurado(duracao))

    def test_vocabulario_vazio_esvazia(self):
        self._importar({"vocabulary": ""})
        self.config.save_vocab_text.assert_called_once_with("")

    def test_perfil_sem_vocabulario_nao_mexe(self):
        for dados in ({}, {"vocabulary": None}, {"vocabulary": ["Docker"]}):
            with self.subTest(dados=dados):
                self._importar(dados)
                self.config.save_vocab_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
