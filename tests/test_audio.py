"""
Testes unitários para o módulo core.audio.AudioManager.
"""

import io
import unittest
from unittest.mock import MagicMock

import numpy as np
import soundfile as sf

from core.audio import AudioManager


class TestAudioManager(unittest.TestCase):

    def setUp(self):
        self.mgr = AudioManager(sample_rate=16000, channels=1)
        # start_recording exige microfone aberto (sem ele era a gravação fantasma).
        self.mgr.stream = MagicMock(active=True)

    def test_compute_rms_silence(self):
        silence = np.zeros((800, 1), dtype=np.float32)
        self.assertEqual(self.mgr.compute_rms(silence), 0.0)

    def test_compute_rms_none(self):
        self.assertEqual(self.mgr.compute_rms(None), 0.0)

    def test_compute_rms_signal(self):
        # Sinal constante de amplitude 0.5 tem RMS = 0.5
        signal = np.full((1000, 1), 0.5, dtype=np.float32)
        rms = self.mgr.compute_rms(signal)
        self.assertAlmostEqual(rms, 0.5, places=5)

    def test_recording_lifecycle(self):
        # Inicia gravação
        ok = self.mgr.start_recording("translate")
        self.assertTrue(ok)
        self.assertTrue(self.mgr.is_recording)
        self.assertEqual(self.mgr.recording_mode, "translate")
        self.assertGreater(self.mgr.recording_start_time, 0.0)
        self.assertIsNotNone(self.mgr.no_speech_start_time)

        # Adiciona dados simulados
        chunk1 = np.ones((800, 1), dtype=np.float32) * 0.1
        chunk2 = np.ones((800, 1), dtype=np.float32) * 0.2
        self.mgr.append_audio(chunk1)
        self.mgr.append_audio(chunk2)

        # Encerra gravação
        res = self.mgr.stop_recording()
        self.assertIsNotNone(res)
        audio_completo, modo = res
        self.assertEqual(modo, "translate")
        self.assertEqual(len(audio_completo), 1600)
        self.assertFalse(self.mgr.is_recording)

    def test_ensure_stream_passa_callback_ao_input_stream(self):
        from unittest.mock import patch
        mgr = AudioManager(sample_rate=16000, channels=1)
        cb = lambda *a: None
        stream_falso = MagicMock(active=True)
        with patch("core.audio.sd.InputStream", return_value=stream_falso) as input_stream:
            self.assertTrue(mgr.ensure_stream(cb))
        self.assertIs(cb, input_stream.call_args.kwargs.get("callback"))

    def test_cancel_recording(self):
        self.mgr.start_recording("transcribe")
        chunk = np.ones((500, 1), dtype=np.float32)
        self.mgr.append_audio(chunk)
        self.mgr.cancel_recording()

        self.assertFalse(self.mgr.is_recording)
        self.assertEqual(len(self.mgr.buffer), 0)

    def test_convert_to_wav(self):
        # 1 segundo de áudio a 16000 Hz
        sample_audio = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 16000)).astype(np.float32)
        wav_buf = self.mgr.convert_to_wav(sample_audio)

        self.assertIsInstance(wav_buf, io.BytesIO)
        wav_buf.seek(0)
        header = wav_buf.read(4)
        self.assertEqual(header, b"RIFF")

        # Lê de volta com soundfile para validar integridade
        wav_buf.seek(0)
        data_read, sr = sf.read(wav_buf)
        self.assertEqual(sr, 16000)
        self.assertEqual(len(data_read), 16000)

    def test_get_input_devices(self):
        # Deve retornar uma lista sem exceções
        devices = AudioManager.get_input_devices()
        self.assertIsInstance(devices, list)

    def test_set_device(self):
        mgr = AudioManager(device_index=None)
        self.assertIsNone(mgr.device_index)
        mgr.set_device(1)
        self.assertEqual(mgr.device_index, 1)

    def test_adaptive_noise_thresholds(self):
        mgr = AudioManager()
        mgr.start_recording("transcribe")
        # Simula ruído de fundo moderado (ex: ar condicionado ou ventilador com RMS 0.008)
        for _ in range(5):
            mgr.update_noise_floor(0.008)

        self.assertGreater(mgr.ambient_noise_floor, 0.005)
        speech_th, silence_th = mgr.get_adaptive_thresholds(0.015, 0.005)
        # O limiar de fala e silêncio deve se adaptar acima do ruído de fundo
        self.assertGreater(speech_th, 0.015)
        self.assertGreater(silence_th, 0.005)
        self.assertLess(silence_th, speech_th)

    def test_split_audio_with_sample_rate(self):
        """A taxa entra por nome.

        O segundo posicional e `chunk_seconds`. Aceitar 48000 ali como se fosse taxa
        exigia adivinhar pela magnitude do numero, e ai um chunk_seconds legitimo de
        10000 virava um header de 10 kHz sobre amostras de 16 kHz, sem erro nenhum.
        """
        audio_data = np.zeros(48000 * 2, dtype=np.float32)
        chunks = self.mgr.split_audio_into_chunks(audio_data, sample_rate=48000)
        self.assertEqual(len(chunks), 1)
        # Valida taxa no header
        chunks[0].seek(0)
        _, sr_read = sf.read(chunks[0])
        self.assertEqual(sr_read, 48000)

        # Nomeado sample_rate=44100
        chunks2 = self.mgr.split_audio_into_chunks(audio_data, chunk_seconds=600, sample_rate=44100)
        chunks2[0].seek(0)
        _, sr_read2 = sf.read(chunks2[0])
        self.assertEqual(sr_read2, 44100)

    def test_meeting_recording_system_audio_fallback(self):
        """Garante que reunião com microfone mudo/vazio preserva o áudio do sistema."""
        self.mgr.start_recording("meeting")
        # Simula buffer do mic vazio, mas sistema com áudio
        sys_chunk = np.ones((1600, 1), dtype=np.float32) * 0.3
        self.mgr.system_buffer.append(sys_chunk)

        res = self.mgr.stop_recording()
        self.assertIsNotNone(res)
        audio_completo, modo = res
        self.assertEqual(modo, "meeting")
        self.assertEqual(len(audio_completo), 1600)


if __name__ == "__main__":
    unittest.main()
