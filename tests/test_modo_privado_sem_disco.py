"""
No modo privado, nada novo do ditado vai para o disco quando algo falha.

A falha (sem internet, limite, chave, bug nosso, Willy ocupado, ata) guardava o áudio na fila
ou no last_failed_audio.wav, e os blocos transcritos de uma reunião ao lado do item: o modo
privado só valia para o histórico. E a pílula dizia "áudio salvo. Clique p/ reenviar".
"""

import os
import unittest
from unittest.mock import patch

import groq

from core.groq_service import FalhaDoLLM
from tests.test_fila_audio_falho import _http, _Pipeline

NAO_GUARDADO = "privado: áudio não salvo"


class TestModoPrivadoSemDisco(_Pipeline):
    def setUp(self):
        super().setUp()
        self.pipeline.config_mgr.private_mode = True

    def _arquivos_do_ditado(self):
        """Todo .wav e .json embaixo da pasta de dados (o log de erros não guarda áudio)."""
        return [os.path.join(raiz, nome) for raiz, _d, nomes in os.walk(self.tmp)
                for nome in nomes if nome.endswith((".wav", ".json", ".entregue"))]

    def test_falha_da_groq_nao_grava_nada(self):
        casos = {
            "sem internet": (ConnectionError("offline"), f"Sem internet ({NAO_GUARDADO})"),
            "limite": (_http(groq.RateLimitError, 429), f"Limite da Groq ({NAO_GUARDADO})"),
            "groq instável": (_http(groq.InternalServerError, 503), f"Groq instável ({NAO_GUARDADO})"),
            "chave": (_http(groq.AuthenticationError, 401), "Chave Groq inválida ou sem permissão"),
            "recusado": (_http(groq.BadRequestError, 400), "A Groq recusou o áudio (HTTP 400)"),
            "bug nosso": (RuntimeError("bug"), f"Erro interno ({NAO_GUARDADO})"),
        }
        for nome, (falha, mensagem) in casos.items():
            with self.subTest(nome):
                self.ui.clear()
                self.assertFalse(self._rodar(b"RIFFsegredo", falha=falha).success)
                self.assertEqual([], self._arquivos_do_ditado())
                self.assertEqual(("error", mensagem), self.ui[-1])
                # Cabe na pílula: no estado fixo dela, perto de 45 caracteres.
                self.assertLessEqual(len(mensagem), 42)

    def _com_um_bloco_transcrito(self, falha):
        """Como o transcribe_chunks de uma reunião longa: um bloco sai, e a falha vem depois."""
        def _efeito(*_a, **_k):
            self.pipeline._blocos[0] = "primeiro bloco transcrito"
            raise falha
        return _efeito

    def test_reuniao_que_cai_no_meio_nao_grava_os_blocos(self):
        self._rodar(b"RIFFreuniao", "meeting", self._com_um_bloco_transcrito(ConnectionError("offline")))
        self.assertEqual([], self._arquivos_do_ditado())

    def test_sem_chave_nao_grava(self):
        self.pipeline.config_mgr.groq_api_key = ""
        self._rodar(b"RIFFsegredo")
        self.assertEqual([], self._arquivos_do_ditado())
        self.assertEqual(("error", "Configure sua chave Groq"), self.ui[-1])

    def test_ocupado_nao_grava(self):
        self.audio_mgr.is_processing = True
        self.assertEqual("busy", self._rodar(b"RIFFsegredo").error_category)
        self.assertEqual([], self._arquivos_do_ditado())
        self.assertEqual(("error", f"Willy ocupado ({NAO_GUARDADO})"), self.ui[-1])

    def test_ata_que_falha_entrega_a_transcricao_sem_guardar(self):
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto ditado")
        self.assertTrue(self._rodar(b"RIFFreuniao", "meeting").success)
        self.assertEqual([], self._arquivos_do_ditado())
        self.assertEqual(("error", f"Ata não gerada ({NAO_GUARDADO})"), self.ui[-1])

    def test_reenvio_de_item_de_antes_do_modo_privado_nao_ganha_blocos(self):
        # O item já estava na fila: ele continua lá, como estava, e o "salvo" é verdade.
        self.pipeline.config_mgr.private_mode = False
        self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline"))
        (item,) = self.fila.itens()
        self.pipeline.config_mgr.private_mode = True
        antes = sorted(self._arquivos_do_ditado())
        self._rodar(b"RIFFreuniao", "meeting", self._com_um_bloco_transcrito(ConnectionError("offline")),
                    retry_path=item)
        self.assertEqual(antes, sorted(self._arquivos_do_ditado()))
        self.assertEqual([item], self.fila.itens())
        self.assertEqual(("offline_retry", "Sem internet: áudio salvo. Clique p/ reenviar"), self.ui[-1])

    def test_item_de_antes_cuja_ata_falha_no_reenvio_continua_na_fila(self):
        # Caiu sem rede antes de ligar o modo; no reenvio, a transcrição sai e a ata falha.
        self.pipeline.config_mgr.private_mode = False
        self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline"))
        (item,) = self.fila.itens()
        self.pipeline.config_mgr.private_mode = True
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto ditado", ConnectionError("Groq fora"))
        self.assertTrue(self._rodar(b"RIFFreuniao", "meeting", retry_path=item).success)
        self.assertEqual([item], self.fila.itens())
        self.assertFalse([a for a in self._arquivos_do_ditado() if a.endswith(".json")])
        self.assertEqual(("offline_retry", "Ata não gerada. Clique p/ reenviar"), self.ui[-1])
        # E o reenvio seguinte não cola a transcrição de novo.
        self.injector.paste_text.reset_mock()
        self._rodar(b"RIFFreuniao", "meeting", retry_path=item)
        self.injector.paste_text.assert_not_called()

    def test_reenvio_cuja_ata_falha_de_novo_nao_ganha_blocos(self):
        self.pipeline.config_mgr.private_mode = False
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto ditado", ConnectionError("Groq fora"))
        self._rodar(b"RIFFreuniao", "meeting")
        (item,) = self.fila.itens()
        self.pipeline.config_mgr.private_mode = True
        antes = sorted(self._arquivos_do_ditado())
        self.groq_service.summarize_meeting.side_effect = self._com_um_bloco_transcrito(
            FalhaDoLLM("ata", "texto ditado", ConnectionError("Groq fora")))
        self._rodar(b"RIFFreuniao", "meeting", retry_path=item)
        self.assertEqual(antes, sorted(self._arquivos_do_ditado()))
        self.assertEqual(("offline_retry", "Ata ainda não gerada. Clique p/ reenviar"), self.ui[-1])


class TestForaDoModoPrivado(_Pipeline):
    def test_disco_que_falha_nao_diz_audio_salvo(self):
        with patch.object(self.fila, "guardar", side_effect=OSError("disco cheio")):
            self._rodar(b"RIFFditado", falha=ConnectionError("offline"))
        self.assertEqual(("error", "Sem internet (o áudio não pôde ser salvo)"), self.ui[-1])

    def test_bug_nosso_continua_guardando_a_copia_avulsa(self):
        self._rodar(b"RIFFditado", falha=RuntimeError("bug"))
        self.assertTrue(os.path.exists(self.avulso))
        self.assertEqual(("error", "Erro interno do Willy: áudio salvo em last_failed_audio.wav"), self.ui[-1])


if __name__ == "__main__":
    unittest.main()
