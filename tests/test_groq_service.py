"""
Testes unitários para o módulo core.groq_service.GroqService.
"""

import io
import unittest
from unittest.mock import MagicMock, patch

import groq

from core import modelos_llm
from core.actions import ActionManager
from core.groq_service import FalhaDoLLM, GroqService
from tests.willy_isolado import _erro_groq as _http
from tests.willy_isolado import _resposta


class TestGroqService(unittest.TestCase):

    def test_init_without_key(self):
        service = GroqService(api_key="")
        self.assertIsNone(service.get_client())

        service2 = GroqService(api_key="sua_chave_aqui")
        self.assertIsNone(service2.get_client())

    def test_set_api_key(self):
        service = GroqService(api_key="")
        service.set_api_key("gsk_test123")
        self.assertEqual(service.api_key, "gsk_test123")

    def test_transcribe_without_key_raises(self):
        service = GroqService(api_key="")
        buf = io.BytesIO(b"fake_wav")
        with self.assertRaises(ValueError):
            service.transcribe(buf, "")

    def test_translate_without_key_raises(self):
        service = GroqService(api_key="")
        buf = io.BytesIO(b"fake_wav")
        with self.assertRaises(ValueError):
            service.translate(buf, "")

    def test_translate_usa_translate_model_e_nao_model_de_transcricao(self):
        service = GroqService(
            api_key="gsk_test",
            model="whisper-large-v3-turbo",
            translate_model="whisper-large-v3",
        )
        cliente = MagicMock()
        cliente.audio.translations.create.return_value = MagicMock(text="Hello world", segments=None)
        service._client = cliente
        res = service.translate(io.BytesIO(b"RIFF"), "prompt")
        self.assertEqual("Hello world", res)
        self.assertEqual(
            "whisper-large-v3",
            cliente.audio.translations.create.call_args.kwargs["model"],
        )

    def test_refine_text_inclui_instrucoes_do_tom_no_prompt_do_sistema(self):
        service = GroqService(api_key="gsk_test")
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.return_value = _resposta("- item um\n- item dois")
        service._client = cliente
        res = service.refine_text("precisamos revisar o item um e o item dois hoje", tone="bullet_points")
        self.assertEqual("- item um\n- item dois", res)
        msgs = cliente.chat.completions.create.call_args.kwargs["messages"]
        sistema = msgs[0]["content"]
        self.assertIn("TOM DE SAÍDA: TÓPICOS / BULLET POINTS", sistema)

    def test_refine_text_short_or_disabled(self):
        service = GroqService(api_key="fake_key")
        # Desativado deve retornar idêntico
        self.assertEqual(service.refine_text("olá mundo teste", enabled=False), "olá mundo teste")

        # Texto vazio
        self.assertEqual(service.refine_text("", enabled=True), "")

        # Menos de 3 palavras não chama o LLM
        self.assertEqual(service.refine_text("olá amigos", enabled=True), "olá amigos")

    def test_set_llm_model(self):
        service = GroqService(api_key="", llm_model="openai/gpt-oss-120b")
        self.assertEqual(service.llm_model, "openai/gpt-oss-120b")
        service.set_llm_model("openai/gpt-oss-20b")
        self.assertEqual(service.llm_model, "openai/gpt-oss-20b")

    def test_summarize_meeting_short_or_empty(self):
        service = GroqService(api_key="")
        # Texto curto deve retornar ele mesmo sem erro
        self.assertEqual(service.summarize_meeting(""), "")
        self.assertEqual(service.summarize_meeting("curto"), "curto")

    def test_generate_agent_prompt_short_or_empty(self):
        service = GroqService(api_key="")
        self.assertEqual(service.generate_agent_prompt(""), "")
        self.assertEqual(service.generate_agent_prompt("oi"), "oi")

    def test_sanitize_whisper_prompt(self):
        # Prompt normal não deve ser alterado
        short_prompt = "Vocabulário: Python, FastAPI"
        self.assertEqual(GroqService._sanitize_whisper_prompt(short_prompt), short_prompt)

        # Prompt vazio ou None
        self.assertEqual(GroqService._sanitize_whisper_prompt(""), "")
        self.assertEqual(GroqService._sanitize_whisper_prompt(None), "")

        # Prompt longo deve ser truncado com segurança abaixo do limite
        long_prompt = "palavra, " * 200  # > 1500 caracteres
        sanitized = GroqService._sanitize_whisper_prompt(long_prompt, max_chars=890)
        self.assertLessEqual(len(sanitized), 890)
        self.assertFalse(sanitized.endswith(","))


class TestPromptDeAgenteSemRede(unittest.TestCase):
    """3 modelos em sequência, 20 s cada, e o SDK refazendo cada chamada até 3 vezes: com a rede
    parada, o prompt de agente levava uns 3 min para desistir, e sem avisar."""

    PROMPT = "/goal \"Criar a tela de login\"\n\nFase 1: investigar o fluxo atual e propor o desenho"

    def _servico(self, efeitos):
        servico = GroqService(api_key="gsk_teste")
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.side_effect = efeitos
        servico._client = cliente
        return servico, cliente

    def test_sem_rede_desiste_na_hora_sem_tentar_os_outros_modelos(self):
        import httpx
        for erro in (groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com")),
                     groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com")),
                     ConnectionError("offline"), TimeoutError("parado")):
            with self.subTest(erro=type(erro).__name__):
                servico, cliente = self._servico([erro, _resposta(self.PROMPT)])
                with self.assertRaises(type(erro)):
                    servico.generate_agent_prompt("criar a tela de login")
                self.assertEqual(1, cliente.chat.completions.create.call_count)

    def test_erro_do_modelo_tenta_o_seguinte(self):
        servico, cliente = self._servico([_http(groq.NotFoundError, 404), _resposta(self.PROMPT)])
        self.assertEqual(self.PROMPT, servico.generate_agent_prompt("criar a tela de login"))
        self.assertEqual(2, cliente.chat.completions.create.call_count)

    def test_sem_as_tentativas_automaticas_do_sdk(self):
        """A chamada tem de sair pela cópia sem tentativas, não pelo cliente compartilhado."""
        servico, cliente = self._servico([])
        copia = MagicMock()
        copia.chat.completions.create.return_value = _resposta(self.PROMPT)
        cliente.with_options.return_value = copia
        servico.generate_agent_prompt("criar a tela de login")
        cliente.with_options.assert_called_once_with(max_retries=0)
        copia.chat.completions.create.assert_called_once()
        cliente.chat.completions.create.assert_not_called()

    def test_orcamento_esgotado_para_de_tentar(self):
        relogio = iter([0.0, 0.5, 30.0, 30.0, 30.0])
        servico, cliente = self._servico([_http(groq.NotFoundError, 404)] * 3)
        with patch("core.groq_service.time.monotonic", side_effect=lambda: next(relogio)):
            self.assertEqual("criar a tela de login", servico.generate_agent_prompt("criar a tela de login"))
        self.assertEqual(1, cliente.chat.completions.create.call_count)

    def test_cada_tentativa_so_espera_o_que_resta_do_orcamento(self):
        relogio = iter([0.0, 18.0, 18.0])
        servico, cliente = self._servico([_resposta(self.PROMPT)])
        with patch("core.groq_service.time.monotonic", side_effect=lambda: next(relogio)):
            servico.generate_agent_prompt("criar a tela de login")
        self.assertAlmostEqual(GroqService.ORCAMENTO_PROMPT_S - 18.0,
                               cliente.chat.completions.create.call_args.kwargs["timeout"])


class TestEtapasDeIAEstritas(unittest.TestCase):
    """Refino, ata, transformar e prompt devolviam o texto cru em silêncio quando a Groq falhava."""

    def _servico(self, efeito):
        servico = GroqService(api_key="gsk_teste")
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.side_effect = efeito
        servico._client = cliente
        return servico

    def _falha(self, chamada, etapa, reserva):
        with self.assertRaises(FalhaDoLLM) as ctx:
            chamada()
        self.assertEqual((etapa, reserva), (ctx.exception.etapa, ctx.exception.reserva))

    def test_cada_etapa_levanta_com_estrito_e_guarda_a_reserva(self):
        erro = _http(groq.InternalServerError, 500)
        texto = "isso aqui é um texto ditado comprido o bastante"
        self._falha(lambda: self._servico(erro).refine_text(texto, estrito=True), "refino", texto)
        self._falha(lambda: self._servico(erro).summarize_meeting(texto, estrito=True), "ata", texto)
        # 5xx no transformar não vira FalhaDoLLM: o comando ditado não tem reserva para colar, e
        # o pipeline guarda o áudio na fila (Bloco 6A). Um erro que não passa ainda vira.
        with self.assertRaises(groq.InternalServerError):
            self._servico(erro).transform_text("seleção", "traduza", estrito=True)
        self._falha(lambda: self._servico([_http(groq.NotFoundError, 404)] * 3).transform_text(
            "seleção", "traduza", estrito=True), "transformar", "seleção")
        self._falha(lambda: self._servico([_http(groq.NotFoundError, 404)] * 3).generate_agent_prompt(
            "criar a tela de login", estrito=True), "prompt", "criar a tela de login")

    def test_resposta_vazia_tambem_e_falha(self):
        vazio = [_resposta("")] * 3
        texto = "isso aqui é um texto ditado comprido o bastante"
        self._falha(lambda: self._servico(vazio).refine_text(texto, estrito=True), "refino", texto)
        self._falha(lambda: self._servico(vazio).summarize_meeting(texto, estrito=True), "ata", texto)
        self._falha(lambda: self._servico(vazio).transform_text("seleção", "traduza", estrito=True),
                    "transformar", "seleção")

    def test_sem_estrito_o_comportamento_antigo_continua(self):
        """A transcrição de arquivo do willy.py usa a ata sem estrito, e conta com a reserva."""
        erro = _http(groq.InternalServerError, 500)
        texto = "isso aqui é um texto ditado comprido o bastante"
        self.assertEqual(texto, self._servico(erro).refine_text(texto))
        self.assertEqual(texto, self._servico(erro).summarize_meeting(texto))
        self.assertEqual("seleção", self._servico(erro).transform_text("seleção", "traduza"))

    def test_rede_no_prompt_continua_sendo_rede(self):
        import httpx
        erro = groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))
        with self.assertRaises(groq.APIConnectionError):
            self._servico([erro]).generate_agent_prompt("criar a tela de login", estrito=True)


class TestPromptComLimiteOuGroqInstavel(unittest.TestCase):
    def test_429_ou_5xx_em_todos_os_modelos_vai_para_a_fila(self):
        """No resto do pipeline, 429 e 5xx são reenvio: o prompt colava a fala crua."""
        for classe, status in ((groq.RateLimitError, 429), (groq.InternalServerError, 500)):
            with self.subTest(status=status):
                servico = GroqService(api_key="gsk_teste")
                cliente = MagicMock()
                cliente.with_options.return_value = cliente
                cliente.chat.completions.create.side_effect = [_http(classe, status)] * 3
                servico._client = cliente
                with self.assertRaises(classe):
                    servico.generate_agent_prompt("criar a tela de login", estrito=True)


class TestLogsStderrEPingComReserva(unittest.TestCase):
    """AUD-032, AUD-150, AUD-151, AUD-152, AUD-153, AUD-154."""

    def test_get_client_loga_falha_em_stderr(self):
        from contextlib import redirect_stderr

        servico = GroqService(api_key="gsk_valida")
        buf = io.StringIO()
        with patch("core.groq_service.Groq", side_effect=RuntimeError("falha ssl")), redirect_stderr(buf):
            self.assertIsNone(servico.get_client())
        self.assertIn("falha ssl", buf.getvalue())

    def test_refine_transform_traduzir_e_ata_logam_em_stderr_sem_usar_stdout(self):
        from contextlib import redirect_stderr, redirect_stdout

        servico = GroqService(api_key="gsk_valida")
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        servico._client = cliente

        # 1. refine_text (AUD-151) — ConnectionError não passa pelo print de completar_com_reserva
        cliente.chat.completions.create.side_effect = [ConnectionError("sem rede no refino")]
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            res = servico.refine_text("um texto longo o suficiente para refinar", estrito=False)
        self.assertEqual(res, "um texto longo o suficiente para refinar")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Erro ao refinar texto", err.getvalue())
        self.assertIn("sem rede no refino", err.getvalue())

        # 2. transform_text com erro comum e passageiro (AUD-152)
        cliente.chat.completions.create.side_effect = [_http(groq.BadRequestError, 400)] * 3
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            res = servico.transform_text("base", "traduza", estrito=False)
        self.assertEqual(res, "base")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Erro ao transformar texto", err.getvalue())

        cliente.chat.completions.create.side_effect = [ConnectionError("sem rede no transformar")]
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            res = servico.transform_text("base", "traduza", estrito=False)
        self.assertEqual(res, "base")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("sem rede no transformar", err.getvalue())

        # 3. _traduzir_texto com erro passageiro em estrito=False (AUD-153)
        cliente.chat.completions.create.side_effect = [ConnectionError("sem rede na traducao")]
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            res = servico.translate_to_spanish("Olá mundo", estrito=False)
        self.assertEqual(res, "Olá mundo")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("sem rede na traducao", err.getvalue())

        # 4. summarize_meeting (AUD-154) — ConnectionError não passa pelo print de completar_com_reserva
        cliente.chat.completions.create.side_effect = [ConnectionError("sem rede na ata")]
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            res = servico.summarize_meeting("transcrição longa da reunião inteira", estrito=False)
        self.assertEqual(res, "transcrição longa da reunião inteira")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Erro ao gerar ata", err.getvalue())
        self.assertIn("sem rede na ata", err.getvalue())

    def test_ping_usa_reserva_quando_modelo_principal_recusa(self):
        # AUD-032: ping usa completar_com_reserva e modelo_em_uso cai para PADRAO se inválido
        servico = GroqService(api_key="gsk_valida", llm_model="qwen/qwen3.8-27b")
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.side_effect = [
            _http(groq.NotFoundError, 404),
            _resposta("pong"),
        ]
        servico._client = cliente
        ok, msg, lat = servico.ping()
        self.assertTrue(ok)
        self.assertEqual(msg, "OK")
        self.assertGreaterEqual(lat, 0.0)


class TestRecusaDoLLMNaoSubstituiDitado(unittest.TestCase):
    """Proteção contra o LLM substituir o ditado por recusa de assistente com HTTP 200."""

    PROMPT_DITADO_1 = (
        "Inspecione os arquivos de log gerados na última compilação do servidor de integração, "
        "agrupe os erros por módulo afetado, compare com o relatório da semana passada e monte "
        "um roteiro objetivo de correção para a equipe de infraestrutura executar amanhã."
    )
    PROMPT_DITADO_2 = (
        "Compare as tabelas do banco de homologação com o esquema de produção atual, liste "
        "todas as colunas divergentes ou índices ausentes e gere o roteiro completo de migração "
        "incremental com validação automática antes de aplicar qualquer alteração."
    )
    RECUSA_PT = "Desculpe, mas não posso ajudar com isso."
    RECUSA_EN = "I'm sorry, but I can't help with that."
    RECUSA_ES = "Lo siento, pero no puedo ayudar con eso."
    META_RECUSA_PT = "Como uma IA, não posso acessar suas mensagens privadas."

    def _servico(self, efeitos, modelo=modelos_llm.SMART):
        servico = GroqService(api_key="gsk_teste", llm_model=modelo)
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.side_effect = efeitos
        servico._client = cliente
        return servico, cliente

    @staticmethod
    def _modelos(cliente):
        return [c.kwargs["model"] for c in cliente.chat.completions.create.call_args_list]

    def test_recusa_no_refino_tenta_coder_e_usa_resposta_revisada(self):
        for texto in (self.PROMPT_DITADO_1, self.PROMPT_DITADO_2):
            with self.subTest(texto=texto[:40]):
                revisado = texto + " Revisado."
                servico, cliente = self._servico([
                    _resposta(self.RECUSA_PT),
                    _resposta("Sinto muito, mas não consigo atender a esse pedido."),
                    _resposta(revisado),
                ])
                saida = servico.refine_text(texto, estrito=True)
                self.assertEqual(revisado, saida)
                self.assertEqual(
                    [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
                    self._modelos(cliente),
                )

    def test_recusa_em_todos_os_modelos_no_refino_levanta_falha_e_pipeline_cola_original(self):
        from core.groq_service import RecusaDoLLM
        from core.pipeline import PipelineContext
        from tests.test_fila_audio_falho import _Pipeline
        from tests.test_velocidade_medida import _wav

        for recusas in (
            [self.RECUSA_PT, self.RECUSA_EN, self.RECUSA_ES],
            [f"<transcricao>{self.RECUSA_PT}</transcricao>", f'"{self.RECUSA_PT}"', self.RECUSA_PT],
        ):
            with self.subTest(recusas=recusas[0]):
                servico, cliente = self._servico([_resposta(r) for r in recusas])
                with self.assertRaises(FalhaDoLLM) as ctx:
                    servico.refine_text(self.PROMPT_DITADO_1, estrito=True)
                self.assertEqual("refino", ctx.exception.etapa)
                self.assertEqual(self.PROMPT_DITADO_1, ctx.exception.reserva)
                self.assertIsInstance(ctx.exception.causa, RecusaDoLLM)
                self.assertFalse(ctx.exception.transitoria)
                self.assertEqual(
                    [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
                    self._modelos(cliente),
                )

        servico_sem_estrito, _ = self._servico([_resposta(self.RECUSA_PT)] * 3)
        self.assertEqual(self.PROMPT_DITADO_1, servico_sem_estrito.refine_text(self.PROMPT_DITADO_1))

        # Caminho real do pipeline: com recusa em todos os modelos, cola o texto original e avisa recusa.
        harness = _Pipeline()
        harness.setUp()
        self.addCleanup(harness.tearDown)
        servico_real, _ = self._servico([_resposta(self.RECUSA_PT)] * 3)
        harness.groq_service.transcribe.side_effect = None
        harness.groq_service.transcribe.return_value = self.PROMPT_DITADO_1
        harness.groq_service.refine_text.side_effect = servico_real.refine_text
        harness.pipeline.process(PipelineContext(
            wav_bytes=_wav(2.0), modo="transcribe",
            app_context=("code.exe", "editor", "general"),
        ))
        harness.injector.paste_text.assert_called_once()
        colado = harness.injector.paste_text.call_args.args[0]
        self.assertEqual(self.PROMPT_DITADO_1, colado)
        self.assertNotIn("Desculpe", colado)
        estado_ui, msg_ui = harness.ui[-1]
        self.assertEqual("error", estado_ui)
        self.assertIn("recusou", msg_ui.lower())
        self.assertNotIn("não respondeu", msg_ui.lower())
        self.assertLessEqual(len(msg_ui), 45)

    def test_eh_recusa_do_llm_detecta_variacoes_pt_en_es_e_duas_frases(self):
        from core.groq_service import eh_recusa_do_llm

        recusas = (
            "Desculpe, mas não posso ajudar com isso.",
            "Desculpa, não consigo ajudar com isso.",
            "Desculpe, mas não posso ajudar com isso. Posso ajudar em outra coisa?",
            "Sinto muito, mas não posso atender a essa solicitação.",
            "Infelizmente não posso atender a essa solicitação.",
            "Não posso ajudar com isso.",
            "Como uma IA, não posso acessar suas mensagens privadas.",
            "Desculpe, mas não posso responder mensagens em seu nome.",
            "I'm sorry, but I can't help with that.",
            "I'm sorry, but I can't help with that request.",
            "I cannot fulfill this request.",
            "I'm sorry, I cannot assist with that. Let me know if you need anything else.",
            "As an AI, I cannot access private messages.",
            "Lo siento, pero no puedo ayudar con eso.",
            "Disculpa, pero no puedo ayudar con esta solicitud.",
            "No puedo ayudar con eso.",
            "Como una IA, no puedo acceder a tus mensajes privados.",
            '"Desculpe, mas não posso ajudar com isso."',
            "<transcricao>Desculpe, mas não posso ajudar com isso.</transcricao>",
        )
        for frase in recusas:
            with self.subTest(frase=frase):
                self.assertTrue(eh_recusa_do_llm(frase, self.PROMPT_DITADO_1))
        # Pedido imperativo curto (4 palavras) recusado com 7 palavras também é detectado.
        self.assertTrue(eh_recusa_do_llm(self.RECUSA_PT, "Audite os logs internos"))

    def test_controles_negativos_nao_sao_classificados_como_recusa(self):
        from core.groq_service import eh_recusa_do_llm

        desculpa_falada = "Bom dia pessoal, peço desculpas pelo atraso na entrega do relatório trimestral da fábrica."
        nao_consigo_prosa = "Boa tarde, revisei a planilha mas eu não consigo apagar os registros antigos do almoxarifado."
        fala_sobre_tela = (
            "Ontem durante a simulação do módulo de faturamento apareceu uma caixa vermelha "
            "avisando que o servidor rejeitou a operação automática por falta de certificado "
            "digital válido no ambiente de testes, então precisamos renovar a credencial antes "
            "de liberar o pacote para o setor financeiro."
        )
        recusa_curta_ditada = "Desculpe, mas não posso ajudar com isso hoje."
        recusa_curta_exata = "Desculpe, mas não posso ajudar com isso."

        for texto in (desculpa_falada, nao_consigo_prosa, fala_sobre_tela, recusa_curta_ditada, recusa_curta_exata):
            with self.subTest(controle=texto[:40]):
                self.assertFalse(eh_recusa_do_llm(texto, texto))
                servico, cliente = self._servico([_resposta(texto)])
                self.assertEqual(texto, servico.refine_text(texto, estrito=True))
                self.assertEqual([modelos_llm.SMART], self._modelos(cliente))

        # Resumo legítimo com objeto específico não pode ser confundido com recusa de assistente.
        texto_longo = " ".join(["relatorio"] * 40)
        self.assertFalse(eh_recusa_do_llm(
            "Infelizmente não consigo ajudar com o transporte dos móveis.", texto_longo
        ))
        self.assertFalse(eh_recusa_do_llm("Não posso responder agora, estou em reunião.", texto_longo))

        # Se o modelo trocar uma fala longa por uma recusa curta, deve bloquear,
        # mesmo quando a própria entrada longa já continha uma recusa em primeira pessoa.
        self.assertTrue(eh_recusa_do_llm(self.RECUSA_PT, fala_sobre_tela))
        fala_longa_com_recusa_em_primeira_pessoa = (
            "Na reunião de logística expliquei que não posso ajudar com isso, e logo depois "
            "detalhei o cronograma completo de manutenção preventiva das empilhadeiras que a "
            "oficina precisa concluir antes do inventário anual do depósito central."
        )
        self.assertTrue(eh_recusa_do_llm(self.RECUSA_PT, fala_longa_com_recusa_em_primeira_pessoa))

        # Tradução legítima de uma recusa falada pela pessoa deve passar sem retentativa.
        self.assertFalse(eh_recusa_do_llm(self.RECUSA_EN, recusa_curta_exata))
        self.assertFalse(eh_recusa_do_llm(self.RECUSA_ES, recusa_curta_exata))

    def test_lacunas_de_mutacao_n12_n14_n15(self):
        from core.groq_service import eh_recusa_do_llm

        # N14: resposta legítima acima de 30 palavras com frase de recusa dentro não é recusa do LLM.
        entrada_sem_recusa = (
            "Resuma o parecer do departamento jurídico sobre a proposta de parceria comercial "
            "apresentada pela fornecedora de sensores industriais na reunião de ontem à tarde."
        )
        resposta_35_palavras = (
            "O parecer jurídico registrou que o contrato atual impede repassar dados brutos de "
            "telemetria sem aditivo formal. No encerramento do memorando, o diretor escreveu: "
            "Desculpe, mas não posso ajudar com isso. A revisão segue agendada para segunda."
        )
        self.assertGreater(len(resposta_35_palavras.split()), 30)
        self.assertFalse(eh_recusa_do_llm(resposta_35_palavras, entrada_sem_recusa))
        servico_n14, cliente_n14 = self._servico([_resposta(resposta_35_palavras)])
        self.assertEqual(resposta_35_palavras, servico_n14.refine_text(entrada_sem_recusa, estrito=True))
        self.assertEqual([modelos_llm.SMART], self._modelos(cliente_n14))

        # N12: transform_text passa entrada=base_text para não inflar contagem com a instrução longa.
        servico_n12, cliente_n12 = self._servico([_resposta("Infelizmente, não posso ajudar com isso.")])
        saida_n12 = servico_n12.transform_text(
            "Não posso ajudar com isso.",
            "reescreva esta frase curta em tom mais formal e adequado para enviar no portal corporativo hoje",
            estrito=True,
        )
        self.assertEqual("Infelizmente, não posso ajudar com isso.", saida_n12)
        self.assertEqual([modelos_llm.SMART], self._modelos(cliente_n12))

        # N15: aspas envolvendo tags vazias não passam pelo retorno interno de refine_text.
        servico_n15, _ = self._servico([_resposta('"<transcricao></transcricao>"')])
        with self.assertRaises(FalhaDoLLM) as ctx_n15:
            servico_n15.refine_text(self.PROMPT_DITADO_1, estrito=True)
        self.assertEqual("refino", ctx_n15.exception.etapa)
        self.assertEqual(self.PROMPT_DITADO_1, ctx_n15.exception.reserva)

    def test_transformar_e_acao_entregam_recusa_educada_confirmada_pelo_coder(self):
        from core.groq_service import RecusaDoLLM

        email_pt = (
            "Olá, gostaríamos de solicitar um desconto de 30% na renovação do plano anual "
            "da nossa assinatura corporativa para o próximo exercício."
        )
        email_en = (
            "Hello, we would like to request a 30% discount on the annual renewal "
            "of our commercial subscription for the upcoming fiscal year."
        )
        casos = (
            (email_pt, "responda recusando educadamente", "Desculpe, mas não posso atender a esse pedido."),
            (email_pt, "responda recusando educadamente", "Infelizmente não posso atender a essa solicitação."),
            (email_en, "reply declining politely in English", "I'm sorry, but I can't help with that request."),
        )
        for email, comando, resposta_educada in casos:
            with self.subTest(fluxo="transform_text", resposta=resposta_educada):
                servico, cliente = self._servico([_resposta(resposta_educada)] * 3)
                self.assertEqual(resposta_educada, servico.transform_text(email, comando, estrito=True))
                self.assertEqual(
                    [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
                    self._modelos(cliente),
                )
            with self.subTest(fluxo="process_action", resposta=resposta_educada):
                servico, cliente = self._servico([_resposta(resposta_educada)] * 3)
                self.assertEqual(resposta_educada, ActionManager.process_action(comando, servico, email))
                self.assertEqual(
                    [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
                    self._modelos(cliente),
                )

        # Simetria quando o modelo configurado já é o CODER: confirmação no SMART (2ª família) entrega.
        servico_coder, cliente_coder = self._servico(
            [_resposta("Desculpe, mas não posso atender a esse pedido.")] * 2,
            modelo=modelos_llm.CODER,
        )
        self.assertEqual(
            "Desculpe, mas não posso atender a esse pedido.",
            servico_coder.transform_text(email_pt, "responda recusando educadamente", estrito=True),
        )
        self.assertEqual([modelos_llm.CODER, modelos_llm.SMART], self._modelos(cliente_coder))

        # Sem confirmação na 2ª família (CODER indisponível) ou com meta-recusa explícita de IA, continua bloqueando.
        for efeitos in (
            [_resposta(self.RECUSA_PT), _resposta(self.RECUSA_PT), _http(groq.NotFoundError, 404)],
            [_resposta(self.META_RECUSA_PT)] * 3,
        ):
            with self.subTest(caso="bloqueia_transform", primeiro=type(efeitos[-1]).__name__):
                servico, _ = self._servico(efeitos)
                with self.assertRaises(FalhaDoLLM) as ctx:
                    servico.transform_text(email_pt, "deixe formal", estrito=True)
                self.assertEqual("transformar", ctx.exception.etapa)
                self.assertIsInstance(ctx.exception.causa, RecusaDoLLM)
            with self.subTest(caso="bloqueia_acao", primeiro=type(efeitos[-1]).__name__):
                servico, _ = self._servico(efeitos)
                with self.assertRaises(FalhaDoLLM) as ctx:
                    ActionManager.process_action("resuma a solicitação", servico, email_pt)
                self.assertEqual("acao", ctx.exception.etapa)
                self.assertIsInstance(ctx.exception.causa, RecusaDoLLM)

    def test_aviso_da_pilula_diz_que_a_ia_recusou_nas_cinco_etapas(self):
        from core.groq_service import RecusaDoLLM
        from core.pipeline import PipelineContext
        from core.pipeline.transcription_pipeline import _AVISO_DA_RECUSA, _NADA_A_COLAR_RECUSA
        from tests.test_fila_audio_falho import _Pipeline
        from tests.test_velocidade_medida import _wav

        for etapa, (_st, msg, _curto) in _AVISO_DA_RECUSA.items():
            with self.subTest(tabela="aviso_recusa", etapa=etapa):
                self.assertIn("recusou", msg.lower())
                self.assertNotIn("não respondeu", msg.lower())
                self.assertLessEqual(len(msg), 45)
        for etapa, msg in _NADA_A_COLAR_RECUSA.items():
            with self.subTest(tabela="nada_a_colar_recusa", etapa=etapa):
                self.assertIn("recusou", msg.lower())
                self.assertNotIn("não respondeu", msg.lower())
                self.assertLessEqual(len(msg), 45)

        # 1. Ação pelo caminho real do pipeline (Willy, ...) com recusa não confirmada / meta-recusa.
        h_acao = _Pipeline()
        h_acao.setUp()
        self.addCleanup(h_acao.tearDown)
        servico_acao, _ = self._servico([_resposta(self.META_RECUSA_PT)] * 3)
        h_acao.groq_service = servico_acao
        h_acao.pipeline.groq_service = servico_acao
        with patch.object(servico_acao, "transcribe", return_value="Willy, explique o erro do certificado"), \
                patch.object(ActionManager, "get_selected_text", return_value="Log de erro do servidor."):
            h_acao.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transcribe",
                app_context=("code.exe", "editor", "general"),
            ))
        h_acao.injector.paste_text.assert_not_called()
        self.assertEqual(("error", _NADA_A_COLAR_RECUSA["acao"]), h_acao.ui[-1])

        # 2. Transformar (Ctrl+Alt+T) com meta-recusa.
        h_tr = _Pipeline()
        h_tr.setUp()
        self.addCleanup(h_tr.tearDown)
        servico_tr, _ = self._servico([_resposta(self.META_RECUSA_PT)] * 3)
        h_tr.pipeline.groq_service = servico_tr
        with patch.object(servico_tr, "transcribe", return_value="deixe mais formal"):
            h_tr.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transform", selected_text="Texto selecionado para teste.",
                app_context=("code.exe", "editor", "general"),
            ))
        h_tr.injector.paste_text.assert_not_called()
        self.assertEqual(("error", _NADA_A_COLAR_RECUSA["transformar"]), h_tr.ui[-1])

        # 3. Prompt de agente e Tradução ES com recusa em todos os modelos.
        for modo, etapa, fala in (
            ("prompt", "prompt", self.PROMPT_DITADO_1),
            ("translate_es", "traducao_es", self.PROMPT_DITADO_1),
        ):
            with self.subTest(modo=modo):
                h = _Pipeline()
                h.setUp()
                self.addCleanup(h.tearDown)
                servico_m, _ = self._servico([_resposta(self.RECUSA_PT)] * 3)
                h.pipeline.groq_service = servico_m
                with patch.object(servico_m, "transcribe", return_value=fala):
                    h.pipeline.process(PipelineContext(
                        wav_bytes=_wav(2.0), modo=modo,
                        app_context=("code.exe", "editor", "general"),
                    ))
                h.injector.paste_text.assert_called_once()
                self.assertEqual(fala, h.injector.paste_text.call_args.args[0])
                self.assertEqual(("error", _AVISO_DA_RECUSA[etapa][1]), h.ui[-1])
                self.assertIsInstance(h.pipeline._falha_llm.causa, RecusaDoLLM)

    def test_t7_rota_de_agente_no_copiloto_mostra_aviso_de_recusa_na_pilula(self):
        """T7 (P08): Na rota de agente do copiloto (prompt/missão/agente/goal/maestro), recusa avisa recusa."""
        from core.pipeline import PipelineContext
        from core.pipeline.transcription_pipeline import _NADA_A_COLAR_RECUSA
        from tests.test_fila_audio_falho import _Pipeline
        from tests.test_velocidade_medida import _wav

        harness = _Pipeline()
        harness.setUp()
        self.addCleanup(harness.tearDown)
        servico, _ = self._servico([_resposta(self.META_RECUSA_PT)] * 3)
        harness.groq_service = servico
        harness.pipeline.groq_service = servico
        with patch.object(servico, "transcribe", return_value="Willy, crie um prompt de agente para auditar logs"), \
                patch.object(ActionManager, "get_selected_text", return_value="Log de compilação do servidor."), \
                patch.object(servico, "generate_agent_prompt", wraps=servico.generate_agent_prompt) as spy_prompt:
            harness.pipeline.process(PipelineContext(
                wav_bytes=_wav(2.0), modo="transcribe",
                app_context=("code.exe", "editor", "general"),
            ))
        spy_prompt.assert_called_once()
        harness.injector.paste_text.assert_not_called()
        self.assertEqual(("error", _NADA_A_COLAR_RECUSA["acao"]), harness.ui[-1])

    def test_refine_text_delimita_com_transcricao_e_remove_tags_ecoadas(self):
        texto = "Liste os módulos com cobertura abaixo de oitenta por cento."
        servico, cliente = self._servico([_resposta(f"<transcricao>\n{texto}\n</transcricao>")])
        saida = servico.refine_text(texto, estrito=True)
        self.assertEqual(texto, saida)
        mensagens = cliente.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn("<transcricao>", mensagens[0]["content"])
        self.assertIn("Jamais recuse", mensagens[0]["content"])
        self.assertEqual(f"<transcricao>\n{texto}\n</transcricao>", mensagens[1]["content"])

        # Aspas em volta das tags também saem.
        servico_aspas, _ = self._servico([_resposta(f'"<transcricao>{texto}</transcricao>"')])
        self.assertEqual(texto, servico_aspas.refine_text(texto, estrito=True))

        # Se o próprio texto ditado já começava com <transcricao>, preserva a tag.
        com_tag = "<transcricao>exemplo literal ditado pelo usuário</transcricao>"
        servico_lit, _ = self._servico([_resposta(com_tag)])
        self.assertEqual(com_tag, servico_lit.refine_text(com_tag, estrito=True))

        # Tag vazia ecoada sem conteúdo útil vira FalhaDoLLM.
        servico_vazio, _ = self._servico([_resposta("<transcricao>   </transcricao>")])
        with self.assertRaises(FalhaDoLLM):
            servico_vazio.refine_text(texto, estrito=True)

    def test_demais_etapas_protegidas_contra_recusa_do_llm(self):
        from core.groq_service import _PROMPT_DA_TRADUCAO_EN, _PROMPT_DA_TRADUCAO_ES, RecusaDoLLM

        self.assertIn("sem recusar nem pedir desculpas", _PROMPT_DA_TRADUCAO_ES)
        self.assertIn("sem recusar nem pedir desculpas", _PROMPT_DA_TRADUCAO_EN)

        prompt_valido = "/goal \"Auditar logs do servidor\"\n\nFase 1: mapear falhas recentes e gerar roteiro."
        ata_valida = "## Ata Executiva da Reunião\n- Decisão principal registrada."
        transcricao_reuniao = "Decidimos auditar os logs de integração hoje e corrigir os alertas críticos."

        etapas_com_recuperacao = (
            ("traducao_es", lambda s: s.translate_to_spanish(self.PROMPT_DITADO_1, estrito=True), "Inspecciona los logs."),
            ("traducao_en", lambda s: s.translate_to_english(self.PROMPT_DITADO_1, estrito=True), "Inspect the logs."),
            ("transformar", lambda s: s.transform_text(self.PROMPT_DITADO_1, "deixe formal", estrito=True), "Texto formal."),
            ("ata", lambda s: s.summarize_meeting(transcricao_reuniao, estrito=True), ata_valida),
            ("prompt", lambda s: s.generate_agent_prompt(self.PROMPT_DITADO_1, estrito=True), prompt_valido),
            ("acao", lambda s: ActionManager.process_action("resuma o roteiro", s, self.PROMPT_DITADO_1), "Resumo pronto."),
        )
        for nome, chamar, resposta_coder in etapas_com_recuperacao:
            with self.subTest(etapa=nome, caso="recupera_no_coder"):
                servico, cliente = self._servico([
                    _resposta(self.RECUSA_PT),
                    _resposta(self.RECUSA_EN),
                    _resposta(resposta_coder),
                ])
                saida = chamar(servico)
                self.assertIn(resposta_coder, saida)
                self.assertEqual(
                    [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
                    self._modelos(cliente),
                )

        etapas_estritas_em_recusa_total = (
            ("traducao_es", lambda s: s.translate_to_spanish(self.PROMPT_DITADO_1, estrito=True), self.PROMPT_DITADO_1),
            ("traducao_en", lambda s: s.translate_to_english(self.PROMPT_DITADO_1, estrito=True), self.PROMPT_DITADO_1),
            ("ata", lambda s: s.summarize_meeting(transcricao_reuniao, estrito=True), transcricao_reuniao),
            ("prompt", lambda s: s.generate_agent_prompt(self.PROMPT_DITADO_1, estrito=True), self.PROMPT_DITADO_1),
        )
        for etapa, chamar, reserva in etapas_estritas_em_recusa_total:
            with self.subTest(etapa=etapa, caso="todos_recusam"):
                servico, cliente = self._servico([_resposta(self.RECUSA_PT)] * 3)
                with self.assertRaises(FalhaDoLLM) as ctx:
                    chamar(servico)
                self.assertEqual((etapa, reserva), (ctx.exception.etapa, ctx.exception.reserva))
                self.assertIsInstance(ctx.exception.causa, RecusaDoLLM)
                self.assertEqual(
                    [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
                    self._modelos(cliente),
                )

        # ActionManager com recusa legítima selecionada para traduzir passa na 1ª chamada.
        servico_trad, cliente_trad = self._servico([_resposta(self.RECUSA_EN)])
        self.assertEqual(
            self.RECUSA_EN,
            ActionManager.process_action("traduza para inglês", servico_trad, self.RECUSA_PT),
        )
        self.assertEqual([modelos_llm.SMART], self._modelos(cliente_trad))

    def test_recusa_nao_sobrescreve_erro_passageiro_anterior(self):
        servico, cliente = self._servico([
            _http(groq.RateLimitError, 429),
            _resposta(self.RECUSA_PT),
            _resposta(self.RECUSA_EN),
        ])
        with self.assertRaises(groq.RateLimitError):
            servico.completar_com_reserva(
                cliente, [{"role": "user", "content": self.PROMPT_DITADO_1}], 0.0, 100, 5.0
            )
        self.assertEqual(
            [modelos_llm.SMART, modelos_llm.FLASH, modelos_llm.CODER],
            self._modelos(cliente),
        )

        servico_prompt, _ = self._servico([
            _http(groq.RateLimitError, 429),
            _resposta(self.RECUSA_PT),
            _resposta(self.RECUSA_EN),
        ])
        with self.assertRaises(groq.RateLimitError):
            servico_prompt.generate_agent_prompt(self.PROMPT_DITADO_1, estrito=True)


if __name__ == "__main__":
    unittest.main()

