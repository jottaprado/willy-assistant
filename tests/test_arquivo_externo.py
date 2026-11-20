"""
Transcrever arquivo e os modos reunião e prompt: idioma, fatiamento na pausa, .m4a grande,
reserva do is_processing e aviso de ata ausente.

- O idioma de entrada dos Ajustes não ia na reunião, no prompt e no arquivo: o Whisper
  adivinhava pelo começo do áudio.
- O arquivo grande era cortado seco a cada 10 min, partindo a palavra da fronteira; a reunião
  gravada já usava o fatiador que procura a pausa.
- Um .m4a acima de 22 MB caía no "Format not recognised" da libsndfile.
- O is_processing do arquivo era conferido e reservado fora do lock.
- A ata que falhava ia para o histórico como transcrição crua, sem aviso.
"""

import io
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from core.groq_service import FalhaDoLLM, GroqService
from core.pipeline.transcription_pipeline import _ATA_AUSENTE
from tests.test_fila_audio_falho import _Pipeline
from tests.willy_isolado import _funcao_do_willy


class TestTranscribeFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = GroqService(api_key="gsk_test")
        self.cliente = MagicMock()
        self.cliente.audio.transcriptions.create.return_value = SimpleNamespace(text=" ok ")
        cliente = patch.object(self.service, "get_client", return_value=self.cliente)
        cliente.start()
        self.addCleanup(cliente.stop)

    def _arquivo(self, nome):
        caminho = os.path.join(self.tmp, nome)
        with open(caminho, "wb") as f:
            f.write(b"RIFF....WAVE")
        return caminho

    def test_arquivo_pequeno_vai_com_o_idioma(self):
        for idioma, esperado in (("pt", "pt"), ("EN", "en")):
            with self.subTest(idioma=idioma):
                self.service.transcribe_file(self._arquivo("a.mp3"), "ctx", language=idioma)
                self.assertEqual(esperado, self.cliente.audio.transcriptions.create.call_args.kwargs["language"])

    def test_auto_deixa_o_whisper_detectar(self):
        for idioma in ("auto", None, ""):
            with self.subTest(idioma=idioma):
                self.service.transcribe_file(self._arquivo("a.mp3"), "ctx", language=idioma)
                self.assertNotIn("language", self.cliente.audio.transcriptions.create.call_args.kwargs)

    def test_m4a_grande_explica_o_que_fazer(self):
        caminho = os.path.join(self.tmp, "reuniao.M4A")
        with open(caminho, "wb") as f:
            f.truncate(23 * 1024 * 1024)
        with patch("soundfile.read") as ler, self.assertRaisesRegex(ValueError, r"\.m4a acima de 22 MB: converta para \.mp3"):
            self.service.transcribe_file(caminho, "ctx")
        ler.assert_not_called()

    def test_arquivo_grande_corta_na_pausa_e_leva_o_idioma(self):
        # 750 s a 16 kHz (24 MB), com fala (ruído) em tudo menos uma pausa entre 597 e 598 s.
        audio = np.random.default_rng(0).uniform(-0.3, 0.3, 16000 * 750).astype(np.float32)
        audio[597 * 16000:598 * 16000] = 0
        caminho = os.path.join(self.tmp, "longo.wav")
        sf.write(caminho, audio, 16000, subtype="PCM_16")
        with patch.object(self.service, "transcribe_chunks", return_value="ok") as blocos:
            self.service.transcribe_file(caminho, "Vocabulário: Willy, Kubernetes", language="pt")
        primeiro = blocos.call_args.args[0][0]
        primeiro.seek(0)
        duracao = sf.info(primeiro).duration
        self.assertTrue(597 <= duracao <= 598, duracao)
        self.assertEqual("pt", blocos.call_args.kwargs["language"])
        prompt_passado = (
            blocos.call_args.args[1]
            if len(blocos.call_args.args) > 1
            else blocos.call_args.kwargs.get("prompt_context")
        )
        self.assertEqual("Vocabulário: Willy, Kubernetes", prompt_passado)

    def test_blocos_vao_com_o_idioma(self):
        with patch.object(self.service, "transcribe", return_value="t") as transcrever:
            self.service.transcribe_chunks([io.BytesIO(b"a"), io.BytesIO(b"b")], "ctx", language="pt")
        self.assertEqual(["pt", "pt"], [c.kwargs["language"] for c in transcrever.call_args_list])

    def test_blocos_vao_com_o_prompt(self):
        with patch.object(self.service, "transcribe", return_value="t") as transcrever:
            self.service.transcribe_chunks(
                [io.BytesIO(b"a"), io.BytesIO(b"b")], "Vocabulário: Willy, Kubernetes", language="pt"
            )
        self.assertEqual(
            ["Vocabulário: Willy, Kubernetes", "Vocabulário: Willy, Kubernetes"],
            [
                c.args[1] if len(c.args) > 1 else c.kwargs.get("prompt_context", c.kwargs.get("prompt"))
                for c in transcrever.call_args_list
            ],
        )
        with patch.object(self.service, "translate", return_value="t") as traduzir:
            self.service.transcribe_chunks(
                [io.BytesIO(b"a"), io.BytesIO(b"b")], "Vocabulário: Willy, Kubernetes", traduzir=True
            )
        self.assertEqual(
            ["Vocabulário: Willy, Kubernetes", "Vocabulário: Willy, Kubernetes"],
            [
                c.args[1] if len(c.args) > 1 else c.kwargs.get("prompt_context", c.kwargs.get("prompt"))
                for c in traduzir.call_args_list
            ],
        )


class TestModosComIdioma(_Pipeline):
    def setUp(self):
        super().setUp()
        self.pipeline.config_mgr.input_language = "pt"

    def test_reuniao_curta(self):
        self._rodar(b"RIFFreuniao", "meeting")
        self.assertEqual("pt", self.groq_service.transcribe.call_args.kwargs["language"])

    def test_reuniao_fatiada(self):
        wav = io.BytesIO()
        sf.write(wav, np.zeros(16000 * 660, dtype=np.float32), 16000, format="WAV", subtype="PCM_16")  # 21 MB
        self.groq_service.transcribe_chunks.return_value = "texto da reunião"
        self._rodar(wav.getvalue(), "meeting")
        self.assertEqual("pt", self.groq_service.transcribe_chunks.call_args.kwargs["language"])

    def test_prompt(self):
        self.groq_service.generate_agent_prompt.return_value = "/goal entregar"
        with patch("core.pipeline.transcription_pipeline.ContextManager.get_git_context", return_value=""):
            self._rodar(b"RIFFpedido", "prompt")
        self.assertEqual("pt", self.groq_service.transcribe.call_args.kwargs["language"])


class _LockQueRegistra:
    def __init__(self):
        self.preso = False

    def __enter__(self):
        self.preso = True

    def __exit__(self, *_a):
        self.preso = False


class _AudioMgr:
    """Registra cada escrita do is_processing e se o lock estava preso nela."""

    def __init__(self):
        self.lock, self.is_recording, self._processando, self.escritas = _LockQueRegistra(), False, False, []

    @property
    def is_processing(self):
        return self._processando

    @is_processing.setter
    def is_processing(self, valor):
        self.escritas.append((valor, self.lock.preso))
        self._processando = valor


class TestTranscreverArquivoExterno(unittest.TestCase):
    def setUp(self):
        self.audio, self.groq = _AudioMgr(), MagicMock()
        self.groq.transcribe_file.return_value = "texto cru da reunião"

    def _transcrever(self, gerar_ata=False, privado=True, replacements=None):
        from core.text_processing import TextProcessor
        config = SimpleNamespace(groq_api_key="gsk_x", get_prompt_context=lambda: "ctx", input_language="pt",
                                 clean_fillers=False, private_mode=privado,
                                 load_replacements=lambda: dict(replacements or {}),
                                 save_output_file=MagicMock(return_value=None), save_history_item=MagicMock())
        transcrever = _funcao_do_willy(
            "transcrever_arquivo_externo", Optional=Optional, config_mgr=config, sound_mgr=MagicMock(),
            atualizar_ui=MagicMock(), audio_mgr=self.audio, groq_service=self.groq, TextProcessor=TextProcessor,
            FalhaDoLLM=FalhaDoLLM, _ATA_AUSENTE=_ATA_AUSENTE, sincronizar_bandeja=MagicMock(), dashboard=None,
            safe_dispatch_ui=MagicMock())
        with patch("core.actions.ActionManager.secure_copy", return_value=True) as self.copiar:
            return transcrever("C:/reuniao.mp3", gerar_ata=gerar_ata)

    def test_copia_aparece_no_win_v_fora_do_modo_privado(self):
        # A pessoa pediu o arquivo transcrito: é uma cópia pedida (decisão do dono, 24/10).
        for privado, oculta in ((False, False), (True, True)):
            with self.subTest(privado=privado):
                self._transcrever(privado=privado)
                self.assertIs(oculta, self.copiar.call_args.kwargs["ocultar_do_historico"])

    def test_vai_com_o_idioma(self):
        self._transcrever()
        self.assertEqual("pt", self.groq.transcribe_file.call_args.kwargs["language"])

    def test_reserva_e_libera_sob_o_lock(self):
        self._transcrever()
        self.assertEqual([(True, True), (False, True)], self.audio.escritas)

    def test_ata_que_falha_vai_com_o_aviso(self):
        self.groq.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto cru da reunião")
        texto = self._transcrever(gerar_ata=True)
        self.assertEqual(_ATA_AUSENTE + "texto cru da reunião", texto)
        self.assertTrue(self.groq.summarize_meeting.call_args.kwargs["estrito"])

    def test_aplica_substituicoes_do_dicionario(self):
        texto = self._transcrever(replacements={"reunião": "Reunião Geral"})
        self.assertEqual("texto cru da Reunião Geral", texto)
        self.copiar.assert_called_once_with("texto cru da Reunião Geral", ocultar_do_historico=True)

    def test_delega_ao_pipeline_salva_duracao_audio_path_e_loga_erro_de_replacements(self):
        """AUD-006, AUD-033 e AUD-149: fatiador unificado, delegação ao pipeline com duracao_s/audio_path e log em replacements."""
        import contextlib

        from core.audio_processing import dsp

        self.assertTrue(hasattr(dsp, "fatiar_audio_para_whisper"))
        buf_stereo = io.BytesIO()
        sf.write(buf_stereo, np.zeros((48000 * 2, 2), dtype=np.float32), 48000, format="WAV", subtype="PCM_16")
        partes = dsp.fatiar_audio_para_whisper(buf_stereo, chunk_seconds=600)
        self.assertEqual(len(partes), 1)
        partes[0].seek(0)
        self.assertEqual(sf.info(partes[0]).samplerate, 16000)

        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(raiz, "willy.py"), encoding="utf-8") as f:
            self.assertNotIn("_ATA_AUSENTE", f.read())

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        wav_path = os.path.join(tmp_dir, "gravacao_externa.wav")
        sf.write(wav_path, np.zeros(16000 * 3, dtype=np.float32), 16000, subtype="PCM_16")

        save_history = MagicMock()
        config = SimpleNamespace(
            groq_api_key="gsk_x", get_prompt_context=lambda: "ctx", input_language="pt",
            clean_fillers=False, private_mode=False,
            load_replacements=MagicMock(side_effect=RuntimeError("falha no disco")),
            save_output_file=MagicMock(return_value=os.path.join(tmp_dir, "saida.md")),
            save_history_item=save_history,
        )
        transcrever = _funcao_do_willy(
            "transcrever_arquivo_externo", Optional=Optional, config_mgr=config, sound_mgr=MagicMock(),
            atualizar_ui=MagicMock(), audio_mgr=self.audio, groq_service=self.groq,
            sincronizar_bandeja=MagicMock(), dashboard=None, safe_dispatch_ui=MagicMock(),
        )
        stderr_buf = io.StringIO()
        with patch("core.actions.ActionManager.secure_copy", return_value=True), \
             contextlib.redirect_stderr(stderr_buf):
            res = transcrever(wav_path, gerar_ata=False)

        self.assertEqual(res, "texto cru da reunião")
        self.assertIn("falha no disco", stderr_buf.getvalue())
        save_history.assert_called_once()
        kwargs = save_history.call_args.kwargs
        self.assertEqual(kwargs.get("audio_path"), wav_path)
        self.assertAlmostEqual(kwargs.get("duracao_s"), 3.0, places=1)


if __name__ == "__main__":
    unittest.main()
