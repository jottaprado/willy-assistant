"""
parse_hotkey recusa duas teclas principais e pontuação sem código próprio no Windows.

- "ctrl+a+b" registrava só o B: o atalho mostrado não era o que valia.
- O ord() de um caractere só é o código (VK) das letras e dos dígitos. "ctrl+alt+," registrava
  o PrintScreen (0x2C), "." o Delete, "[" a tecla do Windows, "'" a seta para a direita.
"""

import unittest

from core.hotkey import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, Win32HotKeyManager

CTRL_ALT = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT


class TestTeclaPrincipal(unittest.TestCase):
    def test_duas_teclas_principais_e_recusado(self):
        for combo in ("ctrl+a+b", "ctrl+alt+space+enter", "ctrl+f1+1", "ctrl+a+a"):
            with self.subTest(combo=combo), self.assertRaisesRegex(ValueError, "mais de uma tecla principal"):
                Win32HotKeyManager.parse_hotkey(combo)

    def test_modificador_depois_da_tecla_continua_valendo(self):
        self.assertEqual((CTRL_ALT, ord("D")), Win32HotKeyManager.parse_hotkey("d+ctrl+alt"))

    def test_letras_e_digitos_seguem_o_ord(self):
        for tecla in ("a", "z", "0", "9"):
            with self.subTest(tecla=tecla):
                self.assertEqual((CTRL_ALT, ord(tecla.upper())), Win32HotKeyManager.parse_hotkey(f"ctrl+alt+{tecla}"))

    def test_virgula_hifen_e_ponto_tem_o_codigo_deles(self):
        for tecla, vk in ((",", 0xBC), ("-", 0xBD), (".", 0xBE)):
            with self.subTest(tecla=tecla):
                self.assertEqual((CTRL_ALT, vk), Win32HotKeyManager.parse_hotkey(f"ctrl+alt+{tecla}"))

    def test_pontuacao_sem_codigo_proprio_e_recusada(self):
        # Os códigos destas mudam com o layout (no ABNT2, o ";" e o "/" ficam em outras teclas).
        for tecla in ("[", "]", "'", ";", "/", "\\", "`", "=", "ç", "é", "*"):
            with self.subTest(tecla=tecla), self.assertRaisesRegex(ValueError, "não reconhecida"):
                Win32HotKeyManager.parse_hotkey(f"ctrl+alt+{tecla}")


if __name__ == "__main__":
    unittest.main()
