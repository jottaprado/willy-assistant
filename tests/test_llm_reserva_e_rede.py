"""
O LLM tem modelo de reserva em toda etapa, e um comando ditado não se perde quando a rede cai.

- Só o prompt de agente tinha reserva. Com o Coder (qwen, em preview na Groq) fora do ar, todo
  refino, transformar, ata e ação falhava.
- Num transformar ou numa ação, rede caída, 429 ou 5xx viravam "Não transformei"/"Não executei"
  e o áudio era descartado: um comando longo ditado no Ctrl+Alt+T se perdia.
- O texto do Qwen podia vir com <thinking>…</thinking>, ou só com o fechamento, e era colado.
"""

import unittest
from unittest.mock import MagicMock, patch

import groq
import httpx

from core import modelos_llm
from core.actions import ActionManager
from core.groq_service import FalhaDoLLM, GroqService
from core.pipeline import PipelineContext
from tests.test_fila_audio_falho import _Pipeline
from tests.test_groq_service import _http, _resposta
from tests.test_velocidade_medida import _wav


def _sem_rede():
    return groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))


def _servico(efeitos, modelo=modelos_llm.CODER):
    servico = GroqService(api_key="gsk_teste", llm_model=modelo)
    cliente = MagicMock()
    cliente.with_options.return_value = cliente
    cliente.chat.completions.create.side_effect = efeitos
    servico._client = cliente
    return servico, cliente


def _modelos(cliente):
    return [c.kwargs["model"] for c in cliente.chat.completions.create.call_args_list]


class TestRaciocinioForaDoTexto(unittest.TestCase):
    def test_tag_citada_e_texto(self):
        # Um texto que explicava a tag (ou um XML transformado) perdia tudo o que vinha antes dela.
        for conteudo in ("Use a tag `</think>` para fechar o raciocínio.",
                         'O parser procura "</think>" no texto.',
                         "O parser procura '</think>' no texto.",
                         "Feche com “</thinking>” e siga.",
                         "```xml\n<resposta>ok</think>\n```",
                         "Use `<think>` e `</think>` para marcar o raciocínio.",
                         "Exemplo:\n```\n<think>rascunho</think>\n```\nFim."):
            with self.subTest(conteudo=conteudo):
                self.assertEqual(conteudo, modelos_llm.texto_sem_raciocinio(conteudo))

    def test_raciocinio_de_verdade_sai_mesmo_com_tag_citada_depois(self):
        for conteudo, esperado in (("pensei bastante</think>Resposta: use `</think>` no fim.",
                                    "Resposta: use `</think>` no fim."),
                                   ("<think>rascunho</think>Texto com `</think>` citado.",
                                    "Texto com `</think>` citado."),
                                   ("<think>a</think>Diga \"<think>\" em voz alta.",
                                    "Diga \"<think>\" em voz alta."),
                                   # Aspa de um lado só não é citação (achado do juiz do 7A).
                                   ('pensei no pedido "traduza"</think>Final', "Final"),
                                   ("ok, vou responder</think>'Final'", "'Final'"),
                                   # Aspas retas dos dois lados, mas de duas citações (2º juiz do 7A).
                                   ('pensei em "bom dia"</think>"Good morning"', '"Good morning"'),
                                   ("pensei em 'bom dia'</think>'Good morning'", "'Good morning'"),
                                   ("pensei em “bom dia”</think>“Good morning”", "“Good morning”")):
            with self.subTest(conteudo=conteudo):
                self.assertEqual(esperado, modelos_llm.texto_sem_raciocinio(conteudo))

    def test_thinking_e_fechamento_sem_abertura(self):
        for conteudo, esperado in (("<thinking>planejar</thinking>Texto final.", "Texto final."),
                                   ("vou pensar nisso primeiro</think>\nTexto final.", "Texto final."),
                                   ("passo 1, passo 2</thinking> Texto final.", "Texto final."),
                                   ("<think>a</think>Texto <b>com tag</b>.", "Texto <b>com tag</b>."),
                                   # O bloco no meio: o fechamento órfão não pode levar o texto de antes.
                                   ("Antes. <thinking>rascunho</thinking>Depois.", "Antes. Depois.")):
            with self.subTest(conteudo=conteudo):
                self.assertEqual(esperado, modelos_llm.texto_sem_raciocinio(conteudo))


class TestOrdemDeTentativa(unittest.TestCase):
    def test_escolhido_depois_as_reservas_sem_repetir(self):
        self.assertEqual([modelos_llm.CODER, modelos_llm.SMART, modelos_llm.FLASH],
                         modelos_llm.ordem_de_tentativa(modelos_llm.CODER))
        self.assertEqual([modelos_llm.SMART, modelos_llm.FLASH], modelos_llm.ordem_de_tentativa(modelos_llm.SMART))
        self.assertEqual([modelos_llm.CODER, modelos_llm.SMART, modelos_llm.FLASH],
                         modelos_llm.ordem_de_tentativa("gemma2-9b-it"))  # desligado: o substituto

    def test_servico_normaliza_o_modelo(self):
        servico = GroqService(api_key="", llm_model="llama-3.3-70b-versatile")
        self.assertEqual(modelos_llm.SMART, servico.llm_model)
        servico.set_llm_model("gemma2-9b-it")
        self.assertEqual(modelos_llm.CODER, servico.llm_model)


class TestCompletarComReserva(unittest.TestCase):
    def test_modelo_que_recusa_passa_para_o_proximo(self):
        servico, cliente = _servico([_http(groq.NotFoundError, 404), _resposta("ok")])
        self.assertEqual("ok", servico.completar_com_reserva(cliente, [], 0.0, 10, 1))
        self.assertEqual([modelos_llm.CODER, modelos_llm.SMART], _modelos(cliente))
        cliente.with_options.assert_called_with(max_retries=0)

    def test_429_e_5xx_tambem_passam_para_o_proximo(self):
        for erro in (_http(groq.RateLimitError, 429), _http(groq.InternalServerError, 503)):
            with self.subTest(erro=type(erro).__name__):
                servico, cliente = _servico([erro, _resposta("ok")])
                self.assertEqual("ok", servico.completar_com_reserva(cliente, [], 0.0, 10, 1))

    def test_rede_caida_nao_troca_de_modelo(self):
        servico, cliente = _servico([_sem_rede(), _resposta("ok")])
        with self.assertRaises(groq.APIConnectionError):
            servico.completar_com_reserva(cliente, [], 0.0, 10, 1)
        self.assertEqual([modelos_llm.CODER], _modelos(cliente))

    def test_todos_recusam_sobe_o_ultimo(self):
        servico, cliente = _servico([_http(groq.NotFoundError, 404)] * 3)
        with self.assertRaises(groq.NotFoundError):
            servico.completar_com_reserva(cliente, [], 0.0, 10, 1)
        self.assertEqual(3, len(_modelos(cliente)))

    def test_todos_recusam_e_um_foi_por_limite_sobe_o_limite(self):
        # Achado do juiz do 7A: 429 no escolhido e 404 nos outros subia o 404, a falha virava
        # recusa e o reenvio saía da fila. Com o 429, ela passa.
        for erros in ([_http(groq.RateLimitError, 429), _http(groq.NotFoundError, 404), _http(groq.BadRequestError, 400)],
                      [_http(groq.NotFoundError, 404), _http(groq.InternalServerError, 503), _http(groq.NotFoundError, 404)]):
            with self.subTest(erros=[type(e).__name__ for e in erros]):
                servico, cliente = _servico(erros)
                with self.assertRaises((groq.RateLimitError, groq.InternalServerError)) as falha:
                    servico.completar_com_reserva(cliente, [], 0.0, 10, 1)
                self.assertTrue(FalhaDoLLM("refino", "", falha.exception).transitoria)


class TestEtapasComReserva(unittest.TestCase):
    TEXTO = "isso aqui é um texto ditado comprido o bastante para refinar"

    def test_refino_ata_transformar_e_acao_usam_a_reserva(self):
        chamadas = {
            "refino": lambda s: s.refine_text(self.TEXTO, estrito=True),
            "ata": lambda s: s.summarize_meeting(self.TEXTO, estrito=True),
            "transformar": lambda s: s.transform_text("seleção", "traduza", estrito=True),
            "acao": lambda s: ActionManager.process_action("explique o que é um mutex", s),
        }
        for etapa, chamar in chamadas.items():
            with self.subTest(etapa=etapa):
                servico, cliente = _servico([_http(groq.NotFoundError, 404), _resposta("Resposta do Smart, comprida.")])
                self.assertIn("Resposta do Smart", chamar(servico))
                self.assertEqual([modelos_llm.CODER, modelos_llm.SMART], _modelos(cliente))


class TestFalhaPassageiraNoComando(unittest.TestCase):
    def test_transformar_estrito_deixa_subir(self):
        for erro in (_sem_rede(), _http(groq.RateLimitError, 429), _http(groq.InternalServerError, 500)):
            with self.subTest(erro=type(erro).__name__):
                servico, _ = _servico([erro] * 3)
                with self.assertRaises(type(erro)):
                    servico.transform_text("seleção", "traduza", estrito=True)

    def test_acao_deixa_subir_a_passageira_e_engole_o_resto(self):
        servico, _ = _servico([_sem_rede()])
        with self.assertRaises(groq.APIConnectionError):
            ActionManager.process_action("explique o que é um mutex", servico)
        servico, _ = _servico([_http(groq.BadRequestError, 400)] * 3)
        self.assertIsNone(ActionManager.process_action("explique o que é um mutex", servico))

    def test_refino_continua_com_a_fala_crua(self):
        servico, _ = _servico([_sem_rede()])
        with self.assertRaises(FalhaDoLLM) as ctx:
            servico.refine_text(TestEtapasComReserva.TEXTO, estrito=True)
        self.assertEqual(TestEtapasComReserva.TEXTO, ctx.exception.reserva)

    def test_generate_agent_prompt_preserva_erro_passageiro_quando_reserva_da_404(self):
        """AUD-030: Se o modelo escolhido dá 429/503 (ou o orçamento expira) e os de reserva dão 404,
        generate_agent_prompt não pode sobrescrever a causa passageira com 404 e descartar o áudio."""
        for erros in (
            [_http(groq.RateLimitError, 429), _http(groq.NotFoundError, 404), _http(groq.BadRequestError, 400)],
            [_http(groq.NotFoundError, 404), _http(groq.InternalServerError, 503), _http(groq.NotFoundError, 404)],
        ):
            with self.subTest(erros=[type(e).__name__ for e in erros]):
                servico, _ = _servico(erros)
                with self.assertRaises((groq.RateLimitError, groq.InternalServerError)):
                    servico.generate_agent_prompt("crie um prompt de agente para testar", estrito=True)

        servico_orc, _ = _servico([_http(groq.NotFoundError, 404)])
        servico_orc.ORCAMENTO_PROMPT_S = 0.5
        with self.assertRaises(TimeoutError):
            servico_orc.generate_agent_prompt("crie um prompt de agente para testar", estrito=True)

    def test_acao_de_prompt_propaga_falha_transitoria_sem_engolir(self):
        """AUD-030: Na rota de prompt/missão de agente em ActionManager.process_action, uma falha
        transitória (429 seguido de 404, ou FalhaDoLLM com causa transitória) deve subir."""
        servico, _ = _servico([
            _http(groq.RateLimitError, 429),
            _http(groq.NotFoundError, 404),
            _http(groq.NotFoundError, 404),
        ])
        with self.assertRaises(groq.RateLimitError):
            ActionManager.process_action("gere um prompt de agente para refatorar", servico, "código")

        servico_mock = MagicMock()
        servico_mock.client = MagicMock()
        servico_mock.generate_agent_prompt.side_effect = FalhaDoLLM(
            "prompt", "DEMANDA...", _http(groq.InternalServerError, 503)
        )
        with self.assertRaises(groq.InternalServerError):
            ActionManager.process_action("defina a missão do agente", servico_mock, "código")


class TestComandoGuardadoNaFila(_Pipeline):
    def _falar(self, fala, selecao="Contrato de 12 meses."):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = fala
        with patch.object(ActionManager, "get_selected_text", return_value=selecao):
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transcribe",
                                                  app_context=("code.exe", "editor", "general")))

    def test_transformar_sem_rede_guarda_o_audio_e_oferece_o_reenvio(self):
        self.groq_service.transform_text.side_effect = _sem_rede()
        self._falar("Willy, resuma este contrato")
        self.injector.paste_text.assert_not_called()
        self.assertEqual(1, len(self.fila))
        self.assertEqual("offline_retry", self.ui[-1][0])

    def test_acao_com_429_guarda_o_audio(self):
        with patch.object(ActionManager, "process_action", side_effect=_http(groq.RateLimitError, 429)):
            self._falar("Willy, explique o que é um mutex")
        self.injector.paste_text.assert_not_called()
        self.assertEqual(1, len(self.fila))
        self.assertIn("Limite", self.ui[-1][1])

    def test_acao_de_prompt_com_falha_transitoria_guarda_audio_novo_e_preserva_reenvio(self):
        """AUD-030: Comando 'Willy, crie um prompt de agente...' que falha por 429/5xx ou FalhaDoLLM
        transitória guarda o áudio na fila em ditado novo e não o apaga no reenvio."""
        self.groq_service.generate_agent_prompt.side_effect = FalhaDoLLM(
            "prompt", "DEMANDA...", _http(groq.RateLimitError, 429)
        )
        self._falar("Willy, crie um prompt de agente para revisar este contrato")
        self.injector.paste_text.assert_not_called()
        self.assertEqual(1, len(self.fila), "o áudio ditado deveria ter sido salvo na fila")
        self.assertEqual("offline_retry", self.ui[-1][0])

        # No reenvio, se continuar com falha transitória, o item NÃO pode ser apagado da fila
        (item,) = self.fila.itens()
        with patch.object(ActionManager, "get_selected_text", return_value="Contrato de 12 meses."):
            self.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transcribe", is_retry=True, retry_path=item,
                app_context=("code.exe", "editor", "general"),
            ))
        self.assertEqual([item], self.fila.itens(), "o reenvio com falha transitória não pode apagar o áudio")


class TestAvisoFallback429(unittest.TestCase):
    def test_429_registra_fallback_por_thread_sem_vazar_entre_threads(self):
        import threading

        servico = GroqService(api_key="gsk_teste", llm_model=modelos_llm.SMART)
        barreira = threading.Barrier(2)
        resultados: dict[str, tuple[str, str] | None] = {}

        def _worker_a():
            cli_a = MagicMock()
            cli_a.with_options.return_value = cli_a
            cli_a.chat.completions.create.side_effect = [_http(groq.RateLimitError, 429), _resposta("Texto polido A.")]
            out = servico.completar_com_reserva(cli_a, [{"role": "user", "content": "texto a"}], 0.0, 64, 2.0)
            self.assertEqual("Texto polido A.", out)
            barreira.wait(timeout=5)
            resultados["a"] = servico.fallback_429_recente()

        def _worker_b():
            cli_b = MagicMock()
            cli_b.with_options.return_value = cli_b
            cli_b.chat.completions.create.side_effect = [_resposta("Texto polido B.")]
            out = servico.completar_com_reserva(cli_b, [{"role": "user", "content": "texto b"}], 0.0, 64, 2.0)
            self.assertEqual("Texto polido B.", out)
            barreira.wait(timeout=5)
            resultados["b"] = servico.fallback_429_recente()

        ta = threading.Thread(target=_worker_a)
        tb = threading.Thread(target=_worker_b)
        ta.start()
        tb.start()
        ta.join(timeout=5)
        tb.join(timeout=5)

        self.assertEqual((modelos_llm.SMART, modelos_llm.FLASH), resultados["a"])
        self.assertIsNone(resultados["b"])

    def test_recusa_para_coder_sem_429_nao_registra_fallback_429(self):
        servico, cliente = _servico(
            [
                _resposta("Desculpe, mas não posso ajudar com isso."),
                _resposta("Desculpe, mas não posso ajudar com isso."),
                _resposta("Lista técnica verificada com sucesso."),
            ],
            modelo=modelos_llm.SMART,
        )
        out = servico.completar_com_reserva(cliente, [{"role": "user", "content": "Verifique os logs do servidor."}], 0.0, 64, 2.0)
        self.assertEqual("Lista técnica verificada com sucesso.", out)
        self.assertIsNone(servico.fallback_429_recente())

    def test_traducao_multi_pedaco_preserva_fallback_429_de_pedaco_anterior(self):
        servico, _cliente = _servico(
            [
                _http(groq.RateLimitError, 429),
                _resposta("Primer bloque traducido."),
                _resposta("Segundo bloque traducido."),
            ],
            modelo=modelos_llm.SMART,
        )
        servico.PEDACO_DA_TRADUCAO = 40
        texto = "Primeira frase tecnica bem longa. Segunda frase tecnica tambem longa."
        saida = servico.translate_to_spanish(texto, estrito=True)
        self.assertIn("Primer bloque", saida)
        self.assertIn("Segundo bloque", saida)
        self.assertEqual((modelos_llm.SMART, modelos_llm.FLASH), servico.fallback_429_recente())

    def test_pipeline_mostra_aviso_verde_nas_cinco_etapas_em_fallback_429(self):
        cenarios = [
            ("transcribe", "refino normal com varias palavras tecnicas para testar", None, "Refinado no Flash."),
            ("translate_es", "texto tecnico longo para traduzir ao espanhol", None, "Texto tecnico en espanol."),
            ("meeting", "Decidimos revisar a arquitetura do servidor nesta semana.", None, "## Ata Executiva\n- Revisar arquitetura."),
            ("transform", "torne mais conciso", "Paragrafo de especificacao tecnica original.", "Especificacao concisa."),
            ("transcribe", "Willy, explique o erro de timeout na conexao", "Timeout ao conectar no banco.", "Verifique a porta e o firewall."),
        ]
        for modo, fala, selecao, resposta_flash in cenarios:
            with self.subTest(modo=modo, fala=fala[:25]):
                h = _Pipeline()
                h.setUp()
                self.addCleanup(h.tearDown)
                svc, _ = _servico([_http(groq.RateLimitError, 429), _resposta(resposta_flash)], modelo=modelos_llm.SMART)
                h.groq_service = svc
                h.pipeline.groq_service = svc
                with patch.object(svc, "transcribe", return_value=fala), \
                        patch.object(ActionManager, "get_selected_text", return_value=selecao or ""):
                    res = h.pipeline.process(PipelineContext(
                        wav_bytes=_wav(2.0), modo=modo, selected_text=selecao,
                        app_context=("code.exe", "editor", "general"),
                    ))
                self.assertTrue(res.success)
                h.injector.paste_text.assert_called_once()
                self.assertEqual(("success", "Colado com Flash (limite no Smart)"), h.ui[-1])

        # Resposta direta sem 429 mantém o sucesso padrão (sem menção de limite).
        h_direto = _Pipeline()
        h_direto.setUp()
        self.addCleanup(h_direto.tearDown)
        svc_ok, _ = _servico([_resposta("Refinado direto no Smart.")], modelo=modelos_llm.SMART)
        h_direto.groq_service = svc_ok
        h_direto.pipeline.groq_service = svc_ok
        with patch.object(svc_ok, "transcribe", return_value="refino direto com varias palavras tecnicas"):
            h_direto.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transcribe", app_context=("code.exe", "editor", "general"),
            ))
        self.assertEqual(("success", None), h_direto.ui[-1])

        # Recusa que vai para o Coder sem 429 mantém sucesso padrão (não diz limite).
        h_rec = _Pipeline()
        h_rec.setUp()
        self.addCleanup(h_rec.tearDown)
        svc_rec, _ = _servico([
            _resposta("Desculpe, mas não posso ajudar com isso."),
            _resposta("Desculpe, mas não posso ajudar com isso."),
            _resposta("Refinado pelo Coder."),
        ], modelo=modelos_llm.SMART)
        h_rec.groq_service = svc_rec
        h_rec.pipeline.groq_service = svc_rec
        with patch.object(svc_rec, "transcribe", return_value="Liste os modulos com falha de compilacao."):
            h_rec.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transcribe", app_context=("code.exe", "editor", "general"),
            ))
        self.assertEqual(("success", None), h_rec.ui[-1])

        # Falha total (429 em todos) mantém o erro de falha do LLM (não vira sucesso com Flash).
        h_err = _Pipeline()
        h_err.setUp()
        self.addCleanup(h_err.tearDown)
        svc_err, _ = _servico([_http(groq.RateLimitError, 429)] * 2, modelo=modelos_llm.SMART)
        h_err.groq_service = svc_err
        h_err.pipeline.groq_service = svc_err
        with patch.object(svc_err, "transcribe", return_value="refino com limite em todos os modelos"):
            h_err.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transcribe", app_context=("code.exe", "editor", "general"),
            ))
        self.assertEqual("error", h_err.ui[-1][0])
        self.assertNotIn("Colado com Flash", str(h_err.ui[-1][1]))


if __name__ == "__main__":
    unittest.main()
