"""
A velocidade nas métricas é medida, não a constante de 145 palavras/min.

O pipeline grava a duração de cada gravação no histórico (duration_s), e a métrica divide as
palavras dos ditados pelos minutos gravados. Prompt de agente, transformar e reunião ficam de
fora: o texto salvo ali não é a fala da pessoa.
"""

import io
import os
import tempfile
import unittest
import wave

import numpy as np

from core.analytics.metrics import calculate_analytics_metrics
from core.pipeline.transcription_pipeline import _segundos_do_wav
from core.storage.history_store import HistoryStore
from tests.test_fila_audio_falho import _Pipeline


def _wav(segundos, taxa=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(np.zeros(int(segundos * taxa), dtype=np.int16).tobytes())
    return buf.getvalue()


class TestDuracaoDaGravacao(unittest.TestCase):
    def test_duracao_do_wav(self):
        self.assertAlmostEqual(12.5, _segundos_do_wav(_wav(12.5)), places=3)
        self.assertAlmostEqual(3.0, _segundos_do_wav(_wav(3.0, taxa=48000)), places=3)

    def test_audio_ilegivel_nao_tem_duracao(self):
        self.assertIsNone(_segundos_do_wav(b"nao e um wav"))

    def test_o_historico_guarda_a_duracao(self):
        with tempfile.TemporaryDirectory() as pasta:
            store = HistoryStore(os.path.join(pasta, ".history.json"))
            (item,) = store.save_history_item("vamos subir o deploy hoje", modo="transcribe", duracao_s=2.04)
            self.assertEqual(2.0, item["duration_s"])
            (_, sem) = store.save_history_item("sem duração", modo="transcribe")
            self.assertNotIn("duration_s", sem)


class TestVelocidade(unittest.TestCase):
    def test_palavras_por_minuto_de_gravacao_nos_ditados(self):
        historico = [
            {"text": "x", "words": 60, "timestamp": "", "mode": "transcribe", "duration_s": 30},
            {"text": "x", "words": 30, "timestamp": "", "mode": "send", "duration_s": 30},
        ]
        self.assertEqual(90, calculate_analytics_metrics(historico)["avg_wpm"])  # 90 palavras em 1 min

    def test_texto_que_nao_e_a_fala_nao_conta(self):
        historico = [
            {"text": "x", "words": 60, "timestamp": "", "mode": "transcribe", "duration_s": 60},
            {"text": "x", "words": 900, "timestamp": "", "mode": "prompt", "duration_s": 10},
            {"text": "x", "words": 900, "timestamp": "", "mode": "transform", "duration_s": 10},
            {"text": "x", "words": 5000, "timestamp": "", "mode": "meeting", "duration_s": 600},
        ]
        self.assertEqual(60, calculate_analytics_metrics(historico)["avg_wpm"])

    def test_itens_sem_duracao_nao_entram_na_conta(self):
        historico = [
            {"text": "x", "words": 50, "timestamp": "", "mode": "transcribe", "duration_s": 30},
            {"text": "x", "words": 400, "timestamp": "", "mode": "transcribe"},
        ]
        self.assertEqual(100, calculate_analytics_metrics(historico)["avg_wpm"])

    def test_tempo_economizado_usa_a_velocidade_medida(self):
        # 1200 palavras: 30 min digitando a 40 wpm; faladas a 120 wpm medidos, 10 min.
        historico = [{"text": "x", "words": 1200, "timestamp": "", "mode": "transcribe", "duration_s": 600}]
        m = calculate_analytics_metrics(historico)
        self.assertEqual(120, m["avg_wpm"])
        self.assertEqual((0, 20), (m["saved_hours"], m["saved_minutes"]))


class TestPipelineGravaADuracao(_Pipeline):
    """Com a bancada do pipeline (Groq, colagem e config falsas) de test_fila_audio_falho."""

    def test_ditado_entregue_vai_ao_historico_com_a_duracao(self):
        self._rodar(_wav(4.0), "transcribe")
        kwargs = self.pipeline.config_mgr.save_history_item.call_args.kwargs
        self.assertAlmostEqual(4.0, kwargs["duracao_s"], places=2)


if __name__ == "__main__":
    unittest.main()
