"""
Teste de contrato entre `willy.py` e as classes reais de `core/` e `ui/`.

`willy.py` tem ~1.670 linhas e nunca é importado pela suíte porque instancia singletons
com efeitos colaterais no topo do módulo (microfone, cofre de credenciais, mutex Win32).
Os testes que usam `_funcao_do_willy(...)` injetam `SimpleNamespace` ou `MagicMock()` sem
`spec_set`, permitindo que chamadas a métodos/atributos inexistentes passem em verde.

Este teste fecha essa brecha em duas camadas sem tocar hardware real:
1. **Contrato estático por AST contra as classes reais**: inspeciona todas as chamadas,
   argumentos nomeados e leituras de atributo feitas em `willy.py` nos singletons conhecidos
   e verifica que cada método/atributo realmente existe na classe real correspondente (ou no
   seu `__init__`), além de validar a fiação de `TranscriptionPipeline`, `callbacks_dash`,
   `tray_callbacks` (contra tudo que `ui/overlays/tray.py` lê), `HotkeyOrchestrator` e
   `verificar_solicitacao`.
2. **Execução das funções críticas de `willy.py` contra `create_autospec(..., spec_set=True)`**:
   qualquer atributo/método renomeado ou assinatura incompatível estoura `AttributeError`
   ou `TypeError` imediatamente.
"""

import ast
import importlib
import inspect
import os
import re
import textwrap
import unittest
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, create_autospec

from core import (
    ActionManager,
    AudioManager,
    AutoStartManager,
    ConfigManager,
    ContextCategory,
    ContextManager,
    GroqService,
    SingleInstanceManager,
    SnippetManager,
    SoundManager,
    TTSManager,
    Win32HotKeyManager,
)
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.system.hotkey_orchestrator import ATALHOS, HotkeyOrchestrator
from core.system.injector import TextInjector
from ui.dashboard import WillyDashboard
from ui.overlays import FloatingPill, HistorySpotlight, LiveTeleprompter, TrayManager

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_WILLY = os.path.join(RAIZ, "willy.py")

EXTRAS = {"default_injector": ("core.system.injector", "TextInjector")}

SINGLETONS_DO_WILLY = {
    "pill": FloatingPill,
    "audio_mgr": AudioManager,
    "config_mgr": ConfigManager,
    "sound_mgr": SoundManager,
    "groq_service": GroqService,
    "hotkey_mgr": Win32HotKeyManager,
    "snippet_mgr": SnippetManager,
    "tts_mgr": TTSManager,
    "spotlight": HistorySpotlight,
    "teleprompter": LiveTeleprompter,
    "tray_mgr": TrayManager,
    "dashboard": WillyDashboard,
    "transcription_pipeline": TranscriptionPipeline,
    "default_injector": TextInjector,
    "single_instance": SingleInstanceManager,
    "hotkey_orchestrator": HotkeyOrchestrator,
    "ContextManager": ContextManager,
    "ActionManager": ActionManager,
    "AutoStartManager": AutoStartManager,
    "Win32HotKeyManager": Win32HotKeyManager,
    "AudioManager": AudioManager,
    "ConfigManager": ConfigManager,
}


def _ler(rel: str) -> str:
    with open(os.path.join(RAIZ, rel), encoding="utf-8") as f:
        return f.read()


def _globais_e_classes(arvore):
    origem = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            for a in no.names:
                origem[a.asname or a.name] = no.module
    globais = dict(EXTRAS)
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Call) and isinstance(no.value.func, ast.Name):
            nome = no.value.func.id
            if nome[:1].isupper() and nome in origem:
                for t in no.targets:
                    if isinstance(t, ast.Name):
                        globais[t.id] = (origem[nome], nome)
    classes = {}
    for g, (mod, nome) in globais.items():
        obj = getattr(importlib.import_module(mod), nome)
        classes[g] = obj if inspect.isclass(obj) else type(obj)
    return classes


def _atributos_da_classe(cls) -> set:
    """Retorna todos os métodos/properties da classe + atributos `self.x` criados na classe."""
    atributos = set(dir(cls))
    for base in inspect.getmro(cls):
        if base is object:
            continue
        try:
            fonte = textwrap.dedent(inspect.getsource(base))
            arvore = ast.parse(fonte)
        except (OSError, TypeError, SyntaxError):
            continue
        for no in ast.walk(arvore):
            if (
                isinstance(no, ast.Attribute)
                and isinstance(no.value, ast.Name)
                and no.value.id == "self"
                and isinstance(no.ctx, ast.Store)
            ):
                atributos.add(no.attr)
    return atributos


def infracoes_do_willy(fonte: str):
    arvore = ast.parse(fonte)
    classes = dict(SINGLETONS_DO_WILLY)
    classes.update(_globais_e_classes(arvore))
    de_instancia = {g: _atributos_da_classe(c) for g, c in classes.items()}
    achados = []
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name) and no.value.id in classes):
            continue
        g, cls = no.value.id, classes[no.value.id]
        if not (hasattr(cls, no.attr) or no.attr in de_instancia[g]):
            achados.append(f"willy.py:{no.lineno}: {g}.{no.attr} não existe em {cls.__name__}")
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and isinstance(no.func.value, ast.Name) and no.func.value.id in classes and no.keywords):
            continue
        metodo = getattr(classes[no.func.value.id], no.func.attr, None)
        if metodo is None or not callable(metodo):
            continue
        try:
            params = inspect.signature(metodo).parameters
        except (TypeError, ValueError):
            continue
        if any(p.kind is p.VAR_KEYWORD for p in params.values()):
            continue
        for kw in no.keywords:
            if kw.arg and kw.arg not in params:
                achados.append(
                    f"willy.py:{no.lineno}: {no.func.value.id}.{no.func.attr}() "
                    f"não aceita {kw.arg}="
                )
    return achados


def _chaves_registradas_no_willy(nome_dict: str, fonte_willy: str | None = None) -> set | None:
    """Retorna as chaves literais de um dicionário atribuído a `nome_dict` em `willy.py`."""
    arvore = ast.parse(fonte_willy if fonte_willy is not None else _ler("willy.py"))
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Assign)
            and isinstance(no.value, ast.Dict)
            and any(isinstance(t, ast.Name) and t.id == nome_dict for t in no.targets)
        ):
            return {
                k.value
                for k in no.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    return None


def chaves_da_bandeja_sem_registro(fonte_willy: str, fonte_bandeja: str):
    lidas = set(
        re.findall(
            r'(?:_call\(|callbacks\.get\(|callbacks\[)\s*["\']([a-z_]+)["\']',
            fonte_bandeja,
        )
    )
    registradas = _chaves_registradas_no_willy("tray_callbacks", fonte_willy)
    if registradas is None:
        return ["tray_callbacks não encontrado no willy.py"]
    return sorted(lidas - registradas)


def _autospec_com_atributos_de_instancia(cls):
    """Cria um `create_autospec(cls, instance=True, spec_set=True)` incluindo atributos de `__init__`."""
    mock_inst = create_autospec(cls, instance=True)
    atributos = _atributos_da_classe(cls)
    for attr in atributos:
        if not attr.startswith("__") and not hasattr(mock_inst, attr):
            setattr(mock_inst, attr, MagicMock(name=f"{cls.__name__}.{attr}"))

    class _Estrito:
        def __getattr__(self, nome):
            if nome not in atributos:
                raise AttributeError(
                    f"{cls.__name__!r} não possui o atributo ou método {nome!r}"
                )
            return getattr(mock_inst, nome)

        def __setattr__(self, nome, valor):
            if nome.startswith("_Estrito__"):
                super().__setattr__(nome, valor)
                return
            if nome not in atributos:
                raise AttributeError(
                    f"{cls.__name__!r} não possui o atributo {nome!r} para atribuição"
                )
            setattr(mock_inst, nome, valor)

    return _Estrito()


class TestContratoDoWillyComAsClasses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codigo_willy = _ler("willy.py")
        cls.arvore = ast.parse(cls.codigo_willy, filename=CAMINHO_WILLY)

    def test_o_que_o_willy_chama_existe_na_classe_real(self):
        """Qualquer `obj.metodo(kw=...)` ou `obj.atributo` em willy.py precisa existir na classe real."""
        self.assertEqual([], infracoes_do_willy(self.codigo_willy))

    def test_a_deteccao_enxerga_os_globais(self):
        """Se o mapeamento de globais quebrar, o teste acima passaria vazio."""
        classes = _globais_e_classes(self.arvore)
        for g in (
            "pill",
            "dashboard",
            "spotlight",
            "teleprompter",
            "tray_mgr",
            "audio_mgr",
            "config_mgr",
            "groq_service",
            "transcription_pipeline",
            "default_injector",
        ):
            self.assertIn(g, classes)

    def test_toda_chave_que_a_bandeja_le_esta_registrada(self):
        """Toda chave lida por `ui/overlays/tray.py` precisa estar em `tray_callbacks` (mata U14)."""
        self.assertEqual(
            [],
            chaves_da_bandeja_sem_registro(self.codigo_willy, _ler("ui/overlays/tray.py")),
        )

    def test_callbacks_dash_e_tray_existem_e_apontam_para_simbolos_reais(self):
        """Valida que `callbacks_dash` e `tray_callbacks` existem em `main()` e não têm valores None."""
        nomes_topo = {
            no.name
            for no in self.arvore.body
            if isinstance(no, (ast.FunctionDef, ast.ClassDef))
        }
        for no in self.arvore.body:
            if isinstance(no, ast.Assign):
                for t in no.targets:
                    if isinstance(t, ast.Name):
                        nomes_topo.add(t.id)
            elif isinstance(no, (ast.Import, ast.ImportFrom)):
                for alias in no.names:
                    nomes_topo.add((alias.asname or alias.name).split(".")[0])

        dicts_encontrados = {}
        for no in ast.walk(self.arvore):
            if isinstance(no, ast.Assign) and isinstance(no.value, ast.Dict):
                for t in no.targets:
                    if isinstance(t, ast.Name) and t.id in ("callbacks_dash", "tray_callbacks"):
                        dicts_encontrados[t.id] = no.value

        self.assertIn("callbacks_dash", dicts_encontrados)
        self.assertIn("tray_callbacks", dicts_encontrados)

        for nome_dict, d in dicts_encontrados.items():
            for k, v in zip(d.keys, d.values):
                chave = k.value if isinstance(k, ast.Constant) else "?"
                self.assertFalse(
                    isinstance(v, ast.Constant) and v.value is None,
                    f"{nome_dict}[{chave!r}] não pode ser None",
                )
                if isinstance(v, ast.Name):
                    self.assertIn(
                        v.id,
                        nomes_topo,
                        f"{nome_dict}[{chave!r}] aponta para {v.id!r} inexistente",
                    )

    def test_handlers_do_hotkey_orchestrator_tem_todas_as_14_acoes(self):
        """O dicionário `handlers` passado ao `HotkeyOrchestrator` precisa cobrir todas as 14 ações."""
        acoes_esperadas = {acao for acao, _, _ in ATALHOS}
        handlers_dict = None
        for no in ast.walk(self.arvore):
            if isinstance(no, ast.Assign) and isinstance(no.value, ast.Dict):
                for t in no.targets:
                    if isinstance(t, ast.Name) and t.id == "handlers":
                        handlers_dict = no.value
        self.assertIsNotNone(handlers_dict, "Dicionário `handlers` não encontrado em willy.py")
        chaves = {k.value for k in handlers_dict.keys if isinstance(k, ast.Constant)}
        self.assertEqual(acoes_esperadas, chaves)
        for k, v in zip(handlers_dict.keys, handlers_dict.values):
            self.assertIsInstance(
                v, ast.Name, f"Handler {k.value!r} deve ser uma função nomeada"
            )

    def test_fiacao_do_transcription_pipeline_e_main(self):
        """Garante que TranscriptionPipeline, set_retry_callback e verificar_solicitacao estão ligados."""
        chamada_pipeline = None
        for no in self.arvore.body:
            if (
                isinstance(no, ast.Assign)
                and isinstance(no.value, ast.Call)
                and getattr(no.value.func, "id", None) == "TranscriptionPipeline"
            ):
                chamada_pipeline = no.value
                break
        self.assertIsNotNone(chamada_pipeline, "Instanciação de TranscriptionPipeline não encontrada")
        kws = {kw.arg: kw.value for kw in chamada_pipeline.keywords}
        esperados = {
            "on_caption": "_pipeline_on_caption",
            "on_pill_text": "_pipeline_on_pill_text",
            "on_success_sync": "_pipeline_on_sync",
            "ui_notifier": "atualizar_ui",
            "ui_dispatcher": "safe_dispatch_ui",
        }
        for arg_nome, func_esperada in esperados.items():
            self.assertIn(arg_nome, kws, f"Keyword {arg_nome!r} ausente em TranscriptionPipeline(...)")
            self.assertIsInstance(
                kws[arg_nome],
                ast.Name,
                f"Keyword {arg_nome!r} em TranscriptionPipeline(...) não pode ser None/constante",
            )
            self.assertEqual(func_esperada, kws[arg_nome].id)

        func_main = next(
            no for no in self.arvore.body
            if isinstance(no, ast.FunctionDef) and no.name == "main"
        )
        chamou_retry = False
        def_verificar = None
        for no in ast.walk(func_main):
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and isinstance(no.func.value, ast.Name)
                and no.func.value.id == "pill"
                and no.func.attr == "set_retry_callback"
            ):
                self.assertEqual(1, len(no.args))
                self.assertIsInstance(no.args[0], ast.Name)
                self.assertEqual("reenviar_ultimo_audio", no.args[0].id)
                chamou_retry = True
            elif isinstance(no, ast.FunctionDef) and no.name == "verificar_solicitacao":
                def_verificar = no
        self.assertTrue(
            chamou_retry,
            "main() deve chamar pill.set_retry_callback(reenviar_ultimo_audio)",
        )
        self.assertIsNotNone(def_verificar, "verificar_solicitacao() não encontrada em main()")

        modulo_verif = ast.Module(body=[def_verificar], type_ignores=[])
        root_mock = MagicMock()
        remove_mock = MagicMock()
        flag_existe = [False]
        escopo_verif = {
            "lembrar_janela_fora_do_willy": MagicMock(),
            "os": SimpleNamespace(
                path=SimpleNamespace(exists=lambda _p: flag_existe[0]),
                remove=remove_mock,
            ),
            "FLAG_SHOW_DASHBOARD": "flag_inexistente",
            "dashboard": _autospec_com_atributos_de_instancia(WillyDashboard),
            "root": root_mock,
        }
        exec(compile(modulo_verif, CAMINHO_WILLY, "exec"), escopo_verif)
        escopo_verif["verificar_solicitacao"]()
        escopo_verif["dashboard"].mostrar.assert_not_called()
        root_mock.after.assert_called_once_with(400, escopo_verif["verificar_solicitacao"])
        flag_existe[0] = True
        escopo_verif["verificar_solicitacao"]()
        remove_mock.assert_called_once_with("flag_inexistente")
        escopo_verif["dashboard"].mostrar.assert_called_once_with()
        self.assertEqual(2, root_mock.after.call_count)
        self.assertEqual((400, escopo_verif["verificar_solicitacao"]), root_mock.after.call_args.args)

    def test_callbacks_dash_get_settings_e_lambdas_contra_autospec(self):
        """Executa o dict `callbacks_dash` de `main()` garantindo todas as chaves de get_settings e lambdas."""
        func_main = next(
            no for no in self.arvore.body
            if isinstance(no, ast.FunctionDef) and no.name == "main"
        )
        assign_dash = next(
            no for no in ast.walk(func_main)
            if isinstance(no, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "callbacks_dash" for t in no.targets)
        )

        cfg_estrito = _autospec_com_atributos_de_instancia(ConfigManager)
        mapa_esperado = {
            "auto_silence": "auto_silence",
            "clean_fillers": "clean_fillers",
            "clipboard_only": "clipboard_only",
            "smart_paragraphing": "smart_paragraphing",
            "output_tone": "output_tone",
            "input_language": "input_language",
            "silence_seconds": "silence_seconds",
            "refine_prompt": "refine_prompt",
            "silent_mode": "silent_mode",
            "private_mode": "private_mode",
            "outputs_dir": "outputs_dir",
            "pill_position": "pill_position",
            "llm_model": "llm_model",
            "audio_device": "audio_device",
            "system_audio_device": "system_audio_device",
            "mic_gain": "mic_gain",
            "prompt_hotkey": "prompt_hotkey",
            "transform_hotkey": "transform_hotkey",
            "profile_hotkey": "profile_hotkey",
            "processing_profile": "processing_profile",
            "whisper_mode": "whisper_mode",
            "voice_hotkey": "hotkey",
            "translate_hotkey": "translate_hotkey",
            "translate_es_hotkey": "translate_es_hotkey",
            "master_hotkey": "master_hotkey",
            "meeting_hotkey": "meeting_hotkey",
            "history_hotkey": "history_hotkey",
            "undo_hotkey": "undo_hotkey",
            "send_hotkey": "send_hotkey",
            "speak_hotkey": "speak_hotkey",
            "sticky_hotkey": "sticky_hotkey",
            "captions_hotkey": "captions_hotkey",
            "save_audio_files": "save_audio_files",
            "silero_vad": "silero_vad",
            "wake_word_enabled": "wake_word_enabled",
            "onboarding_completed": "onboarding_completed",
            "api_key": "groq_api_key",
            "cofre_ilegivel": "cofre_ilegivel",
            "modelo_llm_substituido": "modelo_llm_substituido",
        }
        for chave_setting, attr_cfg in mapa_esperado.items():
            setattr(cfg_estrito, attr_cfg, f"sentinela_{attr_cfg}")

        teleprompter_estrito = _autospec_com_atributos_de_instancia(LiveTeleprompter)
        tray_estrito = _autospec_com_atributos_de_instancia(TrayManager)
        audio_estrito = _autospec_com_atributos_de_instancia(AudioManager)
        snippet_estrito = _autospec_com_atributos_de_instancia(SnippetManager)
        groq_estrito = _autospec_com_atributos_de_instancia(GroqService)
        sound_estrito = _autospec_com_atributos_de_instancia(SoundManager)
        tts_estrito = _autospec_com_atributos_de_instancia(TTSManager)
        autostart_mock = create_autospec(AutoStartManager, spec_set=True)
        autostart_mock.is_enabled.return_value = "sentinela_autostart"

        escopo = {
            "config_mgr": cfg_estrito,
            "AudioManager": _autospec_com_atributos_de_instancia(AudioManager),
            "ConfigManager": _autospec_com_atributos_de_instancia(ConfigManager),
            "AutoStartManager": autostart_mock,
            "ContextManager": _autospec_com_atributos_de_instancia(ContextManager),
            "safe_dispatch_ui": MagicMock(),
            "audio_mgr": audio_estrito,
            "hotkey_orchestrator": _autospec_com_atributos_de_instancia(HotkeyOrchestrator),
            "snippet_mgr": snippet_estrito,
            "transcrever_arquivo_em_segundo_plano": MagicMock(),
            "reusar_no_app_anterior": MagicMock(),
            "importar_perfil": MagicMock(),
            "desfazer_ultimo_ditado": MagicMock(),
            "toggle_modo_envio": MagicMock(),
            "toggle_willy_awake": MagicMock(),
            "dashboard_save_settings": MagicMock(),
            "sincronizar_bandeja": MagicMock(),
            "groq_service": groq_estrito,
            "fechar_aplicacao": MagicMock(),
            "sound_mgr": sound_estrito,
            "tts_mgr": tts_estrito,
            "atualizar_ui": MagicMock(),
            "teleprompter": teleprompter_estrito,
            "on_sticky_hotkey": MagicMock(),
            "tray_mgr": tray_estrito,
            "reformatar_texto": MagicMock(name="reformatar_texto"),
            "ultimo_app_externo": MagicMock(name="ultimo_app_externo"),
            "credenciais_do_willy": MagicMock(name="credenciais_do_willy", return_value=[]),
            "validar_e_aplicar_chave_groq": MagicMock(name="validar_e_aplicar_chave_groq"),
            "recarregar_chave_do_cofre_vivo": MagicMock(name="recarregar_chave_do_cofre_vivo"),
            "capturar_e_testar_ditado": MagicMock(name="capturar_e_testar_ditado"),
            "concluir_onboarding_willy": MagicMock(name="concluir_onboarding_willy"),
        }
        modulo_dash = ast.Module(body=[assign_dash], type_ignores=[])
        exec(compile(modulo_dash, CAMINHO_WILLY, "exec"), escopo)
        callbacks_dash = escopo["callbacks_dash"]

        self.assertIs(escopo["validar_e_aplicar_chave_groq"], callbacks_dash["on_validate_groq_key"])
        self.assertIs(escopo["recarregar_chave_do_cofre_vivo"], callbacks_dash["on_reload_api_key"])
        self.assertIs(escopo["capturar_e_testar_ditado"], callbacks_dash["on_test_dictation"])
        self.assertIs(escopo["concluir_onboarding_willy"], callbacks_dash["on_complete_onboarding"])
        callbacks_dash["get_credential_catalog"]()
        escopo["credenciais_do_willy"].assert_called_once_with(cfg_estrito)

        # Bloco 12: as ligações novas apontam para o que existe no ConfigManager e no willy.py.
        self.assertIs(escopo["reformatar_texto"], callbacks_dash["on_reformat_text"])
        self.assertIs(escopo["ultimo_app_externo"], callbacks_dash["get_last_external_app"])
        callbacks_dash["on_learn_correction"]("vily", "Willy")
        cfg_estrito.learn_correction.assert_called_once_with("vily", "Willy")
        callbacks_dash["get_app_rules"]()
        cfg_estrito.get_app_context_rules.assert_called_once_with()
        callbacks_dash["on_save_app_rules"]([{"app_exe": "slack.exe"}])
        cfg_estrito.save_app_context_rules.assert_called_once_with([{"app_exe": "slack.exe"}])
        callbacks_dash["on_summarize_profile"]("perfil.json")
        cfg_estrito.resumir_perfil.assert_called_once_with("perfil.json")

        settings = callbacks_dash["get_settings"]()
        for chave_setting, attr_cfg in mapa_esperado.items():
            self.assertIn(
                chave_setting,
                settings,
                f"Chave {chave_setting!r} removida de callbacks_dash['get_settings']()",
            )
            self.assertEqual(
                f"sentinela_{attr_cfg}",
                settings[chave_setting],
                f"callbacks_dash['get_settings']()[{chave_setting!r}] lê o atributo errado de config_mgr",
            )
        self.assertEqual("sentinela_autostart", settings["autostart"])

        callbacks_dash["on_toggle_teleprompter"]()
        teleprompter_estrito.toggle.assert_called_once_with()

    def test_reformatar_e_ultimo_app_do_bloco12_contra_autospec(self):
        """`reformatar_texto` e `ultimo_app_externo` (Bloco 12) contra as classes reais em autospec."""
        nos = [no for no in self.arvore.body
               if (isinstance(no, ast.FunctionDef) and no.name in ("reformatar_texto", "ultimo_app_externo"))
               or (isinstance(no, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TONS_DO_REFORMATAR"
                                                      for t in no.targets))]
        self.assertEqual(3, len(nos), "reformatar_texto, ultimo_app_externo e TONS_DO_REFORMATAR no willy.py")
        config_mgr = _autospec_com_atributos_de_instancia(ConfigManager)
        groq_service = _autospec_com_atributos_de_instancia(GroqService)
        context_manager = create_autospec(ContextManager, spec_set=True)
        config_mgr.get_vocab_terms.return_value = ["FastAPI", "Willy"]
        config_mgr.load_replacements.return_value = {"vily": "Willy"}
        config_mgr.processing_profile = "puro"
        config_mgr.smart_paragraphing = True
        escopo = {"Optional": Optional, "Tuple": tuple, "config_mgr": config_mgr, "groq_service": groq_service,
                  "ContextManager": context_manager, "_janela_antes_do_willy": 0}
        exec(compile(ast.Module(body=nos, type_ignores=[]), CAMINHO_WILLY, "exec"), escopo)
        reformatar = escopo["reformatar_texto"]

        groq_service.refine_text.return_value = "Qual é o status do vily."
        self.assertEqual("Qual é o status do Willy?", reformatar("segue aí", "formal"))
        groq_service.refine_text.assert_called_once_with(
            "segue aí", enabled=True, tone="formal", smart_paragraphing=True, profile="dev", estrito=True)

        termos = "Termos da pessoa, que ficam como estão: FastAPI, Willy"
        groq_service.translate_to_english.return_value = "Hello vily."
        self.assertEqual("Hello Willy.", reformatar("bom dia", "translate"))
        groq_service.translate_to_english.assert_called_once_with("bom dia", extra_context=termos, estrito=True)
        groq_service.translate_to_spanish.return_value = "Hola vily."
        self.assertEqual("Hola Willy.", reformatar("bom dia", "translate_es"))
        groq_service.translate_to_spanish.assert_called_once_with("bom dia", extra_context=termos, estrito=True)
        with self.assertRaises(ValueError):
            reformatar("bom dia", "pirata")

        ultimo_app = escopo["ultimo_app_externo"]
        self.assertIsNone(ultimo_app())
        escopo["_janela_antes_do_willy"] = 0x1234
        context_manager.janela_existe.return_value = True
        context_manager.get_foreground_app.return_value = ("slack.exe", "#geral", ContextCategory.MESSAGING)
        self.assertEqual(("slack.exe", "#geral"), ultimo_app())
        context_manager.get_foreground_app.assert_called_once_with(0x1234)
        context_manager.janela_existe.return_value = False
        self.assertIsNone(ultimo_app())

    def test_fluxos_criticos_do_willy_contra_autospec_estrito(self):
        """Executa funções críticas de `willy.py` contra mocks `spec_set` das classes reais."""
        funcoes_alvo = (
            "atualizar_ui",
            "_pronto_para_gravar",
            "_pipeline_on_pill_text",
            "_pipeline_on_caption",
            "_pipeline_on_sync",
            "sincronizar_bandeja",
            "toggle_modo_envio",
            "_soltar_esc",
            "iniciar_gravacao",
            "parar_gravacao",
            "_executar_pipeline_transcricao",
            "cancelar_gravacao",
            "reenviar_ultimo_audio",
            "desfazer_ultimo_ditado",
            "on_history_hotkey",
            "on_captions_hotkey",
            "on_translate_es_hotkey",
            "fechar_aplicacao",
        )
        nos_funcoes = [
            no
            for no in self.arvore.body
            if isinstance(no, ast.FunctionDef) and no.name in funcoes_alvo
        ]
        modulo = ast.Module(body=nos_funcoes, type_ignores=[])
        codigo = compile(modulo, CAMINHO_WILLY, "exec")

        pill = _autospec_com_atributos_de_instancia(FloatingPill)
        audio_mgr = _autospec_com_atributos_de_instancia(AudioManager)
        config_mgr = _autospec_com_atributos_de_instancia(ConfigManager)
        sound_mgr = _autospec_com_atributos_de_instancia(SoundManager)
        hotkey_mgr = _autospec_com_atributos_de_instancia(Win32HotKeyManager)
        spotlight = _autospec_com_atributos_de_instancia(HistorySpotlight)
        teleprompter = _autospec_com_atributos_de_instancia(LiveTeleprompter)
        tray_mgr = _autospec_com_atributos_de_instancia(TrayManager)
        dashboard = _autospec_com_atributos_de_instancia(WillyDashboard)
        transcription_pipeline = _autospec_com_atributos_de_instancia(TranscriptionPipeline)
        single_instance = _autospec_com_atributos_de_instancia(SingleInstanceManager)
        tts_mgr = _autospec_com_atributos_de_instancia(TTSManager)

        audio_mgr.is_awake = True
        audio_mgr.is_recording = False
        audio_mgr.is_processing = False
        audio_mgr.recording_mode = "transcribe"
        audio_mgr.system_device_index = None
        audio_mgr.ambient_noise_floor = 0.005
        audio_mgr.gain_boost = 1.0
        audio_mgr.ensure_stream.return_value = True
        audio_mgr.start_recording.return_value = True
        audio_mgr.stop_recording_com_taxa.return_value = (b"RIFF____WAVEfmt ", "translate", 16000)

        config_mgr.refine_prompt = False
        config_mgr.silent_mode = True
        config_mgr.auto_silence = True
        config_mgr.pill_position = "topo"
        config_mgr.hotkey = "ctrl+space"
        config_mgr.translate_hotkey = "ctrl+alt+space"
        config_mgr.translate_es_hotkey = "ctrl+alt+e"
        config_mgr.master_hotkey = "ctrl+shift+space"
        config_mgr.meeting_hotkey = "ctrl+alt+r"
        config_mgr.prompt_hotkey = "ctrl+alt+p"
        config_mgr.llm_model = "llama"
        config_mgr.output_tone = "default"
        config_mgr.processing_profile = "dev"
        config_mgr.wake_word_enabled = False
        config_mgr.groq_api_key = "gsk_valido"
        config_mgr.load_history.return_value = [{"text": "item_hist"}]

        teleprompter.is_visible = True
        fila_mock = MagicMock()
        fila_mock.mais_recente.return_value = ("item.wav", "transcribe")
        fila_mock.__len__.return_value = 3
        transcription_pipeline.fila = fila_mock

        threads_iniciadas = []

        def _criar_thread(*, target=None, args=(), daemon=None):
            t = MagicMock()
            t.start.side_effect = lambda: threads_iniciadas.append((target, args))
            return t

        fake_threading = SimpleNamespace(Thread=MagicMock(side_effect=_criar_thread))
        fake_keyboard = SimpleNamespace(send=MagicMock())

        escopo = {
            "Optional": Optional,
            "Tuple": tuple,
            "pill": pill,
            "audio_mgr": audio_mgr,
            "config_mgr": config_mgr,
            "sound_mgr": sound_mgr,
            "hotkey_mgr": hotkey_mgr,
            "spotlight": spotlight,
            "teleprompter": teleprompter,
            "tray_mgr": tray_mgr,
            "dashboard": dashboard,
            "transcription_pipeline": transcription_pipeline,
            "default_injector": _autospec_com_atributos_de_instancia(TextInjector),
            "single_instance": single_instance,
            "tts_mgr": tts_mgr,
            "ContextManager": create_autospec(ContextManager, spec_set=True),
            "ActionManager": create_autospec(ActionManager, spec_set=True),
            "Win32HotKeyManager": create_autospec(Win32HotKeyManager, spec_set=True),
            "PipelineContext": PipelineContext,
            "ContextCategory": ContextCategory,
            "safe_dispatch_ui": lambda fn, *a, **kw: fn(*a),
            "lembrar_janela_fora_do_willy": lambda: 100,
            "_soltar_esc_sem_gravacao": MagicMock(),
            "cancelar_por_esc": MagicMock(),
            "callback_audio": MagicMock(),
            "monitorar_hold": MagicMock(),
            "processar_transcricao": MagicMock(),
            "_ATALHO_DO_CANCELAR": "cancelar_gravacao",
            "_ATALHO_DO_CANCELAR_SEGURANDO": "cancelar_gravacao_segurando",
            "FAILED_AUDIO_PATH": "failed.wav",
            "_janela_antes_do_willy": 100,
            "_foco_antes_do_willy": 200,
            "_alvo_da_gravacao": (100, 200),
            "current_app_context": ("code.exe", "VS Code", ContextCategory.GENERAL),
            "selected_text_for_transform": "",
            "last_injected_text": None,
            "root": MagicMock(),
            "threading": fake_threading,
            "keyboard": fake_keyboard,
        }
        escopo["ContextManager"].resolver_janela_alvo.return_value = (100, 200)
        escopo["ContextManager"].get_foreground_app.return_value = (
            "code.exe",
            "VS Code",
            ContextCategory.GENERAL,
        )
        escopo["Win32HotKeyManager"].com_os_modificadores_de.return_value = "ctrl+alt+esc"

        exec(codigo, escopo)

        # 1. atualizar_ui -> pill.show_state
        escopo["atualizar_ui"]("listening", "Ouvindo...", por_cima=True)
        pill.show_state.assert_called_once()

        # 2. _pipeline_on_pill_text -> pill.set_last_text e controle de last_injected_text
        escopo["last_injected_text"] = None
        escopo["_pipeline_on_pill_text"]("apenas copiado", colado=False)
        pill.set_last_text.assert_called_once_with("apenas copiado")
        self.assertIsNone(
            escopo["last_injected_text"],
            "_pipeline_on_pill_text não deve marcar last_injected_text quando colado=False",
        )
        escopo["_pipeline_on_pill_text"]("texto colado", colado=True)
        pill.set_last_text.assert_called_with("texto colado")
        self.assertEqual("texto colado", escopo["last_injected_text"])

        # 3. _pipeline_on_caption -> teleprompter.adicionar_legenda
        escopo["_pipeline_on_caption"]("legenda")
        teleprompter.adicionar_legenda.assert_called_once_with("legenda")

        # 4. sincronizar_bandeja -> tray_mgr.update com valores exatos (mata N11)
        escopo["sincronizar_bandeja"]()
        tray_mgr.update.assert_called_once_with(
            is_awake=True,
            refine_enabled=False,
            silent_mode=True,
            pill_pos="topo",
            hotkey="ctrl+space",
            trans_hotkey="ctrl+alt+space",
            trans_es_hotkey="ctrl+alt+e",
            master_hotkey="ctrl+shift+space",
            meeting_hotkey="ctrl+alt+r",
            llm_model="llama",
            history_items=[{"text": "item_hist"}],
            prompt_hotkey="ctrl+alt+p",
            auto_silence=True,
            pendentes=3,
        )

        # 4b. toggle_modo_envio -> config_mgr.toggle_auto_silence (mata N12)
        escopo["toggle_modo_envio"]()
        config_mgr.toggle_auto_silence.assert_called_once_with()

        # 5. iniciar_gravacao -> ensure_stream, registrar_temporario, start_recording
        escopo["iniciar_gravacao"]("transcribe", "ctrl+alt+d")
        audio_mgr.ensure_stream.assert_called_once()
        audio_mgr.start_recording.assert_called_once_with("transcribe")

        # 6. parar_gravacao -> stop_recording_com_taxa + inicia thread do pipeline com o modo (mata A2 e N4)
        audio_mgr.is_recording = True
        threads_iniciadas.clear()
        escopo["parar_gravacao"]()
        audio_mgr.stop_recording_com_taxa.assert_called_once()
        self.assertEqual(
            [(escopo["processar_transcricao"], (b"RIFF____WAVEfmt ", "translate", 16000, 0.005, (100, 200)))],
            threads_iniciadas,
            "parar_gravacao() deve chamar .start() na Thread de processar_transcricao preservando o modo",
        )

        # 6b. _executar_pipeline_transcricao -> preserva modo no PipelineContext (mata T3)
        escopo["_executar_pipeline_transcricao"](b"RIFF", "translate", True, "item.wav", (100, 200))
        ctx_passado = transcription_pipeline.process.call_args.args[0]
        self.assertEqual("translate", ctx_passado.modo)
        self.assertEqual(b"RIFF", ctx_passado.wav_bytes)
        self.assertTrue(ctx_passado.is_retry)
        self.assertEqual("item.wav", ctx_passado.retry_path)
        self.assertEqual(100, ctx_passado.janela_alvo)
        self.assertEqual(200, ctx_passado.foco_alvo)

        # 7. cancelar_gravacao -> cancel_recording
        audio_mgr.is_recording = True
        escopo["cancelar_gravacao"]()
        audio_mgr.cancel_recording.assert_called_once()

        # 8. reenviar_ultimo_audio -> fila.mais_recente + inicia thread (mata A9)
        audio_mgr.is_recording = False
        audio_mgr.is_processing = False
        threads_iniciadas.clear()
        with unittest.mock.patch("builtins.open", unittest.mock.mock_open(read_data=b"RIFF")):
            escopo["reenviar_ultimo_audio"]()
        fila_mock.mais_recente.assert_called_once()
        self.assertEqual(
            1,
            len(threads_iniciadas),
            "reenviar_ultimo_audio() deve chamar .start() na Thread do pipeline",
        )

        # 9. desfazer_ultimo_ditado -> keyboard.send("ctrl+z")
        escopo["last_injected_text"] = "ditado"
        escopo["ActionManager"].esperar_modificadores_soltos.return_value = True
        escopo["desfazer_ultimo_ditado"]()
        fake_keyboard.send.assert_called_once_with("ctrl+z")

        # 10. on_history_hotkey -> spotlight.mostrar e callback atualiza last_injected_text quando cola
        escopo["on_history_hotkey"]()
        spotlight.mostrar.assert_called_once()
        cb_spotlight = spotlight.mostrar.call_args.kwargs["on_paste_callback"]
        escopo["last_injected_text"] = None
        escopo["default_injector"].paste_text.return_value = False
        cb_spotlight("falhou")
        self.assertIsNone(escopo["last_injected_text"])
        escopo["default_injector"].paste_text.return_value = True
        cb_spotlight("colado pelo spotlight")
        self.assertEqual("colado pelo spotlight", escopo["last_injected_text"])

        # 11. on_captions_hotkey -> teleprompter.toggle
        escopo["on_captions_hotkey"]()
        teleprompter.toggle.assert_called_once()

        # 12. on_translate_es_hotkey -> iniciar_gravacao("translate_es")
        audio_mgr.is_recording = False
        audio_mgr.start_recording.reset_mock()
        escopo["on_translate_es_hotkey"]()
        audio_mgr.start_recording.assert_called_once_with("translate_es")


if __name__ == "__main__":
    unittest.main()
