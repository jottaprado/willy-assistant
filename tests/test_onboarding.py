"""Testes unitários e de integração do Onboarding guiado do Willy."""

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import customtkinter as ctk
import groq
import httpx
import numpy as np

from core.config import ConfigManager
from core.groq_service import GroqService
from tests.config_isolada import isolar_config
from tests.test_cofre_chave import CofreDeMentira
from tests.willy_isolado import destruir_tk


class TestOnboardingConfig(unittest.TestCase):
    """Regras de estado de onboarding, catálogo extensível de chaves e recarga do cofre."""

    def setUp(self):
        self.temp_dir = isolar_config(self)
        self.env_file = os.path.join(self.temp_dir, ".env")

    def _escrever_env(self, conteudo: str):
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write(conteudo)

    def test_instalacao_limpa_precisa_onboarding_e_catalogo_mostra_groq(self):
        from core.config import credenciais_do_willy

        self._escrever_env("GROQ_API_KEY=\nONBOARDING_COMPLETED=false\n")
        cfg = ConfigManager(cofre=CofreDeMentira())

        self.assertFalse(cfg.onboarding_completed)
        self.assertTrue(cfg.precisa_onboarding())

        catalogo = credenciais_do_willy(cfg)
        self.assertGreaterEqual(len(catalogo), 1)
        groq_item = next((c for c in catalogo if c["env_var"] == "GROQ_API_KEY"), None)
        self.assertIsNotNone(groq_item)
        self.assertTrue(groq_item["obrigatoria"])
        self.assertTrue(groq_item["gratuita"])
        self.assertTrue(groq_item["sem_cartao"])
        self.assertFalse(groq_item["configurada"])
        self.assertIn("console.groq.com/keys", groq_item["url_chaves"])

    def test_usuario_existente_com_chave_ou_historico_nao_cai_no_onboarding(self):
        # Usuário antigo atualizando sem ONBOARDING_COMPLETED no .env, mas já com chave no cofre.
        self._escrever_env("VOICE_HOTKEY=ctrl+space\n")
        cfg_com_chave = ConfigManager(cofre=CofreDeMentira(chave="gsk_existente"))
        self.assertTrue(cfg_com_chave.onboarding_completed)
        self.assertFalse(cfg_com_chave.precisa_onboarding())

        # Ou sem chave momentaneamente, mas com histórico prévio.
        isolar_config(self)
        cfg_com_hist = ConfigManager(cofre=CofreDeMentira())
        cfg_com_hist.save_history_item("Ditado antigo", modo="transcribe")
        cfg_reaberto = ConfigManager(cofre=CofreDeMentira())
        self.assertTrue(cfg_reaberto.onboarding_completed)
        self.assertFalse(cfg_reaberto.precisa_onboarding())

    def test_salvar_onboarding_completed_persiste_no_env(self):
        self._escrever_env("GROQ_API_KEY=\nONBOARDING_COMPLETED=false\n")
        cfg = ConfigManager(cofre=CofreDeMentira())
        self.assertTrue(cfg.precisa_onboarding())

        cfg.save_settings({"ONBOARDING_COMPLETED": True})
        cfg2 = ConfigManager(cofre=CofreDeMentira())
        self.assertTrue(cfg2.onboarding_completed)
        self.assertFalse(cfg2.precisa_onboarding())

        cfg2.save_settings({"SILERO_VAD": False})
        cfg3 = ConfigManager(cofre=CofreDeMentira())
        self.assertFalse(cfg3.silero_vad)
        self.assertTrue(cfg3.onboarding_completed)

    def test_recarregar_chave_do_cofre_detecta_chave_gravada_externamente(self):
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira()
        cfg = ConfigManager(cofre=cofre)
        self.assertEqual("", cfg.chave_configurada())

        cofre.set_password("WillyAssistant", "GROQ_API_KEY", "gsk_gravada_fora")
        self.assertTrue(cfg.recarregar_chave_do_cofre())
        self.assertEqual("gsk_gravada_fora", cfg.groq_api_key)
        self.assertEqual("gsk_gravada_fora", cfg.chave_configurada())

        # Também detecta chave colada no .env, migra para o cofre e limpa do arquivo.
        cofre2 = CofreDeMentira()
        cfg2 = ConfigManager(cofre=cofre2)
        self._escrever_env("GROQ_API_KEY=gsk_no_arquivo\n")
        self.assertTrue(cfg2.recarregar_chave_do_cofre())
        self.assertEqual("gsk_no_arquivo", cfg2.groq_api_key)
        self.assertEqual("gsk_no_arquivo", cofre2.chave)
        with open(self.env_file, encoding="utf-8") as f:
            self.assertNotIn("gsk_no_arquivo", f.read())

    def test_m9_recarregar_chave_do_cofre_ignora_os_environ_obsoleto(self):
        """M9: Com chave removida do cofre e do .env, mas GROQ_API_KEY velha em os.environ,
        recarregar_chave_do_cofre() devolve False e zera a chave em memória.
        """
        self._escrever_env("GROQ_API_KEY=gsk_migrada_no_boot\n")
        cofre = CofreDeMentira()
        with patch.dict(os.environ, {}, clear=False):
            cfg = ConfigManager(cofre=cofre)
            # O boot carregou no os.environ, migrou para o cofre e limpou do .env
            self.assertEqual("gsk_migrada_no_boot", cfg.groq_api_key)
            self.assertEqual("gsk_migrada_no_boot", os.environ.get("GROQ_API_KEY"))

            # Remove do cofre (e .env já foi limpo), mas os.environ continua com a chave velha
            cofre.delete_password("WillyAssistant", "GROQ_API_KEY")
            encontrou = cfg.recarregar_chave_do_cofre()
            self.assertFalse(encontrou)
            self.assertEqual("", cfg.groq_api_key)

    def test_parte_b_recarregar_chave_com_cofre_ilegivel_preserva_chave_em_memoria(self):
        """Parte B: Se a leitura do cofre falhar durante recarregar_chave_do_cofre(),
        a chave atual em memória não pode ser apagada e cofre_ilegivel fica True.
        """
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_funcionando")
        cfg = ConfigManager(cofre=cofre)
        self.assertEqual("gsk_funcionando", cfg.groq_api_key)
        self.assertFalse(cfg.cofre_ilegivel)

        cofre.falha = True
        encontrou = cfg.recarregar_chave_do_cofre()
        self.assertFalse(encontrou)
        self.assertTrue(cfg.cofre_ilegivel)
        self.assertEqual("gsk_funcionando", cfg.groq_api_key)
        self.assertEqual("gsk_funcionando", cofre.chave)

    def test_parte_b_cofre_ilegivel_reseta_quando_cofre_volta_a_funcionar(self):
        """Quando o cofre volta a responder depois de falhar e a chave foi apagada dele,
        recarregar_chave_do_cofre() limpa cofre_ilegivel e zera groq_api_key.
        """
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_funcionando")
        cfg = ConfigManager(cofre=cofre)

        cofre.falha = True
        self.assertFalse(cfg.recarregar_chave_do_cofre())
        self.assertTrue(cfg.cofre_ilegivel)
        self.assertEqual("gsk_funcionando", cfg.groq_api_key)

        cofre.falha = False
        cofre.delete_password("WillyAssistant", "GROQ_API_KEY")
        self.assertFalse(cfg.recarregar_chave_do_cofre())
        self.assertFalse(cfg.cofre_ilegivel)
        self.assertEqual("", cfg.groq_api_key)


class TestValidacaoChaveGroq(unittest.TestCase):
    """Validação real da chave Groq com diagnóstico detalhado de erros."""

    def test_rejeita_chave_vazia_placeholder_ou_com_espacos_sem_rede(self):
        svc = GroqService(api_key="")
        with patch("core.groq_service.Groq") as mock_groq:
            for invalida in ("", "   ", "sua_chave_aqui", "gsk_123 456", "gsk_abc\ndef"):
                ok, msg, ms, _ = svc.validar_chave(invalida)
                self.assertFalse(ok)
                self.assertEqual(0.0, ms)
                self.assertTrue(msg)
            mock_groq.assert_not_called()

    def test_chave_valida_lista_modelos_sem_sobrescrever_chave_atual(self):
        svc = GroqService(api_key="gsk_anterior")
        fake_client = MagicMock()
        fake_client.models.list.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(id="whisper-large-v3-turbo"),
                SimpleNamespace(id="whisper-large-v3"),
                SimpleNamespace(id="openai/gpt-oss-120b"),
            ]
        )
        with patch("core.groq_service.Groq", return_value=fake_client) as mock_cls:
            ok, msg, lat, info = svc.validar_chave("gsk_nova_valida")

        self.assertTrue(ok)
        self.assertGreaterEqual(lat, 0.0)
        self.assertIn("válida", msg.lower())
        self.assertEqual([], info.get("faltando"))
        self.assertEqual("gsk_anterior", svc.api_key)
        mock_cls.assert_called_once()
        self.assertEqual("gsk_nova_valida", mock_cls.call_args.kwargs["api_key"])

    def test_diagnostica_401_403_429_e_rede(self):
        svc = GroqService(api_key="")
        req = httpx.Request("GET", "https://api.groq.com/openai/v1/models")
        resp_401 = httpx.Response(401, request=req)
        resp_403 = httpx.Response(403, request=req)
        resp_429 = httpx.Response(429, request=req)

        casos = [
            (groq.AuthenticationError("invalid", response=resp_401, body=None), "401"),
            (groq.PermissionDeniedError("forbidden", response=resp_403, body=None), "403"),
            (groq.RateLimitError("rate", response=resp_429, body=None), "429"),
            (groq.APIConnectionError(request=req), "internet"),
        ]
        for exc, esperado in casos:
            fake_client = MagicMock()
            fake_client.models.list.side_effect = exc
            with patch("core.groq_service.Groq", return_value=fake_client):
                ok, msg, _lat, _info = svc.validar_chave("gsk_teste")
            self.assertFalse(ok)
            self.assertIn(esperado, msg.lower())


class TestOnboardingUI(unittest.TestCase):
    """Testes dos 4 passos do OnboardingTab, SettingsTab reorganizada e banner no Dashboard."""

    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _bombear(self, segundos: float = 0.08):
        fim = time.time() + segundos
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)

    def test_onboarding_fluxo_completo_4_passos_e_importacao_env(self):
        from ui.tabs.tab_onboarding import build_tab_onboarding

        validacoes = []
        conclusoes = []
        salvos = []
        ditado_calls = []

        def fake_validate(chave: str, salvar: bool = False):
            validacoes.append((chave, salvar))
            return True, "Chave válida · Modelos prontos", 55.0, {"faltando": []}

        def fake_test_dictation(stop_event=None, on_level=None):
            ditado_calls.append(True)
            return True, "ola willy teste", "Olá, Willy! Teste.", ""

        callbacks = {
            "get_settings": lambda: {
                "api_key": "",
                "audio_device": None,
                "mic_gain": 1.0,
                "whisper_mode": False,
                "voice_hotkey": "ctrl+space",
                "master_hotkey": "ctrl+shift+space",
                "translate_hotkey": "ctrl+alt+space",
                "input_language": "auto",
                "processing_profile": "dev",
                "autostart": False,
                "onboarding_completed": False,
            },
            "get_credential_catalog": lambda: [
                {
                    "id": "groq",
                    "env_var": "GROQ_API_KEY",
                    "nome": "Groq Cloud",
                    "obrigatoria": True,
                    "gratuita": True,
                    "sem_cartao": True,
                    "url_chaves": "https://console.groq.com/keys",
                    "resumo": "Transcrição Whisper e refino LLM.",
                    "passos": ["Abra o console", "Crie a chave", "Cole aqui"],
                    "configurada": False,
                }
            ],
            "get_audio_devices": lambda: [(0, "Microfone USB")],
            "get_hotkey_failures": lambda: {"VOICE_HOTKEY": "ctrl+space"},
            "on_validate_groq_key": fake_validate,
            "on_reload_api_key": lambda: False,
            "on_save_settings": lambda d: salvos.append(d),
            "on_toggle_autostart": lambda _v: None,
            "on_test_dictation": fake_test_dictation,
            "on_complete_onboarding": lambda abrir_aba="history": conclusoes.append(abrir_aba),
        }

        tab = build_tab_onboarding(self.root, callbacks=callbacks)

        # Passo 1 começa visível e exige validação da chave antes de continuar.
        self.assertEqual(0, tab.passo_atual)

        # Importação de arquivo .env carrega a chave e dispara leitura sem gravar arquivo.
        env_tmp = os.path.join(isolar_config(self), "importado.env")
        with open(env_tmp, "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=gsk_importada_teste\n")
        with patch("tkinter.filedialog.askopenfilename", return_value=env_tmp):
            tab.importar_env()
        self.assertEqual("gsk_importada_teste", tab.entry_api_key.get())

        tab.validar_e_salvar_chave()
        for _ in range(50):
            self._bombear(0.02)
            if validacoes and tab._chave_validada:
                break
        self.assertTrue(validacoes)
        self.assertEqual(("gsk_importada_teste", True), validacoes[-1])

        # Avança para o passo 2 (Microfone).
        tab.avancar_passo()
        self.assertEqual(1, tab.passo_atual)
        tab.avancar_passo()

        # Passo 3 (Atalhos e idioma) sinaliza conflito e permite ajustar o idioma de entrada.
        self.assertEqual(2, tab.passo_atual)
        self.assertIn("Em uso", tab.lbl_alerta_atalho.cget("text"))
        self.assertEqual("🌐 Automático", tab.seg_input_lang.get())
        tab._ao_trocar_idioma("🇧🇷 Português")
        self.assertIn({"INPUT_LANGUAGE": "pt"}, salvos)
        self.assertIn("português brasileiro", tab.lbl_idioma_desc.cget("text").lower())
        tab.recarregar_dados({"input_language": "en"})
        self.assertEqual("🇺🇸 Inglês", tab.seg_input_lang.get())
        tab.avancar_passo()

        # Passo 4 (Primeiro ditado guiado) executa amostra e conclui onboarding.
        self.assertEqual(3, tab.passo_atual)
        tab.testar_primeiro_ditado()
        for _ in range(50):
            self._bombear(0.02)
            if ditado_calls and not tab._ditado_ativo:
                break
        self.assertTrue(ditado_calls)
        self.assertIn("Olá, Willy! Teste.", tab.lbl_ditado_refinado.cget("text"))

        tab.concluir_onboarding()
        self.assertEqual(["history"], conclusoes)

    def test_settings_tab_tem_credenciais_no_topo_sem_atalho_escondido_em_sobre(self):
        from ui.tabs.tab_settings import build_tab_settings

        tab = build_tab_settings(self.root, callbacks={
            "get_settings": lambda: {"api_key": ""},
            "get_app_rules": list,
            "get_audio_devices": list,
            "get_outputs_dir": lambda: "C:/fake",
            "on_validate_groq_key": lambda k, salvar=False: (True, "Chave válida", 40.0, {}),
            "on_reload_api_key": lambda: False,
        })
        self.assertTrue(hasattr(tab, "btn_testar_key"))
        self.assertTrue(hasattr(tab, "btn_reverificar_cofre"))
        self.assertFalse(hasattr(tab, "btn_abrir_onboarding"))

        # O card de credenciais vem antes dos outros cards de configuração na ordem de empacotamento.
        filhos = [w for w in tab.winfo_children() if w is not getattr(tab, "_scrollbar", None)]
        idx_cred = next((i for i, w in enumerate(filhos) if w is tab.card_credenciais), -1)
        idx_envio = next((i for i, w in enumerate(filhos) if w is tab.card_modo_envio), -1)
        self.assertGreaterEqual(idx_cred, 0)
        self.assertGreater(idx_envio, idx_cred)

    def test_dashboard_destaca_guia_no_menu_exibe_banner_e_recarrega_cofre_ao_abrir_ajustes(self):
        from ui.dashboard import WillyDashboard
        from ui.theme import APPLE_ACCENT, APPLE_ACCENT_SUBTLE

        estado = {"api_key": ""}
        reloads = []

        def fake_reload():
            reloads.append(True)
            estado["api_key"] = "gsk_recarregada"
            return True

        dash = WillyDashboard(callbacks={
            "get_history": list,
            "get_app_rules": list,
            "get_settings": lambda: {
                "api_key": estado["api_key"],
                "onboarding_completed": True,
            },
            "on_reload_api_key": fake_reload,
            "on_complete_onboarding": lambda **_kw: True,
        })
        self.addCleanup(destruir_tk, dash)
        dash.withdraw()
        self._bombear(0.05)

        # Item Guia Inicial fica destacado no topo da barra lateral e visível antes de Histórico.
        self.assertIn("onboarding", dash.nav_items)
        item_guia = dash.nav_items["onboarding"]
        item_hist = dash.nav_items["history"]
        self.assertTrue(item_guia.highlighted)
        self.assertLess(int(item_guia.grid_info()["row"]), int(item_hist.grid_info()["row"]))
        self.assertEqual("Começar", item_guia._badge_text)
        self.assertEqual(APPLE_ACCENT_SUBTLE, item_guia.cget("fg_color"))
        self.assertTrue(item_guia.lbl_badge.winfo_manager())

        # Sem chave na aba history, o banner discreto fica visível.
        self.assertTrue(dash.banner_onboarding_visivel)

        # Clicar no item do menu abre onboarding, marca estado ativo e não duplica o banner.
        item_guia._on_click()
        self._bombear(0.05)
        self.assertEqual("onboarding", dash.active_tab)
        self.assertTrue(item_guia.is_active)
        self.assertEqual(APPLE_ACCENT, item_guia.cget("fg_color"))
        self.assertFalse(dash.banner_onboarding_visivel)

        # Ao abrir Ajustes sem chave em memória, recarrega do cofre automaticamente, some o banner e limpa o selo.
        dash.mudar_aba("settings")
        self._bombear(0.05)
        self.assertTrue(reloads)
        self.assertEqual("gsk_recarregada", dash.tab_settings.entry_key.get())
        self.assertFalse(dash.banner_onboarding_visivel)
        self.assertFalse(item_guia.is_active)
        self.assertEqual("", item_guia._badge_text)
        self.assertFalse(item_guia.lbl_badge.winfo_manager())
        self.assertEqual(APPLE_ACCENT_SUBTLE, item_guia.cget("fg_color"))

    def test_chave_invalida_bloqueia_avanco_e_pular_funciona(self):
        from ui.tabs.tab_onboarding import build_tab_onboarding

        conclusoes = []
        tab = build_tab_onboarding(self.root, callbacks={
            "get_settings": lambda: {"api_key": "", "onboarding_completed": False},
            "on_validate_groq_key": lambda _k, salvar=False: (False, "Chave inválida (401).", 0.0, {"codigo": "401"}),
            "on_complete_onboarding": lambda abrir_aba="history": conclusoes.append(abrir_aba),
        })

        tab.entry_api_key.insert(0, "gsk_ruim")
        tab.validar_e_salvar_chave()
        for _ in range(50):
            self._bombear(0.02)
            if not tab._validando_chave:
                break

        self.assertFalse(tab._chave_validada)
        self.assertIn("401", tab.lbl_status_chave.cget("text"))
        tab.avancar_passo()
        self.assertEqual(0, tab.passo_atual)

        tab.pular_onboarding()
        self.assertEqual(["history"], conclusoes)

    def test_m6_com_chave_e_guia_pendente_exibe_selo_comecar_sem_mostrar_banner(self):
        """M6: Com chave presente e onboarding_completed=False, o item da sidebar mostra o selo
        'Começar' e o banner continua escondido.
        """
        from ui.dashboard import WillyDashboard

        dash = WillyDashboard(callbacks={
            "get_history": list,
            "get_app_rules": list,
            "get_settings": lambda: {
                "api_key": "gsk_ja_configurada",
                "onboarding_completed": False,
            },
            "on_reload_api_key": lambda: True,
            "on_complete_onboarding": lambda **_kw: True,
        })
        self.addCleanup(destruir_tk, dash)
        dash.withdraw()
        self._bombear(0.05)

        item_guia = dash.nav_items["onboarding"]
        self.assertEqual("Começar", item_guia._badge_text)
        self.assertTrue(item_guia.lbl_badge.winfo_manager())
        self.assertFalse(dash.banner_onboarding_visivel)

    def test_m10_botao_testar_chave_em_ajustes_chama_validacao_com_salvar_false(self):
        """M10: O botão 'Testar Chave' de Ajustes chama on_validate_groq_key com salvar=False e nunca salva."""
        from ui.tabs.tab_settings import build_tab_settings

        chamadas_validacao = []
        chamadas_salvar = []
        fila_ui = []

        def fake_validate(chave: str, salvar: bool = False):
            chamadas_validacao.append((chave, salvar))
            if salvar:
                chamadas_salvar.append(chave)
            return True, "Chave válida (42 ms)", 42.0, {}

        tab = build_tab_settings(self.root, callbacks={
            "get_settings": lambda: {"api_key": "gsk_anterior"},
            "get_app_rules": list,
            "get_audio_devices": list,
            "get_outputs_dir": lambda: "C:/fake",
            "on_validate_groq_key": fake_validate,
            "on_save_settings": lambda d: chamadas_salvar.append(d),
            "on_reload_api_key": lambda: False,
            "safe_dispatch_ui": lambda fn, *a, **_kw: fila_ui.append((fn, a)),
        })
        tab.entry_key.delete(0, "end")
        tab.entry_key.insert(0, "gsk_apenas_teste")
        tab._testar_chave_api()
        for _ in range(50):
            while fila_ui:
                fn, args = fila_ui.pop(0)
                fn(*args)
            self._bombear(0.02)
            if chamadas_validacao and tab.btn_testar_key.cget("text") == "Testar Chave":
                break

        self.assertEqual([("gsk_apenas_teste", False)], chamadas_validacao)
        self.assertEqual([], chamadas_salvar)
        self.assertIn("válida", tab.lbl_status_key.cget("text").lower())

    def test_parte_b_botoes_reverificar_cofre_mostram_mensagem_distinta_quando_cofre_falha(self):
        """Parte B: Tanto em Ajustes quanto no Guia Inicial, 'Reverificar Cofre' lê cofre_ilegivel
        de get_settings (com on_reload_api_key como função simples) e distingue entre chave em uso
        e cofre ilegível sem chave configurada.
        """
        from ui.tabs.tab_onboarding import build_tab_onboarding
        from ui.tabs.tab_settings import build_tab_settings

        temp_dir = isolar_config(self)
        with open(os.path.join(temp_dir, ".env"), "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=\n")

        # 1. Com chave já em uso quando o cofre falha em runtime:
        cofre = CofreDeMentira(chave="gsk_em_uso")
        cfg = ConfigManager(cofre=cofre)
        cofre.falha = True

        def recarregar_com_chave():
            return cfg.recarregar_chave_do_cofre()

        tab_set = build_tab_settings(self.root, callbacks={
            "get_settings": lambda: {
                "api_key": cfg.groq_api_key,
                "cofre_ilegivel": cfg.cofre_ilegivel,
            },
            "get_app_rules": list,
            "get_audio_devices": list,
            "get_outputs_dir": lambda: "C:/fake",
            "on_reload_api_key": recarregar_com_chave,
        })
        tab_set._reverificar_cofre_api()
        self.assertEqual("gsk_em_uso", tab_set.entry_key.get())
        self.assertEqual(
            "Não foi possível ler o cofre do Windows. O Willy continua com a chave que já estava em uso.",
            tab_set.lbl_status_key.cget("text"),
        )

        tab_onb = build_tab_onboarding(self.root, callbacks={
            "get_settings": lambda: {
                "api_key": cfg.groq_api_key,
                "onboarding_completed": False,
                "cofre_ilegivel": cfg.cofre_ilegivel,
            },
            "on_reload_api_key": recarregar_com_chave,
        })
        ok_onb = tab_onb.reverificar_cofre()
        self.assertFalse(ok_onb)
        self.assertEqual("gsk_em_uso", cfg.groq_api_key)
        self.assertEqual(
            "Não foi possível ler o cofre do Windows. O Willy continua com a chave que já estava em uso.",
            tab_onb.lbl_status_chave.cget("text"),
        )

        # 2. Sem chave em uso (cofre ilegível desde a abertura e .env vazio):
        cofre_sem = CofreDeMentira(falha=True)
        cfg_sem = ConfigManager(cofre=cofre_sem)
        self.assertEqual("", cfg_sem.groq_api_key)

        def recarregar_sem_chave():
            return cfg_sem.recarregar_chave_do_cofre()

        tab_set_sem = build_tab_settings(self.root, callbacks={
            "get_settings": lambda: {
                "api_key": cfg_sem.groq_api_key,
                "cofre_ilegivel": cfg_sem.cofre_ilegivel,
            },
            "get_app_rules": list,
            "get_audio_devices": list,
            "get_outputs_dir": lambda: "C:/fake",
            "on_reload_api_key": recarregar_sem_chave,
        })
        tab_set_sem._reverificar_cofre_api()
        self.assertEqual(
            "Não foi possível ler o cofre do Windows. Cole a chave no campo e clique em Salvar e Aplicar Ajustes.",
            tab_set_sem.lbl_status_key.cget("text"),
        )

        tab_onb_sem = build_tab_onboarding(self.root, callbacks={
            "get_settings": lambda: {
                "api_key": cfg_sem.groq_api_key,
                "onboarding_completed": False,
                "cofre_ilegivel": cfg_sem.cofre_ilegivel,
            },
            "on_reload_api_key": recarregar_sem_chave,
        })
        ok_onb_sem = tab_onb_sem.reverificar_cofre()
        self.assertFalse(ok_onb_sem)
        self.assertEqual(
            "Não foi possível ler o cofre do Windows. Cole a chave no campo e clique em Validar e Salvar Chave.",
            tab_onb_sem.lbl_status_chave.cget("text"),
        )


class TestFluxosOnboardingWilly(unittest.TestCase):
    """Exercita as funções novas de willy.py ligadas ao onboarding e recarga em memória."""

    @staticmethod
    def _carregar_funcoes():
        import ast

        with open("willy.py", encoding="utf-8") as f:
            arvore = ast.parse(f.read(), "willy.py")
        alvos = {
            "aba_inicial",
            "_abrir_painel_sem_chave",
            "validar_e_aplicar_chave_groq",
            "recarregar_chave_do_cofre_vivo",
            "concluir_onboarding_willy",
            "capturar_e_testar_ditado",
        }
        nos = [no for no in arvore.body if isinstance(no, ast.FunctionDef) and no.name in alvos]
        return ast.Module(body=nos, type_ignores=[])

    def test_validacao_recarga_conclusao_e_ditado_guiado_willy(self):
        from core.audio import AudioManager
        from core.audio_processing.dsp import TAXA_WHISPER, condicionar_para_whisper, para_taxa_whisper
        from core.audio_processing.vad import compute_rms

        isolar_config(self)
        cofre = CofreDeMentira()
        cfg = ConfigManager(cofre=cofre)
        svc = GroqService(api_key="")
        audio_mgr = AudioManager()

        class FakeDash:
            def __init__(self):
                self.acoes = []

            def mostrar(self):
                self.acoes.append("mostrar")

            def mudar_aba(self, aba):
                self.acoes.append(("mudar_aba", aba))

            def recarregar_ajustes(self):
                self.acoes.append("recarregar_ajustes")

            def _atualizar_banner_onboarding(self):
                self.acoes.append("_atualizar_banner_onboarding")

        dash = FakeDash()
        salvos = []

        def fake_save_settings(dados):
            salvos.append(dados)
            cfg.save_settings(dados)
            svc.set_api_key(cfg.groq_api_key)

        escopo = {
            "time": time,
            "np": np,
            "TAXA_WHISPER": TAXA_WHISPER,
            "para_taxa_whisper": para_taxa_whisper,
            "condicionar_para_whisper": condicionar_para_whisper,
            "compute_rms": compute_rms,
            "config_mgr": cfg,
            "groq_service": svc,
            "audio_mgr": audio_mgr,
            "dashboard": dash,
            "safe_dispatch_ui": lambda fn, *a, **kw: fn(*a),
            "dashboard_save_settings": fake_save_settings,
            "sincronizar_bandeja": lambda: None,
        }
        exec(compile(self._carregar_funcoes(), "willy.py", "exec"), escopo)

        # Sem chave e sem finalizar guia -> abre aba onboarding.
        escopo["_abrir_painel_sem_chave"]()
        self.assertIn(("mudar_aba", "onboarding"), dash.acoes)

        # Valida e salva chave em memória + cofre via validar_e_aplicar_chave_groq.
        fake_client = MagicMock()
        fake_client.models.list.return_value = SimpleNamespace(data=[])
        with patch("core.groq_service.Groq", return_value=fake_client):
            ok, _msg, _lat, _info = escopo["validar_e_aplicar_chave_groq"]("gsk_nova_willy", salvar=True)
        self.assertTrue(ok)
        self.assertEqual("gsk_nova_willy", cfg.groq_api_key)
        self.assertEqual("gsk_nova_willy", svc.api_key)

        # Chave gravada externamente no cofre é detectada em memória por recarregar_chave_do_cofre_vivo.
        cofre.set_password("WillyAssistant", "GROQ_API_KEY", "gsk_externa")
        self.assertTrue(escopo["recarregar_chave_do_cofre_vivo"]())
        self.assertEqual("gsk_externa", svc.api_key)

        # Ditado guiado funciona sobre áudio simulado (piso + fala + piso) na borda do stream e da API Groq.
        piso = (0.001 * np.sin(2 * np.pi * 200.0 * np.arange(800) / 16000.0)).astype(np.float32)
        tom = (0.25 * np.sin(2 * np.pi * 440.0 * np.arange(800) / 16000.0)).astype(np.float32)
        niveis: list[float] = []

        class FakeStream:
            def __init__(self):
                self.leituras = 0

            def read(self, _n):
                self.leituras += 1
                if self.leituras >= 14:
                    stop_evt.set()
                if 3 <= self.leituras <= 12:
                    return tom, False
                return piso, False

            def stop(self):
                pass

            def close(self):
                pass

        stop_evt = threading.Event()
        escopo["negociar_stream"] = lambda *_a: (FakeStream(), 16000)
        with (
            patch.object(svc, "transcribe", return_value="teste de voz guiado"),
            patch.object(svc, "refine_text", return_value="Teste de voz guiado."),
        ):
            ok_dit, bruto, ref, err = escopo["capturar_e_testar_ditado"](
                stop_event=stop_evt,
                on_level=niveis.append,
            )
        self.assertTrue(ok_dit, err)
        self.assertGreater(max(niveis), 0.5)
        self.assertEqual("teste de voz guiado", bruto)
        self.assertEqual("Teste de voz guiado.", ref)

        # Concluir grava ONBOARDING_COMPLETED=true e abre Histórico.
        dash.acoes.clear()
        escopo["concluir_onboarding_willy"]("history")
        self.assertTrue(cfg.onboarding_completed)
        self.assertIn(("mudar_aba", "history"), dash.acoes)

        # M5: Com o guia já concluído e sem chave, _abrir_painel_sem_chave() abre 'settings'.
        dash.acoes.clear()
        escopo["_abrir_painel_sem_chave"]()
        self.assertIn(("mudar_aba", "settings"), dash.acoes)

        # M2: validar_e_aplicar_chave_groq(chave, salvar=True) com AuthenticationError não chama
        # dashboard_save_settings e mantém a chave anterior em cfg, cofre e groq_service.
        salvos.clear()
        req = httpx.Request("GET", "https://api.groq.com/openai/v1/models")
        resp_401 = httpx.Response(401, request=req)
        fake_client_401 = MagicMock()
        fake_client_401.models.list.side_effect = groq.AuthenticationError(
            "invalid_api_key", response=resp_401, body=None
        )
        with patch("core.groq_service.Groq", return_value=fake_client_401):
            ok_401, _msg_401, _lat_401, _info_401 = escopo["validar_e_aplicar_chave_groq"](
                "gsk_recusada_401", salvar=True
            )
        self.assertFalse(ok_401)
        self.assertEqual([], salvos)
        self.assertEqual("gsk_externa", cfg.groq_api_key)
        self.assertEqual("gsk_externa", cofre.chave)
        self.assertEqual("gsk_externa", svc.api_key)

        # M4: aba_inicial(config_mgr) cobre os 3 casos (guia pendente, guia concluído sem chave, guia concluído com chave).
        self.assertIn("aba_inicial", escopo, "Função aba_inicial deve existir em willy.py")
        dash.acoes.clear()
        cfg.onboarding_completed = False
        cfg.groq_api_key = ""
        self.assertEqual("onboarding", escopo["aba_inicial"](cfg))
        self.assertEqual([("mudar_aba", "onboarding")], dash.acoes)
        dash.acoes.clear()
        cfg.onboarding_completed = True
        cfg.groq_api_key = ""
        self.assertEqual("settings", escopo["aba_inicial"](cfg))
        self.assertEqual([("mudar_aba", "settings")], dash.acoes)
        dash.acoes.clear()
        cfg.onboarding_completed = True
        cfg.groq_api_key = "gsk_externa"
        self.assertIsNone(escopo["aba_inicial"](cfg))
        self.assertEqual([], dash.acoes)

        # M8: capturar_e_testar_ditado() recusa enquanto um ditado real está gravando ou processando.
        chamadas_stream = []

        def _stream_proibido(*_a):
            chamadas_stream.append(True)
            return FakeStream(), 16000

        escopo["negociar_stream"] = _stream_proibido
        try:
            audio_mgr.is_recording = True
            audio_mgr.is_processing = False
            ok_rec, _, _, msg_rec = escopo["capturar_e_testar_ditado"]()
            self.assertFalse(ok_rec)
            self.assertIn("aguarde", msg_rec.lower())
            self.assertEqual([], chamadas_stream)

            audio_mgr.is_recording = False
            audio_mgr.is_processing = True
            ok_proc, _, _, msg_proc = escopo["capturar_e_testar_ditado"]()
            self.assertFalse(ok_proc)
            self.assertIn("aguarde", msg_proc.lower())
            self.assertEqual([], chamadas_stream)
        finally:
            audio_mgr.is_recording = False
            audio_mgr.is_processing = False

        # Parte B no fluxo vivo: se o cofre falhar em recarregar_chave_do_cofre_vivo(),
        # groq_service.api_key e cfg.groq_api_key mantêm a chave anterior.
        cofre.falha = True
        try:
            self.assertFalse(escopo["recarregar_chave_do_cofre_vivo"]())
            self.assertEqual("gsk_externa", cfg.groq_api_key)
            self.assertEqual("gsk_externa", svc.api_key)
        finally:
            cofre.falha = False


if __name__ == "__main__":
    unittest.main()
