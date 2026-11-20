"""
A reunião curta (até 20 MB, sem fatiar) cuja ata falhou não é transcrita de novo no reenvio.

Só a reunião fatiada guardava os blocos ao lado do item. A curta ia para a fila sem eles, e
cada clique em "reenviar" mandava o áudio inteiro para o Whisper de novo, para gerar a ata.
"""

import unittest

from core.groq_service import FalhaDoLLM
from core.pipeline import PipelineContext
from tests.test_fila_audio_falho import _Pipeline


class TestReuniaoCurtaGuardaATranscricao(_Pipeline):
    def _ata_falha_com(self, falha):
        self.groq_service.summarize_meeting.side_effect = falha
        self._rodar(b"RIFFreuniao", "meeting")
        (item,) = self.fila.itens()
        return item

    def _reenviar_com_a_ata_de_volta(self, item):
        self.groq_service.transcribe.reset_mock()
        self.groq_service.summarize_meeting.reset_mock(side_effect=True)
        self.groq_service.summarize_meeting.return_value = "## Ata Executiva\n- decisões"
        return self._rodar(b"RIFFreuniao", "meeting", retry_path=item)

    def test_ata_que_falha_guarda_a_transcricao_ao_lado_do_audio(self):
        for nome, falha in (("IA fora", FalhaDoLLM("ata", "texto ditado")), ("sem internet", ConnectionError("offline"))):
            with self.subTest(nome):
                self.tearDown()  # a pasta temporária da volta anterior
                self.setUp()
                item = self._ata_falha_com(falha)
                self.assertEqual({0: "texto ditado"}, self.fila.ler_blocos(item))

    def test_reenvio_gera_so_a_ata(self):
        for nome, falha in (("IA fora", FalhaDoLLM("ata", "texto ditado")), ("sem internet", ConnectionError("offline"))):
            with self.subTest(nome):
                self.tearDown()  # a pasta temporária da volta anterior
                self.setUp()
                item = self._ata_falha_com(falha)
                self.assertTrue(self._reenviar_com_a_ata_de_volta(item).success)
                self.groq_service.transcribe.assert_not_called()
                self.groq_service.summarize_meeting.assert_called_once_with("texto ditado", estrito=True)
                self.assertEqual([], self.fila.itens())

    def test_reenvio_sem_blocos_transcreve(self):
        # Item guardado antes desta correção, ou de uma falha antes da transcrição.
        self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline"))
        (item,) = self.fila.itens()
        self.assertEqual({}, self.fila.ler_blocos(item))
        self.assertTrue(self._reenviar_com_a_ata_de_volta(item).success)
        self.groq_service.transcribe.assert_called_once()

    def test_transcricao_vazia_nao_vira_bloco(self):
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "")
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = ""
        self.pipeline.process(PipelineContext(wav_bytes=b"RIFFreuniao", modo="meeting",
                                              app_context=("code.exe", "editor", "general")))
        self.assertEqual({}, self.pipeline._blocos)


if __name__ == "__main__":
    unittest.main()
