"""
Testes unitários para o módulo core.system.injector.TextInjector.

A escrita no clipboard é mockada em `ActionManager.secure_copy`: é a única escrita dos
caminhos de injeção (a invariante que exigia `pyperclip.copy` foi revogada, porque era
justamente essa chamada que publicava o ditado no histórico Win+V).

Nada lê o clipboard de verdade: o _clipboard_has_text é falso em todos, e a volta do clipboard
só dispara nos testes que esperam por ela, ainda dentro dos patches. Antes, um timer de 10 ms
podia disparar depois deles e ler o pyperclip real.
"""

import unittest
from unittest.mock import patch

from core.system.injector import TextInjector


@patch("core.system.injector.time.sleep")
@patch("core.system.injector.keyboard")
@patch("core.system.injector.pyperclip")
@patch("core.actions.ActionManager.secure_copy", return_value=True)
class TestTextInjector(unittest.TestCase):
    def setUp(self):
        self.injector = TextInjector(restore_delay=60)
        tem_texto = patch.object(TextInjector, "_clipboard_has_text", return_value=True)
        tem_texto.start()
        self.addCleanup(tem_texto.stop)
        self.addCleanup(self._cancelar_restauracao)

    def _cancelar_restauracao(self):
        restauracao = self.injector._restauracao
        if restauracao:
            restauracao.timer.cancel()

    def _esperar_restauracao(self):
        # Lido uma vez: a volta de 10 ms pode zerar o _restauracao entre a checagem e o .timer.
        restauracao = self.injector._restauracao
        if restauracao:
            restauracao.timer.join(timeout=1.0)

    def test_paste_text_success(self, mock_secure, mock_pyperclip, mock_keyboard, _sleep):
        mock_pyperclip.paste.return_value = "conteudo_anterior"

        success = self.injector.paste_text("novo_texto", auto_send=False)

        self.assertTrue(success)
        mock_secure.assert_any_call("novo_texto")
        mock_keyboard.send.assert_called_with("ctrl+v")

    def test_paste_text_with_auto_send(self, mock_secure, mock_pyperclip, mock_keyboard, _sleep):
        mock_pyperclip.paste.return_value = "antigo"

        success = self.injector.paste_text("texto_com_enter", auto_send=True)

        self.assertTrue(success)
        mock_keyboard.send.assert_any_call("ctrl+v")
        mock_keyboard.send.assert_any_call("enter")

    def test_paste_empty_text(self, mock_secure, mock_pyperclip, mock_keyboard, _sleep):
        success = self.injector.paste_text("", auto_send=False)
        self.assertFalse(success)
        mock_secure.assert_not_called()

    def test_clipboard_restoration(self, mock_secure, mock_pyperclip, mock_keyboard, _sleep):
        self.injector.restore_delay = 0.01
        with patch.object(self.injector, "_clipboard_has_text", return_value=True):
            mock_pyperclip.paste.side_effect = ["clipboard_original", "texto_injetado", "texto_injetado"]

            self.injector.paste_text("texto_injetado", auto_send=False)
            self._esperar_restauracao()

            mock_secure.assert_any_call("clipboard_original")

    def test_nenhuma_escrita_fora_do_escritor_seguro(self, mock_secure, mock_pyperclip, mock_keyboard, _sleep):
        """Um único pyperclip.copy publica o ditado no Win+V, antes da marca de exclusão."""
        self.injector.restore_delay = 0.01
        with patch.object(self.injector, "_clipboard_has_text", return_value=True):
            mock_pyperclip.paste.side_effect = ["senha_copiada", "ditado", "ditado"]

            self.injector.paste_text("ditado", auto_send=True)
            self._esperar_restauracao()

        mock_pyperclip.copy.assert_not_called()
        self.assertEqual(["ditado", "senha_copiada"], [c.args[0] for c in mock_secure.call_args_list])

    def test_escrita_falha_nao_cola_o_conteudo_antigo(self, mock_secure, mock_pyperclip, mock_keyboard, _sleep):
        """Sem o texto novo no clipboard, o Ctrl+V colaria o que estava lá (talvez uma senha)."""
        mock_secure.return_value = False
        mock_pyperclip.paste.return_value = "senha_copiada"

        with patch.object(self.injector, "_clipboard_has_text", return_value=True):
            success = self.injector.paste_text("ditado", auto_send=True)

        self.assertFalse(success)
        mock_keyboard.send.assert_not_called()
        # O clipboard não foi sobrescrito: não há o que restaurar.
        self.assertIsNone(self.injector._restauracao)



if __name__ == "__main__":
    unittest.main()
