"""
Testes unitários para o módulo modular core.pipeline.transcription_pipeline.
Testa os fluxos de validação, transcrição, tradução, reunião, prompt, injeção e tratamento de erros.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.pipeline import PipelineContext, TranscriptionPipeline


class FakeLock:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class TestTranscriptionPipeline(unittest.TestCase):
    """Testes do orquestrador desacoplado TranscriptionPipeline."""

    def setUp(self):
        # Fora do Willy e do shell: com uma janela Tk deste processo na frente, ou a área de
        # trabalho, o ditado sem alvo seria copiado.
        for funcao in ("_foco_numa_janela_do_willy", "_foco_no_shell"):
            foco = patch(f"core.pipeline.transcription_pipeline.{funcao}", return_value=False)
            foco.start()
            self.addCleanup(foco.stop)
        self.tmp_dir = tempfile.mkdtemp()
        self.failed_audio = os.path.join(self.tmp_dir, "failed.wav")

        self.groq_service = MagicMock()
        self.config_mgr = MagicMock()
        self.audio_mgr = MagicMock()
        self.injector = MagicMock()
        self.sound_mgr = MagicMock()
        self.snippet_mgr = MagicMock()
        self.snippet_mgr.match_and_expand.return_value = None
        self.tts_mgr = MagicMock()

        self.audio_mgr.lock = FakeLock()
        self.audio_mgr.is_processing = False

        self.config_mgr.groq_api_key = "gsk_test_key_valid_123456"
        self.config_mgr.get_prompt_context.return_value = "Contexto de teste"
        self.config_mgr.refine_prompt = True
        self.config_mgr.clipboard_only = False
        self.config_mgr.private_mode = False
        self.config_mgr.clean_fillers = True
        self.config_mgr.load_replacements.return_value = {}

        self.ui_status = []
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq_service,
            config_mgr=self.config_mgr,
            audio_mgr=self.audio_mgr,
            injector=self.injector,
            sound_mgr=self.sound_mgr,
            snippet_mgr=self.snippet_mgr,
            tts_mgr=self.tts_mgr,
            ui_notifier=lambda st, msg=None: self.ui_status.append((st, msg)),
            failed_audio_path=self.failed_audio,
            user_data_dir=self.tmp_dir,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pipeline_chave_invalida(self):
        """Verifica recusa imediata quando chave da Groq não está configurada."""
        self.config_mgr.groq_api_key = ""
        ctx = PipelineContext(wav_bytes=b"RIFFdummydata", modo="transcribe")
        res = self.pipeline.process(ctx)

        self.assertFalse(res.success)
        self.assertEqual(res.error_category, "invalid_key")
        self.sound_mgr.sound_error.assert_called_once()
        # Recusa sem chamar a Groq, e o áudio fica na fila (ver test_fila_audio_falho).
        self.assertIn(("error", "Configure sua chave Groq: o áudio ficou salvo"), self.ui_status)
        self.groq_service.transcribe.assert_not_called()

    def test_pipeline_transcricao_normal(self):
        """Verifica fluxo completo de ditado normal com refino e injeção."""
        self.groq_service.transcribe.return_value = "olá mundo"
        self.groq_service.refine_text.return_value = "Olá, mundo!"

        ctx = PipelineContext(wav_bytes=b"RIFFaudiobytes123", modo="transcribe")
        res = self.pipeline.process(ctx)

        self.assertTrue(res.success)
        self.assertEqual(res.text, "Olá, mundo!")
        self.assertEqual(res.action_type, "paste")
        self.assertEqual("Contexto de teste", self.groq_service.transcribe.call_args.args[1])
        self.injector.paste_text.assert_called_once_with("Olá, mundo!", auto_send=False)
        self.sound_mgr.sound_success.assert_called_once()
        self.config_mgr.save_history_item.assert_called_once()



    def test_pipeline_aplica_substituicoes_foneticas_no_texto_entregue(self):
        self.groq_service.transcribe.return_value = "subir os dockers agora"
        self.groq_service.refine_text.return_value = "Subir os dockers agora."
        self.config_mgr.load_replacements.return_value = {"dockers": "Docker"}

        ctx = PipelineContext(wav_bytes=b"RIFFaudiobytes123", modo="transcribe")
        res = self.pipeline.process(ctx)

        self.assertTrue(res.success)
        self.assertEqual("Subir os Docker agora.", res.text)
        self.injector.paste_text.assert_called_once_with("Subir os Docker agora.", auto_send=False)

    def test_pipeline_on_pill_text_informa_colado_apenas_quando_injetado_com_sucesso(self):
        chamadas_pill = []
        self.pipeline.on_pill_text = lambda txt, colado=True: chamadas_pill.append((txt, colado))
        self.groq_service.transcribe.return_value = "olá mundo"
        self.groq_service.refine_text.return_value = "Olá, mundo!"

        # 1. Colagem normal bem-sucedida -> colado=True
        self.injector.paste_text.return_value = True
        self.pipeline.process(PipelineContext(wav_bytes=b"RIFF1", modo="transcribe"))
        self.assertEqual([("Olá, mundo!", True)], chamadas_pill)

        # 2. Modo apenas copiar (clipboard_only=True) -> colado=False (não pode acionar Ctrl+Z no desfazer)
        chamadas_pill.clear()
        self.config_mgr.clipboard_only = True
        with patch("core.pipeline.transcription_pipeline.ActionManager.secure_copy", return_value=True):
            self.pipeline.process(PipelineContext(wav_bytes=b"RIFF2", modo="transcribe"))
        self.assertEqual([("Olá, mundo!", False)], chamadas_pill)

        # 3. Colagem falhou (clipboard ocupado) -> colado=False
        chamadas_pill.clear()
        self.config_mgr.clipboard_only = False
        self.injector.paste_text.return_value = False
        self.pipeline.process(PipelineContext(wav_bytes=b"RIFF3", modo="transcribe"))
        self.assertEqual([("Olá, mundo!", False)], chamadas_pill)

    def test_pipeline_modo_translate(self):
        """Verifica transcrição com tradução simultânea para o inglês."""
        self.groq_service.translate.return_value = "Hello world"

        ctx = PipelineContext(wav_bytes=b"RIFFaudio", modo="translate")
        res = self.pipeline.process(ctx)

        self.assertTrue(res.success)
        self.assertEqual(res.text, "Hello world")
        self.groq_service.translate.assert_called_once()
        self.injector.paste_text.assert_called_once_with("Hello world", auto_send=False)

    def test_pipeline_modo_meeting(self):
        """Verifica transcrição e geração de Ata Executiva no modo reunião."""
        self.groq_service.transcribe.return_value = "Discussão de sprint e backlog"
        self.groq_service.summarize_meeting.return_value = "# Ata Executiva\n- Ponto 1"

        ctx = PipelineContext(wav_bytes=b"RIFFaudio", modo="meeting")
        res = self.pipeline.process(ctx)

        self.assertTrue(res.success)
        self.assertIn("# Ata Executiva", res.text)
        self.groq_service.summarize_meeting.assert_called_once()

    def test_pipeline_modo_prompt(self):
        """Verifica estruturação de missão de agente no modo prompt."""
        self.groq_service.transcribe.return_value = "crie um botão azul"
        self.groq_service.generate_agent_prompt.return_value = "/goal Criar botão com design system"

        ctx = PipelineContext(wav_bytes=b"RIFFaudio", modo="prompt")
        res = self.pipeline.process(ctx)

        self.assertTrue(res.success)
        self.assertTrue(res.text.startswith("/goal"))
        self.groq_service.generate_agent_prompt.assert_called_once()

    def test_pipeline_clipboard_only(self):
        """Verifica cópia para clipboard sem colar quando clipboard_only está ativo."""
        self.config_mgr.clipboard_only = True
        self.groq_service.transcribe.return_value = "texto confidencial"
        self.groq_service.refine_text.return_value = "Texto confidencial."

        with patch("core.actions.ActionManager.secure_copy", return_value=True) as mock_copy:
            ctx = PipelineContext(wav_bytes=b"RIFFaudio", modo="transcribe")
            res = self.pipeline.process(ctx)

            self.assertTrue(res.success)
            self.assertEqual(res.action_type, "copy")
            mock_copy.assert_called_once_with("Texto confidencial.")
            self.injector.paste_text.assert_not_called()

    def test_pipeline_erro_rede_salva_audio_offline(self):
        """Verifica que falha de rede persiste o áudio no disco e sinaliza offline_retry."""
        self.groq_service.transcribe.side_effect = ConnectionError("Failed to connect to api.groq.com")

        ctx = PipelineContext(wav_bytes=b"RIFFimportant_audio", modo="transcribe")
        res = self.pipeline.process(ctx)

        self.assertFalse(res.success)
        self.assertEqual(res.error_category, "offline_retry")
        # Vai para a fila de reenvio (ver test_fila_audio_falho), não para o arquivo avulso.
        caminho, modo = self.pipeline.fila.mais_recente()
        self.assertEqual("transcribe", modo)
        with open(caminho, "rb") as f:
            self.assertEqual(f.read(), b"RIFFimportant_audio")
        self.sound_mgr.sound_error.assert_called_once()

    def test_pipeline_concorrencia_rejeita_quando_ocupado(self):
        """Garante que o pipeline não executa em paralelo se já estiver processando."""
        self.audio_mgr.is_processing = True
        ctx = PipelineContext(wav_bytes=b"RIFFaudio", modo="transcribe")
        res = self.pipeline.process(ctx)

        self.assertFalse(res.success)
        self.assertEqual(res.error_message, "Pipeline ocupado")
        self.groq_service.transcribe.assert_not_called()

    def test_falha_de_persistencia_depois_de_colar_nao_vira_erro_de_transcricao(self):
        """Com o texto já colado, cair em _tratar_erro ofereceria um retry que cola de novo."""
        self.groq_service.transcribe.return_value = "texto ditado"
        self.groq_service.refine_text.return_value = "Texto ditado."
        self.config_mgr.save_history_item.side_effect = OSError("histórico não gravado")

        res = self.pipeline.process(PipelineContext(wav_bytes=b"RIFFaudio", modo="transcribe"))

        self.assertTrue(res.success)
        self.assertIsNone(res.error_category)
        self.injector.paste_text.assert_called_once()
        self.assertFalse(os.path.exists(self.failed_audio), "áudio salvo p/ retry de algo já entregue")
        self.assertNotIn("offline_retry", [st for st, _ in self.ui_status])
        self.assertIn(("error", "Texto entregue, mas o histórico não foi salvo"), self.ui_status)

    def test_colagem_que_falha_avisa_e_guarda_o_texto_no_historico(self):
        """Clipboard ocupado: nada foi colado, então nada de som de sucesso."""
        self.groq_service.transcribe.return_value = "texto ditado"
        self.groq_service.refine_text.return_value = "Texto ditado."
        self.injector.paste_text.return_value = False

        self.pipeline.process(PipelineContext(wav_bytes=b"RIFFaudio", modo="transcribe"))

        self.sound_mgr.sound_success.assert_not_called()
        self.sound_mgr.sound_error.assert_called_once()
        self.assertIn(("error", "Não consegui colar. O texto ficou no histórico"), self.ui_status)
        self.config_mgr.save_history_item.assert_called_once()




    def test_estado_mutavel_isolado_entre_threads_concorrentes(self):
        """AUD-034: Estado transitório (_texto_cru, _falha_llm, _blocos, _regra_do_app) deve ser isolado por thread/execução."""
        import threading

        from core.groq_service import FalhaDoLLM

        barreira = threading.Barrier(2)
        observado_t1 = {}
        observado_t2 = {}

        def _worker1():
            self.pipeline._texto_cru = "texto_thread_1"
            self.pipeline._falha_llm = FalhaDoLLM("refino", "reserva_1")
            self.pipeline._blocos = {0: "bloco_1"}
            barreira.wait(timeout=2.0)
            barreira.wait(timeout=2.0)
            observado_t1["texto_cru"] = self.pipeline._texto_cru
            observado_t1["falha_llm"] = self.pipeline._falha_llm
            observado_t1["blocos"] = dict(self.pipeline._blocos)

        def _worker2():
            barreira.wait(timeout=2.0)
            self.pipeline._texto_cru = "texto_thread_2"
            self.pipeline._falha_llm = None
            self.pipeline._blocos = {0: "bloco_2"}
            barreira.wait(timeout=2.0)
            observado_t2["texto_cru"] = self.pipeline._texto_cru
            observado_t2["falha_llm"] = self.pipeline._falha_llm
            observado_t2["blocos"] = dict(self.pipeline._blocos)

        t1 = threading.Thread(target=_worker1)
        t2 = threading.Thread(target=_worker2)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        self.assertEqual(observado_t1["texto_cru"], "texto_thread_1")
        self.assertIsNotNone(observado_t1["falha_llm"])
        self.assertEqual(observado_t1["blocos"], {0: "bloco_1"})
        self.assertEqual(observado_t2["texto_cru"], "texto_thread_2")
        self.assertIsNone(observado_t2["falha_llm"])
        self.assertEqual(observado_t2["blocos"], {0: "bloco_2"})

    def test_notificar_ui_loga_excecao_no_stderr(self):
        """AUD-156: Exceção em ui_notifier deve ser logada em sys.stderr sem interromper o pipeline."""
        import io
        from contextlib import redirect_stderr

        self.pipeline.ui_notifier = MagicMock(side_effect=RuntimeError("Falha de widget na UI"))
        err = io.StringIO()
        with redirect_stderr(err):
            self.pipeline._notificar_ui("processing", "Testando")
        self.assertIn("Falha de widget na UI", err.getvalue())

    def test_ata_falha_e_fila_guardar_lanca_excecao_nao_oferece_reenvio_falso(self):
        """AUD-157: Se a geração da ata falhar e fila.guardar levantar exceção, não pode exibir 'Clique p/ reenviar'."""
        from core.groq_service import FalhaDoLLM

        self.groq_service.transcribe.return_value = "Transcrição da reunião completa"
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM(
            "ata", "Transcrição da reunião completa", ConnectionError("offline")
        )
        self.injector.paste_text.return_value = True

        with patch.object(self.pipeline.fila, "guardar", side_effect=OSError("Disco cheio")):
            res = self.pipeline.process(PipelineContext(wav_bytes=b"RIFFreuniao", modo="meeting"))

        self.assertTrue(res.success)
        self.assertNotIn("offline_retry", [st for st, _ in self.ui_status])
        self.assertIn(("error", "Ata não gerada (o áudio não pôde ser salvo)"), self.ui_status)


if __name__ == "__main__":
    unittest.main()
