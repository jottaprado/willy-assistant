"""
Testes unitários para o módulo core.context.ContextManager.
"""

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import core.context as context_mod
from core.context import APP_CATEGORY_MAP, ContextCategory, ContextManager


class TestContextManager(unittest.TestCase):

    def test_app_category_mappings(self):
        self.assertEqual(APP_CATEGORY_MAP.get("code.exe"), ContextCategory.CODING)
        self.assertEqual(APP_CATEGORY_MAP.get("cursor.exe"), ContextCategory.CODING)
        self.assertEqual(APP_CATEGORY_MAP.get("whatsapp.exe"), ContextCategory.MESSAGING)
        self.assertEqual(APP_CATEGORY_MAP.get("slack.exe"), ContextCategory.MESSAGING)
        self.assertEqual(APP_CATEGORY_MAP.get("winword.exe"), ContextCategory.DOCUMENT)
        self.assertEqual(APP_CATEGORY_MAP.get("chrome.exe"), ContextCategory.BROWSER)

    def test_get_foreground_app_classifies_process_and_handles_zero_hwnd(self):
        """AUD-105: Verifica deterministicamente get_foreground_app com mocks Win32 e psutil."""
        fake_u32 = MagicMock()
        fake_u32.GetForegroundWindow.return_value = 0
        with patch.object(context_mod, "user32", fake_u32):
            self.assertEqual(
                ContextManager.get_foreground_app(),
                ("desktop.exe", "Área de Trabalho", ContextCategory.GENERAL),
            )

        fake_u32.GetForegroundWindow.return_value = 4242
        fake_u32.GetWindowTextLengthW.return_value = 18

        def _preencher_titulo(_hwnd, buf, _max_len):
             buf.value = "willy.py - VS Code"
             return len(buf.value)

        fake_u32.GetWindowTextW.side_effect = _preencher_titulo
        fake_k32 = MagicMock()
        fake_k32.OpenProcess.return_value = 999

        def _preencher_exe(_hproc, _flags, buf, size_ptr):
            buf.value = r"C:\Program Files\Microsoft VS Code\Code.exe"
            return True

        fake_k32.QueryFullProcessImageNameW.side_effect = _preencher_exe

        with patch.object(context_mod, "user32", fake_u32), \
             patch.object(context_mod, "kernel32", fake_k32):
            exe, title, category = ContextManager.get_foreground_app()

        fake_k32.CloseHandle.assert_called_once_with(999)

        self.assertEqual(exe, "code.exe")
        self.assertEqual(title, "willy.py - VS Code")
        self.assertEqual(category, ContextCategory.CODING)

    def test_prompt_instructions(self):
        inst_code = ContextManager.get_context_prompt_instruction(ContextCategory.CODING)
        self.assertIn("desenvolvimento", inst_code.lower())

        inst_msg = ContextManager.get_context_prompt_instruction(ContextCategory.MESSAGING)
        self.assertIn("mensagens", inst_msg.lower())

        inst_doc = ContextManager.get_context_prompt_instruction(ContextCategory.DOCUMENT)
        self.assertIn("documentos", inst_doc.lower())

        inst_gen = ContextManager.get_context_prompt_instruction(ContextCategory.GENERAL)
        self.assertEqual(inst_gen, "")

    def test_get_git_context_handles_non_git_cleanly(self):
        # AUD-027: Quando o título da janela não contém caminho de diretório, não deve fazer
        # fallback para os.getcwd() (que vazava o próprio repositório do Willy).
        with patch("subprocess.run") as mock_run:
            ctx = ContextManager.get_git_context("Bloco de Notas", "notepad.exe")
            self.assertEqual(ctx, "")
            mock_run.assert_not_called()

    def test_get_git_context_with_mocked_git(self):
        chamadas_kwargs = []

        def mock_subprocess(cmd, **kwargs):
            chamadas_kwargs.append(kwargs)
            mock = MagicMock()
            mock.returncode = 0
            if "rev-parse" in cmd and "--is-inside-work-tree" in cmd:
                mock.stdout = "true\n"
            elif "branch" in cmd:
                mock.stdout = "feature/agent-prompt\n"
            elif "status" in cmd:
                mock.stdout = " M willy.py\n"
            elif "log" in cmd:
                mock.stdout = "abc1234 feat: improve agent prompts\n"
            else:
                mock.stdout = "my-repo\n"
            return mock

        with patch("subprocess.run", side_effect=mock_subprocess):
            titulo = f"willy.py - {os.getcwd()} - Visual Studio Code"
            ctx = ContextManager.get_git_context(titulo, "code.exe")
            self.assertIsInstance(ctx, str)
            self.assertIn("CONTEXTO GIT", ctx)
            self.assertIn("feature/agent-prompt", ctx)
            self.assertIn("willy.py", ctx)
            if sys.platform == "win32":
                for kw in chamadas_kwargs:
                    self.assertEqual(
                        kw.get("creationflags"),
                        subprocess.CREATE_NO_WINDOW,
                        "AUD-027: subprocess.run do git deve usar CREATE_NO_WINDOW no Windows",
                    )


if __name__ == "__main__":
    unittest.main()
