"""
Testes Unitários e de Integração: Perfis de Tom de Escrita & Modo Bilíngue Fluido do Willy.
"""

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from core.config import ConfigManager
from core.groq_service import GroqService
from core.text_processing import TextProcessor
from tests.config_isolada import isolar_config


class TestToneAndLanguage(unittest.TestCase):
    """Bateria de testes para as funcionalidades de Tom de Escrita e Modo Bilíngue."""

    def setUp(self):
        self.tmp_dir_name = isolar_config(self)

    # -------------------------------------------------------------
    # 1. Testes de Detecção de Tom de Voz (TextProcessor.detect_voice_tone)
    # -------------------------------------------------------------
    def test_detect_voice_tone_formal(self):
        # Prefixo com Willy
        text, tone = TextProcessor.detect_voice_tone("Willy formal: Prezado Diretor, segue relatório em anexo.")
        self.assertEqual(tone, "formal")
        self.assertEqual(text, "Prezado Diretor, segue relatório em anexo.")

        # Prefixo executivo
        text, tone = TextProcessor.detect_voice_tone("Willy executivo: Aprovamos a proposta comercial apresentada.")
        self.assertEqual(tone, "formal")
        self.assertEqual(text, "Aprovamos a proposta comercial apresentada.")

        # Prefixo Modo formal
        text, tone = TextProcessor.detect_voice_tone("Modo formal: Bom dia a todos os presentes.")
        self.assertEqual(tone, "formal")
        self.assertEqual(text, "Bom dia a todos os presentes.")

    def test_detect_voice_tone_concise(self):
        text, tone = TextProcessor.detect_voice_tone("Willy conciso: Reunião adiada para amanhã às 15 horas.")
        self.assertEqual(tone, "concise")
        self.assertEqual(text, "Reunião adiada para amanhã às 15 horas.")

        text, tone = TextProcessor.detect_voice_tone("Willy direto: Deploy finalizado com sucesso no cluster.")
        self.assertEqual(tone, "concise")
        self.assertEqual(text, "Deploy finalizado com sucesso no cluster.")

    def test_detect_voice_tone_bullet_points(self):
        text, tone = TextProcessor.detect_voice_tone("Willy em tópicos: comprar café, revisar PR e marcar reunião.")
        self.assertEqual(tone, "bullet_points")
        self.assertEqual(text, "Comprar café, revisar PR e marcar reunião.")

        text, tone = TextProcessor.detect_voice_tone("Willy bullet points: item um, item dois, item três.")
        self.assertEqual(tone, "bullet_points")
        self.assertEqual(text, "Item um, item dois, item três.")

    def test_detect_voice_tone_technical(self):
        text, tone = TextProcessor.detect_voice_tone("Willy técnico: rode docker compose up e verifique os logs da API.")
        self.assertEqual(tone, "technical")
        self.assertEqual(text, "Rode docker compose up e verifique os logs da API.")

        text, tone = TextProcessor.detect_voice_tone("Willy dev: faça git checkout -b feature/login.")
        self.assertEqual(tone, "technical")
        self.assertEqual(text, "Faça git checkout -b feature/login.")

    def test_detect_voice_tone_natural_and_none(self):
        text, tone = TextProcessor.detect_voice_tone("Willy natural: Apenas transcreva sem alterar nada.")
        self.assertEqual(tone, "natural")
        self.assertEqual(text, "Apenas transcreva sem alterar nada.")

        # Texto comum sem prefixo de tom
        text, tone = TextProcessor.detect_voice_tone("Hoje nós vamos falar sobre arquitetura limpa de software.")
        self.assertIsNone(tone)
        self.assertEqual(text, "Hoje nós vamos falar sobre arquitetura limpa de software.")

        # Texto vazio
        text, tone = TextProcessor.detect_voice_tone("")
        self.assertIsNone(tone)
        self.assertEqual(text, "")

    # -------------------------------------------------------------
    # 2. Testes de Limpeza Bilíngue (TextProcessor.clean_filler_words)
    # -------------------------------------------------------------
    def test_clean_filler_words_english(self):
        # Hesitações em inglês
        res = TextProcessor.clean_filler_words("umm, we should definitely try that, you know?")
        self.assertNotIn("umm", res.lower())
        self.assertNotIn("you know", res.lower())
        self.assertTrue("definitely try that" in res)

        # Repetições gaguejadas em inglês
        res_stutter = TextProcessor.clean_filler_words("I I think that that is very good")
        self.assertEqual(res_stutter, "I think that is very good")

        # Preservação do português
        res_pt = TextProcessor.clean_filler_words("então... ééé... vamos aprovar o PR, tipo assim, com certeza, né?")
        self.assertNotIn("ééé", res_pt)
        self.assertNotIn("tipo assim", res_pt)
        self.assertNotIn("né", res_pt)

    # -------------------------------------------------------------
    # 3. Testes de Configuração (ConfigManager)
    # -------------------------------------------------------------
    def test_config_defaults(self):
        cfg = ConfigManager()
        self.assertEqual(cfg.output_tone, "natural")
        self.assertEqual(cfg.input_language, "auto")

    def test_config_save_and_reload(self):
        cfg = ConfigManager()
        cfg.save_settings({
            "OUTPUT_TONE": "formal",
            "INPUT_LANGUAGE": "en"
        })
        self.assertEqual(cfg.output_tone, "formal")
        self.assertEqual(cfg.input_language, "en")

        cfg2 = ConfigManager()
        self.assertEqual(cfg2.output_tone, "formal")
        self.assertEqual(cfg2.input_language, "en")

    def test_get_prompt_context_adaptation(self):
        cfg = ConfigManager()

        # No modo automático, inclui contexto bilíngue
        cfg.input_language = "auto"
        ctx_auto = cfg.get_prompt_context()
        self.assertTrue("bilíngue" in ctx_auto.lower() or "bilingual" in ctx_auto.lower())

        # No modo inglês puro
        cfg.input_language = "en"
        ctx_en = cfg.get_prompt_context()
        self.assertTrue("technical programming" in ctx_en.lower())

        # No modo português
        cfg.input_language = "pt"
        ctx_pt = cfg.get_prompt_context()
        self.assertTrue("vocabulário técnico de programação" in ctx_pt.lower())

    def test_profile_export_and_import_with_tone_and_lang(self):
        cfg = ConfigManager()
        cfg.save_settings({
            "OUTPUT_TONE": "technical",
            "INPUT_LANGUAGE": "pt"
        })

        export_file = os.path.join(self.tmp_dir_name, "perfil_teste.json")
        ok = cfg.export_profile(export_file)
        self.assertTrue(ok)

        with open(export_file, "r", encoding="utf-8") as f:
            dados = json.load(f)
        self.assertEqual(dados["settings"]["OUTPUT_TONE"], "technical")
        self.assertEqual(dados["settings"]["INPUT_LANGUAGE"], "pt")

        # Modifica e restaura
        cfg.save_settings({"OUTPUT_TONE": "natural", "INPUT_LANGUAGE": "auto"})
        self.assertEqual(cfg.output_tone, "natural")

        ok_import = cfg.import_profile(export_file)
        self.assertTrue(ok_import)
        self.assertEqual(cfg.output_tone, "technical")
        self.assertEqual(cfg.input_language, "pt")

    # -------------------------------------------------------------
    # 4. Testes do GroqService (Tone Instructions & Transcribe Language)
    # -------------------------------------------------------------
    def test_groq_service_tone_instructions(self):
        # Verifica se cada tom produz instruções distintas
        inst_formal = GroqService._get_tone_instructions("formal")
        self.assertIn("EXECUTIVO / FORMAL", inst_formal)

        inst_concise = GroqService._get_tone_instructions("concise")
        self.assertIn("DIRETO / CONCISO", inst_concise)

        inst_bullets = GroqService._get_tone_instructions("bullet_points")
        self.assertIn("TÓPICOS / BULLET POINTS", inst_bullets)

        inst_tech = GroqService._get_tone_instructions("technical")
        self.assertIn("TÉCNICO / DEV", inst_tech)

        inst_nat = GroqService._get_tone_instructions("natural")
        self.assertIn("NATURAL / FIEL", inst_nat)

    @patch("core.groq_service.Groq")
    def test_groq_service_transcribe_language_param(self, mock_groq_class):
        mock_client = MagicMock()
        mock_groq_class.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.text = "Hello world from test"
        mock_client.audio.transcriptions.create.return_value = mock_resp

        svc = GroqService(api_key="gsk_teste")
        buf = io.BytesIO(b"fake wav data")

        # Chamada com language="pt"
        res = svc.transcribe(buf, "prompt", language="pt")
        self.assertEqual(res, "Hello world from test")
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        self.assertEqual(call_kwargs["language"], "pt")

        # Chamada com language="auto" (não deve passar language para permitir auto-detecção)
        buf.seek(0)
        svc.transcribe(buf, "prompt", language="auto")
        call_kwargs2 = mock_client.audio.transcriptions.create.call_args[1]
        self.assertNotIn("language", call_kwargs2)


if __name__ == "__main__":
    unittest.main()
