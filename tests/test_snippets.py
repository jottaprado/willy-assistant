"""
Testes unitários para o módulo core.snippets.SnippetManager.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from core.snippets import DEFAULT_SNIPPETS, SnippetManager


class TestSnippetManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file = os.path.join(self.temp_dir.name, "test_snippets.json")
        self.mgr = SnippetManager(file_path=self.temp_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_snippets_loaded(self):
        snippets = self.mgr.get_snippets()
        self.assertGreater(len(snippets), 0)
        triggers = [s["trigger"] for s in snippets]
        self.assertIn("template de bug", triggers)

    def test_add_and_delete_snippet(self):
        self.mgr.save_snippet("meu teste", "Título do Teste", "Conteúdo personalizado")
        snippets = self.mgr.get_snippets()
        triggers = [s["trigger"] for s in snippets]
        self.assertIn("meu teste", triggers)

        # Deletar
        self.mgr.delete_snippet("meu teste")
        snippets_after = self.mgr.get_snippets()
        triggers_after = [s["trigger"] for s in snippets_after]
        self.assertNotIn("meu teste", triggers_after)

    def test_match_and_expand(self):
        self.mgr.save_snippet("template de bug", "Bug", "### BUG REPORT")
        
        # Correspondência exata
        res1 = self.mgr.match_and_expand("template de bug")
        self.assertEqual(res1, "### BUG REPORT")

        # Com prefixo "willy" ou "inserir"
        res2 = self.mgr.match_and_expand("willy template de bug")
        self.assertEqual(res2, "### BUG REPORT")

        res3 = self.mgr.match_and_expand("inserir template de bug")
        self.assertEqual(res3, "### BUG REPORT")

        # Texto normal sem match
        res_none = self.mgr.match_and_expand("olá mundo como vai")
        self.assertIsNone(res_none)


class TestSnippetsNaoSomem(unittest.TestCase):
    """JSON corrompido virava a lista padrão, e a gravação seguinte escrevia os padrões por
    cima: os snippets da pessoa sumiam."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.arquivo = os.path.join(self.temp_dir.name, "snippets.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _quarentenas(self):
        return [n for n in os.listdir(self.temp_dir.name) if ".corrompido-" in n]

    def test_corrompido_vai_para_quarentena_antes_de_gravar(self):
        mgr = SnippetManager(file_path=self.arquivo)
        mgr.save_snippet("meu atalho", "Meu", "conteúdo da pessoa")
        with open(self.arquivo, "r", encoding="utf-8") as f:
            original = f.read()
        with open(self.arquivo, "w", encoding="utf-8") as f:
            f.write(original[: len(original) // 2])  # JSON truncado por um desligamento
        with open(self.arquivo, encoding="utf-8") as f:
            truncado = f.read()

        self.assertTrue(mgr.save_snippet("novo", "Novo", "x"))
        (quarentena,) = self._quarentenas()
        with open(os.path.join(self.temp_dir.name, quarentena), encoding="utf-8") as f:
            self.assertEqual(truncado, f.read())
        self.assertIn("novo", [s["trigger"] for s in mgr.get_snippets()])

    def test_apagar_com_o_arquivo_corrompido_nao_grava_por_cima(self):
        mgr = SnippetManager(file_path=self.arquivo)
        with open(self.arquivo, "w", encoding="utf-8") as f:
            f.write('[{"trigger": "da pessoa", "content": "x"')
        mgr.delete_snippet("meu pix")
        self.assertEqual(1, len(self._quarentenas()))

    def test_ler_um_corrompido_nao_grava_nada(self):
        mgr = SnippetManager(file_path=self.arquivo)
        with open(self.arquivo, "w", encoding="utf-8") as f:
            f.write("{nao e json")
        self.assertEqual(len(DEFAULT_SNIPPETS), len(mgr.get_snippets()))
        with open(self.arquivo, encoding="utf-8") as f:
            self.assertEqual("{nao e json", f.read())
        self.assertEqual([], self._quarentenas())

    def test_formato_inesperado_tambem_vai_para_quarentena(self):
        mgr = SnippetManager(file_path=self.arquivo)
        with open(self.arquivo, "w", encoding="utf-8") as f:
            f.write('{"trigger": "um dict, nao uma lista"}')
        self.assertTrue(mgr.save_snippet("novo", "Novo", "x"))
        self.assertEqual(1, len(self._quarentenas()))

    def test_arquivo_ilegivel_nao_e_sobrescrito(self):
        mgr = SnippetManager(file_path=self.arquivo)
        mgr.save_snippet("meu atalho", "Meu", "conteúdo da pessoa")
        with open(self.arquivo, encoding="utf-8") as f:
            antes = f.read()
        with patch.object(SnippetManager, "_ler_estrito", side_effect=PermissionError("em uso")):
            self.assertFalse(mgr.save_snippet("novo", "Novo", "x"))
            self.assertFalse(mgr.delete_snippet("meu atalho"))
        with open(self.arquivo, encoding="utf-8") as f:
            self.assertEqual(antes, f.read())

    def test_gravacao_que_falha_no_meio_preserva_o_arquivo(self):
        mgr = SnippetManager(file_path=self.arquivo)
        mgr.save_snippet("meu atalho", "Meu", "conteúdo da pessoa")
        with open(self.arquivo, encoding="utf-8") as f:
            antes = f.read()
        with patch("json.dump", side_effect=OSError("disco cheio")):
            self.assertFalse(mgr.save_snippet("novo", "Novo", "x"))
        with open(self.arquivo, encoding="utf-8") as f:
            self.assertEqual(antes, f.read())


class TestSnippetsBomEConcorrencia(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.arquivo = os.path.join(self.temp_dir.name, "snippets.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_arquivo_valido_com_bom_nao_vai_para_quarentena(self):
        """Editado no Bloco de Notas, o JSON ganha BOM: válido, e não pode virar "corrompido"."""
        with open(self.arquivo, "w", encoding="utf-8-sig") as f:
            f.write('[{"trigger": "da pessoa", "title": "Dela", "content": "x"}]')
        mgr = SnippetManager(file_path=self.arquivo)
        self.assertTrue(mgr.save_snippet("novo", "Novo", "y"))
        self.assertEqual([], [n for n in os.listdir(self.temp_dir.name) if ".corrompido-" in n])
        self.assertEqual({"da pessoa", "novo"}, {s["trigger"] for s in mgr.get_snippets()})

    def test_gravar_com_a_transcricao_lendo_ao_mesmo_tempo(self):
        """Cada ditado lê os snippets; o os.replace falhava com o arquivo aberto pela leitura."""
        import threading
        mgr = SnippetManager(file_path=self.arquivo)
        parar = threading.Event()

        def _ler():
            while not parar.is_set():
                mgr.get_snippets()

        leitor = threading.Thread(target=_ler)
        leitor.start()
        try:
            resultados = [mgr.save_snippet(f"gatilho {i}", "T", "c") for i in range(60)]
        finally:
            parar.set()
            leitor.join()
        self.assertEqual([True] * 60, resultados)


if __name__ == "__main__":
    unittest.main()

