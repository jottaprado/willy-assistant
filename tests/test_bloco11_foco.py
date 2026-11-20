"""
Bloco 11, item 2: para onde vai o texto do ditado, e o foco devolvido a essa janela.

- iniciar_gravacao guardava só (exe, título, categoria): a entrega colava onde o foco estivesse
  no fim, e só a janela fixada era trazida de volta.
- focus_window era um SetForegroundWindow puro, que o Windows recusa a quem não é o processo da
  frente (o foreground lock).
- O ditado que terminava com o painel do Willy na frente colava dentro dele.
- A pílula ia para o monitor do painel do Willy ou da barra de tarefas.

Agora o alvo é resolvido no começo (a fixada; a janela da frente, se for de fora do Willy e do
shell; com eles na frente, a de fora sob o cursor e depois a última de fora), com o controle em
que a pessoa digitava (GetGUIThreadInfo). Na entrega, ela volta à frente com as filas de entrada
ligadas (AttachThreadInput), e o Ctrl+V só sai com ela na frente. Sem alvo, com o foco no Willy,
ou sem conseguir voltar: copia e avisa.

Nada aqui muda o primeiro plano de verdade: o user32 é falso, menos nos protótipos.
"""

import ast
import ctypes
import os
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, patch

import core.context as context_mod
from core.context import GUITHREADINFO, ContextManager
from core.pipeline import transcription_pipeline as pipeline_mod
from core.pipeline.transcription_pipeline import PipelineContext, TranscriptionPipeline
from tests.test_pilula_monitor_e_foco import (
    AREA_ESQUERDA,
    AREA_PRIMARIO,
    HWND_FIREFOX,
    HWND_PILULA,
)
from tests.test_pilula_monitor_e_foco import User32Falso as User32DaPilula
from tests.willy_isolado import _funcoes_do_willy, destruir_tk
from ui.overlays import pill as pill_mod
from ui.overlays.pill import FloatingPill

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EU, TID_FRENTE, TID_APP = 1, 20, 30
APP, CAMPO, OUTRO, CAMPO_DO_OUTRO, WILLY, BARRA = 0x1A0, 0x1A1, 0x2B0, 0x2B1, 0x3C0, 0x4D0


class User32Falso:
    """O pedaço do user32 que o ContextManager usa para trocar o foco, com chamadas registradas."""

    def __init__(self, frente=OUTRO, minimizada=False, aceita=True, chega=True, liga=True):
        self.frente, self.minimizada, self.aceita, self.chega, self.liga = frente, minimizada, aceita, chega, liga
        self.existem = {APP, CAMPO, OUTRO, CAMPO_DO_OUTRO, WILLY, BARRA}
        self.tids = {APP: TID_APP, CAMPO: TID_APP, OUTRO: TID_FRENTE, CAMPO_DO_OUTRO: TID_FRENTE}
        self.raiz = {CAMPO: APP, CAMPO_DO_OUTRO: OUTRO}
        self.foco_da_thread = {TID_APP: (CAMPO, 0)}  # tid -> (hwndFocus, hwndCaret)
        self.cursor, self.sob_o_cursor = (100, 200), CAMPO
        self.chamadas = []
        self.erro_no_set_foreground = None
        self.travadas = set()

    def IsWindow(self, h):
        return int(h in self.existem)

    def IsHungAppWindow(self, h):
        return int(h in self.travadas)

    def GetForegroundWindow(self):
        return self.frente

    def GetWindowThreadProcessId(self, h, _pid):
        return self.tids.get(h, 0)

    def AttachThreadInput(self, de, para, ligar):
        self.chamadas.append(("Attach", de, para, bool(ligar)))
        return int(self.liga)

    def IsIconic(self, h):
        return int(self.minimizada)

    def ShowWindow(self, h, cmd):
        self.chamadas.append(("ShowWindow", h, cmd))
        return 1

    def BringWindowToTop(self, h):
        self.chamadas.append(("BringWindowToTop", h))
        return 1

    def SetForegroundWindow(self, h):
        self.chamadas.append(("SetForegroundWindow", h))
        if self.erro_no_set_foreground:
            raise self.erro_no_set_foreground
        if self.aceita and self.chega:
            self.frente = h
        return int(self.aceita)

    def GetAncestor(self, h, flag):
        assert flag == 2  # GA_ROOT
        return self.raiz.get(h, h)

    def SetFocus(self, h):
        self.chamadas.append(("SetFocus", h))
        return 0

    def GetGUIThreadInfo(self, tid, ref):
        info = ref._obj
        assert info.cbSize == ctypes.sizeof(GUITHREADINFO)
        if tid not in self.foco_da_thread:
            return 0
        info.hwndFocus, info.hwndCaret = self.foco_da_thread[tid]
        return 1

    def GetCursorPos(self, ref):
        ref._obj.x, ref._obj.y = self.cursor
        return 1

    def WindowFromPoint(self, ponto):
        self.chamadas.append(("WindowFromPoint", ponto.x, ponto.y))
        return self.sob_o_cursor


class Relogio:
    def __init__(self):
        self.agora = 0.0
        self.ao_dormir = None

    def monotonic(self):
        return self.agora

    def sleep(self, s):
        self.agora += s
        if self.ao_dormir:
            self.ao_dormir()


class _BaseUser32(unittest.TestCase):
    def setUp(self):
        self.u = User32Falso()
        self.relogio = Relogio()
        for nome, valor in (("user32", self.u), ("kernel32", SimpleNamespace(GetCurrentThreadId=lambda: EU)),
                            ("time", self.relogio)):
            p = patch.object(context_mod, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(context_mod.sys, "platform", "win32")
        p.start()
        self.addCleanup(p.stop)


# --------------------------------------------------------------------------- focus_window
class TestFocusWindow(_BaseUser32):
    def test_liga_as_filas_traz_para_a_frente_devolve_o_campo_e_solta(self):
        self.assertTrue(ContextManager.focus_window(APP, CAMPO))
        self.assertEqual([
            ("Attach", EU, TID_FRENTE, True), ("Attach", EU, TID_APP, True),
            ("BringWindowToTop", APP), ("SetForegroundWindow", APP), ("SetFocus", CAMPO),
            ("Attach", EU, TID_FRENTE, False), ("Attach", EU, TID_APP, False),
        ], self.u.chamadas)
        self.assertEqual(APP, self.u.frente)

    def test_minimizada_e_restaurada_antes(self):
        self.u.minimizada = True
        ContextManager.focus_window(APP)
        nomes = [c[0] for c in self.u.chamadas]
        self.assertEqual(("ShowWindow", APP, 9), self.u.chamadas[nomes.index("ShowWindow")])
        self.assertLess(nomes.index("ShowWindow"), nomes.index("SetForegroundWindow"))

    def test_sem_minimizar_nao_mexe_no_tamanho(self):
        ContextManager.focus_window(APP)
        self.assertNotIn("ShowWindow", [c[0] for c in self.u.chamadas])

    def test_campo_de_outra_janela_fechado_ou_nenhum_nao_recebe_o_foco(self):
        self.u.existem.discard(CAMPO)
        for campo in (CAMPO_DO_OUTRO, CAMPO, None, 0):
            with self.subTest(campo=campo):
                self.u.chamadas.clear()
                ContextManager.focus_window(APP, campo)
                self.assertNotIn("SetFocus", [c[0] for c in self.u.chamadas])

    def test_solta_as_filas_mesmo_quando_a_troca_quebra(self):
        self.u.erro_no_set_foreground = OSError("acesso negado")
        self.assertFalse(ContextManager.focus_window(APP, CAMPO))
        soltas = [c for c in self.u.chamadas if c[0] == "Attach" and not c[3]]
        self.assertEqual([("Attach", EU, TID_FRENTE, False), ("Attach", EU, TID_APP, False)], soltas)

    def test_so_solta_o_que_ligou(self):
        self.u.liga = False
        ContextManager.focus_window(APP)
        self.assertEqual([], [c for c in self.u.chamadas if c[0] == "Attach" and not c[3]])

    def test_nao_liga_a_propria_thread_nem_duas_vezes(self):
        self.u.tids[APP] = EU
        ContextManager.focus_window(APP)
        self.assertEqual([("Attach", EU, TID_FRENTE, True), ("Attach", EU, TID_FRENTE, False)],
                         [c for c in self.u.chamadas if c[0] == "Attach"])
        self.u.chamadas.clear()
        self.u.tids[APP] = TID_FRENTE
        ContextManager.focus_window(APP)
        self.assertEqual(2, len([c for c in self.u.chamadas if c[0] == "Attach"]))

    def test_janela_fechada_ou_zero_nao_tenta(self):
        self.u.existem.discard(APP)
        self.assertFalse(ContextManager.focus_window(APP))
        self.assertFalse(ContextManager.focus_window(0))
        self.assertEqual([], self.u.chamadas)

    def test_com_prazo_espera_a_janela_chegar_a_frente(self):
        self.u.chega = False
        def _chega_depois():
            if self.relogio.agora >= 0.1:
                self.u.frente = APP
        self.relogio.ao_dormir = _chega_depois
        self.assertTrue(ContextManager.focus_window(APP, prazo_s=0.6))
        self.assertLess(self.relogio.agora, 0.2)

    def test_com_prazo_desiste_se_nao_chega(self):
        self.u.chega = False
        self.assertFalse(ContextManager.focus_window(APP, prazo_s=0.6))
        self.assertGreaterEqual(self.relogio.agora, 0.6)

    def test_sem_prazo_vale_o_que_o_windows_disse(self):
        self.u.aceita = False
        self.assertFalse(ContextManager.focus_window(APP))


class TestOndeEstaOFoco(_BaseUser32):
    def test_o_controle_com_o_foco_do_teclado(self):
        self.assertEqual(CAMPO, ContextManager.foco_do_teclado(APP))

    def test_sem_foco_vale_o_cursor_de_texto(self):
        self.u.foco_da_thread[TID_APP] = (0, CAMPO)
        self.assertEqual(CAMPO, ContextManager.foco_do_teclado(APP))

    def test_com_os_dois_vale_o_foco_do_teclado(self):
        self.u.raiz[0x1A2] = APP  # outro controle da mesma janela, com o cursor de texto
        self.u.foco_da_thread[TID_APP] = (CAMPO, 0x1A2)
        self.assertEqual(CAMPO, ContextManager.foco_do_teclado(APP))

    def test_foco_em_outra_janela_ou_sem_informacao_e_zero(self):
        self.u.foco_da_thread[TID_APP] = (CAMPO_DO_OUTRO, 0)
        self.assertEqual(0, ContextManager.foco_do_teclado(APP))
        del self.u.foco_da_thread[TID_APP]
        self.assertEqual(0, ContextManager.foco_do_teclado(APP))
        self.assertEqual(0, ContextManager.foco_do_teclado(0))

    def test_janela_sob_o_cursor_e_a_de_topo(self):
        self.assertEqual(APP, ContextManager.janela_sob_o_cursor())
        self.assertIn(("WindowFromPoint", 100, 200), self.u.chamadas)
        self.u.sob_o_cursor = 0
        self.assertEqual(0, ContextManager.janela_sob_o_cursor())


# --------------------------------------------------------------------------- o alvo
class TestResolverJanelaAlvo(unittest.TestCase):
    def setUp(self):
        self.frente, self.sob, self.fixada = APP, OUTRO, None
        self.de_fora = {APP, OUTRO}
        for nome, efeito in (("get_sticky_window", lambda: self.fixada),
                             ("get_foreground_hwnd", lambda: self.frente),
                             ("janela_sob_o_cursor", lambda: self.sob),
                             ("janela_externa", lambda h: h in self.de_fora),
                             ("foco_do_teclado", lambda h: {APP: CAMPO, OUTRO: CAMPO_DO_OUTRO}.get(h, 0))):
            p = patch.object(ContextManager, nome, side_effect=efeito)
            p.start()
            self.addCleanup(p.stop)

    def test_a_da_frente_com_o_campo(self):
        self.assertEqual((APP, CAMPO), ContextManager.resolver_janela_alvo((OUTRO, CAMPO_DO_OUTRO)))

    def test_a_fixada_vem_antes_de_tudo(self):
        self.fixada = (0x999, "chat")
        self.assertEqual((0x999, 0), ContextManager.resolver_janela_alvo())

    def test_willy_na_frente_vale_a_de_fora_sob_o_cursor(self):
        self.frente = WILLY
        self.assertEqual((OUTRO, 0), ContextManager.resolver_janela_alvo((APP, CAMPO)))

    def test_shell_na_frente_e_willy_sob_o_cursor_vale_a_de_antes(self):
        self.frente, self.sob = BARRA, WILLY
        self.assertEqual((APP, CAMPO), ContextManager.resolver_janela_alvo((APP, CAMPO)))

    def test_nenhuma_de_fora(self):
        self.frente, self.sob = WILLY, BARRA
        self.assertEqual((0, 0), ContextManager.resolver_janela_alvo((0, 0)))
        self.de_fora.discard(APP)  # a de antes foi fechada
        self.assertEqual((0, 0), ContextManager.resolver_janela_alvo((APP, CAMPO)))


class TestJanelaExterna(unittest.TestCase):
    def test_existe_e_nao_e_do_willy_nem_do_shell(self):
        with patch.object(ContextManager, "janela_existe", side_effect=lambda h: h != 0x777), \
             patch.object(ContextManager, "eh_janela_do_willy", side_effect=lambda h: h == WILLY), \
             patch.object(ContextManager, "eh_janela_do_shell", side_effect=lambda h: h == BARRA):
            self.assertEqual([True, False, False, False],
                             [ContextManager.janela_externa(h) for h in (APP, WILLY, BARRA, 0x777)])


@unittest.skipUnless(sys.platform == "win32", "Win32 de verdade")
class TestPrototiposDeVerdade(unittest.TestCase):
    """Os protótipos de 64 bits: um HWND acima de 32 bits passa sem ser cortado nem quebrar."""

    GRANDE = 0x1_0000_0000

    def test_as_funcoes_novas_aceitam_hwnd_de_64_bits(self):
        self.assertEqual(0, ContextManager.foco_do_teclado(self.GRANDE))
        self.assertFalse(ContextManager.focus_window(self.GRANDE, self.GRANDE))
        self.assertFalse(ContextManager.janela_existe(self.GRANDE))
        self.assertIsInstance(ContextManager.janela_sob_o_cursor(), int)
        self.assertIs(context_mod.user32.GetGUIThreadInfo.restype, ctypes.wintypes.BOOL)
        self.assertEqual([ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL],
                         context_mod.user32.AttachThreadInput.argtypes)

    def test_o_app_de_uma_janela_dada_e_nao_o_da_frente(self):
        # O nome da janela fixada pelo Ctrl+Alt+F com o painel na frente é o da janela de antes.
        raiz = tk.Tk()
        try:
            raiz.title("Janela de teste do Willy")
            raiz.withdraw()
            raiz.update()
            hwnd = int(raiz.wm_frame(), 16)
            exe, titulo, _categoria = ContextManager.get_foreground_app(hwnd)
            self.assertEqual(os.path.basename(sys.executable).lower(), exe)
            self.assertEqual("Janela de teste do Willy", titulo)
        finally:
            destruir_tk(raiz)

    def test_o_foco_desta_thread(self):
        # A janela de verdade, sem mudar o primeiro plano: a thread dela tem um foco legível.
        raiz = tk.Tk()
        try:
            raiz.withdraw()
            raiz.update()
            hwnd = int(raiz.wm_frame(), 16)
            self.assertIsInstance(ContextManager.foco_do_teclado(hwnd), int)
        finally:
            destruir_tk(raiz)


# --------------------------------------------------------------------------- a entrega
class TestEntregaNaJanelaAlvo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.eventos = []
        self.groq = MagicMock()
        self.groq.transcribe.return_value = "texto ditado"
        self.groq.refine_text.side_effect = lambda texto, **_k: texto
        self.config = MagicMock()
        self.config.groq_api_key = "gsk_teste"
        self.config.clipboard_only = False
        self.config.private_mode = True  # nada vai para o disco
        self.config.clean_fillers = False
        self.config.load_replacements.return_value = {}
        snippet = MagicMock()
        snippet.match_and_expand.return_value = None
        self.injector = MagicMock()
        self.injector.paste_text.side_effect = lambda texto, **_k: self.eventos.append(("colar", texto)) or True
        self.ui = []
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq, config_mgr=self.config, audio_mgr=MagicMock(is_processing=False),
            injector=self.injector, sound_mgr=MagicMock(), snippet_mgr=snippet, tts_mgr=MagicMock(),
            ui_notifier=lambda st, msg=None: self.ui.append((st, msg)),
            failed_audio_path=os.path.join(self.tmp, "avulso.wav"), user_data_dir=self.tmp)
        self.frente, self.existem, self.foco_aceito, self.fixada, self.no_willy = OUTRO, {APP, OUTRO}, True, None, False
        self.no_shell = False
        cm = "core.pipeline.transcription_pipeline.ContextManager"
        self.focar = MagicMock(side_effect=self._focar)
        for alvo, efeito in ((f"{cm}.get_sticky_window", lambda: self.fixada),
                             (f"{cm}.get_foreground_hwnd", lambda: self.frente),
                             (f"{cm}.janela_existe", lambda h: h in self.existem),
                             ("core.pipeline.transcription_pipeline._foco_numa_janela_do_willy", lambda: self.no_willy),
                             ("core.pipeline.transcription_pipeline._foco_no_shell", lambda: self.no_shell)):
            p = patch(alvo, side_effect=efeito)
            p.start()
            self.addCleanup(p.stop)
        p = patch(f"{cm}.focus_window", self.focar)
        p.start()
        self.addCleanup(p.stop)
        self.copiar = patch.object(pipeline_mod.ActionManager, "secure_copy",
                                   side_effect=lambda t, **_k: self.eventos.append(("copiar", t)) or True)
        self.copiar.start()
        self.addCleanup(self.copiar.stop)

    def _focar(self, hwnd, foco=None, prazo_s=0.0):
        self.eventos.append(("focar", hwnd, foco, prazo_s))
        if self.foco_aceito:
            self.frente = hwnd
            self.no_willy = False
        return self.foco_aceito

    def _rodar(self, alvo=(APP, CAMPO), retry_path=None):
        return self.pipeline.process(PipelineContext(
            wav_bytes=b"RIFFfala", modo="transcribe", app_context=("code.exe", "editor", "general"),
            janela_alvo=alvo[0], foco_alvo=alvo[1], is_retry=retry_path is not None, retry_path=retry_path))

    def test_traz_o_alvo_com_o_campo_antes_de_colar(self):
        res = self._rodar()
        self.assertEqual("paste", res.action_type)
        self.assertEqual([("focar", APP, CAMPO, pipeline_mod._ESPERA_DO_FOCO_S), ("colar", "Texto ditado")],
                         self.eventos)

    def test_alvo_ja_na_frente_nao_mexe_no_foco(self):
        self.frente = APP
        self._rodar()
        self.focar.assert_not_called()
        self.assertEqual([("colar", "Texto ditado")], self.eventos)

    def test_com_o_painel_do_willy_na_frente_volta_ao_alvo(self):
        self.frente, self.no_willy = WILLY, True
        self._rodar()
        self.assertEqual(["focar", "colar"], [e[0] for e in self.eventos])

    def test_alvo_que_nao_volta_copia_e_avisa(self):
        self.foco_aceito = False
        res = self._rodar()
        self.assertEqual("copy", res.action_type)
        self.assertNotIn("colar", [e[0] for e in self.eventos])
        self.assertIn(("copiar", "Texto ditado"), self.eventos)
        self.assertIn(("success", "Não voltei ao app: copiado, cole com Ctrl+V"), self.ui)

    def test_sem_alvo_e_com_o_foco_no_willy_copia(self):
        self.frente, self.no_willy = WILLY, True
        res = self._rodar(alvo=(0, 0))
        self.assertEqual("copy", res.action_type)
        self.focar.assert_not_called()
        self.assertIn(("success", "Copiado: cole onde quiser 📋"), self.ui)

    def test_sem_alvo_e_fora_do_willy_cola_onde_esta(self):
        self._rodar(alvo=(0, 0))
        self.focar.assert_not_called()
        self.assertEqual([("colar", "Texto ditado")], self.eventos)

    def test_alvo_fechado_durante_a_transcricao(self):
        self.existem.discard(APP)
        self.no_willy = True
        self.assertEqual("copy", self._rodar().action_type)
        self.focar.assert_not_called()
        self.no_willy = False
        self.eventos.clear()
        self.assertEqual("paste", self._rodar().action_type)

    def test_a_fixada_ganha_do_alvo(self):
        self.fixada = (OUTRO, "chat")
        self.frente = APP
        self._rodar()
        self.assertEqual(("focar", OUTRO, None, pipeline_mod._ESPERA_DO_FOCO_S), self.eventos[0])

    def test_sem_alvo_e_com_o_shell_na_frente_copia(self):
        # A reunião que termina com a área de trabalho na frente: o Ctrl+V não chegaria a app
        # nenhum, e o clipboard voltaria ao de antes (juiz do Bloco 11, 2ª rodada).
        self.no_shell = True
        res = self._rodar(alvo=(0, 0))
        self.assertEqual("copy", res.action_type)
        self.assertIn(("success", "Copiado: cole onde quiser 📋"), self.ui)

    def test_a_fixada_vale_com_o_shell_na_frente(self):
        self.fixada, self.no_shell = (OUTRO, "chat"), True
        self.frente = BARRA
        self.assertEqual("paste", self._rodar(alvo=(0, 0)).action_type)
        self.assertEqual(("focar", OUTRO, None, pipeline_mod._ESPERA_DO_FOCO_S), self.eventos[0])

    def test_com_alvo_o_shell_na_frente_nao_impede_de_colar(self):
        self.no_shell = True
        self.assertEqual("paste", self._rodar().action_type)
        self.assertEqual(["focar", "colar"], [e[0] for e in self.eventos])

    def test_so_copiar_nao_mexe_no_foco(self):
        self.config.clipboard_only = True
        self.frente, self.no_willy = WILLY, True
        self.assertEqual("copy", self._rodar().action_type)
        self.focar.assert_not_called()
        self.assertIn(("success", "Copiado p/ Área de Transferência! 📋"), self.ui)

    def test_nunca_cola_com_o_foco_no_willy(self):
        """Toda combinação: se o Ctrl+V saiu, o foco não estava numa janela do Willy."""
        for alvo in ((APP, CAMPO), (0, 0)):
            for foco_aceito in (True, False):
                for frente in (WILLY, OUTRO, APP):
                    with self.subTest(alvo=alvo, foco_aceito=foco_aceito, frente=frente):
                        self.eventos.clear()
                        self.frente, self.no_willy, self.foco_aceito = frente, frente == WILLY, foco_aceito
                        no_willy_ao_colar = []
                        self.injector.paste_text.side_effect = lambda t, _lista=no_willy_ao_colar, **_k: _lista.append(self.no_willy) or True
                        self._rodar(alvo=alvo)
                        self.assertNotIn(True, no_willy_ao_colar)


# --------------------------------------------------------------------------- willy.py
class TestWillyGuardaOAlvo(unittest.TestCase):
    def _iniciar(self):
        return self._iniciar_no_modo("transcribe")

    def _iniciar_no_modo(self, modo):
        self.ordem = []
        contexto = SimpleNamespace(
            get_foreground_app=lambda: ("code.exe", "editor", "CODING"),
            resolver_janela_alvo=lambda antes: self.ordem.append(("resolver", antes)) or (APP, CAMPO))
        self.pilula = SimpleNamespace(janela_alvo=0)
        audio = SimpleNamespace(is_recording=False, is_processing=False, is_awake=True, system_device_index=None,
                                ensure_stream=lambda cb: True,
                                start_recording=lambda modo: self.ordem.append(("gravar", modo)) or True)
        escopo = _funcoes_do_willy(
            "iniciar_gravacao", Optional=Optional, audio_mgr=audio, ContextManager=contexto, pill=self.pilula,
            _janela_antes_do_willy=OUTRO, _foco_antes_do_willy=CAMPO_DO_OUTRO, current_app_context=None,
            _alvo_da_gravacao=(0, 0), callback_audio=None, sound_mgr=MagicMock(),
            atualizar_ui=lambda *a: self.ordem.append(("ui", self.pilula.janela_alvo) + a),
            hotkey_mgr=MagicMock(), Win32HotKeyManager=MagicMock(com_os_modificadores_de=lambda *a: None),
            _ATALHO_DO_CANCELAR=1, _ATALHO_DO_CANCELAR_SEGURANDO=2, cancelar_por_esc=None,
            _soltar_esc_sem_gravacao=MagicMock(), config_mgr=SimpleNamespace(auto_silence=True))
        escopo["iniciar_gravacao"](modo, None if modo == "meeting" else "ctrl+space")
        return escopo

    def test_a_reuniao_nao_tem_janela_alvo(self):
        # 30 min, 1 h depois, a janela do começo trazida de volta receberia a ata no campo que
        # tivesse o foco nela (o chat da reunião; juiz do Bloco 11, 1ª rodada). A ata vai para
        # onde o foco estiver quando ela sai.
        escopo = self._iniciar_no_modo("meeting")
        self.assertEqual((0, 0), escopo["_alvo_da_gravacao"])
        self.assertEqual(0, self.pilula.janela_alvo)
        self.assertNotIn("resolver", [e[0] for e in self.ordem])

    def test_resolve_o_alvo_no_comeco_com_a_ultima_janela_de_fora(self):
        escopo = self._iniciar()
        self.assertEqual((APP, CAMPO), escopo["_alvo_da_gravacao"])
        self.assertEqual(("resolver", (OUTRO, CAMPO_DO_OUTRO)), self.ordem[0])
        # A pílula já sabe o alvo quando aparece ("ouvindo"), para ir ao monitor dele.
        self.assertEqual(("ui", APP, "listening"), next(e for e in self.ordem if e[0] == "ui"))

    def _executar(self, alvo_global, modo="translate", **kw):
        pipeline = MagicMock()
        escopo = _funcoes_do_willy(
            "_executar_pipeline_transcricao", Optional=Optional, Tuple=tuple,
            config_mgr=SimpleNamespace(groq_api_key="gsk_x"), transcription_pipeline=pipeline, dashboard=None,
            safe_dispatch_ui=MagicMock(), PipelineContext=PipelineContext, current_app_context=None,
            selected_text_for_transform="", sincronizar_bandeja=MagicMock(), _alvo_da_gravacao=alvo_global)
        escopo["_executar_pipeline_transcricao"](b"RIFF", modo, **kw)
        return pipeline.process.call_args.args[0]

    def test_o_pipeline_recebe_o_alvo_da_gravacao(self):
        ctx = self._executar((APP, CAMPO), modo="translate")
        self.assertEqual("translate", ctx.modo)
        self.assertEqual((APP, CAMPO), (ctx.janela_alvo, ctx.foco_alvo))

    def test_o_alvo_dado_ganha_do_da_gravacao(self):
        ctx = self._executar((APP, CAMPO), is_retry=True, retry_path="x.wav", alvo=(OUTRO, 0))
        self.assertEqual((OUTRO, 0), (ctx.janela_alvo, ctx.foco_alvo))

    def test_o_reenvio_resolve_o_alvo_de_agora(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        caminho = os.path.join(tmp, "20261027T100000.000000000Z_transcribe.wav")
        with open(caminho, "wb") as f:
            f.write(b"RIFF")
        # Todo modo menos a reunião: o reenvio de uma tradução ou de um prompt também tem alvo.
        for modo in ("transcribe", "send", "translate", "translate_es", "prompt", "transform"):
            with self.subTest(modo=modo):
                threads = []
                escopo = _funcoes_do_willy(
                    "reenviar_ultimo_audio",
                    transcription_pipeline=SimpleNamespace(fila=SimpleNamespace(mais_recente=lambda m=modo: (caminho, m))),
                    atualizar_ui=MagicMock(), _executar_pipeline_transcricao=None,
                    ContextManager=SimpleNamespace(resolver_janela_alvo=lambda antes: (antes[0], 0)),
                    _janela_antes_do_willy=APP, _foco_antes_do_willy=CAMPO,
                    threading=SimpleNamespace(Thread=lambda target, args, daemon, _t=threads: SimpleNamespace(start=lambda: _t.append(args))))
                escopo["reenviar_ultimo_audio"]()
                self.assertEqual((b"RIFF", modo, True, caminho, (APP, 0)), threads[0])

    def test_reusar_devolve_o_campo_de_antes(self):
        from tests.test_reusar_no_app_anterior import APP as APP_R
        from tests.test_reusar_no_app_anterior import WILLY as WILLY_R
        from tests.test_reusar_no_app_anterior import ContextoFalso
        from tests.test_reusar_no_app_anterior import Relogio as RelogioR
        contexto = ContextoFalso(primeiro_plano=WILLY_R)
        escopo = _funcoes_do_willy(
            "reusar_no_app_anterior", ContextManager=contexto, dashboard=MagicMock(), atualizar_ui=MagicMock(),
            sound_mgr=MagicMock(), default_injector=SimpleNamespace(paste_text=lambda *a, **k: True),
            time=RelogioR(), threading=SimpleNamespace(Thread=lambda target, daemon: SimpleNamespace(start=target)),
            ActionManager=MagicMock(), _janela_antes_do_willy=APP_R, _foco_antes_do_willy=0x55, last_injected_text=None)
        escopo["reusar_no_app_anterior"]("x")
        self.assertEqual(("foco", APP_R, 0x55), contexto.eventos[0])

    def test_a_pilula_recebe_quem_classifica_a_janela_da_frente(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        (chamada,) = [n for n in ast.walk(arvore) if isinstance(n, ast.Call)
                      and getattr(n.func, "id", None) == "FloatingPill"]
        argumento = {k.arg: k.value for k in chamada.keywords}["eh_do_willy_ou_do_shell"]
        self.assertEqual("lambda hwnd: ContextManager.eh_janela_do_willy(hwnd) or ContextManager.eh_janela_do_shell(hwnd)",
                         ast.unparse(argumento))


class TestDoJuizNoFoco(unittest.TestCase):
    """O que a 1ª rodada do juiz mutou sem que nenhum teste reprovasse, e o que ela achou."""

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "o layout de 64 bits")
    def test_a_struct_tem_o_layout_do_sdk(self):
        # Campos trocados de lugar leriam a janela ativa como a do foco, sem erro nenhum.
        self.assertEqual(72, ctypes.sizeof(GUITHREADINFO))
        self.assertEqual([("cbSize", 0), ("flags", 4), ("hwndActive", 8), ("hwndFocus", 16), ("hwndCapture", 24),
                          ("hwndMenuOwner", 32), ("hwndMoveSize", 40), ("hwndCaret", 48), ("rcCaret", 56)],
                         [(nome, getattr(GUITHREADINFO, nome).offset) for nome, _ in GUITHREADINFO._fields_])

    def test_o_reenvio_leva_o_campo_da_janela_de_antes(self):
        recebido = []
        escopo = _funcoes_do_willy(
            "reenviar_ultimo_audio",
            transcription_pipeline=SimpleNamespace(fila=SimpleNamespace(mais_recente=lambda: (__file__, "transcribe"))),
            atualizar_ui=MagicMock(), _executar_pipeline_transcricao=None,
            ContextManager=SimpleNamespace(resolver_janela_alvo=lambda antes: recebido.append(antes) or antes),
            _janela_antes_do_willy=APP, _foco_antes_do_willy=CAMPO,
            threading=SimpleNamespace(Thread=lambda target, args, daemon: SimpleNamespace(start=lambda: None)))
        escopo["reenviar_ultimo_audio"]()
        self.assertEqual([(APP, CAMPO)], recebido)

    def test_com_o_willy_na_frente_o_campo_de_antes_fica(self):
        from tests.test_reusar_no_app_anterior import APP as APP_R
        from tests.test_reusar_no_app_anterior import CAMPO as CAMPO_R
        from tests.test_reusar_no_app_anterior import WILLY as WILLY_R
        from tests.test_reusar_no_app_anterior import ContextoFalso
        contexto = ContextoFalso(primeiro_plano=APP_R)
        escopo = _funcoes_do_willy("lembrar_janela_fora_do_willy", ContextManager=contexto,
                                   _janela_antes_do_willy=0, _foco_antes_do_willy=0)
        escopo["lembrar_janela_fora_do_willy"]()
        contexto.primeiro_plano = WILLY_R  # é justamente com o Willy na frente que o campo de antes vale
        escopo["lembrar_janela_fora_do_willy"]()
        self.assertEqual((APP_R, CAMPO_R), (escopo["_janela_antes_do_willy"], escopo["_foco_antes_do_willy"]))


    def test_o_parar_leva_o_alvo_desta_gravacao(self):
        # Um ditado novo, começado noutro app enquanto este parava, trocava o alvo antes de a
        # thread do pipeline lê-lo (de 16 a 257 ms, conforme o tamanho do áudio).
        threads, escopo = [], {}

        def parar():
            escopo["willy"]["_alvo_da_gravacao"] = (OUTRO, 0)  # o ditado novo, no meio tempo
            return ("audio", "translate", 16000)

        escopo["willy"] = _funcoes_do_willy(
            "parar_gravacao", _alvo_da_gravacao=(APP, CAMPO), _soltar_esc=lambda: None, _soltar_esc_sem_gravacao=lambda: None,
            audio_mgr=SimpleNamespace(stop_recording_com_taxa=parar, ambient_noise_floor=0.0, gain_boost=1.0,
                                      pause_stream=lambda: None),
            config_mgr=SimpleNamespace(wake_word_enabled=True), processar_transcricao="processar",
            threading=SimpleNamespace(Thread=lambda target, args, daemon: SimpleNamespace(start=lambda: threads.append(args))))
        escopo["willy"]["parar_gravacao"]()
        self.assertEqual(("audio", "translate", 16000, 0.0, (APP, CAMPO)), threads[0])

    def test_processar_passa_o_alvo_ao_pipeline(self):
        recebido = []
        escopo = _funcoes_do_willy(
            "processar_transcricao", Optional=Optional, Tuple=tuple, atualizar_ui=MagicMock(), TAXA_WHISPER=16000,
            para_taxa_whisper=lambda a, t: a, condicionar_para_whisper=lambda a, *x, **k: a,
            audio_mgr=SimpleNamespace(convert_to_wav=lambda a, sample_rate: b"RIFF"),
            _executar_pipeline_transcricao=lambda wav, modo, **kw: recebido.append(kw.get("alvo")))
        escopo["processar_transcricao"]([0.0] * 16000, "transcribe", 16000, 0.0, (APP, CAMPO))
        self.assertEqual([(APP, CAMPO)], recebido)


class TestAppTravado(_BaseUser32):
    def test_nao_liga_a_fila_de_um_app_travado(self):
        # Com a fila dele ligada à desta thread, o SetFocus esperaria por ele, e a entrega junto.
        self.u.travadas.add(APP)
        self.assertFalse(ContextManager.focus_window(APP, CAMPO, prazo_s=0.6))
        self.assertEqual([], self.u.chamadas)


class TestFocoNoShell(unittest.TestCase):
    def _no_shell(self, frente, existe=True, shell=True):
        cm = "core.pipeline.transcription_pipeline.ContextManager"
        with patch(f"{cm}.get_foreground_hwnd", return_value=frente), \
             patch(f"{cm}.janela_existe", return_value=existe), \
             patch(f"{cm}.eh_janela_do_shell", return_value=shell) as classificar:
            return pipeline_mod._foco_no_shell(), classificar

    def test_a_barra_de_tarefas_na_frente(self):
        self.assertEqual((True, BARRA), (self._no_shell(BARRA)[0], self._no_shell(BARRA)[1].call_args.args[0]))

    def test_um_app_na_frente(self):
        self.assertFalse(self._no_shell(APP, shell=False)[0])

    def test_sem_janela_ou_janela_que_nao_existe_nao_e_o_shell(self):
        # Sem janela da frente, o eh_janela_do_shell nem é consultado (uma janela que não existe
        # conta como invisível, e invisível conta como shell).
        resultado, classificar = self._no_shell(0x777, existe=False)
        self.assertFalse(resultado)
        classificar.assert_not_called()


class TestReenvioDaReuniao(unittest.TestCase):
    def test_o_reenvio_de_uma_reuniao_nao_tem_alvo(self):
        # A ata de 1 h leva minutos para sair do reenvio: a janela do clique não volta à frente.
        resolver, threads = MagicMock(return_value=(APP, CAMPO)), []
        escopo = _funcoes_do_willy(
            "reenviar_ultimo_audio",
            transcription_pipeline=SimpleNamespace(fila=SimpleNamespace(mais_recente=lambda: (__file__, "meeting"))),
            atualizar_ui=MagicMock(), _executar_pipeline_transcricao=None,
            ContextManager=SimpleNamespace(resolver_janela_alvo=resolver),
            _janela_antes_do_willy=APP, _foco_antes_do_willy=CAMPO,
            threading=SimpleNamespace(Thread=lambda target, args, daemon: SimpleNamespace(start=lambda: threads.append(args))))
        escopo["reenviar_ultimo_audio"]()
        self.assertEqual((0, 0), threads[0][4])
        resolver.assert_not_called()


class TestFixarJanela(unittest.TestCase):
    """O Ctrl+Alt+F com o painel do Willy ou a barra de tarefas na frente fixava a janela deles, e
    o ditado era colado dentro do Willy, ou em lugar nenhum (juiz do Bloco 11, 3ª rodada; já era
    assim antes do bloco)."""

    def _fixar(self, frente, antes):
        self.fixadas, self.ui = [], []
        contexto = SimpleNamespace(
            get_sticky_window=lambda: None, get_foreground_hwnd=lambda: frente,
            janela_externa=lambda h: h in (APP, OUTRO),
            get_foreground_app=lambda hwnd=None: ({APP: "code.exe", OUTRO: "chrome.exe"}.get(hwnd or frente, "willy.exe"), "título", "GENERAL"),
            set_sticky_window=lambda h, nome: self.fixadas.append((h, nome)))
        _funcoes_do_willy("on_sticky_hotkey", ContextManager=contexto, sound_mgr=MagicMock(),
                          atualizar_ui=lambda *a: self.ui.append(a), _janela_antes_do_willy=antes)["on_sticky_hotkey"]()

    def test_app_de_fora_na_frente_e_fixado(self):
        self._fixar(APP, OUTRO)
        self.assertEqual([(APP, "Code")], self.fixadas)

    def test_com_o_willy_ou_o_shell_na_frente_vale_o_app_de_antes(self):
        for frente in (WILLY, BARRA):
            with self.subTest(frente=hex(frente)):
                self._fixar(frente, OUTRO)
                self.assertEqual([(OUTRO, "Chrome")], self.fixadas)
                self.assertEqual(("sticky_pinned", "Destino fixado: Chrome 🎯"), self.ui[-1])

    def test_app_de_antes_que_ja_nao_e_de_fora_nao_e_fixado(self):
        # A de antes fechou, ou é ela mesma do Willy ou do shell: avisa, sem fixar.
        self._fixar(WILLY, BARRA)
        self.assertEqual([], self.fixadas)
        self.assertEqual(("warning", "Nenhuma janela detectada para fixar"), self.ui[-1])

    def test_sem_app_de_antes_avisa_e_nao_fixa(self):
        self._fixar(WILLY, 0)
        self.assertEqual([], self.fixadas)
        self.assertEqual(("warning", "Nenhuma janela detectada para fixar"), self.ui[-1])


class TestEsperaDoFoco(unittest.TestCase):
    def test_a_entrega_espera_o_alvo_ate_0_6_s(self):
        # Como o "Reusar" do Histórico: menos que isso, uma janela pesada (o navegador com muitas
        # abas) ainda não chegou à frente, e o texto era copiado em vez de colado.
        self.assertGreaterEqual(pipeline_mod._ESPERA_DO_FOCO_S, 0.5)


# --------------------------------------------------------------------------- a pílula
class TestPilulaNoMonitorDoAlvo(unittest.TestCase):
    PAINEL_DO_WILLY = 0x5E5E

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def setUp(self):
        self.pill = FloatingPill(self.root, position_getter=lambda: "centro_inferior",
                                 eh_do_willy_ou_do_shell=lambda h: h == self.PAINEL_DO_WILLY)
        self.addCleanup(self.pill.destroy)
        self.pill._hwnd = HWND_PILULA
        self.pill.root.deiconify = MagicMock()

    def _area(self, frente, cursor=(500, 900)):
        with patch.object(pill_mod, "_user32", User32DaPilula(primeiro_plano=frente)):
            return self.pill._area_de_trabalho("centro_inferior", cursor)

    def test_painel_do_willy_na_frente_vale_o_monitor_do_alvo(self):
        self.pill.janela_alvo = HWND_FIREFOX  # na esquerda; o painel e o cursor, no primário
        self.assertEqual(AREA_ESQUERDA, self._area(self.PAINEL_DO_WILLY))

    def test_sem_alvo_vale_o_monitor_do_cursor(self):
        self.pill.janela_alvo = 0
        self.assertEqual(AREA_PRIMARIO, self._area(self.PAINEL_DO_WILLY, cursor=(500, 900)))
        self.assertEqual(AREA_ESQUERDA, self._area(self.PAINEL_DO_WILLY, cursor=(-500, 900)))

    def test_app_de_fora_na_frente_continua_valendo_ele(self):
        self.pill.janela_alvo = 0x1234  # no primário, pelo User32 falso
        self.assertEqual(AREA_ESQUERDA, self._area(HWND_FIREFOX))

    def test_a_propria_pilula_na_frente_vale_o_alvo(self):
        self.pill.janela_alvo = HWND_FIREFOX
        self.assertEqual(AREA_ESQUERDA, self._area(HWND_PILULA))

    def test_sem_quem_classifique_nenhuma_janela_e_do_willy(self):
        pill = FloatingPill(self.root)
        self.addCleanup(pill.destroy)
        self.assertFalse(pill._eh_do_willy_ou_do_shell(self.PAINEL_DO_WILLY))


@unittest.skipUnless(sys.platform == "win32", "Win32 real")
class TestContextManagerWin32Real(unittest.TestCase):
    """Exercita WindowFromPoint, GetAncestor(GA_ROOT) e GetGUIThreadInfo diretamente no user32
    real do Windows, contra uma janela Tk real com um Entry filho."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry("240x120+80+80")
        self.entry = tk.Entry(self.root)
        self.entry.pack(fill="both", expand=True)
        self.root.update()
        self.addCleanup(destruir_tk, self.root)

    def test_janela_sob_o_cursor_resolve_hwnd_raiz_real_pelo_entry(self):
        cx = self.entry.winfo_rootx() + self.entry.winfo_width() // 2
        cy = self.entry.winfo_rooty() + self.entry.winfo_height() // 2
        hwnd_raiz = context_mod.user32.GetAncestor(self.root.winfo_id(), ContextManager._GA_ROOT)

        def _cursor_no_entry(ptr):
            ptr._obj.x, ptr._obj.y = cx, cy
            return 1

        with patch.object(context_mod.user32, "GetCursorPos", side_effect=_cursor_no_entry):
            sob = ContextManager.janela_sob_o_cursor()
        self.assertEqual(hwnd_raiz, sob)
        self.assertTrue(ContextManager.eh_janela_do_willy(sob))

    def test_foco_do_teclado_consulta_guithreadinfo_real_sem_erro(self):
        hwnd_raiz = context_mod.user32.GetAncestor(self.root.winfo_id(), ContextManager._GA_ROOT)
        foco = ContextManager.foco_do_teclado(hwnd_raiz)
        self.assertIsInstance(foco, int)


if __name__ == "__main__":
    unittest.main()
