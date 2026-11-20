"""
Concorrência do AudioManager: travas com o callback do PortAudio e reentrância de gravação.

O stream falso imita o PortAudio: Pa_StopStream espera o callback em andamento terminar, e
o callback do Willy precisa de `audio_mgr.lock`. Então, se stop()/close() rodarem com o lock
na mão, o callback nunca termina e o stop nunca volta. Aqui o stop() tenta pegar o lock e
registra se conseguiu; no app real, não conseguir é travar para sempre.
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from core.audio import AudioManager
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy


class _LockRastreado:
    """Wrapper em torno de um Lock real que conta quantas vezes foi adquirido."""

    def __init__(self, lock):
        self._lock = lock
        self.aquisicoes = 0
        self.em_posse = False

    def acquire(self, *args, **kwargs):
        ok = self._lock.acquire(*args, **kwargs)
        if ok:
            self.aquisicoes += 1
            self.em_posse = True
        return ok

    def release(self):
        self.em_posse = False
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


class StreamQueExigeOLock:
    def __init__(self, mgr):
        self.mgr = mgr
        self.active = True
        self.paradas = []  # uma entrada por stop(): o lock estava livre naquele momento?
        self.fechado = False

    def _callback_consegue_terminar(self):
        livre = self.mgr.lock.acquire(timeout=0.3)
        if livre:
            self.mgr.lock.release()
        return livre

    def stop(self):
        self.paradas.append(self._callback_consegue_terminar())
        self.active = False

    def close(self):
        self.fechado = True


class TestStreamNuncaParaComOLockNaMao(unittest.TestCase):
    def setUp(self):
        self.mgr = AudioManager()
        # start_recording exige microfone aberto (sem ele era a gravação fantasma).
        self.mgr.stream = MagicMock(active=True)
        self.stream = StreamQueExigeOLock(self.mgr)

    def _assert_parou_sem_travar(self):
        self.assertTrue(self.stream.paradas, "o stream nem foi parado")
        self.assertTrue(all(self.stream.paradas),
                        "stop() rodou com o lock na mão: com WASAPI o app trava para sempre")

    def test_trocar_microfone(self):
        self.mgr.stream = self.stream
        self.mgr.set_device(7)
        self._assert_parou_sem_travar()
        self.assertTrue(self.stream.fechado)

    def test_pausar(self):
        self.mgr.stream = self.stream
        self.mgr.pause_stream()
        self._assert_parou_sem_travar()

    def test_fechar_o_app(self):
        self.mgr.stream = self.stream
        self.mgr.close()
        self._assert_parou_sem_travar()

    def test_parar_reuniao_fecha_o_audio_do_sistema(self):
        self.mgr.start_recording("meeting")
        self.mgr.system_stream = self.stream
        self.mgr.append_audio(np.zeros((160, 1), dtype=np.float32))
        self.mgr.stop_recording()
        self._assert_parou_sem_travar()
        self.assertIsNone(self.mgr.system_stream)

    def test_cancelar_reuniao_fecha_o_audio_do_sistema(self):
        self.mgr.start_recording("meeting")
        self.mgr.system_stream = self.stream
        self.mgr.cancel_recording()
        self._assert_parou_sem_travar()
        self.assertIsNone(self.mgr.system_stream)


class TestGravacaoNaoEReiniciadaPorCima(unittest.TestCase):
    def setUp(self):
        self.mgr = AudioManager()
        # start_recording exige microfone aberto (sem ele era a gravação fantasma).
        self.mgr.stream = MagicMock(active=True)

    def test_segundo_inicio_nao_apaga_a_reuniao_em_andamento(self):
        """Atalho de transformar no meio de uma reunião zerava o buffer."""
        self.assertTrue(self.mgr.start_recording("meeting"))
        self.mgr.append_audio(np.ones((16000, 1), dtype=np.float32) * 0.1)

        self.assertFalse(self.mgr.start_recording("transform"))

        self.assertEqual("meeting", self.mgr.recording_mode)
        audio, modo = self.mgr.stop_recording()
        self.assertEqual(("meeting", 16000), (modo, len(audio)))

    def test_nao_inicia_com_pipeline_ocupado(self):
        self.mgr.is_processing = True
        self.assertFalse(self.mgr.start_recording("transcribe"))
        self.assertFalse(self.mgr.is_recording)

    def test_parar_durante_a_negociacao_nao_deixa_stream_do_sistema_orfao(self):
        """O stream aberto depois do "parar" gravava na reunião seguinte, duplicado."""
        self.mgr.system_device_index = 3
        negociado = MagicMock()

        def negociar_enquanto_o_usuario_para(*_a, **_kw):
            self.mgr.stop_recording()  # o segundo toque chega durante a negociação
            return negociado, 48000

        with patch("core.audio.negociar_stream", side_effect=negociar_enquanto_o_usuario_para):
            self.mgr.start_recording("meeting")

        negociado.stop.assert_called_once()
        negociado.close.assert_called_once()
        self.assertIsNone(self.mgr.system_stream)

    def test_callback_do_sistema_atrasado_nao_entra_na_gravacao_seguinte(self):
        self.mgr.system_device_index = 3
        callbacks = []

        def negociar(_idx, cb, *_a):
            callbacks.append(cb)
            return MagicMock(), 16000

        with patch("core.audio.negociar_stream", side_effect=negociar):
            self.mgr.start_recording("meeting")
        self.mgr.stop_recording()
        callbacks[0](np.ones((160, 1), dtype=np.float32), 160, None, None)
        self.assertEqual([], self.mgr.system_buffer)


class TestTrocaDeMicrofoneDuranteAGravacao(unittest.TestCase):
    def setUp(self):
        self.mgr = AudioManager()
        self.antigo = MagicMock()
        self.mgr.stream = self.antigo
        self.mgr._current_callback = lambda *a: None

    def test_troca_e_adiada_para_nao_misturar_taxas_no_buffer(self):
        self.mgr.start_recording("transcribe")
        with patch.object(self.mgr, "ensure_stream") as ensure:
            self.mgr.set_device(5)
            self.antigo.stop.assert_not_called()
            ensure.assert_not_called()

            self.mgr.stop_recording()

            self.antigo.stop.assert_called_once()
            ensure.assert_called_once()
        self.assertEqual(5, self.mgr.device_index)

    def test_audio_sai_com_a_taxa_em_que_foi_gravado(self):
        """O stop reabre o mic novo, que reescreve actual_sample_rate (48k) antes de o chamador
        lê-la: 2 s gravados a 16 kHz viravam 0,67 s, áudio 3x acelerado."""
        self.mgr.actual_sample_rate = 16000
        self.mgr.start_recording("transcribe")
        self.mgr.append_audio(np.zeros((32000, 1), dtype=np.float32))  # 2 s a 16 kHz
        self.mgr.set_device(9)

        with patch("core.audio.negociar_stream", return_value=(MagicMock(), 48000)):
            audio, _modo, taxa = self.mgr.stop_recording_com_taxa()

        self.assertEqual(48000, self.mgr.actual_sample_rate, "o microfone novo foi aberto")
        self.assertEqual(16000, taxa)
        self.assertAlmostEqual(2.0, len(audio) / taxa)

    def test_salvar_os_ajustes_com_o_mesmo_microfone_nao_reinicia_o_stream(self):
        self.mgr.device_index = 2
        self.mgr.set_device(2)
        self.antigo.stop.assert_not_called()


class TestModoSussurroPreservaOGanho(unittest.TestCase):
    def test_desligar_o_sussurro_volta_ao_ganho_do_slider(self):
        """Salvar os Ajustes envia MIC_GAIN e depois WHISPER_MODE; o ganho virava 1.0."""
        mgr = AudioManager()
        mgr.set_gain_boost(2.5)
        mgr.set_whisper_mode(False, base_gain=2.5)
        self.assertEqual(2.5, mgr.gain_boost)

    def test_ligar_o_sussurro_usa_o_ganho_do_modo(self):
        mgr = AudioManager()
        mgr.set_whisper_mode(True, base_gain=2.5)
        self.assertEqual(3.0, mgr.gain_boost)


class TestEstadoProtegidoSobLock(unittest.TestCase):
    """AUD-017: Transições e leituras de estado entre callback_audio, cancelar_por_esc,
    monitorar_hold e AudioManager protegem os campos sob audio_mgr.lock."""

    def test_start_recording_zera_last_wf_time(self):
        mgr = AudioManager()
        mgr.stream = MagicMock(active=True)
        mgr._last_wf_time = 99999.0
        self.assertTrue(mgr.start_recording("transcribe"))
        self.assertEqual(0.0, mgr._last_wf_time)

    def test_cancelar_por_esc_le_estado_sob_lock(self):
        mgr = AudioManager()
        mgr.stream = MagicMock(active=True)
        mgr.start_recording("transcribe")
        rastreado = _LockRastreado(mgr.lock)
        mgr.lock = rastreado
        mgr.is_stopping = True

        fn = _funcao_do_willy(
            "cancelar_por_esc",
            audio_mgr=mgr,
            _soltar_esc=lambda: None,
            _soltar_esc_sem_gravacao=lambda: None,
            config_mgr=MagicMock(wake_word_enabled=True),
            sound_mgr=MagicMock(),
            atualizar_ui=MagicMock(),
        )
        fn()
        self.assertGreaterEqual(rastreado.aquisicoes, 1)

    def test_monitorar_hold_le_sessao_sob_lock(self):
        mgr = AudioManager()
        mgr.stream = MagicMock(active=True)
        mgr.start_recording("transcribe")
        rastreado = _LockRastreado(mgr.lock)
        mgr.lock = rastreado
        mgr.is_recording = False  # encerra no primeiro passo da espera

        from core import Win32HotKeyManager

        fn = _funcao_do_willy(
            "monitorar_hold",
            audio_mgr=mgr,
            Win32HotKeyManager=Win32HotKeyManager,
            _user32=MagicMock(GetAsyncKeyState=MagicMock(return_value=0)),
            _VK_ESCAPE=0x1B,
            cancelar_por_esc=MagicMock(),
            parar_gravacao=MagicMock(),
            time=MagicMock(sleep=lambda _s: None),
        )
        fn("ctrl+space")
        # Deve ter adquirido o lock ao ler recording_start_time inicial e em _mesma_gravacao()
        self.assertGreaterEqual(rastreado.aquisicoes, 2)

    def test_callback_audio_protege_transicoes_e_dispara_parada_fora_do_lock(self):
        from types import SimpleNamespace

        mgr = AudioManager()
        mgr.stream = MagicMock(active=True)
        mgr.start_recording("transcribe")
        rastreado = _LockRastreado(mgr.lock)
        mgr.lock = rastreado

        # Avança calibração de ruído para que callback_audio tome decisões de fala/silêncio
        for _ in range(40):
            mgr.update_noise_floor(0.002, 0.02)
        mgr.has_spoken = True
        mgr.silence_start_time = 100.0
        mgr.recording_start_time = 95.0

        lock_livre_no_start_da_thread = []

        class _ThreadsTeste:
            def Thread(self, target, daemon=None):
                def _start():
                    lock_livre_no_start_da_thread.append(not rastreado.em_posse)
                return SimpleNamespace(start=_start)

        fn = _funcao_do_willy(
            "callback_audio",
            audio_mgr=mgr,
            config_mgr=SimpleNamespace(
                auto_silence=True,
                silero_vad=False,
                speech_threshold=0.01,
                silence_threshold=0.005,
                silence_seconds=2.0,
                wake_word_enabled=False,
            ),
            pill=None,
            safe_dispatch_ui=MagicMock(),
            parar_gravacao=MagicMock(),
            cancelar_gravacao=MagicMock(),
            threading=_ThreadsTeste(),
            time=SimpleNamespace(time=lambda: 103.0),
            _DITADO_LONGO_S=10.0,
            _FOLEGO_EXTRA_S=0.6,
            FLUTUANTE_TEXTO="#fff",
            FLUTUANTE_AMARELO="#ff0",
            FLUTUANTE_LILAS="#f0f",
            FLUTUANTE_ROXO="#a0f",
            FLUTUANTE_VERDE="#0f0",
            FLUTUANTE_CIANO="#0ff",
            FLUTUANTE_LARANJA="#fa0",
        )
        rastreado.aquisicoes = 0
        quadro_silencio = np.zeros((320, 1), dtype=np.float32)
        fn(quadro_silencio, 320, None, None)

        self.assertTrue(mgr.is_stopping)
        self.assertEqual([True], lock_livre_no_start_da_thread)
        # append_audio (1), update_noise_floor (2), get_adaptive_thresholds (3),
        # nivel_de_voz (4), calibrando_ruido (5) + ao menos 1 aquisição para a transição de estado
        self.assertGreaterEqual(rastreado.aquisicoes, 6)


if __name__ == "__main__":
    unittest.main()
