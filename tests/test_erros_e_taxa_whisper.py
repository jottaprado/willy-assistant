"""
Classificação tipada das falhas da Groq e envio a 16 kHz.

As exceções são as do SDK de verdade, montadas sobre respostas httpx, e não strings: a
classificação antiga casava substrings de str(exc) e mandava 413, 503 e bug interno para
o mesmo "sem internet, clique p/ reenviar".
"""

import ast
import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import groq
import httpx
import numpy as np
import soundfile as sf

from core.audio_processing.dsp import TAXA_WHISPER, convert_to_wav, para_taxa_whisper
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.pipeline.transcription_pipeline import _classificar_erro
from tests.willy_isolado import _erro_groq as _status
from tests.willy_isolado import _funcao_do_willy

_REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
_LIMITE_GROQ = 25 * 1024 * 1024


class TestClassificacaoPeloTipo(unittest.TestCase):
    def test_categorias(self):
        casos = {
            "arquivo grande demais (413)": (_status(groq.APIStatusError, 413), "bad_request"),
            "requisição inválida (400)": (_status(groq.BadRequestError, 400), "bad_request"),
            "prompt longo (400)": (_status(groq.BadRequestError, 400, "invalid_prompt: prompt length"),
                                   "prompt_length"),
            "limite (429)": (_status(groq.RateLimitError, 429), "rate_limit"),
            "chave inválida (401)": (_status(groq.AuthenticationError, 401), "invalid_key"),
            "sem permissão (403)": (_status(groq.PermissionDeniedError, 403), "invalid_key"),
            "Groq fora (503)": (_status(groq.InternalServerError, 503), "offline_retry"),
            "timeout do SDK": (groq.APITimeoutError(request=_REQ), "offline_retry"),
            "conexão do SDK": (groq.APIConnectionError(request=_REQ), "offline_retry"),
            "conexão nativa": (ConnectionError("Failed to connect"), "offline_retry"),
            "transporte httpx": (httpx.ConnectError("dns"), "offline_retry"),
            "bug nosso": (AttributeError("'NoneType' object has no attribute 'audio'"), "internal"),
            # A heurística antiga via "429" no texto e chamava isto de limite da Groq.
            "texto que parece HTTP": (ValueError("amostras 429 fora do intervalo"), "internal"),
            "timeout do servidor (408)": (_status(groq.APIStatusError, 408), "offline_retry"),
            "conflito (409)": (_status(groq.ConflictError, 409), "offline_retry"),
            "leitura lenta httpx": (httpx.ReadTimeout("lento"), "offline_retry"),
            "conexão cortada httpx": (httpx.RemoteProtocolError("cortou"), "offline_retry"),
        }
        for nome, (exc, esperado) in casos.items():
            with self.subTest(nome):
                self.assertEqual(esperado, _classificar_erro(exc))


class TestPipelineNaoPrometeRetryImpossivel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.groq_service = MagicMock()
        self.config_mgr = MagicMock()
        self.config_mgr.groq_api_key = "gsk_teste"
        self.config_mgr.clipboard_only = False
        self.config_mgr.private_mode = False
        self.config_mgr.load_replacements.return_value = {}
        self.audio_mgr = MagicMock()
        self.audio_mgr.is_processing = False
        self.ui = []
        snippet = MagicMock()
        snippet.match_and_expand.return_value = None
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq_service, config_mgr=self.config_mgr, audio_mgr=self.audio_mgr,
            injector=MagicMock(), sound_mgr=MagicMock(), snippet_mgr=snippet, tts_mgr=MagicMock(),
            ui_notifier=lambda st, msg=None: self.ui.append((st, msg)),
            failed_audio_path=os.path.join(self.tmp, "failed.wav"), user_data_dir=self.tmp,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _processar(self, exc):
        self.groq_service.transcribe.side_effect = exc
        return self.pipeline.process(PipelineContext(wav_bytes=b"RIFFaudio", modo="transcribe"))

    def test_413_nao_oferece_reenviar(self):
        res = self._processar(_status(groq.APIStatusError, 413))
        self.assertEqual("bad_request", res.error_category)
        self.assertNotIn("offline_retry", [st for st, _ in self.ui])
        self.assertIn(("error", "A Groq recusou o áudio (HTTP 413)"), self.ui)

    def test_limite_da_groq_oferece_reenviar(self):
        res = self._processar(_status(groq.RateLimitError, 429))
        self.assertEqual("rate_limit", res.error_category)
        self.assertEqual("offline_retry", self.ui[-1][0])

    def test_bug_interno_nao_se_passa_por_rede_e_deixa_traceback(self):
        res = self._processar(AttributeError("bug"))
        self.assertEqual("internal", res.error_category)
        self.assertNotIn("offline_retry", [st for st, _ in self.ui])
        with open(os.path.join(self.tmp, "willy_errors.log"), encoding="utf-8") as f:
            self.assertIn("Traceback", f.read())

    def test_reuniao_a_48k_e_fatiada_a_16k(self):
        """WAV salvo a 48 kHz (retry ou importado) virava blocos de 54,9 MB: todos 413."""
        audio = np.zeros(48000 * 60 * 4, dtype=np.float32)  # 4 min a 48 kHz: > 20 MB
        wav = convert_to_wav(audio, sample_rate=48000)
        self.audio_mgr.split_audio_into_chunks.return_value = [io.BytesIO(b"RIFF")]
        self.groq_service.transcribe_chunks.return_value = "ata"

        self.pipeline.process(PipelineContext(wav_bytes=wav, modo="meeting"))

        _, kwargs = self.audio_mgr.split_audio_into_chunks.call_args
        self.assertEqual(TAXA_WHISPER, kwargs["sample_rate"])
        enviado = self.audio_mgr.split_audio_into_chunks.call_args.args[0]
        self.assertEqual(16000 * 60 * 4, len(enviado))


class TestEnvioA16k(unittest.TestCase):
    def test_dez_minutos_a_48k_cabem_no_limite_da_groq(self):
        audio = np.zeros(48000 * 600, dtype=np.float32)
        wav = convert_to_wav(para_taxa_whisper(audio, 48000), sample_rate=TAXA_WHISPER)
        self.assertLess(wav.getbuffer().nbytes, _LIMITE_GROQ)
        wav.seek(0)
        self.assertEqual(TAXA_WHISPER, sf.info(wav).samplerate)

    def test_audio_ja_em_16k_nao_e_copiado(self):
        audio = np.zeros(1600, dtype=np.float32)
        self.assertIs(audio, para_taxa_whisper(audio, 16000))

    def test_willy_reamostra_antes_de_gerar_o_wav(self):
        """willy.py não é importável em teste (instância única, Tk): a ligação é checada no AST."""
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(raiz, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        funcao = next(n for n in ast.walk(arvore)
                      if isinstance(n, ast.FunctionDef) and n.name == "processar_transcricao")
        chamadas = [n for n in ast.walk(funcao) if isinstance(n, ast.Call)]
        nomes = [getattr(c.func, "attr", getattr(c.func, "id", "")) for c in chamadas]

        self.assertIn("para_taxa_whisper", nomes)
        self.assertLess(nomes.index("para_taxa_whisper"), nomes.index("convert_to_wav"))
        wav_call = chamadas[nomes.index("convert_to_wav")]
        taxa = {k.arg: k.value for k in wav_call.keywords}.get("sample_rate")
        self.assertIsNotNone(taxa, "convert_to_wav sem sample_rate usa a taxa do microfone")
        self.assertEqual("TAXA_WHISPER", getattr(taxa, "id", None))

    def test_willy_usa_a_taxa_da_gravacao_e_nao_a_do_microfone_atual(self):
        """Com troca de microfone adiada, actual_sample_rate já é a do device novo no stop."""
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(raiz, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        funcoes = {n.name: n for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)}

        chamadas_parar = {getattr(c.func, "attr", "") for c in ast.walk(funcoes["parar_gravacao"])
                          if isinstance(c, ast.Call)}
        self.assertIn("stop_recording_com_taxa", chamadas_parar)
        self.assertNotIn("stop_recording", chamadas_parar)
        lidos = {getattr(n, "attr", None) for n in ast.walk(funcoes["processar_transcricao"])}
        lidos |= {n.value for n in ast.walk(funcoes["processar_transcricao"]) if isinstance(n, ast.Constant)}
        self.assertNotIn("actual_sample_rate", lidos)

    def test_iniciar_gravacao_sai_antes_de_mexer_no_stream_se_ja_grava(self):
        """Com troca de mic pendente, ensure_stream reabriria o device novo no meio da gravação."""
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(raiz, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        funcao = next(n for n in ast.walk(arvore)
                      if isinstance(n, ast.FunctionDef) and n.name == "iniciar_gravacao")
        guarda = next(n for n in funcao.body if isinstance(n, ast.If))
        lidos = {getattr(n, "attr", None) for n in ast.walk(guarda.test)}
        self.assertIn("is_recording", lidos)
        self.assertIsInstance(guarda.body[0], ast.Return)
        linha_ensure = min(c.lineno for c in ast.walk(funcao)
                           if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "ensure_stream")
        self.assertLess(guarda.lineno, linha_ensure)

    def test_willy_reenvia_da_fila_o_audio_do_limite_da_groq(self):
        """A pílula de 429 é clicável: o clique tem que achar o áudio que o pipeline guardou.

        Antes o elo era o global last_failed_mode; agora é a fila do pipeline, e o reenvio
        leva o caminho do item para que só ele saia da fila.
        """
        tmp = tempfile.mkdtemp()
        try:
            pipeline = TranscriptionPipeline(
                groq_service=MagicMock(), config_mgr=MagicMock(), audio_mgr=MagicMock(),
                injector=MagicMock(), user_data_dir=tmp,
            )
            caminho = pipeline.fila.guardar(b"RIFFlimite", "meeting")
            threads = MagicMock()
            reenviar = _funcao_do_willy(
                "reenviar_ultimo_audio",
                transcription_pipeline=pipeline, threading=threads,
                atualizar_ui=MagicMock(), _executar_pipeline_transcricao="alvo",
                ContextManager=MagicMock(resolver_janela_alvo=lambda antes: (0, 0)),
                _janela_antes_do_willy=0, _foco_antes_do_willy=0,
            )
            reenviar()
            kwargs = threads.Thread.call_args.kwargs
            self.assertEqual((b"RIFFlimite", "meeting", True, caminho, (0, 0)), kwargs["args"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestReamostragem(unittest.TestCase):
    @staticmethod
    def _referencia(audio, origem, destino):
        """A implementação anterior (np.interp sobre posições normalizadas)."""
        n = round(len(audio) * destino / origem)
        x_orig = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        x_novo = np.linspace(0.0, 1.0, num=n, endpoint=False)
        if audio.ndim == 1:
            return np.interp(x_novo, x_orig, audio)
        return np.stack([np.interp(x_novo, x_orig, audio[:, c]) for c in range(audio.shape[1])], axis=1)

    def test_equivale_a_interpolacao_linear_de_referencia(self):
        from core.audio_processing import dsp
        rng = np.random.default_rng(7)
        casos = [(48000, 16000, (300_001,)), (16000, 48000, (70_001,)),
                 (44100, 16000, (88_200, 2)), (22050, 16000, (7,)), (16000, 44100, (5, 1))]
        for origem, destino, forma in casos:
            with self.subTest(origem=origem, destino=destino, forma=forma):
                audio = rng.uniform(-1, 1, forma).astype(np.float32)
                novo = dsp.reamostrar(audio, origem, destino)
                ref = self._referencia(audio, origem, destino)
                self.assertEqual(ref.shape, novo.shape)
                self.assertEqual(np.float32, novo.dtype)
                np.testing.assert_allclose(novo, ref, atol=1e-6)

    def test_audio_inteiro_nao_estoura_na_interpolacao(self):
        """Com int16, a diferença entre duas amostras (30000 - (-30000)) estourava."""
        from core.audio_processing import dsp
        audio = np.array([-30000, 30000] * 500, dtype=np.int16)
        novo = dsp.reamostrar(audio, 16000, 48000)
        ref = self._referencia(audio, 16000, 48000).astype(np.int16)
        self.assertEqual(np.int16, novo.dtype)
        self.assertLessEqual(int(np.max(np.abs(novo.astype(np.int32) - ref))), 1)

    def test_memoria_extra_nao_cresce_com_a_duracao(self):
        """O linspace em float64 da gravação inteira: 1 h a 48 kHz custava ~2,3 GB (MemoryError)."""
        import tracemalloc

        from core.audio_processing import dsp
        audio = np.zeros(48000 * 600, dtype=np.float32)  # 10 min a 48 kHz: 110 MiB
        tracemalloc.start()
        try:
            dsp.reamostrar(audio, 48000, 16000)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        # Saída (1/3 da entrada) + um bloco. A versão com linspace passava de 5x a entrada.
        self.assertLess(pico, 0.5 * audio.nbytes)


if __name__ == "__main__":
    unittest.main()
