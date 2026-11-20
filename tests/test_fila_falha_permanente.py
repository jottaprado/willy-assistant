"""
Um reenvio que o LLM recusa de novo sai da fila; o que falhou por rede, limite ou 5xx fica.

Uma recusa, uma resposta vazia ou um 400 voltam iguais a cada reenvio do mesmo pedido. O item
ficava no topo da fila para sempre: cada clique reenviava sempre ele, e os de antes não eram
mais alcançados.
"""

import unittest
from unittest.mock import patch

import groq

from core.actions import ActionManager
from core.groq_service import FalhaDoLLM
from core.pipeline import PipelineContext
from tests.test_fila_audio_falho import _http, _Pipeline
from tests.test_velocidade_medida import _wav

ATA_RECUSADA = ("error", "Ata recusada pela Groq: saiu da fila")


class TestFalhaTransitoria(unittest.TestCase):
    def test_rede_limite_e_5xx_passam_sozinhos(self):
        for causa in (ConnectionError("offline"), _http(groq.RateLimitError, 429), _http(groq.InternalServerError, 503)):
            with self.subTest(causa=type(causa).__name__):
                self.assertTrue(FalhaDoLLM("ata", "", causa).transitoria)

    def test_recusa_vazio_e_400_nao(self):
        for causa in (None, _http(groq.BadRequestError, 400), _http(groq.NotFoundError, 404)):
            with self.subTest(causa=type(causa).__name__):
                self.assertFalse(FalhaDoLLM("ata", "", causa).transitoria)


class TestReenvioComFalhaPermanente(_Pipeline):
    def _na_fila(self, modo, fala="resuma isso"):
        self.groq_service.transcribe.side_effect = ConnectionError("offline")
        self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo=modo, selected_text="Contrato.",
                                              app_context=("code.exe", "editor", "general")))
        (item,) = self.fila.itens()
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = fala
        return item

    def _reenviar(self, item, modo):
        with patch.object(ActionManager, "get_selected_text", return_value="Contrato."), \
             patch.object(ActionManager, "process_action", return_value=None), \
             patch.object(ActionManager, "esperar_modificadores_soltos", return_value=True):
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo=modo, is_retry=True, retry_path=item,
                                                  app_context=("code.exe", "editor", "general")))

    def test_transformar_recusado_de_novo_sai_da_fila(self):
        item = self._na_fila("transform")
        self.groq_service.transform_text.side_effect = FalhaDoLLM("transformar", "", _http(groq.BadRequestError, 400))
        self._reenviar(item, "transform")
        self.assertEqual([], self.fila.itens())
        self.injector.paste_text.assert_not_called()

    def test_transformar_com_a_groq_fora_continua_na_fila(self):
        item = self._na_fila("transform")
        self.groq_service.transform_text.side_effect = FalhaDoLLM("transformar", "", ConnectionError("offline"))
        self._reenviar(item, "transform")
        self.assertEqual([item], self.fila.itens())

    def test_copiloto_recusado_de_novo_sai_da_fila(self):
        item = self._na_fila("transcribe", fala="Willy, explique o contrato")
        self._reenviar(item, "transcribe")
        self.assertEqual([], self.fila.itens())

    def test_ata_recusada_no_reenvio_entrega_e_sai_da_fila(self):
        item = self._na_fila("meeting", fala="texto da reunião")
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto da reunião")
        self._reenviar(item, "meeting")
        self.assertIn("texto da reunião", self.injector.paste_text.call_args.args[0])
        self.assertEqual([], self.fila.itens())
        self.assertEqual(ATA_RECUSADA, self.ui[-1])

    def test_ata_ja_entregue_e_recusada_de_novo_sai_da_fila(self):
        item = self._na_fila("meeting", fala="texto da reunião")
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto da reunião", ConnectionError("x"))
        self._reenviar(item, "meeting")  # a transcrição sai; a ata falha por rede: o item fica, entregue
        self.assertEqual([item], self.fila.itens())
        self.injector.paste_text.reset_mock()
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto da reunião")
        self._reenviar(item, "meeting")
        self.injector.paste_text.assert_not_called()
        self.assertEqual([], self.fila.itens())
        self.assertEqual(ATA_RECUSADA, self.ui[-1])

    def test_ata_ja_entregue_com_a_groq_fora_continua(self):
        item = self._na_fila("meeting", fala="texto da reunião")
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto da reunião", ConnectionError("x"))
        self._reenviar(item, "meeting")
        self._reenviar(item, "meeting")
        self.assertEqual([item], self.fila.itens())
        self.assertEqual(("offline_retry", "Ata ainda não gerada. Clique p/ reenviar"), self.ui[-1])


if __name__ == "__main__":
    unittest.main()
