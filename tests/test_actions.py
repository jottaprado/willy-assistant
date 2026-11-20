"""
Testes unitários para o módulo core.actions.ActionManager.
"""

import unittest

from core.actions import ActionManager


class TestActionManager(unittest.TestCase):

    def test_is_action_command(self):
        # Casos positivos
        cases_pos = [
            ("Willy, resuma em 3 tópicos", "resuma em 3 tópicos"),
            ("Ei Willy, traduza para inglês", "traduza para inglês"),
            ("willy: corrija a gramática", "corrija a gramática"),
            ("Opa Willy, gere uma lista", "gere uma lista")
        ]
        for frase, esperado in cases_pos:
            is_act, cmd = ActionManager.is_action_command(frase)
            self.assertTrue(is_act, f"Falha para: {frase}")
            self.assertEqual(cmd, esperado)

        # Casos negativos (fala normal, ditado)
        cases_neg = [
            "Olá como você está",
            "Eu preciso fazer uma reunião amanhã",
            "O Willy é um copiloto de voz",
            "",
            None
        ]
        for frase in cases_neg:
            is_act, _ = ActionManager.is_action_command(frase)
            self.assertFalse(is_act, f"Deveria ser falso para: {frase}")

    def test_process_action_without_client_returns_none(self):
        class DummyGroq:
            client = None
            llm_model = "test"

        res = ActionManager.process_action("resuma isso", DummyGroq())
        self.assertIsNone(res)

    def test_process_action_with_real_groq_service_no_key(self):
        from core.groq_service import GroqService
        real_service = GroqService(api_key="")
        # Verifica se o atributo .client existe via @property e é None quando não há chave
        self.assertTrue(hasattr(real_service, "client"))
        self.assertIsNone(real_service.client)
        # process_action deve retornar None sem levantar AttributeError
        res = ActionManager.process_action("resuma isso", real_service)
        self.assertIsNone(res)


class TestAcaoDePromptQueFalha(unittest.TestCase):
    def test_modelo_que_falha_nao_cola_o_payload_cru(self):
        """Sem estrito, o payload "DEMANDA / ESCOPO:..." era colado sobre a seleção em silêncio."""
        from unittest.mock import MagicMock

        from core.groq_service import FalhaDoLLM
        servico = MagicMock()
        servico.generate_agent_prompt.side_effect = FalhaDoLLM("prompt", "DEMANDA / ESCOPO:...")
        self.assertIsNone(ActionManager.process_action("gere um prompt de agente", servico, "seleção"))
        self.assertIs(True, servico.generate_agent_prompt.call_args.kwargs["estrito"])


if __name__ == "__main__":
    unittest.main()

