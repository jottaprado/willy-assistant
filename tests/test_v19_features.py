"""
Testes Unitários para as Funcionalidades do Willy v1.9.0:
1. Modo Transformar Seleção por Voz (In-Place Text AI Transformer)
2. Perfis de Processamento de IA (Dev & Código vs Executivo & Prosa vs Puro Zero-Latency)
3. Modo Sussurro & Ganho Automático (Whisper Mode / AGC 3.0x Boost)
4. Presets Populares no Dicionário Fonético (Kubernetes, Docker, PostgreSQL, PR, etc.)
5. Persistência de Configurações e Backup de Perfil v1.9.0
"""

import json
import os
import unittest
from unittest.mock import MagicMock

from core.actions import ActionManager
from core.audio import AudioManager
from core.config import ConfigManager
from core.groq_service import GroqService
from tests.config_isolada import isolar_config
from versao import __version__


class TestV19TransformText(unittest.TestCase):
    """Testes para a funcionalidade de Transformar Seleção por Voz."""

    def test_is_transform_command(self):
        # Comandos afirmativos de transformação
        ok, inst = ActionManager.is_transform_command("transforme isso em uma lista de tópicos")
        self.assertTrue(ok)
        self.assertIn("lista de tópicos", inst.lower())

        ok, inst = ActionManager.is_transform_command("traduza o texto selecionado para espanhol")
        self.assertTrue(ok)
        self.assertIn("espanhol", inst.lower())

        ok, inst = ActionManager.is_transform_command("reescreva este parágrafo de forma executiva")
        self.assertTrue(ok)
        self.assertIn("executiva", inst.lower())

        ok, inst = ActionManager.is_transform_command("mude isso para código python")
        self.assertTrue(ok)
        self.assertIn("python", inst.lower())

        ok, inst = ActionManager.is_transform_command("resuma essa seleção em 3 bullets")
        self.assertTrue(ok)
        self.assertIn("bullets", inst.lower())

        # Comandos comuns que NÃO devem disparar transformação
        ok, _ = ActionManager.is_transform_command("olá bom dia como vai você")
        self.assertFalse(ok)
        ok, _ = ActionManager.is_transform_command("crie uma nova função chamada calcular_total")
        self.assertFalse(ok)

    def test_transform_text_groq_service(self):
        serv = GroqService(api_key="gsk_dummy_test_key")
        serv.get_client = MagicMock()
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        mock_choice = MagicMock()
        mock_choice.message.content = "Texto transformado com sucesso."
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        serv.get_client.return_value = mock_client

        base = "esse texto aqui ta meio informal"
        instrucao = "torne formal e executivo"
        res = serv.transform_text(base, instrucao)

        self.assertEqual(res, "Texto transformado com sucesso.")
        mock_client.chat.completions.create.assert_called_once()

    def test_transform_text_empty_input_fallback(self):
        serv = GroqService(api_key="")
        res = serv.transform_text("", "faça algo")
        self.assertEqual(res, "")

        res_base = serv.transform_text("Texto original", "")
        self.assertEqual(res_base, "Texto original")


class TestV19AIProcessingProfiles(unittest.TestCase):
    """Testes para os Perfis de Processamento de IA (Dev, Executivo, Puro)."""

    def test_profile_puro_zero_latency_bypass(self):
        serv = GroqService(api_key="gsk_test")
        serv.get_client = MagicMock()
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        serv.get_client.return_value = mock_client

        # No perfil "puro", o LLM deve ser completamente bypassado sem chamadas de rede
        raw_text = "Criando branch feature login no git"
        res = serv.refine_text(raw_text, profile="puro")

        self.assertEqual(res, raw_text)
        mock_client.chat.completions.create.assert_not_called()

    def test_profile_dev_prompt(self):
        serv = GroqService(api_key="gsk_test")
        serv.get_client = MagicMock()
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        mock_choice = MagicMock()
        mock_choice.message.content = "git checkout -b feature/login"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        serv.get_client.return_value = mock_client

        res = serv.refine_text("git checkout b feature login", profile="dev")
        self.assertEqual(res, "git checkout -b feature/login")
        calls = mock_client.chat.completions.create.call_args
        messages = calls[1]["messages"]
        system_content = messages[0]["content"]
        self.assertIn("Perfil de Processamento Ativo: DEV & CÓDIGO", system_content)
        self.assertIn("snake_case", system_content)

    def test_profile_executivo_prompt(self):
        serv = GroqService(api_key="gsk_test")
        serv.get_client = MagicMock()
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client  # o serviço desliga as tentativas do SDK
        mock_choice = MagicMock()
        mock_choice.message.content = "Prezados, confirmamos o alinhamento da reunião."
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        serv.get_client.return_value = mock_client

        res = serv.refine_text("ai gente confirmamos a reunião", profile="executivo")
        self.assertEqual(res, "Prezados, confirmamos o alinhamento da reunião.")
        calls = mock_client.chat.completions.create.call_args
        messages = calls[1]["messages"]
        system_content = messages[0]["content"]
        self.assertIn("Perfil de Processamento Ativo: EXECUTIVO & PROSA", system_content)


class TestV19WhisperModeAndGainBoost(unittest.TestCase):
    """Testes para o Modo Sussurro e amplificação digital AGC."""

    def test_set_whisper_mode_toggle(self):
        audio = AudioManager()
        self.assertFalse(audio.whisper_mode)

        # Ativa o modo sussurro
        audio.set_whisper_mode(True)
        self.assertTrue(audio.whisper_mode)
        self.assertEqual(audio.gain_boost, 3.0)

        # Desativa o modo sussurro
        audio.set_whisper_mode(False)
        self.assertFalse(audio.whisper_mode)
        self.assertEqual(audio.gain_boost, 1.0)

    def test_whisper_mode_adaptive_thresholds(self):
        audio = AudioManager()
        audio.noise_floor = 0.01

        # Modo normal
        thresh_normal, min_sil_normal = audio.get_adaptive_thresholds(0.015, 0.008)

        # Ativa sussurro: limiares devem ser significativamente mais sensíveis (menores)
        audio.set_whisper_mode(True)
        thresh_whisper, min_sil_whisper = audio.get_adaptive_thresholds(0.015, 0.008)

        self.assertLess(thresh_whisper, thresh_normal)
        self.assertLess(min_sil_whisper, min_sil_normal)


class TestV19ConfigAndHotkeys(unittest.TestCase):
    """Testes para persistência de dados v1.9.0 e exportação de perfil."""

    def setUp(self):
        self.test_dir = isolar_config(self)
        self.cfg = ConfigManager()

    def test_v19_default_config_fields(self):
        self.assertEqual(self.cfg.transform_hotkey, "ctrl+alt+t")
        self.assertEqual(self.cfg.profile_hotkey, "ctrl+alt+e")
        self.assertEqual(self.cfg.processing_profile, "dev")
        self.assertFalse(self.cfg.whisper_mode)

    def test_v19_save_and_reload_settings(self):
        novos = {
            "TRANSFORM_HOTKEY": "ctrl+shift+t",
            "PROFILE_HOTKEY": "ctrl+shift+p",
            "PROCESSING_PROFILE": "executivo",
            "WHISPER_MODE": True
        }
        self.cfg.save_settings(novos)

        # Recarrega em uma nova instância apontando para o mesmo .env
        cfg2 = ConfigManager()
        self.assertEqual(cfg2.transform_hotkey, "ctrl+shift+t")
        self.assertEqual(cfg2.profile_hotkey, "ctrl+shift+p")
        self.assertEqual(cfg2.processing_profile, "executivo")
        self.assertTrue(cfg2.whisper_mode)

    def test_v19_export_and_import_profile(self):
        export_file = os.path.join(self.test_dir, "perfil_v19.json")
        self.cfg.processing_profile = "puro"
        self.cfg.whisper_mode = True
        self.cfg.transform_hotkey = "ctrl+alt+t"
        self.cfg.profile_hotkey = "ctrl+alt+e"

        ok = self.cfg.export_profile(export_file)
        self.assertTrue(ok)

        with open(export_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("willy_version"), __version__)
        settings = data.get("settings", {})
        self.assertEqual(settings.get("PROCESSING_PROFILE"), "puro")
        self.assertEqual(settings.get("WHISPER_MODE"), True)
        self.assertEqual(settings.get("TRANSFORM_HOTKEY"), "ctrl+alt+t")
        self.assertEqual(settings.get("PROFILE_HOTKEY"), "ctrl+alt+e")


class TestV19TechPresets(unittest.TestCase):
    """Testes para o catálogo de presets tech do vocabulário fonético."""

    def setUp(self):
        self.test_dir = isolar_config(self)

    def test_presets_vocabulary_keys(self):
        presets = [
            ("k8s", "Kubernetes"),
            ("dock", "Docker"),
            ("postegres", "PostgreSQL"),
            ("git hub", "GitHub"),
            ("pr", "PR"),
            ("ci cd", "CI/CD"),
            ("fast api", "FastAPI"),
            ("tailwind", "Tailwind CSS")
        ]
        # Aplica substituições fonéticas no ConfigManager
        cfg = ConfigManager()
        for de, para in presets:
            cfg.add_replacement(de, para)

        reps = cfg.load_replacements()
        self.assertEqual(reps.get("k8s"), "Kubernetes")
        self.assertEqual(reps.get("postegres"), "PostgreSQL")
        self.assertEqual(reps.get("pr"), "PR")


if __name__ == "__main__":
    unittest.main()
