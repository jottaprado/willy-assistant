"""
Testes Unitários para as Funcionalidades do Willy v1.8.0:
1. Leitura de Texto em Voz Alta (TTS Nativo SAPI Windows)
2. Fixar Aplicativo Alvo (Sticky Focus / Ditado Invisível)
3. Salvar Áudio Original (.wav) junto com Textos e Atas
4. Teleprompter Flutuante de Legendas em Tempo Real (Live Captions)
5. Métricas Avançadas & Insights de Fala (WPM & Tempo Real Economizado)
6. Comandos de Ação para Leitura por Voz
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.actions import ActionManager
from core.config import ConfigManager
from core.context import ContextManager
from core.sound import SoundManager
from core.tts import TTSManager
from tests.config_isolada import isolar_config


class TestV18TTSManager(unittest.TestCase):
    """Testes para o motor de Text-to-Speech nativo Windows SAPI."""

    def setUp(self):
        self.tts = TTSManager()

    def test_voice_selection_pt_and_en(self):
        # Texto predominantemente em português
        texto_pt = "Olá mundo, este é um teste completo do Willy em português."
        voz_pt = self.tts.escolher_voz(texto_pt)
        self.assertIn("MARIA", voz_pt.upper())

        # Texto predominantemente em inglês
        texto_en = "Hello world, this is a complete test of Willy speech synthesizer with english words."
        voz_en = self.tts.escolher_voz(texto_en)
        self.assertIn("ZIRA", voz_en.upper())

    def test_tts_is_speaking_lifecycle(self):
        self.assertFalse(self.tts.is_speaking)
        # Simula processo em execução
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        self.tts._process = mock_proc
        self.tts._is_speaking = True

        self.assertTrue(self.tts.is_speaking)

        # Teste de interrupção instantânea
        self.tts.stop()
        self.assertFalse(self.tts.is_speaking)
        mock_proc.kill.assert_called_once()


class TestV18StickyFocus(unittest.TestCase):
    """Testes para a funcionalidade de Fixar Aplicativo Alvo (Sticky Focus)."""

    def setUp(self):
        ContextManager.clear_sticky_window()

    def tearDown(self):
        ContextManager.clear_sticky_window()

    def test_sticky_window_pin_and_unpin(self):
        self.assertIsNone(ContextManager.get_sticky_window())

        with patch("core.context.user32") as mock_user32:
            mock_user32.IsWindow.return_value = 1
            # Fixa uma janela fictícia (hwnd = 123456)
            ContextManager.set_sticky_window(123456, "Notion")
            self.assertEqual(ContextManager.get_sticky_window(), (123456, "Notion"))

            # Desfixa
            ContextManager.clear_sticky_window()
            self.assertIsNone(ContextManager.get_sticky_window())


class TestV18ActionSpeakCommand(unittest.TestCase):
    """Testes para detecção de comandos de voz para leitura."""

    def test_is_speak_command(self):
        self.assertTrue(ActionManager.is_speak_command("leia isso"))
        self.assertTrue(ActionManager.is_speak_command("ler o texto selecionado"))
        self.assertTrue(ActionManager.is_speak_command("fale em voz alta"))
        self.assertTrue(ActionManager.is_speak_command("diga esse parágrafo"))
        self.assertTrue(ActionManager.is_speak_command("speak this"))
        self.assertFalse(ActionManager.is_speak_command("resuma em 3 tópicos"))
        self.assertFalse(ActionManager.is_speak_command("traduza para inglês"))


class TestV18AudioSavingAndMarkdownLink(unittest.TestCase):
    """Testes para gravação de áudio companion (.wav) e link no Markdown."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        isolar_config(self)
        self.cfg = ConfigManager()
        self.cfg.outputs_dir = self.temp_dir.name
        self.cfg.private_mode = False
        self.cfg.save_audio_files = True

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_output_file_with_wav(self):
        texto = "Reunião de alinhamento estratégico sobre o produto."
        fake_wav = b"RIFF....WAVEfmt ....data...."

        md_path = self.cfg.save_output_file(texto, modo="meeting", wav_bytes=fake_wav)
        self.assertIsNotNone(md_path)
        self.assertTrue(os.path.exists(md_path))

        # Verifica arquivo .wav correspondente
        wav_path = md_path.replace(".md", ".wav")
        self.assertTrue(os.path.exists(wav_path))
        with open(wav_path, "rb") as f:
            self.assertEqual(f.read(), fake_wav)

        # Verifica link no arquivo markdown
        with open(md_path, "r", encoding="utf-8") as f:
            conteudo = f.read()
            self.assertIn("Áudio Original", conteudo)
            self.assertIn(".wav", conteudo)


class TestV18MetricsWPM(unittest.TestCase):
    """Testes para métricas de produtividade avançada (WPM, tempo líquido, horários e termos)."""

    def test_analytics_metrics_calculation(self):
        isolar_config(self)
        cfg = ConfigManager()
        fake_history = [
            {"text": "Python async await docker api", "words": 5, "timestamp": "17/09/2026 14:30", "mode": "transcribe"},
            {"text": "Refatoração de arquitetura de software e testes unitários", "words": 8, "timestamp": "17/09/2026 14:45", "mode": "transcribe"},
            {"text": "Meeting notes feedback sprint roadmap", "words": 5, "timestamp": "17/09/2026 16:10", "mode": "meeting"}
        ]
        with patch.object(cfg, "load_history", return_value=fake_history):
            metrics = cfg.get_analytics_metrics()
            self.assertEqual(metrics["total_prompts"], 3)
            self.assertEqual(metrics["total_words"], 18)
            self.assertEqual(metrics["avg_wpm"], 0)  # itens sem duration_s: nada medido
            self.assertIn("14:00 - 15:00", metrics["peak_hour"])
            self.assertIsInstance(metrics["top_keywords"], list)
            self.assertTrue(len(metrics["top_keywords"]) > 0)


class TestV18SoundManagerPlayWav(unittest.TestCase):
    """Testes para o tocador nativo de áudio do SoundManager."""

    def test_play_wav_file(self):
        sm = SoundManager()
        # Arquivo inexistente retorna False
        self.assertFalse(sm.play_wav_file("arquivo_inexistente_123.wav"))
        self.assertFalse(sm.play_wav_file(""))


if __name__ == "__main__":
    unittest.main()
