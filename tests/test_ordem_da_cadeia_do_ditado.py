"""
A ordem da cadeia do ditado não estraga o que vem depois.

- Os comandos de voz rodavam antes do identificador de código: o "ponto" de "variável ponto de
  venda" virava "." e o identificador não saía.
- O tom ("Willy em tópicos:") tirava o "Willy" da frente, e o copiloto, que depende dele, não via
  mais a ação: "Willy em tópicos: resuma este contrato" era colado como ditado.
- As regex de tom e de envio não tinham fronteira de palavra: "Willy, formalize este e-mail"
  virava "Ize este e-mail", e "Willy, mandei o arquivo?" virava "I o arquivo?" com Enter.
"""

import unittest
from unittest.mock import patch

from core.actions import ActionManager
from core.pipeline import PipelineContext
from core.text_processing import TextProcessor
from tests.test_fila_audio_falho import _Pipeline
from tests.test_velocidade_medida import _wav


class TestFronteiraDePalavra(unittest.TestCase):
    def test_palavra_que_so_comeca_com_o_tom_nao_e_tom(self):
        for fala in ("Willy, formalize este e-mail", "Willy, diretoria aprovou", "Willy, naturalmente sim"):
            with self.subTest(fala=fala):
                self.assertEqual((fala, None), TextProcessor.detect_voice_tone(fala))

    def test_palavra_que_so_comeca_com_o_envio_nao_envia(self):
        for fala in ("Willy, mandei o arquivo?", "Willy, sendo assim, vamos", "Willy, enviarei amanhã"):
            with self.subTest(fala=fala):
                self.assertEqual((fala, False), TextProcessor.detect_send_command(fala))

    def test_tom_e_envio_de_verdade_continuam(self):
        self.assertEqual(("Comprar café, revisar PR", "bullet_points"),
                         TextProcessor.detect_voice_tone("Willy em tópicos: comprar café, revisar PR"))
        self.assertEqual(("Bom dia a todos", True), TextProcessor.detect_send_command("Willy enviar: bom dia a todos"))


class TestPeloPipeline(_Pipeline):
    def _falar(self, fala, selecao=""):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = fala
        self.groq_service.transform_text.return_value = "• Prazo: 12 meses\n• Multa: 10%"
        with patch.object(ActionManager, "process_action", return_value="resposta do LLM") as acao, \
             patch.object(ActionManager, "get_selected_text", return_value=selecao) as self.ler_selecao:
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transcribe",
                                                  app_context=("code.exe", "editor", "general")))
        return acao

    def _colado(self):
        return self.injector.paste_text.call_args.args[0]

    def test_caixa_alta_e_baixa_continuam_com_os_comandos_de_voz(self):
        # Prosa, e não um nome: com o identificador antes dos comandos de voz, saía
        # "ATENÇÃO VÍRGULA EQUIPE".
        for fala, colado in (("caixa alta atenção vírgula equipe", "ATENÇÃO, EQUIPE"),
                             ("caixa baixa Bom Dia ponto final", "bom dia")):
            with self.subTest(fala=fala):
                self._falar(fala)
                self.assertEqual(colado, self._colado())

    def test_hesitacao_e_tom_saem_antes_do_identificador(self):
        # Com a limpeza ligada (o padrão), a cadeia de antes tirava as hesitações antes.
        self.pipeline.config_mgr.clean_fillers = True
        for fala, colado in (("variável éé total", "total"),
                             ("caixa alta éé atenção vírgula equipe", "ATENÇÃO, EQUIPE"),
                             ("caixa baixa tipo assim Bom Dia", "bom dia"),
                             ("Willy, em tom formal: variável total", "total"),
                             ("Variável ponto de venda.", "ponto_de_venda")):
            with self.subTest(fala=fala):
                self._falar(fala)
                self.assertEqual(colado, self._colado())

    def test_limpeza_desligada_deixa_as_hesitacoes(self):
        self.pipeline.config_mgr.clean_fillers = False
        self._falar("variável éé total")
        self.assertEqual("ee_total", self._colado())

    def test_estilo_concorda_com_a_formatacao(self):
        # Os dois leem os mesmos padrões: um texto que o format_code_identifier formata tem estilo.
        for texto in ("caixa alta atenção\nequipe", "variável total", "camel case data de nascimento"):
            with self.subTest(texto=texto):
                self.assertIsNotNone(TextProcessor.format_code_identifier(texto))
                self.assertIsNotNone(TextProcessor.estilo_de_identificador(texto))

    def test_dois_pontos_falado_depois_do_prefixo(self):
        for fala in ("Willy enviar dois pontos variável total", "Willy em tom formal dois pontos variável total"):
            with self.subTest(fala=fala):
                self._falar(fala)
                self.assertEqual("total", self._colado())

    def test_caixa_alta_com_nova_linha(self):
        self._falar("caixa alta atenção nova linha equipe")
        self.assertEqual("ATENÇÃO\nEQUIPE", self._colado())

    def test_identificador_com_envio_por_voz(self):
        self._falar("Willy enviar: variável ponto de venda")
        self.assertEqual("ponto_de_venda", self._colado())
        self.assertIs(True, self.injector.paste_text.call_args.kwargs["auto_send"])

    def test_identificador_com_ponto_no_nome(self):
        self._falar("Variável ponto de venda.")
        self.assertEqual("ponto_de_venda", self.injector.paste_text.call_args.args[0])

    def test_pedido_de_transformacao_depois_do_tom_e_acao_com_o_tom(self):
        self._falar("Willy em tópicos: resuma este contrato", selecao="Contrato de 12 meses, multa de 10%.")
        base, instrucao = self.groq_service.transform_text.call_args.args[:2]
        self.assertEqual("Contrato de 12 meses, multa de 10%.", base)
        self.assertEqual("Resuma este contrato em tópicos", instrucao)
        self.assertEqual("• Prazo: 12 meses\n• Multa: 10%", self.injector.paste_text.call_args.args[0])

    def test_ditado_com_tom_continua_ditado(self):
        acao = self._falar("Willy, em tom formal: preciso de mais prazo")
        acao.assert_not_called()
        self.groq_service.transform_text.assert_not_called()
        self.assertEqual("formal", self.groq_service.refine_text.call_args.kwargs["tone"])

    def test_verbo_de_transformacao_depois_do_tom_sem_selecao_e_ditado(self):
        # Sem seleção, não é pedido sobre ela: virava o aviso "Selecione um texto".
        self._falar("Willy, em tom formal: corrija o relatório até amanhã")
        self.groq_service.transform_text.assert_not_called()
        self.assertEqual("formal", self.groq_service.refine_text.call_args.kwargs["tone"])
        self.injector.paste_text.assert_called_once()

    def test_tom_com_selecao_le_a_selecao_uma_vez(self):
        self._falar("Willy em tópicos: resuma este contrato", selecao="Contrato de 12 meses.")
        self.ler_selecao.assert_called_once_with()

    def test_mandei_nao_aperta_enter(self):
        self._falar("Willy, mandei o arquivo?")
        self.assertIs(False, self.injector.paste_text.call_args.kwargs.get("auto_send", False))


if __name__ == "__main__":
    unittest.main()
