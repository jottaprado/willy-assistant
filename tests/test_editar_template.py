"""
Editar um template com o gatilho trocado, e o modal que só fecha quando gravou.

- O save atualiza pelo gatilho: trocado, ele criava um template novo e o antigo continuava na
  lista, os dois disputando a mesma fala.
- O modal fechava com a gravação falha, e o que foi digitado se perdia.
- Trocar para o gatilho de outro template gravava por cima dele.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

import customtkinter as ctk

from core.snippets import SnippetManager
from tests.willy_isolado import destruir_tk
from ui.tabs.tab_templates import build_tab_templates


class _BaseTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _modal(self, aba, item, gatilho=None, conteudo=None):
        win = aba.abrir_modal_snippet(item=item)
        self.addCleanup(lambda: win.winfo_exists() and win.destroy())
        if gatilho is not None:
            win.campos["gatilho"].delete(0, "end")
            win.campos["gatilho"].insert(0, gatilho)
        if conteudo is not None:
            win.campos["conteudo"].delete("1.0", "end")
            win.campos["conteudo"].insert("1.0", conteudo)
        return win


class TestComOSnippetManagerDeVerdade(_BaseTk):
    """O SnippetManager de verdade num arquivo temporário: o que fica gravado."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mgr = SnippetManager(os.path.join(tmp.name, "snippets.json"))
        self.mgr.save_snippet("bug report", "Bug", "passos para reproduzir")
        self.mgr.save_snippet("assinatura", "Assinatura", "abraço, Jotta")
        self.aba = build_tab_templates(self.root, callbacks={
            "get_snippets": self.mgr.get_snippets,
            "on_save_snippet": self.mgr.save_snippet,
            "on_delete_snippet": self.mgr.delete_snippet,
        })
        self.addCleanup(self.aba.destroy)

    def _gatilhos(self):
        return sorted(s["trigger"] for s in self.mgr.get_snippets() if s["trigger"] in
                      ("bug report", "relato de bug", "assinatura", "Bug Report"))

    def _item(self, gatilho):
        return next(s for s in self.mgr.get_snippets() if s["trigger"] == gatilho)

    def test_trocar_o_gatilho_nao_duplica(self):
        antes = [s["trigger"] for s in self.mgr.get_snippets()]
        win = self._modal(self.aba, self._item("bug report"), gatilho="relato de bug")
        win.salvar()
        self.assertEqual(["assinatura", "relato de bug"], self._gatilhos())
        depois = [s["trigger"] for s in self.mgr.get_snippets()]
        self.assertEqual([("relato de bug" if g == "bug report" else g) for g in antes], depois)
        self.assertEqual("passos para reproduzir", self._item("relato de bug")["content"])
        self.assertFalse(win.winfo_exists(), "o modal ficou aberto depois de gravar")

    def test_so_maiusculas_trocadas_nao_apaga_o_template(self):
        # O save guarda em minúsculas: excluir "bug report" depois apagaria o que acabou de gravar.
        win = self._modal(self.aba, self._item("bug report"), gatilho="Bug Report", conteudo="novo")
        win.salvar()
        self.assertIn("bug report", self._gatilhos(), "o template editado foi apagado")
        self.assertEqual("novo", self._item("bug report")["content"])

    def test_gatilho_de_outro_template_e_recusado(self):
        win = self._modal(self.aba, self._item("bug report"), gatilho="assinatura")
        win.salvar()
        self.assertEqual("abraço, Jotta", self._item("assinatura")["content"], "gravou por cima do outro")
        self.assertIn("bug report", self._gatilhos())
        self.assertTrue(win.winfo_exists())
        self.assertIn("assinatura", win.lbl_erro.cget("text"))

    def test_trocar_so_o_acento_renomeia(self):
        # "reunião" e "reuniao" são o mesmo gatilho falado: não é o de outro template.
        self.mgr.save_snippet("link da reunião", "Link", "meet.google.com/x")
        win = self._modal(self.aba, self._item("link da reunião"), gatilho="link da reuniao")
        win.salvar()
        self.assertFalse(win.winfo_exists(), win.lbl_erro.cget("text"))
        gatilhos = [s["trigger"] for s in self.mgr.get_snippets() if s["trigger"].startswith("link da")]
        self.assertEqual(["link da reuniao"], gatilhos)

    def test_mesmo_gatilho_atualiza_no_lugar(self):
        # Clica no botão real "Editar" do card "bug report" e no botão "Salvar Template" do modal
        cards = [w for w in self.aba.scroll_snippets.winfo_children() if isinstance(w, ctk.CTkFrame)]
        btn_editar_bug = None
        for c in cards:
            textos_card = [
                sub.cget("text")
                for f in c.winfo_children() if isinstance(f, ctk.CTkFrame)
                for h in f.winfo_children() if isinstance(h, ctk.CTkFrame)
                for sub in h.winfo_children() if isinstance(sub, ctk.CTkLabel)
            ]
            if any("bug report" in t for t in textos_card):
                botoes = [
                    b for f in c.winfo_children() if isinstance(f, ctk.CTkFrame)
                    for b in f.winfo_children() if isinstance(b, ctk.CTkButton) and b.cget("text") == "Editar"
                ]
                if botoes:
                    btn_editar_bug = botoes[0]
                    break
        self.assertIsNotNone(btn_editar_bug, "Botão Editar do card 'bug report' não encontrado")
        antes_toplevels = set(self.aba.winfo_children())
        btn_editar_bug.invoke()
        novos = [w for w in self.aba.winfo_children() if w not in antes_toplevels and isinstance(w, ctk.CTkToplevel)]
        self.assertEqual(len(novos), 1, "Modal de edição deveria ter aberto ao clicar em Editar")
        win = novos[0]
        self.addCleanup(lambda: win.winfo_exists() and win.destroy())
        self.assertEqual("bug report", win.campos["gatilho"].get(), "Botão Editar deve passar o item para abrir_modal_snippet")
        win.campos["conteudo"].delete("1.0", "end")
        win.campos["conteudo"].insert("1.0", "passos novos")
        botoes_salvar = [
            b for f in win.winfo_children()
            for sub in f.winfo_children()
            for b in (sub.winfo_children() if hasattr(sub, "winfo_children") else ())
            if isinstance(b, ctk.CTkButton) and b.cget("text") == "Salvar Template"
        ]
        self.assertEqual(len(botoes_salvar), 1, "Botão Salvar Template deve existir no modal")
        botoes_salvar[0].invoke()
        self.assertFalse(win.winfo_exists())
        self.assertEqual(["assinatura", "bug report"], self._gatilhos())
        self.assertEqual("passos novos", self._item("bug report")["content"])


class TestModalSoFechaQuandoGravou(_BaseTk):
    def _aba(self, salvar, excluir=None):
        aba = build_tab_templates(self.root, callbacks={
            "get_snippets": lambda: [{"trigger": "bug report", "title": "Bug", "content": "x"}],
            "on_save_snippet": salvar,
            "on_delete_snippet": excluir or MagicMock(return_value=True),
        })
        self.addCleanup(aba.destroy)
        return aba

    def test_gravacao_falha_mantem_o_modal_e_avisa(self):
        win = self._modal(self._aba(MagicMock(return_value=False)), None, gatilho="novo", conteudo="texto")
        win.salvar()
        self.assertTrue(win.winfo_exists())
        self.assertIn("Não salvei", win.lbl_erro.cget("text"))
        self.assertEqual("novo", win.campos["gatilho"].get(), "o que foi digitado se perdeu")

    def test_gravacao_falha_nao_exclui_o_antigo(self):
        excluir = MagicMock(return_value=True)
        win = self._modal(self._aba(MagicMock(return_value=False), excluir),
                          {"trigger": "bug report", "title": "Bug", "content": "x"}, gatilho="relato")
        win.salvar()
        excluir.assert_not_called()

    def test_antigo_que_nao_saiu_mantem_o_modal_e_avisa(self):
        win = self._modal(self._aba(MagicMock(return_value=True), MagicMock(return_value=False)),
                          {"trigger": "bug report", "title": "Bug", "content": "x"}, gatilho="relato")
        win.salvar()
        self.assertTrue(win.winfo_exists())
        self.assertIn("bug report", win.lbl_erro.cget("text"))

    def test_tentar_de_novo_depois_do_antigo_nao_sair_conclui(self):
        # O segundo Salvar achava o gatilho que o primeiro gravou e o tratava como de outro
        # template: a recusa era para sempre e a duplicata ficava.
        gravados = [{"trigger": "bug report", "title": "Bug", "content": "x"}]

        def _salvar(tr, ti, co):
            if not any(s["trigger"] == tr.lower() for s in gravados):
                gravados.append({"trigger": tr.lower(), "title": ti, "content": co})
            return True

        excluir = MagicMock(side_effect=[False, True])
        aba = build_tab_templates(self.root, callbacks={
            "get_snippets": lambda: list(gravados), "on_save_snippet": _salvar, "on_delete_snippet": excluir})
        self.addCleanup(aba.destroy)
        win = self._modal(aba, {"trigger": "bug report", "title": "Bug", "content": "x"}, gatilho="relato de bug")
        win.salvar()
        self.assertTrue(win.winfo_exists())
        win.salvar()
        self.assertFalse(win.winfo_exists(), win.lbl_erro.cget("text") if win.winfo_exists() else "")
        self.assertEqual(2, excluir.call_count)

    def test_campos_vazios_avisam(self):
        salvar = MagicMock(return_value=True)
        win = self._modal(self._aba(salvar), None)
        win.salvar()
        salvar.assert_not_called()
        self.assertTrue(win.winfo_exists())
        self.assertIn("Preencha", win.lbl_erro.cget("text"))

    def test_gravou_fecha(self):
        win = self._modal(self._aba(MagicMock(return_value=True)), None, gatilho="novo", conteudo="texto")
        win.salvar()
        self.assertFalse(win.winfo_exists())


class _SnippetsComOldTrigger:
    """O contrato do SnippetManager.save_snippet do Bloco 7A: com old_trigger, troca gatilho,
    título e conteúdo no mesmo índice, numa gravação só; gatilho de outro template volta False."""

    def __init__(self, gatilhos):
        self.lista = [{"trigger": g, "title": g.title(), "content": f"conteúdo de {g}"} for g in gatilhos]
        self.excluidos = []
        self.chamadas = []

    def get_snippets(self):
        return [dict(s) for s in self.lista]

    def save_snippet(self, trigger, title, content, old_trigger=None):
        self.chamadas.append((trigger, old_trigger))
        novo, antigo = trigger.strip().lower(), (old_trigger or "").strip().lower()
        if any(s["trigger"] == novo and s["trigger"] != antigo for s in self.lista):
            return False
        for s in self.lista:
            if antigo and s["trigger"] == antigo:
                s.update(trigger=novo, title=title, content=content)
                return True
        self.lista.append({"trigger": novo, "title": title, "content": content})
        return True

    def delete_snippet(self, trigger):
        self.excluidos.append(trigger)
        self.lista = [s for s in self.lista if s["trigger"] != trigger.lower()]
        return True


class TestRenomearNoLugar(_BaseTk):
    def setUp(self):
        self.mgr = _SnippetsComOldTrigger(["assinatura", "bug report", "link da reunião"])
        self.aba = build_tab_templates(self.root, callbacks={
            "get_snippets": self.mgr.get_snippets,
            "on_save_snippet": self.mgr.save_snippet,
            "on_delete_snippet": self.mgr.delete_snippet,
        })
        self.addCleanup(self.aba.destroy)

    def test_gatilho_trocado_fica_no_mesmo_lugar(self):
        win = self._modal(self.aba, self.mgr.get_snippets()[1], gatilho="relato de bug")
        win.salvar()
        self.assertEqual(["assinatura", "relato de bug", "link da reunião"], [s["trigger"] for s in self.mgr.lista])
        self.assertEqual([("relato de bug", "bug report")], self.mgr.chamadas, "uma gravação só, com o antigo")
        self.assertEqual([], self.mgr.excluidos, "renomear no lugar não apaga nada")
        self.assertFalse(win.winfo_exists())

    def test_gravacao_recusada_mantem_o_modal(self):
        def _recusa(trigger, title, content, old_trigger=None):
            return False  # o disco falhou, ou o gatilho novo é de outro template

        aba = build_tab_templates(self.root, callbacks={"get_snippets": self.mgr.get_snippets,
                                                        "on_save_snippet": _recusa,
                                                        "on_delete_snippet": self.mgr.delete_snippet})
        self.addCleanup(aba.destroy)
        win = self._modal(aba, self.mgr.get_snippets()[1], gatilho="relato de bug")
        win.salvar()
        self.assertTrue(win.winfo_exists())
        self.assertIn("Não salvei", win.lbl_erro.cget("text"))
        self.assertEqual([], self.mgr.excluidos)

    def test_callback_de_tres_argumentos_continua_com_gravar_e_apagar(self):
        lista = [{"trigger": "bug report", "title": "Bug", "content": "x"}]
        salvar = MagicMock(return_value=True)  # aceita qualquer coisa, mas não declara old_trigger
        excluir = MagicMock(return_value=True)
        aba = build_tab_templates(self.root, callbacks={"get_snippets": lambda: list(lista),
                                                        "on_save_snippet": salvar, "on_delete_snippet": excluir})
        self.addCleanup(aba.destroy)
        win = self._modal(aba, lista[0], gatilho="relato de bug")
        win.salvar()
        salvar.assert_called_once_with("relato de bug", "Bug", "x")
        excluir.assert_called_once_with("bug report")


if __name__ == "__main__":
    unittest.main()
