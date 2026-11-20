"""
Frase comum que começa com "Classe" ou com "Willy" é ditado, e não identificador nem pedido.

- "Classe média está alta este ano" saía MediaEstaAltaEsteAno: o prefixo "classe" pedia
  PascalCase. Sem os dois-pontos, frase com verbo de ligação, pontuação no meio ou mais de
  5 palavras depois de "classe" é prosa. "classe: …" e "pascal case …" são sempre pedido.
- Qualquer fala que começava com "Willy" ia ao copiloto: "Willy mandou um abraço" virava
  pedido ao LLM. "Willy" sem vírgula seguido de verbo na 3ª pessoa é ditado.
"""

import unittest
from unittest.mock import patch

from core.actions import ActionManager
from core.pipeline import PipelineContext
from core.text_processing import TextProcessor
from tests.test_fila_audio_falho import _Pipeline
from tests.test_velocidade_medida import _wav


class TestClasseEmProsa(unittest.TestCase):
    def test_frase_comum_nao_vira_identificador(self):
        for fala in ("Classe média está alta este ano.", "Classe executiva estava cheia.",
                     "Classe de 2010, a nossa turma.", "classe alta mora longe do centro da cidade hoje"):
            with self.subTest(fala=fala):
                self.assertIsNone(TextProcessor.format_code_identifier(fala))
                self.assertIsNone(TextProcessor.estilo_de_identificador(fala))

    def test_pedido_de_classe_continua(self):
        for fala, nome in (("classe pedido de compra", "PedidoDeCompra"), ("Classe pedido de compra.", "PedidoDeCompra"),
                           ("classe: pedido de compra", "PedidoDeCompra"), ("classe usuário", "Usuario"),
                           ("Classe: média está alta", "MediaEstaAlta"),
                           ("pascal case cliente que está ativo", "ClienteQueEstaAtivo")):
            with self.subTest(fala=fala):
                self.assertEqual(nome, TextProcessor.format_code_identifier(fala))
                self.assertEqual("pascal", TextProcessor.estilo_de_identificador(fala))

    def test_dois_pontos_vale_nos_outros_prefixos(self):
        self.assertEqual("total_de_vendas", TextProcessor.format_code_identifier("variável: total de vendas"))


class TestWillyEmProsa(unittest.TestCase):
    def test_frase_sobre_alguem_chamado_willy_e_ditado(self):
        for fala in ("Willy mandou um abraço", "Willy disse que vem", "Willy chegou cedo", "Willy está na sala",
                     "Willy saiu agora", "Willy escreveu o relatório", "willy é o novo estagiário"):
            with self.subTest(fala=fala):
                self.assertEqual((False, ""), ActionManager.is_action_command(fala))

    def test_pedido_ao_willy_continua(self):
        for fala, comando in (("Willy, resuma isso", "resuma isso"), ("Willy: crie uma função", "crie uma função"),
                              ("Willy me ajude com isso", "me ajude com isso"), ("Ei Willy mandou bem", "mandou bem"),
                              ("Willy resuma este contrato", "resuma este contrato"), ("Willy, chegou cedo?", "chegou cedo?"),
                              ("Willy fala o resumo", "fala o resumo"), ("Opa Willy, ajuda aqui", "ajuda aqui"),
                              ("Willy eu quero um resumo disso", "eu quero um resumo disso"),
                              # Presente que começa um pedido sem a vírgula (achado do juiz do 7A).
                              ("Willy tem como resumir isso?", "tem como resumir isso?"),
                              ("Willy sabe traduzir isso?", "sabe traduzir isso?"),
                              ("Willy quer revisar o texto", "quer revisar o texto"),
                              ("Willy precisa de um resumo disso", "precisa de um resumo disso"),
                              ("Willy vai resumir isso pra mim", "vai resumir isso pra mim"),
                              # Imperativo informal (2º juiz do 7A).
                              ("Willy acha um sinônimo para feliz", "acha um sinônimo para feliz"),
                              ("Willy vem cá e resume isso", "vem cá e resume isso"),
                              ("Willy trabalha nesse texto", "trabalha nesse texto")):
            with self.subTest(fala=fala):
                self.assertEqual((True, comando), ActionManager.is_action_command(fala))


class TestPeloPipeline(_Pipeline):
    def _falar(self, fala):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = fala
        with patch.object(ActionManager, "process_action", return_value="resposta do LLM") as acao, \
             patch.object(ActionManager, "get_selected_text", return_value=""):
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transcribe",
                                                  app_context=("code.exe", "editor", "general")))
        return acao

    def test_ditado_sobre_o_willy_e_colado(self):
        acao = self._falar("Willy mandou um abraço para todos.")
        acao.assert_not_called()
        self.assertEqual("Willy mandou um abraço para todos.", self.injector.paste_text.call_args.args[0])

    def test_frase_com_classe_e_colada(self):
        self._falar("Classe média está alta este ano.")
        self.assertEqual("Classe média está alta este ano.", self.injector.paste_text.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
