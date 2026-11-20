"""
Aba de Histórico: o menu "..." de cada linha, o destaque no hover, a exclusão que chega ao
resto do Willy e o botão do .md.

- O menu fica em coordenadas fixas da janela e só fechava ao escolher Excluir: rolando a
  lista ou trocando de aba, ficava solto por cima de outra coisa. O segundo clique no "..."
  abria outro em vez de fechar.
- Com qualquer menu aberto, nenhum cartão apagava o destaque ao perder o ponteiro: passar o
  mouse pela lista ia acendendo todos.
- Excluir e limpar ruídos mudavam o disco e a aba, mas o Dashboard seguia com a lista antiga
  e a bandeja com os "Prompts recentes" de antes.
- Sem o .md do item, o botão abria o .md mais recente da pasta: o de outro ditado.
"""

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_history import HistoryTab, build_tab_history


def _item(texto, i):
    return {"id": f"id-{i}", "text": texto, "mode": "transcribe", "timestamp": "2026-10-23T10:00:00"}


class _BaseTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.geometry("900x600+-6000+100")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def setUp(self):
        itens = [_item("primeiro ditado da lista", 1), _item("segundo ditado da lista", 2)]
        self.aba = build_tab_history(self.root, callbacks={"get_history": lambda: itens}, history_items=itens)
        self.aba.grid(row=0, column=0, sticky="nsew")
        self.addCleanup(self.aba.destroy)
        self._bombear()

    def _bombear(self, segundos=0.15):
        fim = time.time() + segundos
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)

    def _ancora(self):
        """Um "btn_box" de linha: o dono do menu."""
        f = ctk.CTkFrame(self.aba, width=40, height=20)
        f.grid(row=9, column=0)
        self.addCleanup(f.destroy)
        return f


class TestMenuFecha(_BaseTk):
    def test_segundo_clique_no_mesmo_menu_fecha(self):
        ancora = self._ancora()
        self.aba._abrir_menu_item({"id": "x"}, ancora)
        self.assertIsNotNone(self.aba._item_menu_popup)
        self.aba._abrir_menu_item({"id": "x"}, ancora)
        self.assertIsNone(self.aba._item_menu_popup)

    def test_menu_de_outra_linha_troca_em_vez_de_fechar(self):
        a, b = self._ancora(), self._ancora()
        self.aba._abrir_menu_item({"id": "a"}, a)
        primeiro = self.aba._item_menu_popup
        self.aba._abrir_menu_item({"id": "b"}, b)
        self.assertIsNotNone(self.aba._item_menu_popup)
        self.assertIs(b, self.aba._item_menu_dono)
        self.assertFalse(primeiro.winfo_exists())

    def test_clique_fora_fecha(self):
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self._bombear()
        self.aba.lbl_total_prompts.event_generate("<Button-1>", x=2, y=2)
        self.assertIsNone(self.aba._item_menu_popup)

    def test_clique_no_proprio_menu_nao_fecha(self):
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self._bombear()
        self.aba._item_menu_popup.event_generate("<Button-1>", x=2, y=2)
        self.assertIsNotNone(self.aba._item_menu_popup)

    def test_clique_na_linha_dona_nao_fecha(self):
        # O "..." da linha dona já abriu ou fechou o menu antes de o clique chegar à janela.
        ancora = self._ancora()
        self.aba._abrir_menu_item({"id": "x"}, ancora)
        self._bombear()
        ancora.event_generate("<Button-1>", x=2, y=2)
        self.assertIsNotNone(self.aba._item_menu_popup)

    def test_esc_fecha(self):
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self._bombear()
        self.root.event_generate("<Escape>")
        self.assertIsNone(self.aba._item_menu_popup)

    def test_rolar_fecha(self):
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self._bombear()
        self.aba.lbl_total_prompts.event_generate("<MouseWheel>", delta=-120)
        self.assertIsNone(self.aba._item_menu_popup)

    def test_trocar_de_aba_fecha(self):
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self._bombear()
        self.aba.grid_forget()  # é o que mudar_aba faz com a aba que sai
        self._bombear()
        self.assertIsNone(self.aba._item_menu_popup)

    def test_lista_refeita_fecha(self):
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self.aba.atualizar_lista_historico()
        self.assertIsNone(self.aba._item_menu_popup)

    def test_fechar_avisa_a_linha(self):
        ao_fechar = MagicMock()
        self.aba._abrir_menu_item({"id": "x"}, self._ancora(), ao_fechar=ao_fechar)
        self.root.event_generate("<Escape>")
        ao_fechar.assert_called_once_with()

    def test_ligacoes_da_janela_nao_apagam_as_dos_outros(self):
        alheio = self.root.bind("<Button-1>", lambda e: None, add="+")
        self.addCleanup(lambda: self.root.unbind("<Button-1>"))
        self.aba._abrir_menu_item({"id": "x"}, self._ancora())
        self.aba._fechar_menu_item()
        self.assertIn(alheio, self.root.bind("<Button-1>"))


class TestDestaqueSoNoDono(_BaseTk):
    def _linhas(self):
        """(row_frame, btn_box, botão "...") de cada cartão na tela."""
        linhas = []
        for wrapper in self.aba.scroll_historico.winfo_children():
            for row in wrapper.winfo_children():
                if row.winfo_children() and isinstance(row, ctk.CTkFrame):
                    meta = next(w for w in row.winfo_children() if isinstance(w, ctk.CTkFrame))
                    box = next(w for w in meta.winfo_children() if isinstance(w, ctk.CTkFrame))
                    linhas.append((row, box))
        return linhas

    def _entrar(self, row):
        row._canvas.event_generate("<Enter>")

    def _sair(self, row):
        row._canvas.event_generate("<Leave>")

    def _acesa(self, row):
        return row.cget("fg_color") != "transparent"

    def test_com_o_menu_aberto_so_a_dona_fica_acesa(self):
        (a, box_a), (b, _) = self._linhas()
        self._entrar(a)
        mais = box_a.winfo_children()[-1]  # o "..." é o último botão da linha
        mais.invoke()
        self._sair(a)
        self._entrar(b)
        self._sair(b)
        self.assertTrue(self._acesa(a), "a linha dona do menu apagou com o menu aberto")
        self.assertFalse(self._acesa(b), "outra linha ficou acesa por causa do menu aberto")

    def test_fechar_o_menu_apaga_a_dona_sem_o_ponteiro(self):
        (a, box_a), _ = self._linhas()
        self._entrar(a)
        box_a.winfo_children()[-1].invoke()
        self._sair(a)
        with patch.object(a, "winfo_pointerxy", return_value=(-1, -1)):
            self.aba._fechar_menu_item()
        self.assertFalse(self._acesa(a))

    def test_fechar_o_menu_com_o_ponteiro_na_dona_mantem_acesa(self):
        (a, box_a), _ = self._linhas()
        self._entrar(a)
        box_a.winfo_children()[-1].invoke()
        sobre_a_linha = (a.winfo_rootx() + 5, a.winfo_rooty() + 5)
        with patch.object(a, "winfo_pointerxy", return_value=sobre_a_linha):
            self.aba._fechar_menu_item()
        self.assertTrue(self._acesa(a))


class TestExclusaoChegaAoResto(unittest.TestCase):
    def setUp(self):
        from core.storage.history_store import HistoryStore
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        caminho = os.path.join(self.tmp.name, ".history.json")
        p = patch("core.config.HISTORY_FILE", caminho)
        p.start()
        self.addCleanup(p.stop)
        self.store = HistoryStore(caminho)
        self.store.save_history_item("ditado que fica")
        self.store.save_history_item("é")
        self.aba = MagicMock()
        self.aba.history_items = self.store.load_history()
        self.mudou = MagicMock()
        self.aba._avisar_que_o_historico_mudou = lambda: HistoryTab._avisar_que_o_historico_mudou(self.aba)
        self.aba.callbacks = {"on_history_changed": self.mudou}

    def test_excluir_avisa_com_a_lista_nova(self):
        HistoryTab._excluir_item(self.aba, self.aba.history_items[0])
        self.mudou.assert_called_once()
        (itens,), _ = self.mudou.call_args
        self.assertEqual(["é"], [it["text"] for it in itens])

    def test_limpar_ruidos_avisa_com_a_lista_nova(self):
        HistoryTab._limpar_ruidos_acidentais(self.aba)
        self.mudou.assert_called_once()
        (itens,), _ = self.mudou.call_args
        self.assertEqual(["ditado que fica"], [it["text"] for it in itens])

    def test_sem_ruido_nao_avisa(self):
        self.aba.history_items = [it for it in self.aba.history_items if it["text"] != "é"]
        HistoryTab._limpar_ruidos_acidentais(self.aba)
        self.mudou.assert_not_called()

    def test_excluir_que_nao_salvou_nao_avisa(self):
        from core.storage.history_store import HistoryStore
        with patch.object(HistoryStore, "_load_strict", side_effect=PermissionError("em uso")):
            HistoryTab._excluir_item(self.aba, self.aba.history_items[0])
        self.mudou.assert_not_called()


class TestDashboardRecebeOAviso(unittest.TestCase):
    def test_a_aba_recebe_o_aviso_do_dashboard(self):
        dash = MagicMock()
        dash.callbacks = {"get_history": list}
        with patch("ui.dashboard.build_tab_history") as construir:
            WillyDashboard._construir_aba_historico(dash)
        callbacks = construir.call_args.kwargs["callbacks"]
        self.assertIs(dash._historico_mudou_na_aba, callbacks.get("on_history_changed"))
        self.assertIn("get_history", callbacks)

    def test_dashboard_adota_a_lista_e_avisa_a_bandeja(self):
        bandeja = MagicMock()
        dash = SimpleNamespace(history_items=["velho"], callbacks={"on_history_changed": bandeja})
        nova = [{"text": "novo"}]
        WillyDashboard._historico_mudou_na_aba(dash, nova)
        self.assertIs(nova, dash.history_items)
        bandeja.assert_called_once_with(nova)


class TestArquivoMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "Textos"))
        self.outro = os.path.join(self.tmp.name, "Textos", "outro_ditado.md")
        with open(self.outro, "w", encoding="utf-8") as f:
            f.write("de outro ditado")
        self.abrir = MagicMock(return_value=True)
        self.aba = MagicMock()
        self.aba.callbacks = {"get_outputs_dir": lambda: self.tmp.name, "on_open_file": self.abrir}

    def test_sem_o_md_do_item_nao_abre_o_de_outro(self):
        sumido = os.path.join(self.tmp.name, "Textos", "apagado.md")
        HistoryTab._abrir_arquivo_md_card(self.aba, {"mode": "transcribe", "file_path": sumido})
        self.abrir.assert_not_called()
        self.aba._abrir_pasta_arquivos.assert_called_once_with()
        args, kwargs = self.aba._mostrar_toast.call_args
        self.assertIn(".md", args[0])
        self.assertIs(False, kwargs.get("ok"))

    def test_item_sem_file_path_avisa(self):
        HistoryTab._abrir_arquivo_md_card(self.aba, {"mode": "transcribe"})
        self.abrir.assert_not_called()
        self.aba._mostrar_toast.assert_called_once()

    def test_md_do_item_abre_sem_aviso(self):
        HistoryTab._abrir_arquivo_md_card(self.aba, {"mode": "transcribe", "file_path": self.outro})
        self.abrir.assert_called_once_with(self.outro)
        self.aba._mostrar_toast.assert_not_called()
        self.aba._abrir_pasta_arquivos.assert_not_called()

    def test_arquivo_recusado_pela_porta_avisa(self):
        self.abrir.return_value = False
        HistoryTab._abrir_arquivo_md_card(self.aba, {"mode": "transcribe", "file_path": self.outro})
        self.aba._mostrar_toast.assert_called_once()
        self.aba._abrir_pasta_arquivos.assert_called_once_with()


class TestToast(_BaseTk):
    def test_falha_sem_o_check(self):
        self.aba._mostrar_toast("Não deu", ok=False)
        self.assertEqual("Não deu", self.aba.lbl_toast.cget("text"))

    def test_timer_do_toast_anterior_nao_apaga_o_seguinte(self):
        timers = []
        with patch.object(self.aba, "_safe_after", side_effect=lambda ms, f: timers.append(f)):
            self.aba._mostrar_toast("primeiro")
            self.aba._mostrar_toast("segundo", ok=False)
        timers[0]()
        self.assertEqual("segundo", self.aba.lbl_toast.cget("text"))
        timers[1]()
        self.assertEqual("", self.aba.lbl_toast.cget("text"))


if __name__ == "__main__":
    unittest.main()
