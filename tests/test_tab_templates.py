"""
Testes unitários para o módulo modular ui.tabs.tab_templates.
Verifica a integridade de TemplatesTab, build_tab_templates e compatibilidade com WillyDashboard.
"""

import unittest

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_templates import TemplatesTab, build_tab_templates


class TestTabTemplates(unittest.TestCase):
    """Testes dos componentes e execução das operações de snippets/templates."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_templates_tab_componentes_e_estado_vazio(self):
        """Verifica a inicialização dos widgets e mensagem de estado vazio."""
        callbacks = {
            "get_snippets": list,
        }
        tab = build_tab_templates(self.root, callbacks=callbacks)
        self.assertIsInstance(tab, TemplatesTab)
        self.assertTrue(hasattr(tab, "btn_novo_snippet"))
        self.assertTrue(hasattr(tab, "entry_busca_snippets"))
        self.assertTrue(hasattr(tab, "scroll_snippets"))

        # Como a lista de snippets está vazia, deve haver um label de estado vazio
        children = tab.scroll_snippets.winfo_children()
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], ctk.CTkLabel)
        self.assertIn("Nenhum template cadastrado ainda", children[0].cget("text"))

    def test_templates_tab_listagem_e_filtro_busca(self):
        """Testa a renderização de cards e o comportamento do filtro de busca por gatilho/título/conteúdo."""
        snippets_data = [
            {
                "trigger": "bug report",
                "title": "Bug Report GitHub",
                "content": "Descrição do problema:\nPassos para reproduzir:\nComportamento esperado:",
            },
            {
                "trigger": "email comercial",
                "title": "Email de Apresentação Comercial",
                "content": "Prezado cliente, apresentamos nossa proposta comercial.",
            },
            {
                "trigger": "deploy checklist",
                "title": "Checklist de Deploy",
                "content": "1. Rodar testes\n2. Gerar build\n3. Atualizar release notes",
            },
        ]
        callbacks = {
            "get_snippets": lambda: snippets_data,
        }
        tab = build_tab_templates(self.root, callbacks=callbacks)
        tab.atualizar_lista_templates()

        # 3 cards devem ser renderizados
        cards = tab.scroll_snippets.winfo_children()
        self.assertEqual(len(cards), 3)

        # Filtrando por "email"
        tab.entry_busca_snippets.delete(0, "end")
        tab.entry_busca_snippets.insert(0, "email")
        tab.atualizar_lista_templates()

        cards_filtrados = tab.scroll_snippets.winfo_children()
        self.assertEqual(len(cards_filtrados), 1)

        # Filtrando sem acento por termo acentuado ("apresentacao" -> "Apresentação", "descricao" -> "Descrição")
        tab.entry_busca_snippets.delete(0, "end")
        tab.entry_busca_snippets.insert(0, "apresentacao")
        tab.atualizar_lista_templates()
        cards_apresentacao = [c for c in tab.scroll_snippets.winfo_children() if isinstance(c, ctk.CTkFrame)]
        self.assertEqual(len(cards_apresentacao), 1)

        tab.entry_busca_snippets.delete(0, "end")
        tab.entry_busca_snippets.insert(0, "descricao")
        tab.atualizar_lista_templates()
        cards_descricao = [c for c in tab.scroll_snippets.winfo_children() if isinstance(c, ctk.CTkFrame)]
        self.assertEqual(len(cards_descricao), 1)

        # Filtrando por termo inexistente -> estado vazio
        tab.entry_busca_snippets.delete(0, "end")
        tab.entry_busca_snippets.insert(0, "termo_inexistente_xyz")
        tab.atualizar_lista_templates()

        cards_vazios = tab.scroll_snippets.winfo_children()
        self.assertEqual(len(cards_vazios), 1)
        self.assertIsInstance(cards_vazios[0], ctk.CTkLabel)

    def test_modal_e_operacoes_deletar_e_salvar(self):
        """Testa a abertura do modal e a delegação dos callbacks de salvar e deletar."""
        deletados = []
        salvos = []

        callbacks = {
            "get_snippets": lambda: [{"trigger": "teste", "title": "Teste", "content": "Conteudo"}],
            "on_delete_snippet": lambda tr: deletados.append(tr),
            "on_save_snippet": lambda tr, ti, co: salvos.append((tr, ti, co)),
        }
        tab = build_tab_templates(self.root, callbacks=callbacks)

        # Testa deletar
        tab.deletar_snippet("teste")
        self.assertEqual(deletados, ["teste"])

        # Testa abertura de modal sem levantar exceção
        win_novo = tab.abrir_modal_snippet()
        self.addCleanup(lambda: win_novo.destroy() if win_novo.winfo_exists() else None)
        self.assertTrue(win_novo.bind("<Escape>"), "Modal de snippet deve vincular <Escape>")
        win_novo.fechar()
        self.assertFalse(win_novo.winfo_exists())
        # Modal para edição
        item_edicao = {"trigger": "edicao", "title": "Titulo Edicao", "content": "Conteudo Edicao"}
        win_edicao = tab.abrir_modal_snippet(item=item_edicao)
        self.addCleanup(lambda: win_edicao.destroy() if win_edicao.winfo_exists() else None)
        win_edicao.fechar()
        self.assertFalse(win_edicao.winfo_exists())

    def test_templates_tab_normalizacao_formato_dict(self):
        """Verifica que tab_templates lida com get_snippets retornando formato dict sem estourar AttributeError."""
        callbacks = {
            "get_snippets": lambda: {"#meu_gatilho": "Conteudo do snippet"},
        }
        tab = build_tab_templates(self.root, callbacks=callbacks)
        cards = [c for c in tab.scroll_snippets.winfo_children() if isinstance(c, ctk.CTkFrame)]
        self.assertEqual(len(cards), 1)

    def test_dashboard_delegacao_templates(self):
        """Testa a fachada e delegação de WillyDashboard para tab_templates."""
        isolar_config(self)
        dash = WillyDashboard(callbacks={"get_history": list, "get_snippets": list, "get_app_rules": list})
        dash.withdraw()
        try:
            self.assertIn("snippets", dash.frames_abas)
            self.assertIsInstance(dash.frames_abas["snippets"], TemplatesTab)
            self.assertTrue(hasattr(dash, "tab_templates"))
            self.assertIsNotNone(dash.entry_busca_snippets)
            self.assertIsNotNone(dash.scroll_snippets)
            self.assertIsNotNone(dash.btn_novo_snippet)

            # Teste chamada de fachada
            dash.atualizar_lista_templates()
        finally:
            destruir_tk(dash)




if __name__ == "__main__":
    unittest.main()
