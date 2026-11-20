"""
Testes unitários para o Sistema de Armazenamento Automático de Arquivos do Willy (Documentos\\Willy\\).
"""

import os
import unittest

from core.config import ConfigManager
from tests.config_isolada import isolar_config


class TestFileStorage(unittest.TestCase):

    def setUp(self):
        self.tmp_dir_name = isolar_config(self)
        self.test_outputs_dir = os.path.join(self.tmp_dir_name, "Willy_Outputs")
        self.test_history_file = os.path.join(self.tmp_dir_name, ".history.json")

    def test_sanitize_filename(self):
        # Caracteres proibidos no Windows: \ / : * ? " < > |
        nome_sujo = 'Ata: Reunião *Urgente* <Projeto/Willy>? Sim | Não "100%"'
        limpo = ConfigManager.sanitize_filename(nome_sujo)

        for char in r'\/*?:"<>|':
            self.assertNotIn(char, limpo)

        self.assertIn("Ata", limpo)
        self.assertIn("Reunião", limpo)

    def test_subfolder_mapping(self):
        cfg = ConfigManager()
        self.assertEqual(cfg.get_subfolder_for_mode("meeting"), "Atas")
        self.assertEqual(cfg.get_subfolder_for_mode("prompt"), "Prompts")
        self.assertEqual(cfg.get_subfolder_for_mode("transcribe"), "Textos")
        self.assertEqual(cfg.get_subfolder_for_mode("translate"), "Traducoes")
        self.assertEqual(cfg.get_subfolder_for_mode("action"), "Acoes")
        self.assertEqual(cfg.get_subfolder_for_mode("desconhecido"), "Textos")

    def test_save_output_meeting(self):
        cfg = ConfigManager()
        cfg.outputs_dir = self.test_outputs_dir

        texto_reuniao = (
            "## 📝 Ata Executiva da Reunião\n"
            "### 📌 Visão Geral & Tópicos Principais\n"
            "- Planejamento do Sprint 42 e Deploy\n\n"
            "### 🎯 Decisões Tomadas\n"
            "- Aprovação do release v1.5.0\n\n"
            "---\n\n"
            "## 📜 Transcrição na Íntegra\n\n"
            "Bom dia a todos, vamos iniciar nossa reunião..."
        )

        caminho = cfg.save_output_file(texto_reuniao, modo="meeting")
        self.assertIsNotNone(caminho)
        self.assertTrue(os.path.exists(caminho))

        # Deve estar dentro da subpasta Atas
        self.assertIn("Atas", caminho)
        self.assertTrue(caminho.endswith(".md"))

        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()

        self.assertIn("Ata Executiva & Transcrição", conteudo)
        self.assertIn("Planejamento do Sprint 42", conteudo)
        self.assertIn("Bom dia a todos", conteudo)

    def test_save_output_prompt_extracts_goal_title(self):
        cfg = ConfigManager()
        cfg.outputs_dir = self.test_outputs_dir

        texto_prompt = (
            '/goal "Criar tela de checkout responsiva com Tailwind" /loop /maestro:maestro\n\n'
            "MAESTRO → AGENTE 1 · MISSÃO DE LONGO CURSO [FRONTEND]\n"
            "1. FASE 1 (SETUP): ..."
        )

        caminho = cfg.save_output_file(texto_prompt, modo="prompt")
        self.assertIsNotNone(caminho)
        self.assertTrue(os.path.exists(caminho))
        self.assertIn("Prompts", caminho)

        # Nome do arquivo deve conter o goal sanitizado
        nome_arquivo = os.path.basename(caminho)
        self.assertIn("Criar_tela_de_checkout", nome_arquivo)

    def test_save_output_respects_private_mode(self):
        cfg = ConfigManager()
        cfg.outputs_dir = self.test_outputs_dir
        cfg.private_mode = True

        caminho = cfg.save_output_file("Minha senha ultra secreta 123", modo="transcribe")
        self.assertIsNone(caminho)

        # Nenhuma pasta ou arquivo deve ter sido criado
        pasta_textos = os.path.join(self.test_outputs_dir, "Textos")
        self.assertFalse(os.path.exists(pasta_textos))

    def test_modos_send_e_transform_e_audio_path_em_pasta_com_ponto_md(self):
        """AUD-026: save_output_file suporta 'send'/'transform', expõe last_saved_wav_path e HistoryStore não corrompe pasta com '.md'."""
        from core.storage.history_store import HistoryStore

        cfg = ConfigManager()
        cfg.outputs_dir = os.path.join(self.tmp_dir_name, "usuario.md", "Willy_Outputs")
        cfg.private_mode = False
        cfg.save_audio_files = True

        self.assertEqual(cfg.get_subfolder_for_mode("transform"), "Acoes")
        self.assertEqual(cfg.get_subfolder_for_mode("send"), "Textos")

        md_transform = cfg.save_output_file("Texto transformado pela IA", modo="transform", wav_bytes=b"RIFF....WAVE")
        self.assertIsNotNone(md_transform)
        self.assertIn("Acoes", md_transform)
        self.assertIsNotNone(cfg.last_saved_wav_path)
        self.assertTrue(os.path.exists(cfg.last_saved_wav_path))
        with open(md_transform, "r", encoding="utf-8") as f:
            self.assertIn("Transformação de Seleção por Voz", f.read())

        md_send = cfg.save_output_file("Mensagem enviada", modo="send")
        self.assertIsNotNone(md_send)
        self.assertIsNone(cfg.last_saved_wav_path)
        with open(md_send, "r", encoding="utf-8") as f:
            self.assertIn("Ditado e Envio Automático", f.read())

        store = HistoryStore(filepath=self.test_history_file)
        itens = store.save_history_item("Texto transformado pela IA", modo="transform", file_path=md_transform)
        self.assertEqual(itens[-1].get("audio_path"), os.path.splitext(md_transform)[0] + ".wav")
        self.assertIn("usuario.md", itens[-1]["audio_path"])


if __name__ == "__main__":
    unittest.main()
