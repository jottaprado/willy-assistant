"""
Bloco 12, funcionalidade 3: regras por aplicativo (Contexto Automático).

Uma regra liga um app (executável e/ou trecho do título) a um tom, um modo e uma instrução extra.
Precedência: o tom falado > o atalho específico (o modo já não é "transcribe") > a regra do app >
a configuração global.

Direto: ContextManager.resolve_app_rule puro, AppRulesStore/ConfigManager/ProfileManager em
arquivos temporários, o TranscriptionPipeline de verdade com a Groq em autospec (só o Win32 que
diz qual app está na janela-alvo é substituído) e a SettingsTab com widgets de verdade.
"""

import gc
import json
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

import customtkinter as ctk

from core.config import ConfigManager
from core.context import ContextManager
from core.groq_service import FalhaDoLLM, GroqService
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.storage.settings_store import (
    MAX_INSTRUCAO_DA_REGRA,
    MAX_REGRAS_DE_APP,
    AppRulesStore,
    sanitizar_regras_de_app,
)
from core.system.injector import TextInjector
from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.tabs.tab_settings import build_tab_settings

WAV = b"RIFF" + b"\0" * 40
JANELA_DO_WHATSAPP = 0x1A2B


def _regra(**campos):
    base = {"app_exe": "", "title_contains": "", "tone": "default", "action_mode": "default", "custom_instruction": ""}
    base.update(campos)
    return base


class TestResolveAppRule(unittest.TestCase):
    def test_app_e_titulo_ganham_de_so_titulo_que_ganha_de_so_app(self):
        so_app = _regra(app_exe="chrome.exe", tone="concise")
        so_titulo = _regra(title_contains="gmail", tone="natural")
        os_dois = _regra(app_exe="chrome.exe", title_contains="gmail", tone="formal")
        regras = [so_app, so_titulo, os_dois]
        self.assertEqual("formal", ContextManager.resolve_app_rule("chrome.exe", "Caixa de entrada - Gmail", regras)["tone"])
        self.assertEqual("natural", ContextManager.resolve_app_rule("msedge.exe", "Gmail", regras)["tone"])
        self.assertEqual("concise", ContextManager.resolve_app_rule("chrome.exe", "YouTube", regras)["tone"])

    def test_so_titulo_ganha_de_so_app_quando_os_dois_casam(self):
        regras = [_regra(app_exe="chrome.exe", tone="concise"), _regra(title_contains="gmail", tone="natural")]
        self.assertEqual("natural", ContextManager.resolve_app_rule("chrome.exe", "Gmail - Caixa", regras)["tone"])
        self.assertEqual("natural", ContextManager.resolve_app_rule("chrome.exe", "Gmail - Caixa", regras[::-1])["tone"])

    def test_sem_diferenciar_maiusculas_e_com_caminho(self):
        regra = _regra(app_exe="slack.exe", title_contains="geral", tone="concise")
        self.assertEqual(regra, ContextManager.resolve_app_rule(r"C:\Apps\SLACK.EXE", "#Geral | Slack", [regra]))

    def test_filtro_que_nao_casa_derruba_a_regra(self):
        regra = _regra(app_exe="slack.exe", title_contains="geral")
        self.assertIsNone(ContextManager.resolve_app_rule("slack.exe", "#random", [regra]))
        self.assertIsNone(ContextManager.resolve_app_rule("teams.exe", "geral", [regra]))
        regra_code = _regra(app_exe="code.exe", tone="technical")
        self.assertIsNone(ContextManager.resolve_app_rule("vscode.exe", "", [regra_code]))
        self.assertIsNone(ContextManager.resolve_app_rule("xcode.exe", "", [regra_code]))
        self.assertEqual(regra_code, ContextManager.resolve_app_rule("Code.exe", "", [regra_code]))

    def test_empate_vale_a_primeira_e_regra_sem_filtro_nao_casa(self):
        primeira, segunda = _regra(app_exe="code.exe", tone="technical"), _regra(app_exe="code.exe", tone="formal")
        self.assertEqual("technical", ContextManager.resolve_app_rule("code.exe", "", [_regra(), primeira, segunda])["tone"])
        self.assertIsNone(ContextManager.resolve_app_rule("code.exe", "x", [_regra(tone="formal")]))

    def test_devolve_copia(self):
        regra = _regra(app_exe="code.exe", tone="technical")
        ContextManager.resolve_app_rule("code.exe", "", [regra])["tone"] = "formal"
        self.assertEqual("technical", regra["tone"])


class TestSanitizarRegras(unittest.TestCase):
    def test_entrada_que_nao_e_lista_de_dicts(self):
        self.assertEqual([], sanitizar_regras_de_app({"app_exe": "x.exe"}))
        self.assertEqual([], sanitizar_regras_de_app(["slack.exe", 3, None]))

    def test_normaliza_app_e_titulo_e_descarta_sem_filtro(self):
        limpas = sanitizar_regras_de_app([
            {"app_exe": "  Slack ", "tone": "concise"},
            {"app_exe": r"C:\Program Files\Microsoft Office\WINWORD.EXE", "tone": "formal"},
            {"title_contains": "  Pull   Request ", "tone": "technical"},
            {"tone": "formal"},
        ])
        self.assertEqual(["slack.exe", "winword.exe", ""], [r["app_exe"] for r in limpas])
        self.assertEqual("pull request", limpas[2]["title_contains"])

    def test_tom_e_modo_desconhecidos_viram_padrao_e_instrucao_e_cortada(self):
        regra = sanitizar_regras_de_app([{"app_exe": "x.exe", "tone": "pirata", "action_mode": "rm -rf",
                                          "custom_instruction": "a" * 2000, "extra": "fora"}])[0]
        self.assertEqual(("default", "default", MAX_INSTRUCAO_DA_REGRA), (regra["tone"], regra["action_mode"],
                                                                        len(regra["custom_instruction"])))
        self.assertNotIn("extra", regra)

    def test_limite_de_regras(self):
        self.assertEqual(MAX_REGRAS_DE_APP, len(sanitizar_regras_de_app([{"app_exe": f"a{i}.exe"} for i in range(80)])))


class TestPersistenciaDasRegras(unittest.TestCase):
    def setUp(self):
        self.pasta = isolar_config(self)
        self.cfg = ConfigManager()

    def test_o_arquivo_das_regras_esta_isolado_nos_testes(self):
        self.assertTrue(self.cfg.app_rules_store.rules_file.startswith(self.pasta))

    def test_gravar_poe_em_vigor_e_sobrevive_ao_reload(self):
        self.assertTrue(self.cfg.save_app_context_rules([{"app_exe": "Slack", "tone": "concise"}]))
        self.assertEqual("slack.exe", self.cfg.app_context_rules[0]["app_exe"])
        self.assertEqual(self.cfg.app_context_rules, ConfigManager().app_context_rules)
        with open(self.cfg.app_rules_store.rules_file, encoding="utf-8") as f:
            self.assertEqual("concise", json.load(f)[0]["tone"])

    def test_get_devolve_copia(self):
        self.cfg.save_app_context_rules([{"app_exe": "slack.exe", "tone": "concise"}])
        self.cfg.get_app_context_rules()[0]["tone"] = "formal"
        self.assertEqual("concise", self.cfg.app_context_rules[0]["tone"])

    def test_corrompido_vai_para_quarentena(self):
        caminho = self.cfg.app_rules_store.rules_file
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("[{trunca")
        self.assertEqual([], AppRulesStore(caminho).load_rules())
        self.assertTrue(self.cfg.save_app_context_rules([{"app_exe": "code.exe", "tone": "technical"}]))
        quarentena = [n for n in os.listdir(self.pasta) if n.startswith(".app_rules.json.corrompido-")]
        self.assertEqual(1, len(quarentena))

    def test_ilegivel_nao_e_sobrescrito_e_as_de_antes_continuam(self):
        self.cfg.save_app_context_rules([{"app_exe": "code.exe", "tone": "technical"}])
        caminho = self.cfg.app_rules_store.rules_file
        with open(caminho, "rb") as f:
            bytes_antes = f.read()
        open_real = open

        def _open_bloqueado(path, *args, **kwargs):
            if os.path.abspath(str(path)) == os.path.abspath(caminho):
                raise PermissionError("arquivo em uso")
            return open_real(path, *args, **kwargs)

        with patch("builtins.open", side_effect=_open_bloqueado):
            self.assertFalse(self.cfg.save_app_context_rules([]))
        with open(caminho, "rb") as f:
            self.assertEqual(bytes_antes, f.read())
        self.assertEqual("code.exe", self.cfg.app_context_rules[0]["app_exe"])

    def test_perfil_exporta_e_importa_as_regras(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate_es"}])
        perfil = os.path.join(self.pasta, "perfil.json")
        self.assertTrue(self.cfg.export_profile(perfil))
        self.cfg.save_app_context_rules([])
        self.assertTrue(self.cfg.import_profile(perfil))
        self.assertEqual("translate_es", self.cfg.app_context_rules[0]["action_mode"])

    def test_perfil_antigo_sem_regras_nao_mexe_nas_de_agora(self):
        self.cfg.save_app_context_rules([{"app_exe": "code.exe", "tone": "technical"}])
        perfil = os.path.join(self.pasta, "antigo.json")
        with open(perfil, "w", encoding="utf-8") as f:
            json.dump({"settings": {}}, f)
        self.assertTrue(self.cfg.import_profile(perfil))
        self.assertEqual("code.exe", self.cfg.app_context_rules[0]["app_exe"])

    def test_perfil_com_regras_invalidas_e_sanitizado(self):
        perfil = os.path.join(self.pasta, "perfil.json")
        with open(perfil, "w", encoding="utf-8") as f:
            json.dump({"app_rules": [{"app_exe": "Teams", "tone": "hacker"}, "lixo", {"tone": "formal"}]}, f)
        self.assertTrue(self.cfg.import_profile(perfil))
        self.assertEqual([_regra(app_exe="teams.exe")], self.cfg.app_context_rules)


class TestRegraNoPipeline(unittest.TestCase):
    """O TranscriptionPipeline de verdade; do Win32 só o "qual app está nesta janela"."""

    def setUp(self):
        self.pasta = isolar_config(self)
        for funcao in ("_foco_numa_janela_do_willy", "_foco_no_shell"):
            p = patch(f"core.pipeline.transcription_pipeline.{funcao}", return_value=False)
            p.start()
            self.addCleanup(p.stop)
        # A cópia de reserva (foco que não volta ao app) iria ao clipboard da sessão: vira registro.
        self.copias = []
        copia = patch("core.actions.ActionManager.secure_copy",
                      side_effect=lambda texto, **kw: (self.copias.append(texto), True)[1])
        copia.start()
        self.addCleanup(copia.stop)
        self.apps_lidos = []

        def _app_da_janela(hwnd=None):
            self.apps_lidos.append(hwnd)
            return {JANELA_DO_WHATSAPP: ("whatsapp.exe", "Equipe", "MESSAGING")}.get(hwnd, ("notepad.exe", "", "GENERAL"))

        for nome, valor in (("get_foreground_app", _app_da_janela), ("janela_existe", lambda hwnd: False),
                            ("get_sticky_window", lambda: None), ("get_git_context", lambda *a, **k: "")):
            p = patch.object(ContextManager, nome, staticmethod(valor))
            p.start()
            self.addCleanup(p.stop)
        self.cfg = ConfigManager()
        # Todo ajuste de que o teste depende, explícito: o os.environ pode chegar com o de um teste
        # anterior (o reload usa load_dotenv com override), e "apenas copiar" mudaria a entrega.
        self.cfg.save_settings({"GROQ_API_KEY": "gsk_teste", "OUTPUTS_DIR": os.path.join(self.pasta, "saida"),
                                "REFINE_PROMPT": True, "CLEAN_FILLERS": False, "OUTPUT_TONE": "natural",
                                "CLIPBOARD_ONLY": False, "PRIVATE_MODE": False, "PROCESSING_PROFILE": "dev"})
        self.groq = create_autospec(GroqService, instance=True)
        self.groq.transcribe.return_value = "bom dia equipe vamos começar a reunião"
        self.groq.translate.return_value = "Good morning team"
        self.groq.translate_to_spanish.return_value = "Buenos días equipo"
        self.groq.refine_text.side_effect = lambda texto, **kw: f"<{kw['tone']}> {texto}"
        self.injector = create_autospec(TextInjector, instance=True)
        self.injector.paste_text.return_value = True
        self.audio = SimpleNamespace(lock=threading.Lock(), is_processing=False)
        self.avisos_ui = []
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq,
            config_mgr=self.cfg,
            audio_mgr=self.audio,
            injector=self.injector,
            ui_notifier=lambda estado, msg=None, **_k: self.avisos_ui.append((estado, msg)),
            user_data_dir=self.pasta,
        )

    def _ditar(self, modo="transcribe", janela=JANELA_DO_WHATSAPP):
        return self.pipeline.process(PipelineContext(wav_bytes=WAV, modo=modo, janela_alvo=janela,
                                                     app_context=("willy.exe", "Willy", "GENERAL")))

    def test_regra_promove_o_ditado_para_espanhol(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate_es"}])
        res = self._ditar()
        self.assertEqual(("translate_es", "Buenos días equipo"), (res.modo, res.text))
        self.assertEqual("translate_es", self.cfg.load_history()[-1]["mode"])
        self.groq.refine_text.assert_not_called()

    def test_regra_promove_o_ditado_para_ingles_pelo_whisper(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate"}])
        self.assertEqual("Good morning team", self._ditar().text)
        self.groq.translate.assert_called_once()
        self.groq.transcribe.assert_not_called()

    def test_atalho_especifico_ganha_da_regra(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate"}])
        self.assertEqual("translate_es", self._ditar(modo="translate_es").modo)
        self.groq.translate.assert_not_called()

    def test_ditado_com_enter_leva_o_tom_da_regra(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "tone": "concise"}])
        res = self._ditar(modo="send")
        self.assertEqual(("send", True), (res.modo, res.auto_send))
        self.assertEqual("concise", self.groq.refine_text.call_args.kwargs["tone"])
        self.injector.paste_text.assert_called_once_with(
            "<concise> Bom dia equipe vamos começar a reunião", auto_send=True
        )

    def test_ditado_com_enter_e_regra_translate_traduz_e_envia(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate"}])
        res = self._ditar(modo="send")
        self.assertEqual(("translate", "Good morning team", True), (res.modo, res.text, res.auto_send))
        self.groq.translate.assert_called_once()
        self.groq.transcribe.assert_not_called()
        self.injector.paste_text.assert_called_once_with("Good morning team", auto_send=True)
        self.assertEqual("translate", self.cfg.load_history()[-1]["mode"])

    def test_ditado_com_enter_e_regra_translate_quando_whisper_falha_nao_cola_nem_envia(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate"}])
        self.groq.translate.side_effect = ConnectionError("sem rede")
        res = self._ditar(modo="send")
        self.assertFalse(res.success)
        self.assertFalse(res.auto_send)
        self.injector.paste_text.assert_not_called()
        self.assertEqual("translate", self.pipeline.fila.mais_recente()[1])

    def test_ditado_com_enter_e_regra_translate_es_traduz_e_envia(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate_es"}])
        res = self._ditar(modo="send")
        self.assertEqual(("translate_es", "Buenos días equipo", True), (res.modo, res.text, res.auto_send))
        self.groq.translate_to_spanish.assert_called_once()
        self.injector.paste_text.assert_called_once_with("Buenos días equipo", auto_send=True)
        ultimo = self.cfg.load_history()[-1]
        self.assertEqual("translate_es", ultimo["mode"])
        self.assertEqual("Bom dia equipe vamos começar a reunião", ultimo["raw_text"])

    def test_ditado_com_enter_e_regra_translate_es_quando_llm_falha_cola_reserva_sem_enviar_e_avisa(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate_es"}])
        self.groq.translate_to_spanish.side_effect = FalhaDoLLM(
            "traducao_es", "Bom dia equipe vamos começar a reunião"
        )
        res = self._ditar(modo="send")
        self.assertEqual(
            ("translate_es", "Bom dia equipe vamos começar a reunião", False),
            (res.modo, res.text, res.auto_send),
        )
        self.injector.paste_text.assert_called_once_with(
            "Bom dia equipe vamos começar a reunião", auto_send=False
        )
        self.assertIn(("error", "Sem tradução: o texto ficou em português"), self.avisos_ui)

    def test_regra_do_app_ganha_do_tom_global(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "tone": "concise"}])
        self.assertTrue(self._ditar().text.startswith("<concise>"))

    def test_tom_falado_ganha_da_regra(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "tone": "concise"}])
        self.groq.transcribe.return_value = "Willy em tópicos: comprar café e revisar o PR hoje"
        self._ditar()
        self.assertEqual("bullet_points", self.groq.refine_text.call_args.kwargs["tone"])

    def test_sem_regra_vale_o_tom_global(self):
        self.cfg.save_app_context_rules([{"app_exe": "slack.exe", "tone": "concise"}])
        self._ditar()
        self.assertEqual("natural", self.groq.refine_text.call_args.kwargs["tone"])

    def test_instrucao_da_regra_vai_ao_refino(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "custom_instruction": "sem emojis"}])
        self._ditar()
        self.assertIn("Instrução da pessoa para este aplicativo: sem emojis",
                      self.groq.refine_text.call_args.kwargs["extra_context"])

    def test_a_regra_e_do_app_que_recebe_o_texto_e_nao_do_que_estava_na_frente(self):
        self.cfg.save_app_context_rules([{"app_exe": "willy.exe", "tone": "formal"},
                                         {"app_exe": "whatsapp.exe", "tone": "concise"}])
        self._ditar()
        self.assertEqual("concise", self.groq.refine_text.call_args.kwargs["tone"])

    def test_janela_fixada_ganha_da_janela_alvo(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "tone": "concise"}])
        with patch.object(ContextManager, "get_sticky_window", staticmethod(lambda: (0x9999, "Bloco de notas"))), \
                patch.object(ContextManager, "get_foreground_hwnd", staticmethod(lambda: 0x9999)):
            self._ditar()
        self.assertEqual("natural", self.groq.refine_text.call_args.kwargs["tone"])
        self.assertIn(0x9999, self.apps_lidos)
        self.assertEqual([], self.copias, "a fixada está na frente: cola, não copia")

    def test_outros_modos_nao_consultam_regra(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate_es"}])
        self.groq.generate_agent_prompt.return_value = "/goal x"
        self.assertEqual("prompt", self._ditar(modo="prompt").modo)
        self.assertNotIn(JANELA_DO_WHATSAPP, self.apps_lidos)

    def test_sem_regras_nenhuma_consulta_ao_windows(self):
        self._ditar()
        self.assertNotIn(JANELA_DO_WHATSAPP, self.apps_lidos)

    def test_ditado_guardado_por_ocupado_leva_o_modo_da_regra(self):
        self.cfg.save_app_context_rules([{"app_exe": "whatsapp.exe", "action_mode": "translate_es"}])
        self.audio.is_processing = True
        self.assertEqual("busy", self._ditar().error_category)
        self.assertEqual("translate_es", self.pipeline.fila.mais_recente()[1])


class TestSecaoNosAjustes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gc.collect()
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        fim = time.time() + 0.3
        while time.time() < fim:
            cls.root.update()
            time.sleep(0.01)
        destruir_tk(cls.root)
        gc.collect()

    def setUp(self):
        gc.collect()
        isolar_config(self)
        self.cfg = ConfigManager()
        self.ultimo_app = ("slack.exe", "#geral | Slack")
        self.tab = build_tab_settings(self.root, callbacks={
            "get_app_rules": self.cfg.get_app_context_rules,
            "on_save_app_rules": self.cfg.save_app_context_rules,
            "get_last_external_app": lambda: self.ultimo_app,
        })
        self.addCleanup(self.tab.destroy)
        self.secao = self.tab.secao_regras_app

    def _linhas(self):
        textos = []
        for linha in self.secao.linhas_da_lista:
            textos += [w.cget("text") for w in ([linha] + linha.winfo_children()) if isinstance(w, ctk.CTkLabel)]
        return textos

    def test_adicionar_pelo_formulario_grava_e_lista(self):
        self.secao.btn_capturar.invoke()
        self.assertEqual("slack.exe", self.secao.entry_app.get())
        self.secao.entry_titulo.insert(0, "Geral")
        self.secao.opt_tom.set("Conciso")
        self.secao.opt_modo.set("Traduzir → EN")
        self.secao.entry_instrucao.insert(0, "sem emojis")
        self.secao.btn_adicionar.invoke()
        self.assertEqual([_regra(app_exe="slack.exe", title_contains="geral", tone="concise", action_mode="translate",
                                 custom_instruction="sem emojis")], self.cfg.app_context_rules)
        self.assertEqual(self.cfg.app_context_rules, ConfigManager().app_context_rules, "gravado no disco")
        self.assertEqual(["slack.exe · título contém “geral” → Conciso · Traduzir → EN · instrução extra"], self._linhas())
        self.assertEqual("", self.secao.entry_app.get(), "o formulário volta vazio")

    def test_mesmo_app_e_titulo_troca_a_regra_no_lugar(self):
        self.cfg.save_app_context_rules([{"app_exe": "code.exe", "tone": "technical"}, {"app_exe": "slack.exe", "tone": "concise"}])
        self.secao.recarregar()
        self.secao.entry_app.insert(0, "code.exe")
        self.secao.opt_tom.set("Formal")
        self.secao.btn_adicionar.invoke()
        self.assertEqual(["code.exe", "slack.exe"], [r["app_exe"] for r in self.cfg.app_context_rules])
        self.assertEqual("formal", self.cfg.app_context_rules[0]["tone"])

    def test_preset_e_remover(self):
        next(b for b in self.secao.botoes_de_preset if b.cget("text").startswith("VS Code")).invoke()
        self.assertEqual({("code.exe", "technical"), ("cursor.exe", "technical")},
                         {(r["app_exe"], r["tone"]) for r in self.cfg.app_context_rules})
        self.secao.remover_regra(0)
        self.assertEqual(["cursor.exe"], [r["app_exe"] for r in self.cfg.app_context_rules])

    def test_sem_app_nem_titulo_nada_e_gravado(self):
        self.secao.opt_tom.set("Formal")
        self.secao.btn_adicionar.invoke()
        self.assertEqual([], self.cfg.app_context_rules)
        self.assertIn("aplicativo", self.secao.lbl_status.cget("text"))

    def test_regra_sem_efeito_nao_e_gravada(self):
        self.secao.entry_app.insert(0, "slack.exe")
        self.secao.btn_adicionar.invoke()
        self.assertEqual([], self.cfg.app_context_rules)

    def test_capturar_sem_app_avisa(self):
        self.ultimo_app = None
        self.secao.btn_capturar.invoke()
        self.assertEqual("", self.secao.entry_app.get())
        self.assertIn("Nenhum app", self.secao.lbl_status.cget("text"))

    def test_falha_ao_gravar_mantem_a_lista_do_disco(self):
        self.secao.callbacks["on_save_app_rules"] = lambda regras: False
        self.secao.entry_app.insert(0, "slack.exe")
        self.secao.opt_tom.set("Conciso")
        self.secao.btn_adicionar.invoke()
        self.assertEqual([], self.secao.regras)
        self.assertIn("Não consegui salvar", self.secao.lbl_status.cget("text"))
        self.assertEqual("slack.exe", self.secao.entry_app.get(), "o formulário fica para tentar de novo")

    def test_rotulo_desconhecido_em_opt_tom_ou_modo_nao_levanta_stop_iteration(self):
        self.secao.entry_app.insert(0, "slack.exe")
        self.secao.entry_instrucao.insert(0, "sem emojis")
        self.secao.opt_tom.set("")
        self.secao.opt_modo.set("Valor Inexistente")
        self.assertTrue(self.secao.adicionar_regra())
        self.assertEqual("default", self.cfg.app_context_rules[0]["tone"])
        self.assertEqual("default", self.cfg.app_context_rules[0]["action_mode"])


if __name__ == "__main__":
    unittest.main()
