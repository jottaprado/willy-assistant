"""
Testes unitários para divisão de áudio em chunks e transcrição de arquivos externos.
"""

import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from core.audio import AudioManager
from core.groq_service import GroqService


class TestAudioChunking(unittest.TestCase):

    def setUp(self):
        self.audio_mgr = AudioManager(sample_rate=16000, channels=1)

    def test_split_audio_short(self):
        # 5 segundos de áudio com chunk_seconds=10 -> 1 chunk
        audio_data = np.zeros((16000 * 5,), dtype=np.float32)
        chunks = self.audio_mgr.split_audio_into_chunks(audio_data, chunk_seconds=10)
        self.assertEqual(len(chunks), 1)
        self.assertIsInstance(chunks[0], io.BytesIO)

        # Valida que o chunk é um WAV válido
        chunks[0].seek(0)
        data, sr = sf.read(chunks[0])
        self.assertEqual(sr, 16000)
        self.assertEqual(len(data), 16000 * 5)

    def test_split_audio_long_multiple_chunks(self):
        # 25 segundos de áudio com chunk_seconds=10 -> 3 chunks (10s, 10s, 5s)
        audio_data = np.zeros((16000 * 25,), dtype=np.float32)
        chunks = self.audio_mgr.split_audio_into_chunks(audio_data, chunk_seconds=10)
        self.assertEqual(len(chunks), 3)

        # Checa tamanho do primeiro chunk (10s = 160.000 amostras)
        chunks[0].seek(0)
        data0, _sr0 = sf.read(chunks[0])
        self.assertEqual(len(data0), 16000 * 10)

        # Checa tamanho do terceiro chunk (5s = 80.000 amostras)
        chunks[2].seek(0)
        data2, _sr2 = sf.read(chunks[2])
        self.assertEqual(len(data2), 16000 * 5)

    def test_transcribe_chunks_joins_text(self):
        service = GroqService(api_key="gsk_test")
        chunk1 = io.BytesIO(b"RIFFdummy1")
        chunk2 = io.BytesIO(b"RIFFdummy2")

        progress_calls = []
        def _prog(cur, tot):
            progress_calls.append((cur, tot))

        with patch.object(service, "transcribe", side_effect=["Primeira parte da reunião.", "Segunda parte e conclusão."]):
            res = service.transcribe_chunks([chunk1, chunk2], "contexto", progress_callback=_prog)

        self.assertIn("Primeira parte da reunião.", res)
        self.assertIn("Segunda parte e conclusão.", res)
        self.assertEqual(progress_calls, [(1, 2), (2, 2)])

    def test_transcribe_file_not_found(self):
        service = GroqService(api_key="gsk_test")
        with self.assertRaises(FileNotFoundError):
            service.transcribe_file("arquivo_inexistente_12345.mp3", "contexto")

    def test_transcribe_file_without_key_raises(self):
        service = GroqService(api_key="")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFFdummy")
            tmp_path = tmp.name

        try:
            with self.assertRaises(ValueError):
                service.transcribe_file(tmp_path, "contexto")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_transcribe_file_direct_upload(self):
        service = GroqService(api_key="gsk_test")
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Transcrição do arquivo de áudio bem-sucedida."
        mock_client.audio.transcriptions.create.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(b"ID3dummydata")
            tmp_path = tmp.name

        progress_msgs = []
        def _prog(msg):
            progress_msgs.append(msg)

        try:
            with patch.object(service, "get_client", return_value=mock_client):
                res = service.transcribe_file(tmp_path, "contexto", progress_callback=_prog)

            self.assertEqual(res, "Transcrição do arquivo de áudio bem-sucedida.")
            mock_client.audio.transcriptions.create.assert_called_once()
            self.assertTrue(len(progress_msgs) > 0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


    def test_arquivo_grande_a_48k_e_fatiado_a_16k(self):
        """Fatiado na taxa nativa, cada bloco de 10 min de um MP3 de 48 kHz passava dos 25 MB."""
        import numpy as np
        import soundfile as sf
        service = GroqService(api_key="gsk_test")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        sf.write(tmp_path, np.zeros(48000 * 245, dtype=np.float32), 48000, subtype="PCM_16")  # ~23,5 MB
        try:
            with patch.object(service, "get_client", return_value=MagicMock()), \
                 patch.object(service, "transcribe_chunks", return_value="ok") as chunks:
                service.transcribe_file(tmp_path, "contexto")

            partes = chunks.call_args.args[0]
            for parte in partes:
                parte.seek(0)
                info = sf.info(parte)
                self.assertEqual(16000, info.samplerate)
                self.assertLess(parte.getbuffer().nbytes, 25 * 1024 * 1024)
            self.assertEqual(16000 * 245, sum(sf.info(p).frames for p in partes if not p.seek(0)))
        finally:
            os.remove(tmp_path)

    def test_split_audio_finds_silence_valley(self):
        # 12 segundos a 16000 Hz. Bloco de 10s.
        # Amostras de 0 a 8s: sinal alto (0.8)
        # Amostras de 8.5s a 9.5s: vale de silêncio (0.01)
        # Amostras de 9.5s a 12s: sinal alto (0.8)
        sr = 16000
        audio = np.full(sr * 12, 0.8, dtype=np.float32)
        audio[int(sr * 8.5):int(sr * 9.5)] = 0.01

        chunks = self.audio_mgr.split_audio_into_chunks(audio, chunk_seconds=10)
        self.assertEqual(len(chunks), 2)

        # O corte deve ter ocorrido próximo ao silêncio (~9s), e não exatamente nos 10s
        chunks[0].seek(0)
        data0, _ = sf.read(chunks[0])
        duracao_chunk0 = len(data0) / sr
        self.assertAlmostEqual(duracao_chunk0, 9.0, delta=0.6)


class TestBlocosJaTranscritos(unittest.TestCase):
    def test_pula_os_blocos_feitos_e_avisa_os_novos(self):
        service = GroqService(api_key="gsk_test")
        novos = []
        with patch.object(service, "transcribe", side_effect=["parte 2"]) as transcribe:
            res = service.transcribe_chunks(
                [io.BytesIO(b"c0"), io.BytesIO(b"c1"), io.BytesIO(b"c2")], "contexto",
                ja_transcritos={0: "parte 0", 1: "parte 1"},
                ao_transcrever=lambda i, t: novos.append((i, t)),
            )
        self.assertEqual("parte 0\n\nparte 1\n\nparte 2", res)
        self.assertEqual(1, transcribe.call_count)
        self.assertEqual([(2, "parte 2")], novos)


if __name__ == "__main__":
    unittest.main()


