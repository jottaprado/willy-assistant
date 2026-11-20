"""
Testes unitários para o módulo modular ui.tabs.tab_history.
Verifica a integridade de HistoryTab, build_tab_history e compatibilidade com WillyDashboard.
"""

import unittest
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_history import HistoryTab, build_tab_history


class TestTabHistory(unittest.TestCase):
    """Testes dos componentes e execução das operações de histórico de prompts e transcrições."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_history_tab_componentes_e_metricas(self):
        """Verifica a inicialização dos widgets e renderização de métricas de produtividade."""
        mock_analytics = {
            "words_today": 1250,
            "total_words": 45000,
            "avg_wpm": 150,
            "saved_hours": 3,
            "saved_minutes": 20,
            "favorite_mode": "Ditado PT",
        }
        callbacks = {
            "get_history": list,
            "get_analytics": lambda: mock_analytics,
        }
        tab = build_tab_history(self.root, callbacks=callbacks)
        self.assertIsInstance(tab, HistoryTab)
        self.assertTrue(hasattr(tab, "lbl_stat_words_today"))
        self.assertTrue(hasattr(tab, "lbl_stat_total_words"))
        self.assertTrue(hasattr(tab, "lbl_stat_wpm"))
        self.assertTrue(hasattr(tab, "lbl_stat_time_saved"))
        self.assertTrue(hasattr(tab, "lbl_stat_favorite_mode"))
        self.assertTrue(hasattr(tab, "entry_busca"))
        self.assertTrue(hasattr(tab, "seg_filtro_historico"))
        self.assertTrue(hasattr(tab, "scroll_historico"))
        self.assertTrue(hasattr(tab, "lbl_total_prompts"))
        self.assertTrue(hasattr(tab, "btn_importar_audio"))
        self.assertTrue(hasattr(tab, "btn_abrir_pasta"))
        self.assertTrue(hasattr(tab, "btn_exportar_md"))

        self.assertIn("1.250", tab.lbl_stat_words_today.cget("text"))
        self.assertIn("45.000", tab.lbl_stat_total_words.cget("text"))
        self.assertEqual("150 WPM", tab.lbl_stat_wpm.cget("text"))
        self.assertEqual("3h 20m", tab.lbl_stat_time_saved.cget("text"))

    def test_history_tab_filtros_e_busca(self):
        """Testa filtros por categoria e busca textual em tempo real."""
        itens = [
            {"text": "Refatorar módulo de áudio", "mode": "prompt", "timestamp": "16/09/2026 14:00"},
            {"text": "Criar documentação de API", "mode": "transcribe", "timestamp": "16/09/2026 15:30"},
            {"text": "Traduzir termos técnicos", "mode": "translate", "timestamp": "16/09/2026 16:15"},
            {"text": "Ata de alinhamento com equipe", "mode": "meeting", "timestamp": "16/09/2026 17:00"},
            {"text": "Executar testes de regressão", "mode": "action", "timestamp": "16/09/2026 18:00"},
        ]
        callbacks = {
            "get_history": lambda: itens,
        }
        tab = build_tab_history(self.root, callbacks=callbacks, history_items=itens)
        tab.atualizar_lista_historico()

        # Total: 5 cards
        cards = tab.scroll_historico.winfo_children()
        self.assertEqual(len(cards), 5)
        self.assertIn("5 de 5", tab.lbl_total_prompts.cget("text"))

        # Filtro: Prompts de Agente (aciona pelo comando real do botão para testar o on_change)
        tab.seg_filtro_historico.buttons["Prompts"].invoke()
        self.assertEqual(len(tab.scroll_historico.winfo_children()), 1)
        self.assertIn("1 de 5", tab.lbl_total_prompts.cget("text"))

        # Filtro: Ações
        tab.seg_filtro_historico.buttons["Ações"].invoke()
        self.assertEqual(len(tab.scroll_historico.winfo_children()), 1)
        self.assertIn("1 de 5", tab.lbl_total_prompts.cget("text"))

        # Restaura Todos e faz busca textual
        tab.seg_filtro_historico.buttons["Todos"].invoke()
        tab.entry_busca.insert(0, "Ata")
        tab.atualizar_lista_historico()
        self.assertEqual(len(tab.scroll_historico.winfo_children()), 1)
        self.assertIn("1 de 5", tab.lbl_total_prompts.cget("text"))

        # Busca inexistente -> Estado vazio
        tab.entry_busca.delete(0, "end")
        tab.entry_busca.insert(0, "termo_inexistente_xyz_123")
        tab.atualizar_lista_historico()
        children = tab.scroll_historico.winfo_children()
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], ctk.CTkLabel)
        self.assertIn("Nenhum prompt encontrado", children[0].cget("text"))

        # AUD-071: inclui modos 'send' em Ditados, 'transform' em Ações, e busca em raw_text
        itens.append({"text": "Enviar mensagem rápida", "mode": "send", "timestamp": "16/09/2026 18:30"})
        itens.append({"text": "Texto polido pela IA", "raw_text": "fala original bruta", "mode": "transform", "timestamp": "16/09/2026 19:00"})
        tab.entry_busca.delete(0, "end")
        tab.seg_filtro_historico.buttons["Ditados"].invoke()
        self.assertEqual(len(tab.scroll_historico.winfo_children()), 2)
        tab.seg_filtro_historico.buttons["Ações"].invoke()
        self.assertEqual(len(tab.scroll_historico.winfo_children()), 2)
        tab.seg_filtro_historico.buttons["Todos"].invoke()
        tab.entry_busca.insert(0, "original bruta")
        tab.atualizar_lista_historico()
        self.assertEqual(len(tab.scroll_historico.winfo_children()), 1)

        tab.entry_busca.delete(0, "end")
        tab.entry_busca.insert(0, "termo_inexistente_xyz_123")
        tab.atualizar_lista_historico()
        children = tab.scroll_historico.winfo_children()
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], ctk.CTkLabel)
        self.assertIn("Nenhum prompt encontrado", children[0].cget("text"))

    def test_history_tab_operacoes_e_callbacks(self):
        """Testa callbacks de reprodução, TTS, pasta e limpeza."""
        audio_tocado = []
        tts_falado = []
        limpo = []
        pasta_aberta = []

        callbacks = {
            "get_history": lambda: [{"text": "Teste", "mode": "transcribe"}],
            "on_play_audio": lambda path: audio_tocado.append(path),
            "on_speak_text": lambda text: tts_falado.append(text),
            "on_clear_history": lambda: limpo.append(True),
            "on_open_outputs": lambda: pasta_aberta.append(True),
        }
        tab = build_tab_history(self.root, callbacks=callbacks)

        tab._tocar_audio("fake_audio.wav")
        self.assertEqual(audio_tocado, ["fake_audio.wav"])

        self.assertFalse(hasattr(tab, "_ler_texto_tts"))
        self.assertEqual(tts_falado, [])

        tab._abrir_pasta_arquivos()
        self.assertTrue(pasta_aberta)

        tab._confirmar_limpar_historico()
        self.assertTrue(limpo)
        self.assertEqual(tab.history_items, [])

    def test_history_tab_botoes_hover_reusar_e_excluir_item(self):
        """Testa os comandos reais dos botões de hover (Reusar e Menu -> Excluir...)."""
        reusados = []
        item = {"id": "it-1", "text": "Texto para reusar ou excluir", "mode": "transcribe", "timestamp": "16/09/2026 14:00"}
        tab = build_tab_history(
            self.root,
            callbacks={
                "get_history": lambda: [item],
                "on_reuse_text": lambda t: (reusados.append(t), True)[1],
            },
            history_items=[item],
        )
        tab.atualizar_lista_historico()
        card_wrapper = tab.scroll_historico.winfo_children()[0]
        row_frame = next(w for w in card_wrapper.winfo_children() if isinstance(w, ctk.CTkFrame))
        # Dispara o handler Tcl registrado em <Enter> no _canvas do CTkFrame para criar os botões de hover (_garantir_acoes)
        script_enter = row_frame._canvas.bind("<Enter>")
        cmd_tcl = script_enter.split("[", 1)[1].split()[0]
        tab.tk.call(cmd_tcl, *(["0"] * 19))
        meta_row = next(w for w in row_frame.winfo_children() if isinstance(w, ctk.CTkFrame))
        btn_box = next(w for w in meta_row.winfo_children() if isinstance(w, ctk.CTkFrame))
        botoes = [w for w in btn_box.winfo_children() if isinstance(w, ctk.CTkButton)]
        # Ordem sem áudio: [btn_reusar, btn_abrir_md, btn_menu_item]
        btn_reusar = botoes[0]
        btn_menu_item = botoes[-1]

        with patch("ui.tabs.tab_history.copiar_pelo_clique", return_value=True):
            btn_reusar.invoke()
        self.assertEqual(reusados, ["Texto para reusar ou excluir"])

        with patch.object(tab, "_confirmar_excluir_item") as mock_confirmar:
            btn_menu_item.invoke()
            self.assertIsNotNone(tab._item_menu_popup)
            btn_excluir = next(w for w in tab._item_menu_popup.winfo_children() if isinstance(w, ctk.CTkButton))
            btn_excluir.invoke()
            mock_confirmar.assert_called_once_with(item)

    def test_dashboard_delegacao_historico(self):
        """Testa a fachada e delegação de WillyDashboard para tab_history."""
        test_history = [
            {"text": "Prompt 1", "mode": "prompt", "timestamp": "01/01/2026 10:00"},
            {"text": "Ditado 1", "mode": "transcribe", "timestamp": "01/01/2026 10:10"},
        ]
        isolar_config(self)
        dash = WillyDashboard(callbacks={"get_history": lambda: test_history, "get_app_rules": list})
        dash.withdraw()
        try:
            self.assertIn("history", dash.frames_abas)
            self.assertIsInstance(dash.frames_abas["history"], HistoryTab)
            self.assertTrue(hasattr(dash, "tab_history"))
            self.assertIsNotNone(dash.entry_busca)
            self.assertIsNotNone(dash.scroll_historico)
            self.assertIsNotNone(dash.seg_filtro_historico)
            self.assertIsNotNone(dash.lbl_total_prompts)
            self.assertIsNotNone(dash.btn_importar_audio)

            # Teste chamada de fachada
            dash.atualizar_lista_historico()
            self.assertIn("2 de 2", dash.lbl_total_prompts.cget("text"))
        finally:
            destruir_tk(dash)

    def test_apple_redesign_features(self):
        """Valida requisitos do redesign Apple: pluralização, tempo humanizado, datas e descarte de ruído."""
        import datetime

        from ui.theme import format_relative_date, format_time_saved, pluralize

        # 1. Pluralização
        self.assertEqual("1 palavra", pluralize(1, "palavra", "palavras"))
        self.assertEqual("2 palavras", pluralize(2, "palavra", "palavras"))
        self.assertEqual("0 palavras", pluralize(0, "palavra", "palavras"))
        self.assertEqual("1 prompt", pluralize(1, "prompt", "prompts"))
        self.assertEqual("5 prompts", pluralize(5, "prompt", "prompts"))

        # 2. Tempo economizado humanizado
        self.assertEqual("45 s", format_time_saved(0, 0, 45))
        self.assertEqual("5 min", format_time_saved(0, 5, 0))
        self.assertEqual("2h 15m", format_time_saved(2, 15, 0))

        # 3. Data relativa
        hoje_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        self.assertIn("Hoje", format_relative_date(hoje_str))

        # 4. Descarte de ruído acidental ("K")
        itens_com_ruido = [
            {"text": "K", "mode": "transcribe", "timestamp": "01/01/2026 10:00"},
            {"text": "Ditado com texto válido", "mode": "transcribe", "timestamp": "01/01/2026 10:05"},
        ]
        tab = build_tab_history(self.root, callbacks={"get_history": lambda: itens_com_ruido}, history_items=itens_com_ruido)
        tab.atualizar_lista_historico()
        # Apenas o item válido deve ser renderizado
        cards = tab.scroll_historico.winfo_children()
        self.assertEqual(len(cards), 1)

        # 5. Segmented control sem emojis
        for val in tab.seg_filtro_historico.cget("values"):
            # Nenhum emoji deve estar presente nos valores do segmented control
            self.assertTrue(val in ("Todos", "Ditados", "Traduções", "Prompts", "Ações", "Reuniões"))

        # 6. Botão de menu três pontos presente
        self.assertTrue(hasattr(tab, "btn_menu_opcoes"))


class TestAbaNaoSobrescreveOHistorico(unittest.TestCase):
    """A aba gravava a PRÓPRIA lista no disco, apagando o que o pipeline acrescentou depois."""

    def setUp(self):
        import os
        import tempfile

        from core.storage.history_store import HistoryStore
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, ".history.json")
        self.patch_arquivo = patch("core.config.HISTORY_FILE", self.path)
        self.patch_arquivo.start()
        self.store = HistoryStore(self.path)
        self.velho = self.store.save_history_item("ditado antigo")[-1]
        self.ruido = self.store.save_history_item("é")[-1]
        # A aba carregou a lista AQUI. Depois disso o pipeline acrescenta um ditado novo.
        self.aba = MagicMock()
        self.aba.history_items = self.store.load_history()
        self.store.save_history_item("ditado que chegou depois")

    def tearDown(self):
        self.patch_arquivo.stop()
        self.tmp.cleanup()

    def _textos(self):
        return [it["text"] for it in self.store.load_history()]

    def test_excluir_preserva_o_que_chegou_depois(self):
        HistoryTab._excluir_item(self.aba, self.aba.history_items[0])
        self.assertEqual(["é", "ditado que chegou depois"], self._textos())
        self.aba._mostrar_toast.assert_called_with("Transcrição excluída do histórico")

    def test_limpar_ruidos_preserva_o_que_chegou_depois(self):
        HistoryTab._limpar_ruidos_acidentais(self.aba)
        self.assertEqual(["ditado antigo", "ditado que chegou depois"], self._textos())

    def test_excluir_com_disco_em_uso_avisa_em_vez_de_confirmar(self):
        from core.storage.history_store import HistoryStore
        with patch.object(HistoryStore, "_load_strict", side_effect=PermissionError("em uso")):
            HistoryTab._excluir_item(self.aba, self.aba.history_items[0])
        self.aba._mostrar_toast.assert_called_with("Não consegui salvar o histórico. O item pode voltar", ok=False)


class TestTratamentoDeErrosHistoryTab(unittest.TestCase):
    """Testes de regressão para T-19 (AUD-072, AUD-175 a AUD-185)."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_confirmar_limpar_historico_nao_finge_sucesso_em_erro(self):
        """AUD-184: falha em on_clear_history preserva itens, loga em stderr e mostra toast de erro."""
        import io
        itens = [{"text": "Item importante", "mode": "transcribe", "timestamp": "16/09/2026 14:00"}]

        def _falhar_limpeza():
            raise PermissionError("arquivo .history.json bloqueado")

        tab = build_tab_history(
            self.root,
            callbacks={"on_clear_history": _falhar_limpeza},
            history_items=list(itens),
        )
        try:
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                tab._confirmar_limpar_historico()
            self.assertEqual(len(tab.history_items), 1)
            self.assertIn("arquivo .history.json bloqueado", buf.getvalue())
            self.assertEqual(tab.lbl_toast.cget("text"), "Não foi possível limpar o histórico")
        finally:
            tab.destroy()

    def test_exportar_historico_md_exibe_toast_e_loga_em_erro(self):
        """AUD-072: falha de I/O ao exportar Markdown loga em stderr e mostra toast de erro."""
        import io
        tab = build_tab_history(
            self.root,
            history_items=[{"text": "Texto exportado", "mode": "transcribe", "timestamp": "16/09/2026 14:00"}],
        )
        try:
            buf = io.StringIO()
            with (
                patch("tkinter.filedialog.asksaveasfilename", return_value="C:/invalido/historico.md"),
                patch("builtins.open", side_effect=PermissionError("acesso negado")),
                patch("sys.stderr", buf),
            ):
                tab._exportar_historico_md()
            self.assertIn("acesso negado", buf.getvalue())
            self.assertEqual(tab.lbl_toast.cget("text"), "Não foi possível exportar o histórico")
        finally:
            tab.destroy()

    def test_reusar_e_copiar_exibem_toast_mesmo_se_botao_falhar(self):
        """AUD-180, AUD-181: falha ao configurar ícone do botão não omite o toast ao usuário."""
        import io
        tab = build_tab_history(self.root, callbacks={"on_reuse_text": lambda _t: False})
        try:
            botao_quebrado = MagicMock()
            botao_quebrado.configure.side_effect = RuntimeError("widget destruído")
            buf = io.StringIO()
            with (
                patch("ui.tabs.tab_history.copiar_pelo_clique", return_value=True),
                patch("sys.stderr", buf),
            ):
                tab._reusar_com_feedback("texto reusado", botao_quebrado)
                self.assertIn("Não achei o app de antes: copiado, cole com Ctrl+V", tab.lbl_toast.cget("text"))

                ok = tab._copiar_com_feedback("texto copiado", botao_quebrado)
                self.assertTrue(ok)
                self.assertIn("Copiado para a área de transferência", tab.lbl_toast.cget("text"))
        finally:
            tab.destroy()

    def test_ia_disponivel_retorna_false_e_callbacks_logam_erros(self):
        """AUD-175..179, AUD-182, AUD-185: _ia_disponivel retorna False sob erro e callbacks logam em stderr."""
        import io
        buf = io.StringIO()

        def _boom(*_a, **_kw):
            raise RuntimeError("falha simulada callback")

        with patch("sys.stderr", buf):
            tab = build_tab_history(
                self.root,
                callbacks={
                    "get_history": _boom,
                    "get_analytics": _boom,
                    "get_settings": _boom,
                    "on_open_outputs": _boom,
                    "on_play_audio": _boom,
                    "on_transcribe_file": _boom,
                },
            )
            try:
                self.assertEqual(tab.history_items, [])
                self.assertFalse(tab._ia_disponivel())

                tab._abrir_pasta_arquivos()
                self.assertEqual(tab.lbl_toast.cget("text"), "Não foi possível abrir a pasta de arquivos")

                tab._tocar_audio("inexistente.wav")
                self.assertEqual(tab.lbl_toast.cget("text"), "Não foi possível reproduzir o áudio")

                with patch("tkinter.filedialog.askopenfilename", return_value="C:/audio.wav"):
                    tab._dialogo_importar_audio()
                self.assertEqual(tab.lbl_toast.cget("text"), "Não foi possível enviar o áudio para transcrição")

                tab.callbacks["safe_dispatch_ui"] = _boom
                tab._safe_after(10, lambda: None)
            finally:
                tab.destroy()

        logs = buf.getvalue()
        self.assertIn("Erro ao carregar histórico inicial", logs)
        self.assertIn("Erro ao atualizar métricas analíticas", logs)
        self.assertIn("Erro ao verificar disponibilidade da IA", logs)
        self.assertIn("Erro ao abrir pasta de arquivos", logs)
        self.assertIn("Erro ao reproduzir áudio", logs)
        self.assertIn("Erro ao importar áudio para transcrição", logs)
        self.assertIn("Erro em safe_dispatch_ui", logs)


if __name__ == "__main__":
    unittest.main()
