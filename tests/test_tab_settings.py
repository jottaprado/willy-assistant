"""
Testes unitários para a aba modular ui.tabs.tab_settings.
Verifica a inicialização, controles visuais, recarregamento, salvamento,
exportação/importação de perfil e fachadas de delegação no WillyDashboard.
"""

import unittest
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard
from ui.tabs.tab_settings import SettingsTab, build_tab_settings


class TestTabSettings(unittest.TestCase):
    """Testes dos componentes e operações da Aba de Ajustes & Configurações."""

    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def test_settings_tab_widgets_initialization(self):
        """Valida que todos os 10 blocos de configurações instanciam seus respectivos widgets."""
        callbacks = {
            "get_settings": dict,
            "get_app_rules": list,
            "get_audio_devices": lambda: [(0, "Microfone Padrão"), (1, "Headset USB")],
            "get_outputs_dir": lambda: "C:/fake/outputs",
        }
        tab = build_tab_settings(self.root, callbacks=callbacks)
        self.assertIsInstance(tab, SettingsTab)

        expected_widgets = [
            "seg_modo_envio", "lbl_modo_envio_desc", "slider_silencio", "lbl_silence_val",
            "seg_tone", "lbl_tom_desc", "seg_input_lang", "lbl_lang_desc",
            "seg_perfil", "lbl_perfil_desc",
            "switch_ia", "switch_mudo", "switch_autostart", "switch_private_mode",
            "switch_clean_fillers", "switch_clipboard_only", "switch_smart_paragraphing",
            "switch_save_audio", "switch_silero_vad", "switch_wake_word", "switch_whisper_mode",
            "entry_hk_voice", "entry_hk_trans", "entry_hk_prompt", "entry_hk_meeting",
            "entry_hk_master", "entry_hk_transform", "entry_hk_profile", "entry_hk_history",
            "entry_hk_undo", "entry_hk_send", "entry_hk_speak", "entry_hk_sticky", "entry_hk_captions",
            "seg_posicao", "seg_modelo",
            "combo_microfone", "combo_sys_audio", "seg_mic_gain", "btn_test_mic_live", "bar_vu_meter",
            "btn_exportar_perfil", "btn_importar_perfil",
            "entry_key", "lbl_status_key", "btn_ver_key", "btn_salvar_config",
            "lbl_pasta_path", "btn_abrir_pasta_dir"
        ]

        for w_name in expected_widgets:
            self.assertTrue(hasattr(tab, w_name), f"Widget ausente em SettingsTab: {w_name}")
            widget = getattr(tab, w_name)
            self.assertIsNotNone(widget, f"Widget nulo em SettingsTab: {w_name}")

    def test_recarregar_dados_config_completa(self):
        """Verifica se recarregar_dados popula corretamente os campos com base no dicionário de config."""
        tab = build_tab_settings(self.root, callbacks={"get_app_rules": list})

        cfg_mock = {
            "auto_silence": False,
            "silence_seconds": 3.5,
            "refine_prompt": False,
            "silent_mode": True,
            "pill_position": "topo",
            "llm_model": "openai/gpt-oss-20b",
            "audio_device": None,
            "system_audio_device": None,
            "mic_gain": 2.0,
            "api_key": "gsk_test_mock_key_12345",
            "autostart": True,
            "private_mode": True,
            "clean_fillers": False,
            "clipboard_only": True,
            "smart_paragraphing": False,
            "save_audio_files": True,
            "silero_vad": False,
            "wake_word_enabled": True,
            "whisper_mode": True,
            "processing_profile": "executivo",
            "output_tone": "formal",
            "input_language": "pt",
            "voice_hotkey": "ctrl+alt+1",
            "translate_hotkey": "ctrl+alt+2",
            "prompt_hotkey": "ctrl+alt+3",
            "meeting_hotkey": "ctrl+alt+4",
            "master_hotkey": "ctrl+alt+5",
        }

        tab.recarregar_dados(cfg_mock)

        self.assertIn("Manual", tab.seg_modo_envio.get())
        self.assertEqual(tab.slider_silencio.get(), 3.5)
        self.assertEqual(tab.switch_ia.get(), 0)
        self.assertEqual(tab.switch_mudo.get(), 1)
        self.assertEqual(tab.seg_posicao.get(), "Topo da Tela")
        self.assertIn("Flash", tab.seg_modelo.get())
        self.assertIn("2.0x", tab.seg_mic_gain.get())
        self.assertEqual(tab.entry_key.get(), "gsk_test_mock_key_12345")
        self.assertIn("ativa", tab.lbl_status_key.cget("text").lower())
        self.assertEqual(tab.switch_autostart.get(), 1)
        self.assertEqual(tab.switch_private_mode.get(), 1)
        self.assertEqual(tab.switch_clean_fillers.get(), 0)
        self.assertEqual(tab.switch_clipboard_only.get(), 1)
        self.assertEqual(tab.switch_smart_paragraphing.get(), 0)
        self.assertEqual(tab.switch_save_audio.get(), 1)
        self.assertEqual(tab.switch_silero_vad.get(), 0)
        self.assertEqual(tab.switch_wake_word.get(), 1)
        self.assertEqual(tab.switch_whisper_mode.get(), 1)
        self.assertIn("Executivo", tab.seg_perfil.get())
        self.assertIn("Executivo", tab.seg_tone.get())
        self.assertIn("Português", tab.seg_input_lang.get())
        self.assertEqual(tab.entry_hk_voice.get(), "ctrl+alt+1")
        self.assertEqual(tab.entry_hk_trans.get(), "ctrl+alt+2")
        self.assertEqual(tab.entry_hk_prompt.get(), "ctrl+alt+3")
        self.assertEqual(tab.entry_hk_meeting.get(), "ctrl+alt+4")
        self.assertEqual(tab.entry_hk_master.get(), "ctrl+alt+5")

    def test_salvar_configuracoes_disparo_callbacks(self):
        """Verifica se salvar_configuracoes coleta todos os valores e aciona on_save_settings."""
        dados_salvos = []
        autostart_toggle = []

        callbacks = {
            "on_save_settings": lambda dados: dados_salvos.append(dados),
            "get_app_rules": list,
            "on_toggle_autostart": lambda enabled: autostart_toggle.append(enabled),
        }
        tab = build_tab_settings(self.root, callbacks=callbacks)

        tab.seg_modo_envio.set("⚡ Automático (Silêncio)")
        tab.slider_silencio.set(2.4)
        tab.switch_ia.select()
        tab.switch_mudo.deselect()
        tab.seg_posicao.set("Rodapé Central (Padrão)")
        tab.seg_modelo.set("🧠 Smart (GPT-OSS 120B)")
        tab.seg_perfil.set("💻 Dev & Código")
        tab.seg_tone.set("🌿 Natural / Fiel")
        tab.seg_input_lang.set("🌐 Automático")
        tab.entry_key.delete(0, "end")
        tab.entry_key.insert(0, "gsk_minha_nova_chave_segura")
        tab.switch_autostart.select()
        tab.switch_private_mode.select()
        tab.switch_clipboard_only.select()
        tab.switch_save_audio.select()
        tab.switch_silero_vad.select()
        tab.switch_wake_word.select()
        tab.switch_whisper_mode.select()

        tab.salvar_configuracoes()

        self.assertEqual(len(dados_salvos), 1)
        cfg = dados_salvos[0]
        self.assertTrue(cfg["AUTO_SILENCE"])
        self.assertTrue(cfg["PRIVATE_MODE"])
        self.assertTrue(cfg["CLIPBOARD_ONLY"])
        self.assertTrue(cfg["SAVE_AUDIO_FILES"])
        self.assertTrue(cfg["SILERO_VAD"])
        self.assertTrue(cfg["WAKE_WORD_ENABLED"])
        self.assertTrue(cfg["WHISPER_MODE"])
        self.assertAlmostEqual(cfg["SILENCE_SECONDS"], 2.4, places=1)
        self.assertTrue(cfg["REFINE_PROMPT"])
        self.assertFalse(cfg["SILENT_MODE"])
        self.assertEqual(cfg["PILL_POSITION"], "centro_inferior")
        self.assertEqual(cfg["GROQ_LLM_MODEL"], "openai/gpt-oss-120b")
        self.assertEqual(cfg["PROCESSING_PROFILE"], "dev")
        self.assertEqual(cfg["OUTPUT_TONE"], "natural")
        self.assertEqual(cfg["INPUT_LANGUAGE"], "auto")
        self.assertEqual(cfg["GROQ_API_KEY"], "gsk_minha_nova_chave_segura")
        self.assertEqual(autostart_toggle, [True])

        mapa_switches = [
            ("switch_ia", "REFINE_PROMPT"),
            ("switch_mudo", "SILENT_MODE"),
            ("switch_private_mode", "PRIVATE_MODE"),
            ("switch_clean_fillers", "CLEAN_FILLERS"),
            ("switch_clipboard_only", "CLIPBOARD_ONLY"),
            ("switch_smart_paragraphing", "SMART_PARAGRAPHING"),
            ("switch_save_audio", "SAVE_AUDIO_FILES"),
            ("switch_silero_vad", "SILERO_VAD"),
            ("switch_wake_word", "WAKE_WORD_ENABLED"),
            ("switch_whisper_mode", "WHISPER_MODE"),
        ]
        for attr_ligado, chave_ligada in mapa_switches:
            for attr, _ in mapa_switches:
                getattr(tab, attr).deselect()
            getattr(tab, attr_ligado).select()
            dados_salvos.clear()
            tab.salvar_configuracoes()
            cfg_isolada = dados_salvos[-1]
            for _, chave in mapa_switches:
                self.assertEqual(
                    chave == chave_ligada,
                    cfg_isolada[chave],
                    f"Switch {attr_ligado} deveria gravar apenas {chave_ligada}=True, mas {chave}={cfg_isolada[chave]}",
                )

    def test_eventos_ui_e_descricoes(self):
        """Testa reações dinâmicas de UI a mudanças de modo de envio, tom, idioma e slider."""
        tab = build_tab_settings(self.root, callbacks={"get_app_rules": list})

        # Modo de envio
        tab._on_change_modo_envio("🛑 Manual (Pressione p/ Parar)")
        self.assertIn("Pausado", tab.lbl_silence_val.cget("text"))
        tab._on_change_modo_envio("⚡ Automático (Silêncio)")
        self.assertIn("s", tab.lbl_silence_val.cget("text"))

        # Slider de silêncio
        tab._on_slider_silencio(1.8)
        self.assertEqual(tab.lbl_silence_val.cget("text"), "1.8s")

        # Mudança de tom
        tab._on_change_tom("⚡ Direto / Conciso")
        self.assertIn("direto", tab.lbl_tom_desc.cget("text").lower())

        # Mudança de idioma
        tab._on_change_idioma("🇺🇸 Inglês")
        self.assertIn("inglês", tab.lbl_lang_desc.cget("text").lower())

        # Toggle visibilidade da chave de API
        tab.entry_key.insert(0, "gsk_teste")
        self.assertEqual(tab.entry_key.cget("show"), "•")
        tab._toggle_ver_chave()
        self.assertEqual(tab.entry_key.cget("show"), "")
        tab._toggle_ver_chave()
        self.assertEqual(tab.entry_key.cget("show"), "•")

    def test_exportar_e_importar_perfil(self):
        """Testa as rotinas de exportação e importação de perfil."""
        export_chamado = []
        import_chamado = []

        callbacks = {
            "on_export_profile": lambda path, incluir: export_chamado.append((path, incluir)) or True,
            "on_import_profile": lambda path: import_chamado.append(path) or True,
            "get_settings": lambda: {"refine_prompt": True},
            "get_app_rules": list,
        }
        tab = build_tab_settings(self.root, callbacks=callbacks)

        # O histórico fica de fora por padrão (decisão do dono, 22/10); o interruptor o inclui.
        with patch("customtkinter.filedialog.asksaveasfilename", return_value="C:/fake/perfil.json"):
            tab.exportar_perfil_json()
            tab.switch_incluir_historico.select()
            tab.exportar_perfil_json()
            self.assertEqual(export_chamado, [("C:/fake/perfil.json", False), ("C:/fake/perfil.json", True)])

        with patch("customtkinter.filedialog.askopenfilename", return_value="C:/fake/perfil_in.json"):
            tab.importar_perfil_json()
            self.assertEqual(import_chamado, ["C:/fake/perfil_in.json"])

    def test_dashboard_delegacao_settings(self):
        """Valida que WillyDashboard instancia a aba modular e delega todos os atributos e métodos."""
        config_mock = {
            "auto_silence": True,
            "silence_seconds": 2.5,
            "refine_prompt": True,
            "silent_mode": False,
            "api_key": "gsk_dashboard_test",
        }
        callbacks = {
            "get_settings": lambda: config_mock,
            "get_app_rules": list,
            "get_audio_devices": lambda: [(0, "Padrão")],
            "on_save_settings": MagicMock(),
        }

        dash = WillyDashboard(callbacks=callbacks)
        dash.withdraw()
        try:
            self.assertIn("settings", dash.frames_abas)
            self.assertIsInstance(dash.frames_abas["settings"], SettingsTab)
            self.assertTrue(hasattr(dash, "tab_settings"))

            # Fachada de atributos
            self.assertIsNotNone(dash.seg_modo_envio)
            self.assertIsNotNone(dash.slider_silencio)
            self.assertIsNotNone(dash.switch_ia)
            self.assertIsNotNone(dash.combo_microfone)
            self.assertIsNotNone(dash.entry_key)
            self.assertIsNotNone(dash.btn_salvar_config)

            # Recarregamento via fachada
            dash.recarregar_dados()
            self.assertEqual(dash.entry_key.get(), "gsk_dashboard_test")

            # Salvar via fachada
            dash._salvar_configuracoes()
            self.assertEqual(callbacks["on_save_settings"].call_count, 1)
        finally:
            destruir_tk(dash)

    def test_falha_em_get_settings_loga_e_impede_sobrescrita_silenciosa(self):
        """Falha em get_settings() deve logar em stderr e impedir sobrescrita silenciosa no salvar."""
        import io

        salvos = []
        stderr_buf = io.StringIO()

        def _get_falho():
            raise RuntimeError("disco corrompido ao ler .env")

        with patch("sys.stderr", stderr_buf):
            tab = build_tab_settings(self.root, callbacks={
                "get_settings": _get_falho,
                "on_save_settings": lambda d: salvos.append(d),
            })
        self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())
        self.assertIn("[SettingsTab]", stderr_buf.getvalue())
        self.assertTrue(tab._falha_carregamento_config)

        # Tentar salvar com estado não carregado não deve sobrescrever .env
        tab.salvar_configuracoes()
        self.assertEqual(salvos, [])
        self.assertIn("Não salvei", tab.btn_salvar_config.cget("text"))

        # Após recarregar com sucesso, salvar volta a funcionar
        tab.recarregar_dados({"api_key": "gsk_recuperada", "refine_prompt": True})
        self.assertFalse(tab._falha_carregamento_config)
        tab.salvar_configuracoes()
        self.assertEqual(len(salvos), 1)
        self.assertEqual(salvos[0]["GROQ_API_KEY"], "gsk_recuperada")

    def test_exportar_e_importar_perfil_exibem_feedback_em_falha(self):
        """Retorno False em on_export_profile / on_import_profile deve atualizar o texto do botão com aviso de falha."""
        tab = build_tab_settings(self.root, callbacks={
            "on_export_profile": lambda _path, _inc: False,
            "on_import_profile": lambda _path: False,
        })
        self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())

        with patch("tkinter.filedialog.asksaveasfilename", return_value="C:/fake/perfil.json"):
            tab.exportar_perfil_json()
        self.assertIn("Falha", tab.btn_exportar_perfil.cget("text"))

        with patch("tkinter.filedialog.askopenfilename", return_value="C:/fake/perfil.json"):
            tab.importar_perfil_json()
        self.assertIn("Falha", tab.btn_importar_perfil.cget("text"))

    def test_worker_teste_microfone_preserva_causa_e_sinaliza_erro(self):
        """Falha em negociar_stream deve preservar a exceção original em stderr e sinalizar no botão."""
        import io

        tab = build_tab_settings(self.root, callbacks={
            "safe_dispatch_ui": lambda fn, *a, delay_ms=0, **_kw: fn(*a) if delay_ms == 0 else None,
        })
        self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())

        stderr_buf = io.StringIO()
        with patch("ui.tabs.tab_settings.negociar_stream", side_effect=RuntimeError("PortAudioError: Invalid device")), \
             patch("sys.stderr", stderr_buf):
            tab._worker_teste_microfone(0)

        self.assertIn("PortAudioError: Invalid device", stderr_buf.getvalue())
        self.assertIn("Erro", tab.btn_test_mic_live.cget("text"))

    def test_callbacks_com_erro_logam_em_stderr(self):
        """Erros em safe_dispatch_ui, on_open_outputs, webbrowser.open, get_audio_devices e get_outputs_dir devem logar em stderr."""
        import io

        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            tab = build_tab_settings(self.root, callbacks={
                "get_settings": lambda: {"refine_prompt": True},
            "get_app_rules": list,
                "get_audio_devices": lambda: (_ for _ in ()).throw(RuntimeError("falha audio devices")),
                "get_outputs_dir": lambda: (_ for _ in ()).throw(RuntimeError("falha outputs dir")),
                "on_open_outputs": lambda: (_ for _ in ()).throw(RuntimeError("falha abrir pasta")),
                "safe_dispatch_ui": lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("falha dispatch")),
            })
            self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())
            tab._safe_after(10, lambda: None)
            tab._abrir_pasta_arquivos()
            with patch("ui.tabs.tab_settings.webbrowser.open", side_effect=RuntimeError("falha browser")):
                tab._abrir_site_groq()
            with patch.object(tab, "winfo_toplevel", side_effect=RuntimeError("falha navegar atalhos")):
                tab._navegar_atalhos()

        logs = stderr_buf.getvalue()
        self.assertIn("falha audio devices", logs)
        self.assertIn("falha outputs dir", logs)
        self.assertIn("falha abrir pasta", logs)
        self.assertIn("falha dispatch", logs)
        self.assertIn("falha browser", logs)
        self.assertIn("falha navegar atalhos", logs)


if __name__ == "__main__":
    unittest.main()
