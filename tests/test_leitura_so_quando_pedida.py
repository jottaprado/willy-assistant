"""
A leitura em voz alta só acontece quando o comando é um pedido de leitura.

is_speak_command procurava "ler", "fale" e "diga" em qualquer ponto do comando: "Willy, crie uma
função para ler um arquivo CSV" e "Willy, fale sobre Docker" iam para o TTS, que lia a própria
frase (ou a seleção), em vez de o pedido ir ao LLM.

E a pontuação das pontas não atrapalha: o Whisper fecha a fala curta com ponto, e "Willy, leia."
ia ao LLM, que colava a resposta por cima da seleção.
"""

import unittest
from unittest.mock import patch

from core.actions import ActionManager
from core.pipeline import PipelineContext
from tests.test_fila_audio_falho import _Pipeline
from tests.test_velocidade_medida import _wav


class TestPedidoDeLeitura(unittest.TestCase):
    def test_pedidos_de_leitura(self):
        for c in ("leia", "Leia isso.", "leia a seleção", "leia em voz alta", "fale em voz alta",
                  "por favor leia isso", "diga esse parágrafo", "ler o texto selecionado", "speak this",
                  "leia isso, por favor", "Leia.", "Leia!", "Por favor, leia isso.", "Por favor: leia isso", "fale isso",
                  "Leia em voz alta…"):
            with self.subTest(comando=c):
                self.assertTrue(ActionManager.is_speak_command(c))

    def test_pedidos_ao_llm_que_mencionam_ler_ou_falar(self):
        for c in ("crie uma função para ler um arquivo CSV", "fale sobre Docker",
                  "diga três fatos sobre Python", "qual a leitura do termômetro", "explique como ler um log",
                  "resuma em 3 tópicos"):
            with self.subTest(comando=c):
                self.assertFalse(ActionManager.is_speak_command(c))


class TestPeloPipeline(_Pipeline):
    def _falar(self, fala):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = fala
        with patch.object(ActionManager, "process_action", return_value="def ler_csv(caminho): ...") as acao, \
             patch.object(ActionManager, "get_selected_text", return_value=""):
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transcribe",
                                                  app_context=("code.exe", "editor", "general")))
        return acao

    def test_pedido_de_codigo_que_fala_em_ler_vai_ao_llm(self):
        acao = self._falar("Willy, crie uma função para ler um arquivo CSV")
        acao.assert_called_once()
        self.pipeline.tts_mgr.speak_async.assert_not_called()
        self.assertEqual("def ler_csv(caminho): ...", self.injector.paste_text.call_args.args[0])

    def test_pedido_de_leitura_continua_lendo(self):
        for fala in ("Willy, leia isso", "Willy, leia."):
            with self.subTest(fala=fala):
                self.pipeline.tts_mgr.reset_mock()
                acao = self._falar(fala)
                acao.assert_not_called()
                self.pipeline.tts_mgr.speak_async.assert_called_once()


if __name__ == "__main__":
    unittest.main()
