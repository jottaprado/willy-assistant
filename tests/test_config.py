"""
Testes unitários para o módulo core.config.ConfigManager.
"""

import os
import unittest
from unittest.mock import patch

import core.config as cfg_module
from core.config import DEV_PROMPT_CONTEXT, ConfigManager
from tests.config_isolada import isolar_config


class TestConfigManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = isolar_config(self)

    def test_default_values(self):
        # O load_dotenv de outros testes deixa GROQ_LLM_MODEL no ambiente.
        with patch.dict(os.environ):
            os.environ.pop("GROQ_LLM_MODEL", None)
            cfg = ConfigManager()
        self.assertEqual(cfg.hotkey, "ctrl+space")
        self.assertEqual(cfg.translate_hotkey, "ctrl+alt+space")
        self.assertEqual(cfg.master_hotkey, "ctrl+shift+space")
        self.assertEqual(cfg.meeting_hotkey, "ctrl+alt+r")
        self.assertEqual(cfg.model, "whisper-large-v3-turbo")
        self.assertEqual(cfg.translate_model, "whisper-large-v3")
        self.assertEqual("openai/gpt-oss-120b", cfg.llm_model)
        self.assertIsInstance(cfg.silence_seconds, float)

    def test_save_and_reload_settings(self):
        cfg = ConfigManager()
        cfg.save_settings({
            "SILENCE_SECONDS": 3.0,
            "REFINE_PROMPT": False,
            "SILENT_MODE": True,
            "PILL_POSITION": "topo",
            "GROQ_LLM_MODEL": "openai/gpt-oss-20b",
            "MEETING_HOTKEY": "ctrl+alt+m",
            "GROQ_API_KEY": "test_key_12345"
        })

        cfg2 = ConfigManager()
        self.assertEqual(cfg2.silence_seconds, 3.0)
        self.assertFalse(cfg2.refine_prompt)
        self.assertTrue(cfg2.silent_mode)
        self.assertEqual(cfg2.pill_position, "topo")
        self.assertEqual(cfg2.llm_model, "openai/gpt-oss-20b")
        self.assertEqual(cfg2.meeting_hotkey, "ctrl+alt+m")
        self.assertEqual(cfg2.groq_api_key, "test_key_12345")

    def test_history_operations(self):
        cfg = ConfigManager()
        self.assertEqual(cfg.load_history(), [])

        # Salva itens
        cfg.save_history_item("Primeiro teste", "transcribe")
        cfg.save_history_item("Segundo teste", "translate")

        itens = cfg.load_history()
        self.assertEqual(len(itens), 2)
        self.assertEqual(itens[0]["text"], "Primeiro teste")
        self.assertEqual(itens[0]["mode"], "transcribe")
        self.assertEqual(itens[1]["text"], "Segundo teste")
        self.assertEqual(itens[1]["mode"], "translate")

        # Limpa histórico
        cfg.clear_history()
        self.assertEqual(cfg.load_history(), [])

    def test_history_limit_100(self):
        cfg = ConfigManager()
        for i in range(120):
            cfg.save_history_item(f"Prompt {i}")

        itens = cfg.load_history()
        self.assertEqual(len(itens), 100)
        self.assertEqual(itens[-1]["text"], "Prompt 119")

    def test_vocab_operations(self):
        cfg = ConfigManager()
        conteudo = "FastAPI, PyTorch, LangChain\nKubernetes, Docker\n# Comentário\n"
        cfg.save_vocab_text(conteudo)

        self.assertEqual(cfg.load_vocab_text(), conteudo)

        termos = cfg.get_vocab_terms()
        self.assertIn("FastAPI", termos)
        self.assertIn("PyTorch", termos)
        self.assertIn("LangChain", termos)
        self.assertIn("Kubernetes", termos)
        self.assertIn("Docker", termos)
        self.assertNotIn("# Comentário", termos)

        contexto = cfg.get_prompt_context()
        self.assertIn("FastAPI", contexto)
        self.assertIn(DEV_PROMPT_CONTEXT, contexto)

    def test_get_analytics_metrics(self):
        cfg = ConfigManager()
        cfg.save_history_item("Texto número um com seis palavras", modo="transcribe")
        cfg.save_history_item("Another prompt in English with seven words", modo="translate")

        metrics = cfg.get_analytics_metrics()
        self.assertEqual(metrics["total_prompts"], 2)
        self.assertEqual(metrics["total_words"], 13)
        self.assertGreaterEqual(metrics["words_today"], 13)
        self.assertIn("favorite_mode", metrics)


    def test_prompt_context_length_limit(self):
        cfg = ConfigManager()
        # Simula vocabulário enorme com mais de 3000 caracteres
        vocab_longo = "\n".join([f"termo_tecnico_{i}, conceito_muito_longo_{i}" for i in range(150)])
        cfg.save_vocab_text(vocab_longo)

        ctx = cfg.get_prompt_context()
        # Deve respeitar rigorosamente o teto seguro de 850 caracteres
        self.assertLessEqual(len(ctx), 850)
        self.assertLessEqual(len(ctx), 896)

    def test_save_settings_persiste_modelos_whisper_e_limiares_rms(self):
        """AUD-024: save_settings atualiza GROQ_MODEL, GROQ_TRANSLATE_MODEL, SILENCE_THRESHOLD e SPEECH_THRESHOLD."""
        cfg = ConfigManager()
        cfg.save_settings({
            "GROQ_MODEL": "whisper-large-v3",
            "GROQ_TRANSLATE_MODEL": "whisper-large-v3-turbo",
            "SILENCE_THRESHOLD": 0.012,
            "SPEECH_THRESHOLD": 0.025,
        })
        self.assertEqual(cfg.model, "whisper-large-v3")
        self.assertEqual(cfg.translate_model, "whisper-large-v3-turbo")
        self.assertAlmostEqual(cfg.silence_threshold, 0.012)
        self.assertAlmostEqual(cfg.speech_threshold, 0.025)

        relido = ConfigManager()
        self.assertEqual(relido.model, "whisper-large-v3")
        self.assertEqual(relido.translate_model, "whisper-large-v3-turbo")
        self.assertAlmostEqual(relido.silence_threshold, 0.012)
        self.assertAlmostEqual(relido.speech_threshold, 0.025)

        # Valores inválidos para os limiares ou modelos vazios mantêm os anteriores
        relido.save_settings({
            "GROQ_MODEL": "   ",
            "GROQ_TRANSLATE_MODEL": "",
            "SILENCE_THRESHOLD": -5.0,
            "SPEECH_THRESHOLD": "invalido",
        })
        self.assertEqual(relido.model, "whisper-large-v3")
        self.assertEqual(relido.translate_model, "whisper-large-v3-turbo")
        self.assertAlmostEqual(relido.silence_threshold, 0.012)
        self.assertAlmostEqual(relido.speech_threshold, 0.025)

    def test_validacao_de_dominio_em_output_tone_input_language_e_pill_position(self):
        """AUD-024: valores inválidos para OUTPUT_TONE, INPUT_LANGUAGE e PILL_POSITION são recusados."""
        cfg = ConfigManager()
        cfg.save_settings({
            "OUTPUT_TONE": "formal",
            "INPUT_LANGUAGE": "pt",
            "PILL_POSITION": "seguir_cursor",
        })
        self.assertEqual(cfg.output_tone, "formal")
        self.assertEqual(cfg.input_language, "pt")
        self.assertEqual(cfg.pill_position, "seguir_cursor")

        cfg.save_settings({
            "OUTPUT_TONE": "sarcastico_invalido",
            "INPUT_LANGUAGE": "klingon",
            "PILL_POSITION": "fora_da_tela",
        })
        self.assertEqual(cfg.output_tone, "formal")
        self.assertEqual(cfg.input_language, "pt")
        self.assertEqual(cfg.pill_position, "seguir_cursor")

        # Em reload() a partir de .env editado manualmente com valores inválidos, cai nos padrões seguros
        with open(cfg_module.ENV_FILE, "w", encoding="utf-8") as f:
            f.write("OUTPUT_TONE=invalido\nINPUT_LANGUAGE=xx\nPILL_POSITION=invalido\n")
        cfg_env_invalido = ConfigManager()
        self.assertEqual(cfg_env_invalido.output_tone, "natural")
        self.assertEqual(cfg_env_invalido.input_language, "auto")
        self.assertEqual(cfg_env_invalido.pill_position, "centro_inferior")

    def test_settings_store_falha_no_replace_nao_trunca_env_nem_vaza_temporario(self):
        """AUD-044: falha persistente em os.replace não sobrescreve o .env de forma não-atômica nem deixa .tmp_*."""
        from core.storage.settings_store import SettingsStore

        store = SettingsStore(env_file=cfg_module.ENV_FILE)
        with open(cfg_module.ENV_FILE, "w", encoding="utf-8") as f:
            f.write("# Comentario importante\nVOICE_HOTKEY=ctrl+space\n")

        with patch("os.replace", side_effect=OSError("disco bloqueado")):
            ok = store.save_settings({"VOICE_HOTKEY": "ctrl+alt+v"})

        self.assertFalse(ok)
        with open(cfg_module.ENV_FILE, "r", encoding="utf-8") as f:
            conteudo = f.read()
        self.assertEqual(conteudo, "# Comentario importante\nVOICE_HOTKEY=ctrl+space\n")
        temporarios = [nome for nome in os.listdir(self.test_dir) if nome.startswith(".tmp_")]
        self.assertEqual(temporarios, [])

        # Retentativa em PermissionError transitório (ex.: antivírus no Windows) deve ter sucesso
        chamadas = []
        replace_real = os.replace

        def replace_transitorio(src, dst):
            chamadas.append((src, dst))
            if len(chamadas) == 1:
                raise PermissionError("arquivo temporariamente em uso")
            return replace_real(src, dst)

        with patch("os.replace", side_effect=replace_transitorio), patch("time.sleep"):
            self.assertTrue(store.save_settings({"VOICE_HOTKEY": "ctrl+alt+v"}))
        self.assertEqual(len(chamadas), 2)

        # AUD-082 e AUD-084: .env.template contém as chaves gerenciadas e .gitignore ignora quarentenas
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(raiz, ".env.template"), "r", encoding="utf-8") as f:
            template_txt = f.read()
        for chave in ("SYSTEM_AUDIO_DEVICE=", "MIC_GAIN=", "PRIVATE_MODE=", "OUTPUTS_DIR="):
            self.assertIn(chave, template_txt)
        with open(os.path.join(raiz, ".gitignore"), "r", encoding="utf-8") as f:
            gitignore_txt = f.read()
        self.assertIn("*.corrompido-*", gitignore_txt)


if __name__ == "__main__":
    unittest.main()
