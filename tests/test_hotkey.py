"""
Testes unitários para o módulo core.hotkey.Win32HotKeyManager.
"""

import threading
import time
import unittest
from unittest.mock import patch

from core.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    VK_MAP,
    WM_HOTKEY,
    Win32HotKeyManager,
    user32,
)


def _atalho_livre_no_windows(combo: str) -> bool:
    mods, vk = Win32HotKeyManager.parse_hotkey(combo)
    resultado = {"livre": False}

    def _provar():
        livre = bool(user32.RegisterHotKey(None, 0x7E57, mods, vk))
        if livre:
            user32.UnregisterHotKey(None, 0x7E57)
        resultado["livre"] = livre

    t = threading.Thread(target=_provar, daemon=True)
    t.start()
    t.join(timeout=1.0)
    return resultado["livre"]


def _escolher_atalhos_livres(qtd: int) -> list[str]:
    candidatos = [
        f"ctrl+alt+shift+f{n}" for n in range(12, 0, -1)
    ] + [
        f"ctrl+alt+shift+{c}" for c in ("9", "8", "7", "6", "5", "4")
    ]
    livres: list[str] = []
    for combo in candidatos:
        if _atalho_livre_no_windows(combo):
            livres.append(combo)
            if len(livres) == qtd:
                break
    return livres


class TestWin32HotKeyManager(unittest.TestCase):

    def test_parse_hotkey_valid(self):
        self.assertEqual(0x0312, WM_HOTKEY)
        self.assertEqual(0x4000, MOD_NOREPEAT)
        # 1. Ctrl + Space
        m, v = Win32HotKeyManager.parse_hotkey("ctrl+space")
        self.assertEqual(m, MOD_CONTROL | MOD_NOREPEAT)
        self.assertEqual(v, VK_MAP["space"])

        # 2. Ctrl + Shift + Space
        m, v = Win32HotKeyManager.parse_hotkey("ctrl+shift+space")
        self.assertEqual(m, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT)
        self.assertEqual(v, VK_MAP["space"])

        # 3. Ctrl + Alt + Space
        m, v = Win32HotKeyManager.parse_hotkey("ctrl+alt+space")
        self.assertEqual(m, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT)
        self.assertEqual(v, VK_MAP["space"])

        # 4. F8
        m, v = Win32HotKeyManager.parse_hotkey("f8")
        self.assertEqual(m, MOD_NOREPEAT)
        self.assertEqual(v, VK_MAP["f8"])

        # 5. Letra A
        m, v = Win32HotKeyManager.parse_hotkey("ctrl+a")
        self.assertEqual(m, MOD_CONTROL | MOD_NOREPEAT)
        self.assertEqual(v, ord("A"))

    def test_parse_hotkey_invalid(self):
        with self.assertRaises(ValueError):
            Win32HotKeyManager.parse_hotkey("")

        with self.assertRaises(ValueError):
            Win32HotKeyManager.parse_hotkey("ctrl+shift")

    def test_manager_lifecycle(self):
        # AUD-117: Não sequestra ctrl+space globalmente no desktop hospedeiro durante o teste de ciclo de vida.
        mgr = Win32HotKeyManager()
        id1 = mgr.register("ctrl+space", lambda: None)
        id2 = mgr.register("ctrl+shift+space", lambda: None)
        self.assertEqual(id1, 1)
        self.assertEqual(id2, 2)

        with patch.object(user32, "RegisterHotKey", return_value=1), \
             patch.object(user32, "UnregisterHotKey", return_value=1):
            mgr.start()
            self.assertTrue(mgr.running)
            mgr.stop()
            self.assertFalse(mgr.running)

    def test_manager_clear_resets_hotkeys(self):
        mgr = Win32HotKeyManager()
        mgr.register("ctrl+space", lambda: None)
        mgr.register("ctrl+shift+space", lambda: None)
        self.assertEqual(len(mgr.hotkeys), 2)
        self.assertEqual(mgr.next_id, 3)

        mgr.clear()
        self.assertEqual(len(mgr.hotkeys), 0)
        self.assertEqual(len(mgr.last_trigger_time), 0)
        self.assertEqual(mgr.next_id, 1)
        self.assertFalse(mgr.running)

    def test_manager_clear_and_reregister_cycle(self):
        mgr = Win32HotKeyManager()
        # Primeiro ciclo
        id1 = mgr.register("ctrl+space", lambda: None)
        id2 = mgr.register("ctrl+alt+space", lambda: None)
        self.assertEqual(id1, 1)
        self.assertEqual(id2, 2)
        self.assertEqual(len(mgr.hotkeys), 2)

        # Limpeza e re-registro (como no dashboard save / profile reload)
        mgr.clear()
        self.assertEqual(len(mgr.hotkeys), 0)

        # Segundo ciclo deve reiniciar os IDs do 1 sem vazamento de atalhos antigos
        id_novo1 = mgr.register("ctrl+space", lambda: None)
        id_novo2 = mgr.register("ctrl+shift+a", lambda: None)
        self.assertEqual(id_novo1, 1)
        self.assertEqual(id_novo2, 2)
        self.assertEqual(len(mgr.hotkeys), 2)

    def test_disparo_wm_hotkey_na_thread_real_chama_callback_e_respeita_debounce(self):
        livres = _escolher_atalhos_livres(2)
        if len(livres) < 2:
            self.skipTest("Sem duas combinações de tecla livres nesta sessão do Windows")

        self.assertEqual(0x0312, WM_HOTKEY)
        disparos = []
        evento = threading.Event()
        barreira = threading.Event()
        mgr = Win32HotKeyManager()
        self.addCleanup(mgr.stop)
        hk_id = mgr.register(livres[0], lambda: (disparos.append(1), evento.set()))
        hk_barreira = mgr.register(livres[1], barreira.set)
        mgr.start()
        self.assertIsNotNone(mgr.thread_id)

        # Envia dois WM_HOTKEY (0x0312) seguidos para hk_id e um terceiro para hk_barreira:
        # a fila Win32 é FIFO, então quando hk_barreira disparar, as duas mensagens de hk_id
        # já foram processadas pelo loop (a 1ª dispara; a 2ª cai no debounce de 0.35s).
        self.assertTrue(user32.PostThreadMessageW(mgr.thread_id, 0x0312, hk_id, 0))
        self.assertTrue(user32.PostThreadMessageW(mgr.thread_id, 0x0312, hk_id, 0))
        self.assertTrue(user32.PostThreadMessageW(mgr.thread_id, 0x0312, hk_barreira, 0))
        self.assertTrue(barreira.wait(timeout=1.5), "A barreira FIFO do WM_HOTKEY não disparou")
        self.assertTrue(evento.wait(timeout=1.5), "O callback do WM_HOTKEY não disparou na thread real")
        time.sleep(0.05)
        self.assertEqual([1], disparos)

    def test_atalho_temporario_registra_dispara_e_solta_na_thread_real(self):
        livres = _escolher_atalhos_livres(1)
        if not livres:
            self.skipTest("Sem combinação de tecla livre nesta sessão do Windows")

        disparou = threading.Event()
        mgr = Win32HotKeyManager()
        self.addCleanup(mgr.stop)
        mgr.start()

        self.assertTrue(mgr.registrar_temporario("esc_teste", livres[0], disparou.set))
        hk_id_temp = mgr.temporarios["esc_teste"][0]
        self.assertTrue(user32.PostThreadMessageW(mgr.thread_id, WM_HOTKEY, hk_id_temp, 0))
        self.assertTrue(disparou.wait(timeout=1.5), "O atalho temporário não disparou na thread real")

        mgr.soltar_temporario("esc_teste")
        self.assertNotIn("esc_teste", mgr.temporarios)


if __name__ == "__main__":
    unittest.main()
