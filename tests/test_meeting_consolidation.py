"""
Testes unitários para a Consolidação de Reuniões (Ata Executiva + Transcrição na Íntegra).
"""

import unittest
from unittest.mock import MagicMock

from core.groq_service import GroqService


class TestMeetingConsolidation(unittest.TestCase):

    def test_summarize_meeting_consolidates_minutes_and_transcript(self):
        service = GroqService(api_key="fake_key")

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = (
            "## 📝 Ata Executiva da Reunião\n"
            "### 📌 Visão Geral & Tópicos Principais\n"
            "- Alinhamento sobre o novo release v1.5.0\n\n"
            "### 🎯 Decisões Tomadas\n"
            "- Unificar ata e transcrição completa\n\n"
            "### ⚡ Plano de Ação (Action Items)\n"
            "- [ ] Compilar executável"
        )
        mock_choice.message = mock_msg
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        service.get_client = MagicMock(return_value=mock_client)

        transcricao_bruta = (
            "Bom dia a todos, estamos iniciando a nossa reunião semanal de engenharia. "
            "Hoje vamos decidir sobre o formato consolidado de reuniões do Willy. "
            "Queremos a ata executiva no início e a transcrição na íntegra logo abaixo."
        )

        resultado = service.summarize_meeting(transcricao_bruta)

        # 1. Deve conter a ata executiva no início
        self.assertTrue(resultado.startswith("## 📝 Ata Executiva da Reunião"))
        self.assertIn("### 📌 Visão Geral & Tópicos Principais", resultado)
        self.assertIn("### 🎯 Decisões Tomadas", resultado)

        # 2. Deve conter a seção separadora e a transcrição na íntegra intacta abaixo
        self.assertIn("---", resultado)
        self.assertIn("## 📜 Transcrição na Íntegra", resultado)
        self.assertIn(transcricao_bruta, resultado)

    def test_summarize_meeting_fallback_preserves_transcript_on_failure(self):
        service = GroqService(api_key="fake_key")

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        mock_client.chat.completions.create.side_effect = RuntimeError("Conexão interrompida")
        service.get_client = MagicMock(return_value=mock_client)

        transcricao_bruta = "Texto importante da reunião gravado com sucesso pelo microfone."

        resultado = service.summarize_meeting(transcricao_bruta)

        # Em caso de falha da IA, o texto transcrito original NUNCA é perdido
        self.assertEqual(resultado, transcricao_bruta)


if __name__ == "__main__":
    unittest.main()

