"""
Erro e sucesso que não encerram a gravação chegam à pílula com por_cima=True.

Desfazer (Ctrl+Alt+Z), reenviar sem áudio guardado, colar do histórico e transcrever um
arquivo com outro processo em curso mandavam "error"/"success" comuns: no meio de uma
gravação, a pílula sumia e a gravação seguia invisível. O comportamento da pílula está em
test_pilula_monitor_e_foco.TestAvisosPorCima; aqui, quem manda o quê, validando contra a
FloatingPill real e contratos com create_autospec.
"""

import threading
import tkinter as tk
import unittest
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, create_autospec

from core.actions import ActionManager
from core.audio import AudioManager
from core.config import ConfigManager
from core.groq_service import GroqService
from core.sound import SoundManager
from core.system.injector import TextInjector
from tests.willy_isolado import _funcao_do_willy
from ui.overlays.pill import FloatingPill
from ui.overlays.spotlight import HistorySpotlight


class TestAtualizarUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.pill = FloatingPill(self.root)
        self.addCleanup(self.pill.destroy)

    def _despachado(self, *args, **kwargs):
        chamadas = []

        def _despachar(fn, *a):
            chamadas.append((fn, a))
            fn(*a)

        audio_mgr = create_autospec(AudioManager, instance=True)
        audio_mgr.recording_mode = "meeting"
        config_mgr = create_autospec(ConfigManager, instance=True)
        config_mgr.refine_prompt = True
        atualizar = _funcao_do_willy(
            "atualizar_ui", pill=self.pill, safe_dispatch_ui=_despachar,
            audio_mgr=audio_mgr, config_mgr=config_mgr)
        atualizar(*args, **kwargs)
        return chamadas[-1][1]

    def test_por_cima_chega_a_pilula_real_sem_apagar_gravacao(self):
        self.pill.show_state("listening", "Ouvindo...", "meeting", True)
        args = self._despachado("error", "Nenhum ditado para desfazer", por_cima=True)
        self.assertEqual(("error", "Nenhum ditado para desfazer", "meeting", True, True), args)
        self.assertEqual("error", self.pill.current_state)
        self.assertIsNotNone(self.pill._persistente, "o estado ouvindo tem que continuar guardado")

    def test_sem_pedir_nao_passa_por_cima(self):
        args = self._despachado("success", "Colado")
        self.assertIs(False, args[-1])
        self.assertEqual("success", self.pill.current_state)

    def test_atalho_durante_processamento_avisa_por_cima_sem_som_e_pilula_restaura_estado(self):
        """Item 1.2: Atalho de gravação durante processamento mostra aviso por cima e volta ao mesmo processing."""
        msg_proc = "Aguardando a cota da Groq (18 s)..."
        self.pill.show_state("processing", msg_proc, "translate_es", True)
        texto_proc_antes = self.pill.canvas.itemcget(self.pill.text, "text")

        audio_mgr = create_autospec(AudioManager, instance=True)
        audio_mgr.is_processing = True
        audio_mgr.is_recording = False
        audio_mgr.is_awake = True
        audio_mgr.recording_mode = "translate_es"
        config_mgr = create_autospec(ConfigManager, instance=True)
        config_mgr.refine_prompt = True
        config_mgr.groq_api_key = "gsk_ok"
        som = create_autospec(SoundManager, instance=True)

        atualizar = _funcao_do_willy(
            "atualizar_ui", pill=self.pill, safe_dispatch_ui=lambda fn, *a: fn(*a),
            audio_mgr=audio_mgr, config_mgr=config_mgr,
        )
        pronto = _funcao_do_willy(
            "_pronto_para_gravar", audio_mgr=audio_mgr, config_mgr=config_mgr,
            sound_mgr=som, atualizar_ui=atualizar,
        )
        on_voice = _funcao_do_willy(
            "on_voice_hotkey", _pronto_para_gravar=pronto, audio_mgr=audio_mgr,
        )
        on_voice()
        som.sound_error.assert_not_called()
        audio_mgr.start_recording.assert_not_called()
        self.assertTrue(audio_mgr.is_processing)
        self.assertEqual("error", self.pill.current_state)
        self.assertEqual("Aguarde o processo atual...", self.pill.canvas.itemcget(self.pill.text, "text"))
        self.assertEqual(("processing", msg_proc, "translate_es", True), self.pill._persistente)

        # Ao encerrar o aviso temporário, a pílula volta exatamente ao mesmo processing guardado.
        self.pill._voltar(self.pill._persistente)
        self.assertEqual("processing", self.pill.current_state)
        self.assertEqual(("processing", msg_proc, "translate_es", True), self.pill._persistente)
        self.assertEqual(texto_proc_antes, self.pill.canvas.itemcget(self.pill.text, "text"))


class TestDesfazer(unittest.TestCase):
    def _desfazer(self, ultimo, falha=False, soltou=True):
        ui = MagicMock()
        self.teclado = MagicMock()
        self.som = create_autospec(SoundManager, instance=True)
        self.espera = create_autospec(ActionManager.esperar_modificadores_soltos, return_value=soltou)
        if falha:
            self.teclado.send.side_effect = RuntimeError("sem foco")
        desfazer = _funcao_do_willy(
            "desfazer_ultimo_ditado", atualizar_ui=ui, keyboard=self.teclado,
            sound_mgr=self.som, last_injected_text=ultimo,
            ActionManager=SimpleNamespace(esperar_modificadores_soltos=self.espera))
        desfazer()
        self.ultimo_depois = desfazer.__globals__["last_injected_text"]
        return ui

    def test_espera_o_alt_subir_antes_do_ctrl_z(self):
        # Com o Alt preso, o Ctrl+Z saía como Ctrl+Alt+Z, o próprio atalho do Willy.
        self._desfazer("texto colado")
        self.espera.assert_called_once_with(2.0)
        self.teclado.send.assert_called_once_with("ctrl+z")
        self.assertIsNone(self.ultimo_depois)

    def test_atalho_ainda_preso_pede_para_soltar_e_guarda_o_ditado(self):
        ui = self._desfazer("texto colado", soltou=False)
        self.teclado.send.assert_not_called()
        self.som.sound_error.assert_called_once_with()
        ui.assert_called_once_with("error", "Solte o atalho para desfazer", por_cima=True)
        self.assertEqual("texto colado", self.ultimo_depois)

    def test_sem_ditado_para_desfazer(self):
        self._desfazer(None).assert_called_once_with("error", "Nenhum ditado para desfazer", por_cima=True)

    def test_ditado_desfeito(self):
        self._desfazer("texto colado").assert_called_once_with("success", "Ditado desfeito! ↩️", por_cima=True)

    def test_falha_ao_desfazer(self):
        self._desfazer("texto colado", falha=True).assert_called_once_with(
            "error", "Falha ao desfazer", por_cima=True)


class TestTranscreverArquivoComOutroProcesso(unittest.TestCase):
    def _transcrever(self, processando, gravando):
        ui = MagicMock()
        groq = create_autospec(GroqService, instance=True)
        som = create_autospec(SoundManager, instance=True)
        audio_mgr = create_autospec(AudioManager, instance=True)
        audio_mgr.is_processing = processando
        audio_mgr.is_recording = gravando
        audio_mgr.lock = threading.Lock()
        config_mgr = create_autospec(ConfigManager, instance=True)
        config_mgr.groq_api_key = "gsk_x"
        transcrever = _funcao_do_willy(
            "transcrever_arquivo_externo", Optional=Optional, atualizar_ui=ui, sound_mgr=som,
            audio_mgr=audio_mgr, config_mgr=config_mgr, groq_service=groq)
        self.assertIsNone(transcrever("C:/audio.mp3"))
        groq.transcribe_file.assert_not_called()
        return ui

    def test_no_meio_de_uma_gravacao_pede_para_aguardar(self):
        # Sem isto, o "processando" do arquivo tomava a pílula do ditado em curso.
        self._transcrever(False, True).assert_called_once_with(
            "error", "Aguarde o processo atual...", por_cima=True)

    def test_com_outro_processamento_pede_para_aguardar(self):
        self._transcrever(True, False).assert_called_once_with(
            "error", "Aguarde o processo atual...", por_cima=True)


class TestReenviarEColar(unittest.TestCase):
    def test_reenviar_sem_audio_guardado(self):
        ui = MagicMock()
        reenviar = _funcao_do_willy(
            "reenviar_ultimo_audio", atualizar_ui=ui,
            transcription_pipeline=SimpleNamespace(fila=SimpleNamespace(mais_recente=lambda: None)))
        reenviar()
        ui.assert_called_once_with("error", "Nenhum áudio salvo para reenviar", por_cima=True)

    def test_colar_do_historico_que_falha(self):
        ui = MagicMock()
        spotlight = create_autospec(HistorySpotlight, instance=True)
        som = create_autospec(SoundManager, instance=True)
        injector = create_autospec(TextInjector, instance=True)
        injector.paste_text.return_value = False
        config_mgr = create_autospec(ConfigManager, instance=True)
        itens_hist = [{"text": "um prompt", "mode": "transcribe"}]
        config_mgr.load_history.return_value = itens_hist
        abrir = _funcao_do_willy(
            "on_history_hotkey", atualizar_ui=ui, spotlight=spotlight, sound_mgr=som,
            audio_mgr=SimpleNamespace(is_awake=True), config_mgr=config_mgr,
            default_injector=injector,
            safe_dispatch_ui=lambda funcao: funcao())
        abrir()
        config_mgr.load_history.assert_called_once_with()
        self.assertEqual(itens_hist, spotlight.mostrar.call_args.args[0])
        cb = spotlight.mostrar.call_args.kwargs["on_paste_callback"]
        cb("um prompt")
        injector.paste_text.assert_called_once_with("um prompt", auto_send=False)
        ui.assert_called_once_with("error", "Não consegui colar. Tente de novo", por_cima=True)

        # Quando paste_text retorna True, toca som de sucesso
        injector.paste_text.reset_mock()
        injector.paste_text.return_value = True
        cb("outro prompt")
        injector.paste_text.assert_called_once_with("outro prompt", auto_send=False)
        som.sound_success.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
