"""
Um pedido sobre a seleção que caiu sem rede: o reenvio usa a seleção de agora, e sem ela diz
que o pedido saiu da fila, sem travar a fila.

- "Willy, resuma este contrato" (ou o Ctrl+Alt+T) sem rede vai para a fila. O reenvio vem sem
  a seleção de antes. O item saía calado, como um "cancelado". Guardá-lo também não serve: ele
  ficaria no topo, reenviado (e transcrito) a cada clique, e os áudios de antes, uma reunião
  por exemplo, nunca mais seriam alcançados; a bandeja, com o foco no Willy, nunca tem seleção.
- O reenvio do Ctrl+Alt+T recebia a seleção guardada do último atalho, talvez de outro pedido:
  a instrução de um áudio era aplicada ao texto de outro.
"""

import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

from core.actions import ActionManager
from core.pipeline import PipelineContext
from tests.test_fila_audio_falho import _Pipeline
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy
from tests.test_velocidade_medida import _wav

DESCARTADO = ("error", "Sem seleção: pedido descartado")


class TestReenvioDePedidoSobreSelecao(_Pipeline):
    def _pedir(self, modo, selecao, retry_path=None, sem_rede=False, selecao_do_atalho=None, soltou=True):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = "Willy, resuma este contrato" if modo == "transcribe" else "resuma"
        self.groq_service.transform_text.side_effect = ConnectionError("offline") if sem_rede else None
        self.groq_service.transform_text.return_value = "Resumo."
        with patch.object(ActionManager, "get_selected_text", return_value=selecao), \
             patch.object(ActionManager, "esperar_modificadores_soltos", return_value=soltou):
            return self.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo=modo, selected_text=selecao_do_atalho,
                app_context=("code.exe", "editor", "general"),
                is_retry=retry_path is not None, retry_path=retry_path))

    def _caiu_sem_rede(self, modo):
        self._pedir(modo, "Contrato de 12 meses.", sem_rede=True, selecao_do_atalho="Contrato de 12 meses.")
        (item,) = self.fila.itens()
        return item

    def test_reenvio_sem_selecao_descarta_o_pedido_e_avisa(self):
        for modo in ("transcribe", "transform"):
            with self.subTest(modo=modo):
                self.tearDown()  # a pasta temporária da volta anterior
                self.setUp()
                item = self._caiu_sem_rede(modo)
                self._pedir(modo, "", retry_path=item)
                self.assertEqual([], self.fila.itens())
                self.assertEqual(DESCARTADO, self.ui[-1])
                self.injector.paste_text.assert_not_called()

    def test_pedido_descartado_nao_tranca_a_reuniao_de_antes(self):
        self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline"))
        (reuniao,) = self.fila.itens()
        self._pedir("transcribe", "Contrato de 12 meses.", sem_rede=True, selecao_do_atalho="Contrato de 12 meses.")
        (item,) = set(self.fila.itens()) - {reuniao}
        self.assertEqual(item, self.fila.mais_recente()[0], "o clique reenvia este primeiro")
        self._pedir("transcribe", "", retry_path=item)
        self.assertEqual([reuniao], self.fila.itens())
        self.assertEqual(("offline_retry", "Sem seleção: descartado. Clique p/ o próximo"), self.ui[-1])

    def test_reenvio_com_selecao_transforma_e_consome_o_item(self):
        for modo in ("transcribe", "transform"):
            with self.subTest(modo=modo):
                self.tearDown()
                self.setUp()
                item = self._caiu_sem_rede(modo)
                self._pedir(modo, "Contrato novo.", retry_path=item)
                self.assertEqual("Contrato novo.", self.groq_service.transform_text.call_args.args[0])
                self.assertEqual("Resumo.", self.injector.paste_text.call_args.args[0])
                self.assertEqual([], self.fila.itens())

    def test_reenvio_com_tecla_presa_le_a_selecao_assim_mesmo(self):
        # O reenvio vem de um clique (talvez com Shift), não do atalho: não pede para soltá-lo.
        item = self._caiu_sem_rede("transform")
        self._pedir("transform", "Contrato novo.", retry_path=item, soltou=False)
        self.assertEqual("Resumo.", self.injector.paste_text.call_args.args[0])

    def test_pedido_novo_sem_selecao_so_avisa(self):
        self._pedir("transcribe", "")
        self.assertEqual(("error", "Selecione um texto antes de transformar"), self.ui[-1])


class TestReenvioNaoUsaASelecaoGuardada(unittest.TestCase):
    def _executar(self, is_retry):
        pipeline = MagicMock()
        executar = _funcao_do_willy(
            "_executar_pipeline_transcricao", config_mgr=MagicMock(groq_api_key="gsk_x"),
            transcription_pipeline=pipeline, dashboard=None, safe_dispatch_ui=MagicMock(),
            PipelineContext=PipelineContext, current_app_context=None, Optional=Optional,
            Tuple=tuple, _alvo_da_gravacao=(0, 0),
            selected_text_for_transform="seleção do último Ctrl+Alt+T", sincronizar_bandeja=MagicMock())
        executar(b"RIFFaudio", "transform", is_retry=is_retry, retry_path="C:/fila/item.wav" if is_retry else None)
        return pipeline.process.call_args.args[0].selected_text

    def test_gravacao_nova_usa_a_do_atalho(self):
        self.assertEqual("seleção do último Ctrl+Alt+T", self._executar(is_retry=False))

    def test_reenvio_le_a_de_agora(self):
        self.assertIsNone(self._executar(is_retry=True))


if __name__ == "__main__":
    unittest.main()
