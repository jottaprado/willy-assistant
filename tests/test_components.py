"""
Testes unitários para a biblioteca de componentes compartilhados em ui/components/.
Verifica integridade, instanciação e comportamento dos componentes centrais.
"""

import unittest

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.components import (
    Button,
    EmptyState,
    Keycap,
    PageHeader,
    SearchField,
    SectionHeader,
    SegmentedControl,
)


class TestComponents(unittest.TestCase):
    """Testes unitários para todos os componentes do Willy Design System."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def tearDown(self):
        destruir_tk(*self.root.winfo_children())

    def test_page_header(self):
        header = PageHeader(self.root, title="Histórico", subtitle="Subtítulo teste")
        header.add_action("Ação")
        self.assertEqual(header.lbl_title.cget("text"), "Histórico")
        self.assertIsNotNone(header.lbl_subtitle)
        self.assertEqual(header.lbl_subtitle.cget("text"), "Subtítulo teste")
        self.assertGreater(len(header.actions_box.winfo_children()), 0)

        header.set_title("Novo Título")
        self.assertEqual(header.lbl_title.cget("text"), "Novo Título")

    def test_search_field(self):
        changed = []
        cleared = []
        search = SearchField(
            self.root,
            placeholder="Buscar...",
            on_change=lambda t: changed.append(t),
            on_clear=lambda: cleared.append(True)
        )
        self.assertEqual(search.get(), "")
        search.set("teste de busca")
        self.assertEqual(search.get(), "teste de busca")
        self.assertIn("teste de busca", changed)

        search.clear()
        self.assertEqual(search.get(), "")
        self.assertTrue(cleared)

    def test_segmented_control(self):
        opts = ["Todos", "Ditados", "Prompts"]
        selected_log = []
        seg = SegmentedControl(
            self.root,
            options=opts,
            selected="Todos",
            on_change=lambda val: selected_log.append(val)
        )
        self.assertEqual(seg.get(), "Todos")
        self.assertEqual(seg.cget("values"), opts)

        seg.set("Ditados")
        self.assertEqual(seg.get(), "Ditados")

    def test_button_variants(self):
        clicked = []
        btn_prim = Button(self.root, text="Primário", variant="primary", command=lambda: clicked.append("prim"))
        btn_sec = Button(self.root, text="Secundário", variant="secondary")
        btn_ghost = Button(self.root, text="Ghost", variant="ghost")

        self.assertEqual(btn_prim.variant, "primary")
        self.assertEqual(btn_sec.variant, "secondary")
        self.assertEqual(btn_ghost.variant, "ghost")

        btn_prim._command()
        self.assertIn("prim", clicked)

    def test_section_header(self):
        btn_action = Button(self.root, text="Importar", variant="ghost")
        header = SectionHeader(self.root, text="Termos Técnicos", action=btn_action)
        self.assertEqual(header.lbl_title.cget("text"), "TERMOS TÉCNICOS")

    def test_keycap(self):
        changed = []
        kp = Keycap(
            self.root,
            keys=["Ctrl", "Alt", "Espaço"],
            on_change=lambda k: changed.append(k),
            editable=True
        )
        self.assertEqual(kp.get_hotkey(), "Ctrl+Alt+Espaço")

        kp.set_keys("ctrl+shift+p")
        self.assertEqual(kp.get_hotkey(), "ctrl+shift+p")

    def test_empty_state(self):
        empty = EmptyState(
            self.root,
            icon_key="empty",
            title="Nenhum prompt",
            hint="Tente ajustar os filtros"
        )
        self.assertIn("Nenhum prompt", empty.cget("text"))
        self.assertIn("Tente ajustar os filtros", empty.cget("text"))

    def test_teardown_limpa_filhos_e_destruir_tk_cancela_afters(self):
        self.assertEqual([], self.root.winfo_children())
        quadro = ctk.CTkFrame(self.root)
        after_id = self.root.after(60000, lambda: None)
        self.assertIn(after_id, self.root.tk.splitlist(self.root.tk.call("after", "info") or ""))
        destruir_tk(quadro)
        self.assertFalse(quadro.winfo_exists())
        self.assertNotIn(after_id, self.root.tk.splitlist(self.root.tk.call("after", "info") or ""))


if __name__ == "__main__":
    unittest.main()
