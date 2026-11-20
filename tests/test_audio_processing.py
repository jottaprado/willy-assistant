"""
Testes unitários para o pacote core.audio_processing (DSP, VAD e Dispositivos).
"""

import io
import unittest

import numpy as np
import soundfile as sf

from core.audio_processing import (
    NoiseFloorTracker,
    compute_rms,
    convert_to_wav,
    get_input_devices,
    preencher,
    reamostrar,
    split_audio_into_chunks,
)


class TestAudioDevices(unittest.TestCase):
    def test_get_input_devices(self):
        fake_devices = [
            {"name": "Microfone USB", "max_input_channels": 2},
            {"name": "Fone de Ouvido", "max_input_channels": 0},
            {"name": "Mixagem Estéreo", "max_input_channels": 1},
        ]
        devices = get_input_devices(query_fn=lambda: fake_devices)
        self.assertEqual(2, len(devices))
        self.assertEqual((0, "Microfone USB"), devices[0])
        self.assertEqual((2, "Mixagem Estéreo"), devices[1])

    def test_get_input_devices_exception_handled(self):
        def faulty():
            raise RuntimeError("Hardware error")
        import sys
        from unittest.mock import patch

        stderr_falso = io.StringIO()
        with patch.object(sys, "stderr", stderr_falso):
            devices = get_input_devices(query_fn=faulty)
        self.assertIn("Hardware error", stderr_falso.getvalue())
        self.assertEqual([], devices)


class TestAudioVAD(unittest.TestCase):
    def test_compute_rms_empty_or_none(self):
        self.assertEqual(0.0, compute_rms(None))
        self.assertEqual(0.0, compute_rms(np.array([])))

    def test_compute_rms_values(self):
        zeros = np.zeros(100, dtype=np.float32)
        self.assertEqual(0.0, compute_rms(zeros))

        ones = np.ones(100, dtype=np.float32)
        self.assertAlmostEqual(1.0, compute_rms(ones), places=5)

    def test_noise_floor_tracker_lifecycle(self):
        tracker = NoiseFloorTracker(min_samples=3, calibracao_s=0.0)
        self.assertEqual(0.0, tracker.ambient_noise_floor)

        # O piso vale desde a 1ª amostra (antes, ficava em 0 até a 3ª: o deadlock da C920).
        self.assertAlmostEqual(0.01, tracker.update(0.01), places=4)
        self.assertAlmostEqual(0.015, tracker.update(0.02), places=4)
        self.assertAlmostEqual(0.02, tracker.update(0.03), places=4)
        self.assertTrue(tracker.calibrando)

        # Reset limpa o estado
        tracker.reset()
        self.assertEqual(0, len(tracker.noise_samples))
        self.assertEqual(0.0, tracker.ambient_noise_floor)
        self.assertTrue(tracker.calibrando)

    def test_adaptive_thresholds_normal_and_whisper(self):
        tracker = NoiseFloorTracker()
        # Sem ruído de fundo
        sp, sil = tracker.get_adaptive_thresholds(0.04, 0.02, is_whisper=False)
        self.assertEqual((0.04, 0.02), (sp, sil))

        # Com ruído de fundo significativo
        tracker.ambient_noise_floor = 0.05
        sp, sil = tracker.get_adaptive_thresholds(0.04, 0.02, is_whisper=False)
        self.assertAlmostEqual(0.05 * 3.3, sp, places=4)
        self.assertAlmostEqual(0.05 * 2.2, sil, places=4)

        # Modo Sussurro: os limiares base baixam, mas o piso continua valendo (com o ruído alto, o
        # silêncio fixo ficava abaixo do ruído e o ditado não terminava).
        sp_w, sil_w = tracker.get_adaptive_thresholds(0.04, 0.02, is_whisper=True)
        self.assertAlmostEqual(0.05 * 3.3, sp_w, places=4)
        self.assertAlmostEqual(0.05 * 2.2, sil_w, places=4)
        tracker.ambient_noise_floor = 0.0
        sp_w, sil_w = tracker.get_adaptive_thresholds(0.04, 0.02, is_whisper=True)
        self.assertAlmostEqual(0.04 * 0.45, sp_w, places=4)
        self.assertAlmostEqual(0.02 * 0.45, sil_w, places=4)

    def test_zeros_digitais_apos_fala_atualizam_histerese_e_descontam_som_sem_pausa(self):
        """AUD-022: Quadros de silêncio digital (zero=True) após fala contínua devem
        desligar _em_fala e descontar _som_sem_pausa_s quando o nível suavizado cai."""
        tracker = NoiseFloorTracker()
        while tracker.calibrando:
            tracker.update(0.01, 0.02)
        # Simula fala contínua acima de 3,3x o piso e de 0,025
        for _ in range(30):
            tracker.update(0.15, 0.02)
        self.assertTrue(tracker._em_fala)
        som_antes = tracker._som_sem_pausa_s
        self.assertGreater(som_antes, 0.2)

        # Microfone entra em silêncio digital (mute / noise gate = 0.0) por 300 ms (15 quadros)
        for _ in range(15):
            tracker.update(0.0, 0.02)
        self.assertEqual(0.0, tracker.nivel)
        self.assertFalse(tracker._em_fala)
        self.assertLess(tracker._som_sem_pausa_s, som_antes)

    def test_constantes_canonicas_exportadas_pelo_vad_sem_duplicacao(self):
        """AUD-020: FATOR_FALA, FATOR_SILENCIO, LIMIAR_FALA_BASE, LIMIAR_SILENCIO_BASE e ZERO_DIGITAL
        moram em core/audio_processing/vad.py e são importadas por dsp.py e diagnostico.py."""
        import ast
        import os

        from core.audio_processing import vad

        self.assertEqual(3.3, vad.FATOR_FALA)
        self.assertEqual(2.2, vad.FATOR_SILENCIO)
        self.assertEqual(0.009, vad.LIMIAR_FALA_BASE)
        self.assertEqual(0.005, vad.LIMIAR_SILENCIO_BASE)
        self.assertEqual(1e-4, vad.ZERO_DIGITAL)

        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for arq in ("dsp.py", "diagnostico.py"):
            caminho = os.path.join(raiz, "core", "audio_processing", arq)
            with open(caminho, encoding="utf-8") as f:
                arvore = ast.parse(f.read())
            imports_vad = [
                alias.name
                for node in ast.walk(arvore)
                if isinstance(node, ast.ImportFrom) and node.module == "vad"
                for alias in node.names
            ]
            for esperado in ("FATOR_FALA", "FATOR_SILENCIO", "LIMIAR_FALA_BASE", "LIMIAR_SILENCIO_BASE"):
                self.assertIn(esperado, imports_vad, f"{arq} deve importar {esperado} de .vad")


class TestAudioDSP(unittest.TestCase):
    def test_reamostrar_identity(self):
        audio = np.ones((100, 1), dtype=np.float32)
        self.assertIs(audio, reamostrar(audio, 16000, 16000))
        self.assertEqual(0, len(reamostrar(np.array([]), 16000, 48000)))

    def test_reamostrar_scaling(self):
        audio = np.ones((100, 1), dtype=np.float32)
        res = reamostrar(audio, 16000, 48000)
        self.assertEqual(300, len(res))

    def test_preencher(self):
        audio = np.ones((50, 1), dtype=np.float32)
        padded = preencher(audio, 100)
        self.assertEqual(100, len(padded))
        self.assertEqual(1.0, float(padded[49, 0]))
        self.assertEqual(0.0, float(padded[50, 0]))

        # Sem necessidade de preenchimento
        same = preencher(audio, 30)
        self.assertEqual(30, len(same))

    def test_convert_to_wav(self):
        audio = np.zeros(16000, dtype=np.float32)
        buf = convert_to_wav(audio, sample_rate=16000)
        self.assertIsInstance(buf, io.BytesIO)
        buf.seek(0)
        data, sr = sf.read(buf, dtype="float32")
        self.assertEqual(16000, sr)
        self.assertEqual(16000, len(data))

    def test_split_audio_into_chunks(self):
        # 15s de áudio em blocos de 5s -> 3 chunks
        audio = np.zeros(16000 * 15, dtype=np.float32)
        chunks = split_audio_into_chunks(audio, chunk_seconds=5, sample_rate=16000)
        self.assertEqual(3, len(chunks))
        for c in chunks:
            c.seek(0)
            data, sr = sf.read(c, dtype="float32")
            self.assertEqual(16000, sr)
            self.assertEqual(16000 * 5, len(data))

    def test_split_audio_into_chunks_usa_rms_real_na_janela_de_corte(self):
        """AUD-021: split_audio_into_chunks deve escolher o bloco de menor RMS real,
        e não menor média absoluta (MAV)."""
        sr = 1000
        # 10 s de áudio total com chunk_seconds = 6 -> janela de busca entre 3,0 s e 6,0 s (30 blocos de 100 amostras)
        audio = np.full(sr * 10, 0.30, dtype=np.float32)
        # Nos primeiros 29 blocos da janela (3,0 s a 5,9 s), colocamos pulsos esparsos:
        # 10 amostras em 0.50 e 90 amostras em 0.0 -> MAV = 0.05, mas RMS = sqrt(0.1 * 0.25) = 0.1581
        for b in range(29):
            ini = 3000 + b * 100
            audio[ini:ini + 100] = 0.0
            audio[ini:ini + 10] = 0.50
        # No bloco 20 (offset 2000 -> amostras 5000..5100), colocamos sinal constante de 0.08:
        # MAV = 0.08 (> 0.05), mas RMS = 0.08 (< 0.1581).
        audio[5000:5100] = 0.08

        chunks = split_audio_into_chunks(audio, chunk_seconds=6, sample_rate=sr)
        chunks[0].seek(0)
        bloco1, _ = sf.read(chunks[0], dtype="float32")
        # O corte pelo menor RMS deve cair no meio do bloco 5000..5100 -> 5050 amostras
        self.assertEqual(5050, len(bloco1))


if __name__ == "__main__":
    unittest.main()
