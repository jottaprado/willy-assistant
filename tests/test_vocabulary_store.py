"""
Testes unitários para o módulo core.storage.vocabulary_store.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from core.storage.vocabulary_store import VocabularyStore


class TestVocabularyStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vocab_path = os.path.join(self.temp_dir.name, "vocabulario.txt")
        self.reps_path = os.path.join(self.temp_dir.name, ".replacements.json")
        self.store = VocabularyStore(vocab_file=self.vocab_path, replacements_file=self.reps_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_vocab_crud(self):
        self.assertEqual(self.store.load_vocab_text(), "")
        self.assertEqual(self.store.get_vocab_terms(), [])

        content = "# Comentário\nKubernetes, Docker\nFastAPI, Redis\n"
        self.store.save_vocab_text(content)

        self.assertEqual(self.store.load_vocab_text(), content)
        terms = self.store.get_vocab_terms()
        self.assertEqual(terms, ["Kubernetes", "Docker", "FastAPI", "Redis"])

    def test_replacements_crud(self):
        self.assertEqual(self.store.load_replacements(), {})

        self.assertTrue(self.store.add_replacement("dock", "Docker"))
        self.assertTrue(self.store.add_replacement("cube", "Kubernetes"))

        reps = self.store.load_replacements()
        self.assertEqual(reps.get("dock"), "Docker")
        self.assertEqual(reps.get("cube"), "Kubernetes")

        # Remover
        self.assertTrue(self.store.delete_replacement("dock"))
        self.assertFalse(self.store.delete_replacement("inexistente"))

        reps_pos = self.store.load_replacements()
        self.assertNotIn("dock", reps_pos)
        self.assertIn("cube", reps_pos)

    def test_build_prompt_context(self):
        base = "TypeScript Python"
        custom = ["Docker", "Kubernetes", "python"]  # python duplicado em lower
        reps = {"api": "FastAPI"}

        ctx = self.store.build_prompt_context(
            base_context=base,
            custom_terms=custom,
            replacements=reps,
            max_prompt_len=100
        )

        self.assertIn("TypeScript", ctx)
        self.assertIn("Docker", ctx)
        self.assertIn("Kubernetes", ctx)
        self.assertIn("FastAPI", ctx)
        # python em minúsculo não deve ser duplicado
        self.assertEqual(ctx.lower().count("python"), 1)

    def test_build_prompt_context_length_limit(self):
        base = "Base " * 50
        custom = ["TermoMuitoLongo" * 10]
        ctx = self.store.build_prompt_context(
            base_context=base,
            custom_terms=custom,
            max_prompt_len=80
        )
        self.assertLessEqual(len(ctx), 80)


class TestVocabularioESubstituicoesNaoSomem(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vocab_path = os.path.join(self.temp_dir.name, "vocabulario.txt")
        self.reps_path = os.path.join(self.temp_dir.name, ".replacements.json")
        self.store = VocabularyStore(vocab_file=self.vocab_path, replacements_file=self.reps_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_vocabulario_que_falha_no_meio_preserva_o_anterior(self):
        """A escrita direta truncava o arquivo antes de gravar e engolia o erro."""
        self.assertTrue(self.store.save_vocab_text("Kubernetes, Docker\n"))
        # Falha na troca, com o temporário já escrito: a escrita direta antiga nem passava por
        # aqui e já teria trocado o conteúdo.
        with patch("os.replace", side_effect=OSError("disco cheio")):
            self.assertFalse(self.store.save_vocab_text("Outro"))
        self.assertEqual("Kubernetes, Docker\n", self.store.load_vocab_text())
        self.assertEqual([], [n for n in os.listdir(self.temp_dir.name) if n.startswith(".tmp_")])

    def test_substituicao_nova_com_o_arquivo_corrompido_preserva_as_antigas(self):
        """load_replacements devolve {} para JSON corrompido, e add_replacement gravava por cima."""
        with open(self.reps_path, "w", encoding="utf-8") as f:
            f.write('{"dockers": "Docker", "cubernets"')
        self.assertTrue(self.store.add_replacement("reacti", "React"))
        quarentenas = [n for n in os.listdir(self.temp_dir.name) if ".corrompido-" in n]
        self.assertEqual(1, len(quarentenas))
        with open(os.path.join(self.temp_dir.name, quarentenas[0]), encoding="utf-8") as f:
            self.assertIn("dockers", f.read())
        self.assertEqual({"reacti": "React"}, self.store.load_replacements())

    def test_substituicoes_ilegiveis_nao_sao_sobrescritas(self):
        self.store.save_replacements({"dockers": "Docker"})
        with open(self.reps_path, encoding="utf-8") as f:
            antes = f.read()
        real_open = open

        def _em_uso(caminho, modo="r", *a, **k):
            if caminho == self.reps_path and "r" in modo:
                raise PermissionError("em uso")
            return real_open(caminho, modo, *a, **k)

        with patch("builtins.open", _em_uso):
            self.assertFalse(self.store.add_replacement("reacti", "React"))
            self.assertFalse(self.store.delete_replacement("dockers"))
        with open(self.reps_path, encoding="utf-8") as f:
            self.assertEqual(antes, f.read())

    def test_vocabulario_corrompido_vai_para_quarentena_e_ilegivel_nao_e_sobrescrito(self):
        """AUD-045: load_vocab_text loga em stderr, e save_vocab_text faz quarentena ou aborta se ilegível."""
        import io
        # 1. Bytes inválidos em UTF-8: load_vocab_text loga em stderr e save_vocab_text move para quarentena
        with open(self.vocab_path, "wb") as f:
            f.write(b"Kubernetes\xff\xfeDocker")
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            self.assertEqual(self.store.load_vocab_text(), "")
        self.assertIn("[VocabularyStore]", stderr_buf.getvalue())

        self.assertTrue(self.store.save_vocab_text("FastAPI\n"))
        quarentenas = [n for n in os.listdir(self.temp_dir.name) if "vocabulario.txt.corrompido-" in n]
        self.assertEqual(1, len(quarentenas))
        self.assertEqual("FastAPI\n", self.store.load_vocab_text())

        # 2. Arquivo em uso/sem permissão de leitura: save_vocab_text aborta sem sobrescrever
        real_open = open

        def _em_uso_vocab(caminho, modo="r", *a, **k):
            if caminho == self.vocab_path and "r" in modo:
                raise PermissionError("em uso")
            return real_open(caminho, modo, *a, **k)

        with patch("builtins.open", _em_uso_vocab):
            self.assertFalse(self.store.save_vocab_text("Sobrescrito\n"))
        self.assertEqual("FastAPI\n", self.store.load_vocab_text())


class TestVocabularioBomEConcorrencia(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vocab_path = os.path.join(self.temp_dir.name, "vocabulario.txt")
        self.reps_path = os.path.join(self.temp_dir.name, ".replacements.json")
        self.store = VocabularyStore(vocab_file=self.vocab_path, replacements_file=self.reps_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_substituicoes_validas_com_bom_sao_preservadas(self):
        with open(self.reps_path, "w", encoding="utf-8-sig") as f:
            f.write('{"dockers": "Docker"}')
        self.assertEqual({"dockers": "Docker"}, self.store.load_replacements())
        self.assertTrue(self.store.add_replacement("reacti", "React"))
        self.assertEqual({"dockers": "Docker", "reacti": "React"}, self.store.load_replacements())
        self.assertEqual([], [n for n in os.listdir(self.temp_dir.name) if ".corrompido-" in n])

    def test_vocabulario_com_bom_nao_traz_o_bom_no_primeiro_termo(self):
        with open(self.vocab_path, "w", encoding="utf-8-sig") as f:
            f.write("Kubernetes, Docker")
        self.assertEqual(["Kubernetes", "Docker"], self.store.get_vocab_terms())

    def test_gravar_com_a_transcricao_lendo_ao_mesmo_tempo(self):
        import threading
        parar = threading.Event()

        def _ler():
            while not parar.is_set():
                self.store.load_replacements()
                self.store.load_vocab_text()

        leitor = threading.Thread(target=_ler)
        leitor.start()
        try:
            regras = [self.store.add_replacement(f"de{i}", f"para{i}") for i in range(40)]
            textos = [self.store.save_vocab_text(f"termo{i}") for i in range(40)]
        finally:
            parar.set()
            leitor.join()
        self.assertEqual([True] * 40, regras)
        self.assertEqual([True] * 40, textos)


if __name__ == "__main__":
    unittest.main()

