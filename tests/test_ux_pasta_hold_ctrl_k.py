"""
Três correções pequenas de UX: a pasta de configuração, o segurar-para-falar e o Ctrl+K.

- O item "Abrir pasta de configuração (AppData)" da bandeja abria a pasta do programa.
- monitorar_hold olhava sempre a barra de espaço: com Ctrl+Alt+P ou Ctrl+Shift+Enter,
  segurar o P ou o Enter não era percebido. E olhava só a tecla principal (um espaço digitado
  depois de um toque em Ctrl+Espaço cortava o ditado), encerrava a gravação seguinte à que
  viu começar, e o Ctrl+Alt+T não tinha segurar-para-falar.
- A aba Histórico religava o Ctrl+K na janela por cima do bind do dashboard, e o Ctrl+K na
  aba Templates puxava para a busca do Histórico.
"""

import ast
import os
import time
import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

from core.hotkey import Win32HotKeyManager
from tests.config_isolada import isolar_config
from tests.willy_isolado import _funcao_do_willy, destruir_tk
from ui.dashboard import WillyDashboard

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPastaDeConfiguracao(unittest.TestCase):
    def test_abre_a_pasta_dos_dados(self):
        abrir = MagicMock()
        _funcao_do_willy("abrir_pasta_config", os=SimpleNamespace(startfile=abrir),
                         USER_DATA_DIR="C:/Users/ana/AppData/Roaming/Willy")()
        abrir.assert_called_once_with("C:/Users/ana/AppData/Roaming/Willy")

    def test_a_bandeja_usa_essa_funcao(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        valores = [v for n in ast.walk(arvore) if isinstance(n, ast.Dict)
                   for k, v in zip(n.keys, n.values)
                   if isinstance(k, ast.Constant) and k.value == "on_open_folder"]
        self.assertEqual(["abrir_pasta_config"], [getattr(v, "id", None) for v in valores])


CTRL, ALT, SHIFT, WIN_ESQ, WIN_DIR = 0x11, 0x12, 0x10, 0x5B, 0x5C
# A espera dos 650 ms do monitorar_hold, em passos de 25 ms: o sleep seguinte já é do segurar.
PASSOS_DA_ESPERA = 26


class User32Falso:
    """A tecla principal `vk` fica apertada pelas primeiras `leituras` consultas a ela; as de
    `presas` ficam apertadas o tempo todo."""

    def __init__(self, vk, leituras, presas=()):
        self.vk, self.leituras, self.presas, self.consultadas = vk, leituras, set(presas), []

    def GetAsyncKeyState(self, vk):
        self.consultadas.append(vk)
        if vk == self.vk and self.leituras > 0:
            self.leituras -= 1
            return 0x8000
        return 0x8000 if vk in self.presas else 0


class TestSegurarParaFalar(unittest.TestCase):
    def _monitorar(self, combo, vk_segurada, leituras=3, presas=(CTRL, ALT, SHIFT), troca_de_gravacao=None):
        self.parar = MagicMock()
        self.user32 = User32Falso(vk_segurada, leituras, presas)
        self.audio = SimpleNamespace(is_recording=True, is_awake=True, recording_start_time=100.0,
                                     recording_mode="transcribe")
        sleeps = self.sleeps = []

        def _sleep(_s):
            # Simula outra gravação começando enquanto o monitor espera: "650ms" é o 1º passo da
            # espera dos 650 ms; "laço" é o 1º passo do segurar.
            sleeps.append(_s)
            quando = "650ms" if len(sleeps) == 1 else "laço" if len(sleeps) == PASSOS_DA_ESPERA + 1 else None
            if troca_de_gravacao is not None and troca_de_gravacao == quando:
                self.audio.recording_start_time = 200.0

        monitorar = _funcao_do_willy(
            "monitorar_hold", Win32HotKeyManager=Win32HotKeyManager, parar_gravacao=self.parar,
            _user32=self.user32, ctypes=SimpleNamespace(windll=SimpleNamespace(user32=self.user32)),
            time=SimpleNamespace(sleep=_sleep), audio_mgr=self.audio, _VK_ESCAPE=0x1B,
            cancelar_por_esc=MagicMock(side_effect=AssertionError("Esc sem ninguém apertar")))
        monitorar(combo)

    def test_segurar_o_atalho_encerra_ao_soltar(self):
        for combo, vk in (("ctrl+alt+p", ord("P")), ("ctrl+shift+enter", 0x0D), ("ctrl+space", 0x20)):
            with self.subTest(combo=combo):
                self._monitorar(combo, vk)
                self.parar.assert_called_once_with()

    def test_a_espera_dura_650_ms_em_passos_de_25_ms(self):
        # Juiz do Bloco 10, 18ª rodada: com o Esc lido durante a espera, o teste contava os passos e
        # deixava de olhar a duração; com passos de 50 ms, segurar por 1 s virava toque.
        self._monitorar("ctrl+alt+p", ord("P"))
        espera = self.sleeps[:PASSOS_DA_ESPERA]
        self.assertEqual([0.025] * PASSOS_DA_ESPERA, espera)
        self.assertAlmostEqual(0.65, sum(espera))

    def test_segurar_o_espaco_num_atalho_sem_espaco_nao_encerra(self):
        self._monitorar("ctrl+alt+p", 0x20)
        self.parar.assert_not_called()

    def test_toque_rapido_nao_encerra(self):
        self._monitorar("ctrl+alt+p", ord("P"), leituras=0)
        self.parar.assert_not_called()

    def test_combinacao_invalida_nao_consulta_teclado(self):
        self._monitorar("ctrl+", 0x20)
        self.assertEqual([], self.user32.consultadas)

    def test_tecla_principal_sem_os_modificadores_nao_e_segurar(self):
        # Toque rápido em Ctrl+Espaço e, aos 650 ms, a pessoa digita um espaço: soltar o
        # espaço cortava o ditado que ela tinha deixado gravando.
        for combo, vk, presas in (("ctrl+space", 0x20, ()), ("ctrl+alt+p", ord("P"), (CTRL,)),
                                  ("ctrl+shift+enter", 0x0D, (SHIFT,)), ("win+alt+d", ord("D"), (ALT,))):
            with self.subTest(combo=combo, presas=presas):
                self._monitorar(combo, vk, presas=presas)
                self.parar.assert_not_called()

    def test_qualquer_lado_do_win_vale(self):
        for lado in (WIN_ESQ, WIN_DIR):
            with self.subTest(lado=hex(lado)):
                self._monitorar("win+alt+d", ord("D"), presas=(lado, ALT))
                self.parar.assert_called_once_with()

    def test_nao_encerra_a_gravacao_seguinte(self):
        # Toque, toque e toque: aos 650 ms já é outra gravação, que tem o monitor dela. Este
        # nem lê o teclado, ou o larga logo, com a pessoa ainda segurando para a gravação nova.
        # As leituras da espera são do Esc, uma por passo.
        for quando, leituras_no_maximo in (("650ms", 0), ("laço", PASSOS_DA_ESPERA + 9)):
            with self.subTest(troca=quando):
                self._monitorar("ctrl+alt+p", ord("P"), leituras=1000, troca_de_gravacao=quando)
                self.parar.assert_not_called()
                self.assertLessEqual(len(self.user32.consultadas), leituras_no_maximo)

    def test_quem_soltou_depois_de_parar_por_outro_caminho_nao_para_de_novo(self):
        self.parar = MagicMock()
        self.user32 = User32Falso(ord("P"), 3, (CTRL, ALT))
        audio = SimpleNamespace(is_recording=True, is_awake=True, recording_start_time=1.0,
                                recording_mode="transcribe")
        sleeps = []

        def _sleep(_s):
            sleeps.append(_s)
            if len(sleeps) > PASSOS_DA_ESPERA:
                audio.is_recording = False  # o silêncio encerrou a gravação durante o segurar

        _funcao_do_willy(
            "monitorar_hold", Win32HotKeyManager=Win32HotKeyManager, parar_gravacao=self.parar,
            _user32=self.user32, ctypes=SimpleNamespace(windll=SimpleNamespace(user32=self.user32)),
            time=SimpleNamespace(sleep=_sleep), audio_mgr=audio, _VK_ESCAPE=0x1B,
            cancelar_por_esc=MagicMock())("ctrl+alt+p")
        self.parar.assert_not_called()
        self.assertGreater(len(sleeps), PASSOS_DA_ESPERA, "não chegou a segurar")


class TestQuemChamaOSegurar(unittest.TestCase):
    """Cada atalho passa a própria combinação: é dela a tecla que a pessoa segura."""

    ATALHOS: ClassVar[dict] = {
        "on_voice_hotkey": ("transcribe", "ctrl+alt+d"),
        "on_translate_hotkey": ("translate", "ctrl+alt+space"),
        "on_prompt_hotkey": ("prompt", "ctrl+alt+p"),
        "on_send_hotkey": ("send", "ctrl+shift+enter"),
        "on_transform_hotkey": ("transform", "ctrl+alt+t"),
    }

    def test_handlers_passam_a_combinacao_deles(self):
        config = SimpleNamespace(groq_api_key="gsk_x", hotkey="ctrl+alt+d", translate_hotkey="ctrl+alt+space",
                                 prompt_hotkey="ctrl+alt+p", send_hotkey="ctrl+shift+enter",
                                 transform_hotkey="ctrl+alt+t")
        for nome, (modo_esperado, combo) in self.ATALHOS.items():
            with self.subTest(handler=nome):
                threading = MagicMock()
                audio = SimpleNamespace(is_processing=False, is_awake=True, is_recording=False)

                iniciados = []

                def _iniciar(modo="transcribe", atalho=None, _audio=audio, _iniciados=iniciados):
                    _iniciados.append((modo, atalho))
                    _audio.is_recording, _audio.recording_mode = True, modo

                handler = _funcao_do_willy(
                    nome, threading=threading, config_mgr=config, monitorar_hold="monitorar_hold",
                    audio_mgr=audio, iniciar_gravacao=_iniciar, parar_gravacao=MagicMock(), sound_mgr=MagicMock(),
                    atualizar_ui=MagicMock(), dashboard=None, safe_dispatch_ui=MagicMock(),
                    ActionManager=SimpleNamespace(get_selected_text=lambda: "contrato",
                                                  esperar_modificadores_soltos=lambda: True))
                handler()
                kwargs = threading.Thread.call_args.kwargs
                self.assertEqual("monitorar_hold", kwargs["target"])
                self.assertEqual((combo,), kwargs["args"])
                threading.Thread.return_value.start.assert_called_once_with()
                # A mesma combinação e o modo exato vão para iniciar_gravacao (mata A3, T1, T7).
                self.assertEqual([(modo_esperado, combo)], iniciados)


class TestSegurarOTransformar(unittest.TestCase):
    """Ctrl+Alt+T segurado: com o Alt preso, o Ctrl+C não copia (e no ABNT2 digitaria "₢"). A
    seleção fica para o pipeline, que a lê quando a gravação termina."""

    def _apertar(self, soltou_a_tempo=True, selecao="contrato", gravando=None):
        self.audio = SimpleNamespace(is_awake=True, is_recording=gravando is not None, recording_mode=gravando)
        self.ler, self.threading, self.ui = MagicMock(return_value=selecao), MagicMock(), MagicMock()

        def _iniciar(modo="transcribe", atalho=None):
            if not self.audio.is_recording:  # como o de verdade: com gravação em curso, nada
                self.audio.is_recording, self.audio.recording_mode = True, modo

        handler = _funcao_do_willy(
            "on_transform_hotkey", audio_mgr=self.audio, threading=self.threading, iniciar_gravacao=_iniciar,
            ActionManager=SimpleNamespace(get_selected_text=self.ler,
                                          esperar_modificadores_soltos=lambda: soltou_a_tempo),
            parar_gravacao=MagicMock(), sound_mgr=MagicMock(), atualizar_ui=self.ui, monitorar_hold="monitorar_hold",
            config_mgr=SimpleNamespace(transform_hotkey="ctrl+alt+t"), selected_text_for_transform="de antes")
        handler()
        self.guardada = handler.__globals__["selected_text_for_transform"]

    def test_toque_le_a_selecao_na_hora(self):
        self._apertar()
        self.ler.assert_called_once_with()
        self.assertEqual("contrato", self.guardada)
        self.threading.Thread.assert_called_once()

    def test_segurando_nao_le_e_deixa_para_o_pipeline(self):
        self._apertar(soltou_a_tempo=False)
        self.ler.assert_not_called()
        self.assertIsNone(self.guardada)
        self.assertEqual("transform", self.audio.recording_mode)
        self.threading.Thread.assert_called_once()

    def test_toque_sem_selecao_avisa_e_nao_grava(self):
        self._apertar(selecao="")
        self.assertFalse(self.audio.is_recording)
        self.ui.assert_called_once_with("warning", "Selecione um texto antes de transformar")

    def test_no_meio_de_uma_reuniao_nao_vigia_a_reuniao(self):
        # O monitor guardaria a sessão da reunião, e segurar e soltar o T a encerrava.
        self._apertar(gravando="meeting")
        # AUD-004: nem lê seleção (Ctrl+C) nem sobrescreve selected_text_for_transform
        self.ler.assert_not_called()
        self.assertEqual("de antes", self.guardada)
        self.threading.Thread.assert_not_called()

    def test_guarda_de_prontidao_no_transform_hotkey(self):
        """AUD-004: on_transform_hotkey respeita is_processing, is_awake (com som/dica) e groq_api_key antes de Ctrl+C."""
        ler = MagicMock(return_value="novo")
        som, ui = MagicMock(), MagicMock()
        h_proc = _funcao_do_willy(
            "on_transform_hotkey",
            audio_mgr=SimpleNamespace(is_processing=True, is_awake=True, is_recording=False),
            config_mgr=SimpleNamespace(groq_api_key="gsk_ok", transform_hotkey="ctrl+alt+t"),
            sound_mgr=som, atualizar_ui=ui, dashboard=None, safe_dispatch_ui=MagicMock(),
            ActionManager=SimpleNamespace(get_selected_text=ler, esperar_modificadores_soltos=lambda: True),
            iniciar_gravacao=MagicMock(), parar_gravacao=MagicMock(), threading=MagicMock(),
            monitorar_hold="monitorar_hold", selected_text_for_transform="preservado",
        )
        h_proc()
        ler.assert_not_called()
        self.assertEqual("preservado", h_proc.__globals__["selected_text_for_transform"])

        h_sleep = _funcao_do_willy(
            "on_transform_hotkey",
            audio_mgr=SimpleNamespace(is_processing=False, is_awake=False, is_recording=False),
            config_mgr=SimpleNamespace(groq_api_key="gsk_ok", transform_hotkey="ctrl+alt+t"),
            sound_mgr=som, atualizar_ui=ui, dashboard=None, safe_dispatch_ui=MagicMock(),
            ActionManager=SimpleNamespace(get_selected_text=ler, esperar_modificadores_soltos=lambda: True),
            iniciar_gravacao=MagicMock(), parar_gravacao=MagicMock(), threading=MagicMock(),
            monitorar_hold="monitorar_hold", selected_text_for_transform="preservado",
        )
        h_sleep()
        ler.assert_not_called()
        som.sound_error.assert_called_once_with()
        ui.assert_called_once_with("sleeping_hint")

        som.reset_mock()
        ui.reset_mock()
        dash = MagicMock()
        h_sem_chave = _funcao_do_willy(
            "on_transform_hotkey",
            audio_mgr=SimpleNamespace(is_processing=False, is_awake=True, is_recording=False),
            config_mgr=SimpleNamespace(groq_api_key="sua_chave_aqui", transform_hotkey="ctrl+alt+t"),
            sound_mgr=som, atualizar_ui=ui, dashboard=dash, safe_dispatch_ui=lambda fn: fn(),
            ActionManager=SimpleNamespace(get_selected_text=ler, esperar_modificadores_soltos=lambda: True),
            iniciar_gravacao=MagicMock(), parar_gravacao=MagicMock(), threading=MagicMock(),
            monitorar_hold="monitorar_hold", selected_text_for_transform="preservado",
        )
        h_sem_chave()
        ler.assert_not_called()
        som.sound_error.assert_called_once_with()
        ui.assert_called_once_with("error", "Configure sua chave Groq")
        dash.mostrar.assert_called_once_with()
        dash.mudar_aba.assert_called_once_with("settings")

    def test_modo_transform_no_cronometro_manual_e_cor_das_barras(self):
        """AUD-005 e AUD-063: callback_audio no modo manual e FloatingPill.cor_das_barras suportam 'transform'."""
        from ui.overlays.pill import FloatingPill
        from ui.theme import FLUTUANTE_CIANO, FLUTUANTE_LARANJA, FLUTUANTE_LILAS, FLUTUANTE_ROXO, FLUTUANTE_VERDE

        self.assertEqual(FLUTUANTE_LILAS, FloatingPill.cor_das_barras(0.1, "transform"))

        pill = MagicMock()
        audio = SimpleNamespace(
            is_recording=True, is_awake=True, recording_mode="transform",
            recording_start_time=100.0, last_status_msg="", ambient_noise_floor=0.005,
            actual_sample_rate=16000, sample_rate=16000, _last_wf_time=105.0,
            append_audio=MagicMock(), compute_rms=lambda _d: 0.02, update_noise_floor=MagicMock(),
        )
        cb = _funcao_do_willy(
            "callback_audio",
            audio_mgr=audio, config_mgr=SimpleNamespace(auto_silence=False, wake_word_enabled=False),
            pill=pill, safe_dispatch_ui=lambda fn, *a: fn(*a), time=SimpleNamespace(time=lambda: 105.0),
            FLUTUANTE_LILAS=FLUTUANTE_LILAS, FLUTUANTE_ROXO=FLUTUANTE_ROXO,
            FLUTUANTE_VERDE=FLUTUANTE_VERDE, FLUTUANTE_CIANO=FLUTUANTE_CIANO,
            FLUTUANTE_LARANJA=FLUTUANTE_LARANJA,
        )
        cb(b"\x00\x00" * 160, 160, None, None)
        pill.update_status_text.assert_called_once_with(
            "🪄 Transformar Manual... 00:05 (Pressione atalho p/ enviar)",
            FLUTUANTE_LILAS,
        )


class TestCtrlK(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls.dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list})
        cls.dash.withdraw()
        fim = time.time() + 0.4  # a aba Histórico religava o Ctrl+K 100 ms depois de montar
        while time.time() < fim:
            cls.dash.update()
            time.sleep(0.01)

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def test_o_ctrl_k_continua_com_o_dashboard(self):
        for sequencia in ("<Control-k>", "<Control-K>"):
            with self.subTest(sequencia=sequencia):
                self.assertIn("_on_global_ctrl_k", self.dash.bind(sequencia))

    def test_na_aba_templates_foca_a_busca_dos_templates(self):
        self.dash.mudar_aba("snippets")
        with patch.object(self.dash.tab_templates.search_field, "focus") as templates, \
             patch.object(self.dash.tab_history.search_field, "focus") as historico:
            self.assertEqual("break", self.dash._on_global_ctrl_k())
        templates.assert_called_once_with()
        historico.assert_not_called()
        self.assertEqual("snippets", self.dash.active_tab)


if __name__ == "__main__":
    unittest.main()
