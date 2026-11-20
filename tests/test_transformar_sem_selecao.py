"""
"Willy, resuma este contrato" sem texto selecionado não cola a frase do comando.

Sem seleção, transform_text devolvia vazio, o ramo do copiloto acabava, e o refino recebia
"Willy, resuma este contrato", polia e colava. Uma transformação que voltava vazia caía no mesmo
caminho.

No Ctrl+Alt+T segurado (e no reenvio), a seleção não vem do atalho: o pipeline a lê antes de
transcrever, e sem ela avisa em vez de terminar num "cancelado".
"""

from unittest.mock import patch

from core.actions import ActionManager
from core.pipeline import PipelineContext
from tests.test_fila_audio_falho import _Pipeline
from tests.test_velocidade_medida import _wav


class TestTransformarSemSelecao(_Pipeline):
    def _falar(self, selecao, resultado="Resumo."):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = "Willy, resuma este contrato"
        self.groq_service.transform_text.return_value = resultado
        with patch.object(ActionManager, "get_selected_text", return_value=selecao):
            return self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transcribe",
                                                         app_context=("code.exe", "editor", "general")))

    def test_sem_selecao_avisa_e_nao_cola(self):
        for selecao in (None, "", "   \n"):
            with self.subTest(selecao=selecao):
                self.ui.clear()
                self.injector.paste_text.reset_mock()
                self.groq_service.refine_text.reset_mock()
                self._falar(selecao)
                self.injector.paste_text.assert_not_called()
                self.groq_service.transform_text.assert_not_called()
                self.groq_service.refine_text.assert_not_called()
                self.assertIn(("error", "Selecione um texto antes de transformar"), self.ui)

    def test_sem_selecao_toca_o_som_de_erro(self):
        self._falar("")
        self.pipeline.sound_mgr.sound_error.assert_called()

    def test_transformacao_vazia_nao_cola_o_comando(self):
        self._falar("Contrato de 12 meses.", resultado="")
        self.injector.paste_text.assert_not_called()
        self.groq_service.refine_text.assert_not_called()
        self.assertIn(("error", "Não transformei: Groq não respondeu"), self.ui)

    def test_com_selecao_transforma(self):
        self._falar("Contrato de 12 meses.")
        self.assertEqual("Resumo.", self.injector.paste_text.call_args.args[0])


class TestModoTransformSemSelecaoDoAtalho(_Pipeline):
    def _transformar(self, selecao, soltou=True):
        ordem = []
        self.groq_service.transcribe.side_effect = lambda *_a, **_k: ordem.append("transcrição") or "deixe formal"
        self.groq_service.transform_text.return_value = "Prezados,"
        with patch.object(ActionManager, "get_selected_text", side_effect=lambda: ordem.append("seleção") or selecao), \
             patch.object(ActionManager, "esperar_modificadores_soltos", return_value=soltou) as self.espera:
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transform", selected_text=None,
                                                  app_context=("code.exe", "editor", "general")))
        return ordem

    def test_espera_mais_que_a_thread_do_atalho(self):
        # A gravação segurada pode acabar pelo silêncio com o Alt ainda preso.
        self._transformar("oi pessoal")
        (espera,) = self.espera.call_args.args
        self.assertGreaterEqual(espera, 1.0)

    def test_atalho_ainda_preso_guarda_o_audio_na_fila(self):
        # A instrução falada se perdia; na fila, o clique na pílula a reenvia com as teclas soltas.
        self.assertEqual([], self._transformar("oi pessoal", soltou=False))
        (item,) = self.fila.itens()
        self.assertEqual((item, "transform"), self.fila.mais_recente())
        self.assertEqual(("offline_retry", "Solte o atalho. Áudio salvo: clique p/ reenviar"), self.ui[-1])

    def test_atalho_ainda_preso_no_modo_privado_so_pede_para_soltar(self):
        self.pipeline.config_mgr.private_mode = True
        self.assertEqual([], self._transformar("oi pessoal", soltou=False))
        self.assertEqual([], self.fila.itens())
        self.assertEqual(("error", "Solte o atalho para transformar"), self.ui[-1])

    def test_reenvio_do_audio_guardado_transforma_a_selecao_de_agora(self):
        self._transformar("oi pessoal", soltou=False)
        (item,) = self.fila.itens()
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = "deixe formal"
        with patch.object(ActionManager, "get_selected_text", return_value="oi pessoal"), \
             patch.object(ActionManager, "esperar_modificadores_soltos", return_value=False):
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transform", is_retry=True,
                                                  retry_path=item, app_context=("code.exe", "editor", "general")))
        self.assertEqual("Prezados,", self.injector.paste_text.call_args.args[0])
        self.assertEqual([], self.fila.itens())

    def test_le_a_selecao_antes_de_transcrever(self):
        self.assertEqual(["seleção", "transcrição"], self._transformar("oi pessoal"))
        self.assertEqual("oi pessoal", self.groq_service.transform_text.call_args.args[0])
        self.assertEqual("Prezados,", self.injector.paste_text.call_args.args[0])

    def test_sem_selecao_avisa_sem_transcrever(self):
        for selecao in (None, "", "  "):
            with self.subTest(selecao=selecao):
                self.ui.clear()
                self.assertEqual(["seleção"], self._transformar(selecao))
                self.groq_service.transform_text.assert_not_called()
                self.assertIn(("error", "Selecione um texto antes de transformar"), self.ui)
