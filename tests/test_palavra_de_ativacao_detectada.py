"""
A checagem do "Ei Willy" manda o trecho a 16 kHz e só age se o Willy ainda está livre.

- O trecho ia na taxa do microfone: a 48 kHz, três vezes maior para a Groq a cada fala ouvida.
- A transcrição leva um tempo. Se nele a pessoa começava um ditado pelo atalho, punha o Willy
  em repouso ou desligava a palavra, o som de início e o "Ei Willy detectado!" saíam por cima.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from core.audio_processing.dsp import TAXA_WHISPER, para_taxa_whisper
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy


class _ThreadsAdiadas:
    """threading falso: guarda o worker, e o teste decide quando ele roda."""

    def __init__(self):
        self.alvos = []

    def Thread(self, target, daemon=None):
        return SimpleNamespace(start=lambda: self.alvos.append(target))

    def rodar(self):
        for alvo in self.alvos:
            alvo()


class TestPalavraDeAtivacaoDetectada(unittest.TestCase):
    def setUp(self):
        self.audio = SimpleNamespace(actual_sample_rate=48000, sample_rate=16000, is_awake=True,
                                     is_recording=False, is_processing=False,
                                     convert_to_wav=MagicMock(return_value=b"wav"))
        self.config = SimpleNamespace(wake_word_enabled=True)
        self.groq = MagicMock()
        self.groq.transcribe.return_value = "Ei Willy"
        self.som, self.ui, self.despacho = MagicMock(), MagicMock(), MagicMock()
        self.threads = _ThreadsAdiadas()
        self.blocos = [np.full((4800, 1), 0.1, dtype=np.float32) for _ in range(3)]  # 0,3 s a 48 kHz
        self.escopo = {
            "_wake_word_processing": False, "_wake_word_buffer": list(self.blocos), "threading": self.threads,
            "audio_mgr": self.audio, "config_mgr": self.config, "groq_service": self.groq, "sound_mgr": self.som,
            "atualizar_ui": self.ui, "safe_dispatch_ui": self.despacho, "iniciar_gravacao": MagicMock(),
            "para_taxa_whisper": para_taxa_whisper, "TAXA_WHISPER": TAXA_WHISPER}

    def _checar(self, durante_a_transcricao=None):
        if durante_a_transcricao:
            def _transcrever(*_a, **_k):
                durante_a_transcricao()
                return "Ei Willy"
            self.groq.transcribe.side_effect = _transcrever
        fn = _funcao_do_willy("_trigger_wake_word_check", **self.escopo)
        fn()
        self.threads.rodar()
        self.globs = fn.__globals__

    def test_manda_o_trecho_a_16_khz(self):
        self._checar()
        audio, = self.audio.convert_to_wav.call_args.args
        self.assertEqual(TAXA_WHISPER, self.audio.convert_to_wav.call_args.kwargs["sample_rate"])
        self.assertEqual(4800, len(audio))  # 0,3 s a 16 kHz

    def test_a_taxa_e_a_de_quando_o_trecho_foi_ouvido(self):
        _funcao_do_willy("_trigger_wake_word_check", **self.escopo)()
        self.audio.actual_sample_rate = 16000  # o microfone trocou antes de o worker rodar
        self.threads.rodar()
        audio, = self.audio.convert_to_wav.call_args.args
        self.assertEqual(4800, len(audio))

    def test_livre_detecta_e_inicia(self):
        self._checar()
        self.som.sound_start.assert_called_once_with()
        self.ui.assert_called_once_with("listening", "Ei Willy detectado! 🗣️")
        self.despacho.assert_called_once()
        # O callback despachado deve acionar iniciar_gravacao(modo="transcribe") (mata A7)
        cb_despachado = self.despacho.call_args.args[0]
        cb_despachado()
        self.escopo["iniciar_gravacao"].assert_called_once_with(modo="transcribe")
        # E a trava _wake_word_processing deve voltar a False no finally (mata A8)
        self.assertFalse(self.globs["_wake_word_processing"])

    def test_ocupado_depois_da_transcricao_nao_age(self):
        mudancas = {
            "ditado pelo atalho": lambda: setattr(self.audio, "is_recording", True),
            "processando": lambda: setattr(self.audio, "is_processing", True),
            "repouso": lambda: setattr(self.audio, "is_awake", False),
            "palavra desligada": lambda: setattr(self.config, "wake_word_enabled", False),
        }
        for nome, mudanca in mudancas.items():
            with self.subTest(nome):
                self.setUp()
                self._checar(durante_a_transcricao=mudanca)
                self.som.sound_start.assert_not_called()
                self.ui.assert_not_called()
                self.despacho.assert_not_called()

    def test_worker_registra_excecao_no_stderr_e_libera_flag(self):
        """AUD-003: Falha no worker de wake word é registrada em sys.stderr e libera _wake_word_processing."""
        import io

        stderr_falso = io.StringIO()
        self.escopo["sys"] = SimpleNamespace(stderr=stderr_falso)
        self.groq.transcribe.side_effect = RuntimeError("falha simulada na Groq")
        fn = _funcao_do_willy("_trigger_wake_word_check", **self.escopo)
        fn()
        self.threads.rodar()
        self.assertFalse(fn.__globals__["_wake_word_processing"])
        self.assertIn("falha simulada na Groq", stderr_falso.getvalue())

    def test_trigger_usa_wake_word_lock(self):
        """AUD-003: _trigger_wake_word_check protege _wake_word_buffer e _wake_word_processing com _wake_word_lock."""
        entradas = []

        class _LockSpy:
            def __enter__(self):
                entradas.append("enter")
                return self

            def __exit__(self, *a):
                entradas.append("exit")
                return False

        self.escopo["_wake_word_lock"] = _LockSpy()
        self._checar()
        # Deve adquirir na checagem/cópia inicial e no finally do worker
        self.assertGreaterEqual(entradas.count("enter"), 2)

    def test_toggle_willy_awake_limpa_wake_word_buffer_ao_pausar(self):
        """AUD-003: Colocar o Willy em repouso limpa _wake_word_buffer sob _wake_word_lock."""
        entradas = []

        class _LockSpy:
            def __enter__(self):
                entradas.append("enter")
                return self

            def __exit__(self, *a):
                entradas.append("exit")
                return False

        buf = [np.zeros((160, 1), dtype=np.float32)]
        audio = SimpleNamespace(
            is_awake=True,
            is_recording=False,
            ensure_stream=MagicMock(),
            cancel_recording=MagicMock(),
            pause_stream=MagicMock(),
        )
        fn = _funcao_do_willy(
            "toggle_willy_awake",
            audio_mgr=audio,
            config_mgr=SimpleNamespace(wake_word_enabled=True),
            sound_mgr=MagicMock(),
            atualizar_ui=MagicMock(),
            sincronizar_bandeja=MagicMock(),
            dashboard=None,
            safe_dispatch_ui=MagicMock(),
            _soltar_esc=MagicMock(),
            _wake_word_buffer=buf,
            _wake_word_lock=_LockSpy(),
        )
        fn()
        self.assertFalse(audio.is_awake)
        self.assertEqual([], buf)
        self.assertGreaterEqual(entradas.count("enter"), 1)

    def test_pipeline_on_pill_text_despacha_na_thread_da_ui(self):
        """AUD-002: _pipeline_on_pill_text despacha pill.set_last_text via safe_dispatch_ui."""
        pill_mock = MagicMock()
        despacho = MagicMock()
        fn = _funcao_do_willy(
            "_pipeline_on_pill_text",
            pill=pill_mock,
            safe_dispatch_ui=despacho,
            last_injected_text=None,
        )
        fn("Olá mundo", True)
        pill_mock.set_last_text.assert_not_called()
        despacho.assert_called_once_with(pill_mock.set_last_text, "Olá mundo")
        self.assertEqual("Olá mundo", fn.__globals__["last_injected_text"])


if __name__ == "__main__":
    unittest.main()
