"""
Testes unitários para o módulo core.groq_service.GroqService.
"""

import io
import unittest
from unittest.mock import MagicMock, patch

import groq

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


if __name__ == "__main__":
    unittest.main()

