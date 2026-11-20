"""
Testes unitários para o módulo modular ui.tabs.tab_vocabulary.
Verifica a integridade de VocabularyTab, build_tab_vocabulary e compatibilidade com WillyDashboard.
"""

import unittest

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_vocabulary import VocabularyTab, build_tab_vocabulary


class TestTabVocabulary(unittest.TestCase):
    """Testes da renderização e contratos da aba de vocabulário e substituições."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_vocabulary_tab_componentes(self):
        """Verifica se todos os componentes visuais essenciais são instanciados."""
        saved_vocab = []
        callbacks = {
            "on_save_vocab": lambda txt: saved_vocab.append(txt) or True,
            "get_vocab": lambda: "Python, FastAPI",
            "get_replacements": lambda: {"k8s": "Kubernetes"},
            "on_save_replacement": lambda de, para: None,
            "on_delete_replacement": lambda de: None,
        }
        tab = build_tab_vocabulary(self.root, callbacks=callbacks)
        self.assertIsInstance(tab, VocabularyTab)
        self.assertTrue(hasattr(tab, "txt_vocab"))
        self.assertTrue(hasattr(tab, "btn_salvar_vocab"))
        self.assertTrue(hasattr(tab, "entry_rep_de"))
        self.assertTrue(hasattr(tab, "entry_rep_para"))
        self.assertTrue(hasattr(tab, "btn_add_rep"))
        self.assertTrue(hasattr(tab, "frame_reps_lista"))

        # Testa salvamento
        tab.txt_vocab.delete("1.0", "end")
        tab.txt_vocab.insert("1.0", "Docker, Kubernetes")
        tab.salvar_vocabulario()
        self.assertIn("Docker, Kubernetes", saved_vocab)

    def test_vocabulary_crud_replacements(self):
        """Testa adição e exclusão de regras de substituição fonética."""
        reps_store = {}

        def _save(de, para):
            reps_store[de] = para
            return True

        def _delete(de):
            return reps_store.pop(de, None) is not None

        callbacks = {
            "get_replacements": lambda: dict(reps_store),
            "on_save_replacement": _save,
            "on_delete_replacement": _delete,
        }
        tab = build_tab_vocabulary(self.root, callbacks=callbacks)

        # Adicionar regra
        tab.entry_rep_de.insert(0, "postgre")
        tab.entry_rep_para.insert(0, "PostgreSQL")
        tab.adicionar_replacement()

        self.assertIn("postgre", reps_store)
        self.assertEqual(reps_store["postgre"], "PostgreSQL")

        # Deletar regra
        tab.deletar_replacement("postgre")
        self.assertNotIn("postgre", reps_store)

    def test_carregar_presets_tech(self):
        """Testa o carregamento de presets comuns de termos técnicos."""
        reps_store = {}
        callbacks = {
            "get_replacements": lambda: dict(reps_store),
            "on_save_replacement": lambda de, para: reps_store.update({de: para}) or True,
        }
        tab = build_tab_vocabulary(self.root, callbacks=callbacks)
        tab.carregar_termos_tech_comuns()

        self.assertIn("k8s", reps_store)
        self.assertEqual(reps_store["k8s"], "Kubernetes")
        self.assertIn("dock", reps_store)
        self.assertEqual(reps_store["dock"], "Docker")

    def test_dashboard_delegacao_vocabulario(self):
        """Testa a fachada e delegação de WillyDashboard para tab_vocabulary."""
        isolar_config(self)
        dash = WillyDashboard(callbacks={
            "get_history": list,
            "get_app_rules": list,
            "get_vocab": lambda: "TypeScript",
            "get_replacements": lambda: {"pr": "Pull Request"},
        })
        dash.withdraw()
        try:
            self.assertIn("vocab", dash.frames_abas)
            self.assertIsInstance(dash.frames_abas["vocab"], VocabularyTab)
            self.assertTrue(hasattr(dash, "tab_vocab"))

            # Fachada de compatibilidade
            self.assertIsNotNone(dash.txt_vocab)
            self.assertIsNotNone(dash.frame_reps_lista)
            self.assertEqual(dash.txt_vocab.get("1.0", "end").strip(), "TypeScript")
        finally:
            destruir_tk(dash)

    def test_destroy_cancela_timers_pendentes(self):
        """Timers after() agendados em VocabularyTab devem ser cancelados no destroy()."""
        tab = build_tab_vocabulary(self.root, callbacks={
            "on_save_vocab": lambda _txt: True,
            "on_save_replacement": lambda _de, _para: True,
            "get_replacements": dict,
        })
        tab._on_vocab_keyrelease()
        self.assertIsNotNone(tab._debounce_save_timer)
        tab.salvar_vocabulario()
        self.assertIsNone(tab._debounce_save_timer, "salvar_vocabulario deve limpar _debounce_save_timer")
        self.assertIsNotNone(tab._reset_salvar_timer)
        tab.carregar_termos_tech_comuns()
        self.assertIsNotNone(tab._reset_preset_timer)
        tab._on_vocab_keyrelease()
        self.assertIsNotNone(tab._debounce_save_timer)
        tab.destroy()
        self.assertIsNone(tab._debounce_save_timer)
        self.assertIsNone(tab._reset_salvar_timer)
        self.assertIsNone(tab._reset_preset_timer)

    def test_importar_aceita_cp1252_e_reporta_erro_de_leitura(self):
        """_importar_vocabulario deve aceitar arquivos cp1252 e reportar falhas de leitura em stderr e na UI."""
        import io
        import os
        import tempfile
        from unittest.mock import patch

        salvos = []
        tab = build_tab_vocabulary(self.root, callbacks={
            "on_save_vocab": lambda txt: salvos.append(txt) or True,
            "get_replacements": dict,
        })
        self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())

        with tempfile.TemporaryDirectory() as tmp:
            arq_cp1252 = os.path.join(tmp, "vocab_ansi.txt")
            with open(arq_cp1252, "wb") as f:
                f.write("São Paulo, Conceição\n".encode("cp1252"))
            with patch("tkinter.filedialog.askopenfilename", return_value=arq_cp1252):
                tab._importar_vocabulario()
            self.assertEqual(salvos, ["São Paulo, Conceição"])

            arq_inexistente = os.path.join(tmp, "nao_existe.txt")
            stderr_buf = io.StringIO()
            with patch("tkinter.filedialog.askopenfilename", return_value=arq_inexistente), \
                 patch("sys.stderr", stderr_buf):
                tab._importar_vocabulario()
            self.assertIn("[VocabularyTab]", stderr_buf.getvalue())
            self.assertIn("Erro ao importar", tab.lbl_status_salvo.cget("text"))

    def test_exportar_e_regras_reportam_erros_em_stderr(self):
        """_exportar_vocabulario e _regras devem logar falhas em sys.stderr sem engolir em silêncio."""
        import io
        from unittest.mock import patch

        def _falhar_reps():
            raise RuntimeError("falha no store")

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            tab = build_tab_vocabulary(self.root, callbacks={
                "get_replacements": _falhar_reps,
            })
        self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())
        self.assertIn("[VocabularyTab]", stderr_buf.getvalue())

        stderr_exp = io.StringIO()
        with patch("tkinter.filedialog.asksaveasfilename", return_value="C:/caminho/bloqueado.txt"), \
             patch("builtins.open", side_effect=PermissionError("acesso negado")), \
             patch("sys.stderr", stderr_exp):
            tab._exportar_vocabulario()
        self.assertIn("[VocabularyTab]", stderr_exp.getvalue())
        self.assertIn("Erro ao exportar", tab.lbl_status_salvo.cget("text"))


if __name__ == "__main__":
    unittest.main()
