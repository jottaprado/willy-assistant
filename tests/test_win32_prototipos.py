"""
context.py, single_instance.py, pill.py, spotlight.py e dwm.py chamam o Win32 por WinDLL próprios,
carregados uma vez, com protótipos de 64 bits.

- Pelo ctypes.windll global, sem argtypes, um HWND, HMONITOR ou HANDLE acima de 32 bits nem
  chegava à API (ArgumentError), o HWND_TOPMOST = -1 ia truncado em 32 bits (0x00000000FFFFFFFF,
  erro 1400 em SetWindowPos), e o restype padrão devolvia o handle num int de 32 bits.
- eh_janela_do_shell, eh_janela_do_willy e _monitor_ativo carregavam um WinDLL novo a cada chamada.
- A segunda instância não fechava o handle do mutex da primeira. No app ela sai logo depois,
  e o handle fecha junto; mas no mesmo processo o mutex seguia vivo depois do release() da
  primeira, e uma terceira se recusava.

Toca objetos reais do Windows (um mutex com nome de teste e uma janela Tk escondida), mas não
o clipboard nem o Cofre de Credenciais.
"""

import ctypes
import os
import sys
import tkinter as tk
import unittest
from ctypes import wintypes
from unittest.mock import patch

from core import context, single_instance
from core.context import ContextManager
from core.single_instance import SingleInstanceManager
from ui.navigation import dwm
from ui.overlays import pill, spotlight

HANDLE_DE_64_BITS = 0x1_0000_0000  # inválido, mas grande demais para um int de 32 bits


@unittest.skipUnless(sys.platform == "win32", "Win32")
class TestPrototipos(unittest.TestCase):
    def test_nao_usam_o_windll_global(self):
        self.assertIsNot(context.user32, ctypes.windll.user32)
        self.assertIsNot(context.kernel32, ctypes.windll.kernel32)
        self.assertIsNot(single_instance._k32, ctypes.windll.kernel32)
        self.assertIsNot(single_instance._u32, ctypes.windll.user32)
        self.assertIsNot(pill._user32, ctypes.windll.user32)
        self.assertIsNot(spotlight._user32, ctypes.windll.user32)
        self.assertIsNot(dwm._user32, ctypes.windll.user32)
        self.assertIsNot(dwm._dwmapi, ctypes.windll.dwmapi)

    def test_handles_de_64_bits_chegam_a_api(self):
        pid, nome = wintypes.DWORD(), ctypes.create_unicode_buffer(8)
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        info_pill = pill._MONITORINFO()
        info_pill.cbSize = ctypes.sizeof(pill._MONITORINFO)
        from core import actions
        info_spot = spotlight._MONITORINFO()
        info_spot.cbSize = ctypes.sizeof(spotlight._MONITORINFO)
        info_gui = context.GUITHREADINFO()
        info_gui.cbSize = ctypes.sizeof(context.GUITHREADINFO)
        chamadas = {
            "GetGUIThreadInfo": lambda: context.user32.GetGUIThreadInfo(0, ctypes.byref(info_gui)),
            "actions.SetClipboardData": lambda: actions._u32.SetClipboardData(13, HANDLE_DE_64_BITS),
            "GetWindowTextLengthW": lambda: context.user32.GetWindowTextLengthW(HANDLE_DE_64_BITS),
            "GetWindowTextW": lambda: context.user32.GetWindowTextW(HANDLE_DE_64_BITS, nome, 8),
            "GetWindowThreadProcessId": lambda: context.user32.GetWindowThreadProcessId(HANDLE_DE_64_BITS, ctypes.byref(pid)),
            "IsIconic": lambda: context.user32.IsIconic(HANDLE_DE_64_BITS),
            "IsWindow": lambda: context.user32.IsWindow(HANDLE_DE_64_BITS),
            "ShowWindow": lambda: context.user32.ShowWindow(HANDLE_DE_64_BITS, 0),
            "SetForegroundWindow": lambda: context.user32.SetForegroundWindow(HANDLE_DE_64_BITS),
            "GetClassNameW": lambda: context.user32.GetClassNameW(HANDLE_DE_64_BITS, nome, 8),
            "IsWindowVisible": lambda: context.user32.IsWindowVisible(HANDLE_DE_64_BITS),
            "GetWindowLongW": lambda: context.user32.GetWindowLongW(HANDLE_DE_64_BITS, -20),
            "QueryFullProcessImageNameW": lambda: context.kernel32.QueryFullProcessImageNameW(
                HANDLE_DE_64_BITS, 0, nome, ctypes.byref(pid)),
            "CloseHandle": lambda: context.kernel32.CloseHandle(HANDLE_DE_64_BITS),
            "DwmGetWindowAttribute": lambda: context.dwmapi.DwmGetWindowAttribute(
                HANDLE_DE_64_BITS, 14, ctypes.byref(pid), ctypes.sizeof(pid)),
            "single_instance.CloseHandle": lambda: single_instance._k32.CloseHandle(HANDLE_DE_64_BITS),
            "single_instance.ShowWindow": lambda: single_instance._u32.ShowWindow(HANDLE_DE_64_BITS, 0),
            "single_instance.SetForegroundWindow": lambda: single_instance._u32.SetForegroundWindow(HANDLE_DE_64_BITS),
            "pill.GetParent": lambda: pill._user32.GetParent(HANDLE_DE_64_BITS),
            "pill.SetForegroundWindow": lambda: pill._user32.SetForegroundWindow(HANDLE_DE_64_BITS),
            "pill.GetWindowLongW": lambda: pill._user32.GetWindowLongW(HANDLE_DE_64_BITS, -20),
            "pill.SetWindowLongW": lambda: pill._user32.SetWindowLongW(HANDLE_DE_64_BITS, -20, 0),
            "pill.ShowWindow": lambda: pill._user32.ShowWindow(HANDLE_DE_64_BITS, 4),
            "pill.SetWindowPos": lambda: pill._user32.SetWindowPos(HANDLE_DE_64_BITS, -1, 0, 0, 0, 0, 0x0013),
            "pill.MonitorFromWindow": lambda: pill._user32.MonitorFromWindow(HANDLE_DE_64_BITS, 2),
            "pill.GetMonitorInfoW": lambda: pill._user32.GetMonitorInfoW(HANDLE_DE_64_BITS, ctypes.byref(info_pill)),
            "spotlight.MonitorFromWindow": lambda: spotlight._user32.MonitorFromWindow(HANDLE_DE_64_BITS, 2),
            "spotlight.GetMonitorInfoW": lambda: spotlight._user32.GetMonitorInfoW(HANDLE_DE_64_BITS, ctypes.byref(info_spot)),
            "spotlight.GetDpiForMonitor": lambda: spotlight._shcore.GetDpiForMonitor(
                HANDLE_DE_64_BITS, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)),
            "dwm.GetAncestor": lambda: dwm._user32.GetAncestor(HANDLE_DE_64_BITS, 2),
            "dwm.GetParent": lambda: dwm._user32.GetParent(HANDLE_DE_64_BITS),
            "dwm.DwmSetWindowAttribute": lambda: dwm._dwmapi.DwmSetWindowAttribute(
                HANDLE_DE_64_BITS, 20, ctypes.byref(pid), ctypes.sizeof(pid)),
        }
        for nome_da_funcao, chamar in chamadas.items():
            with self.subTest(nome_da_funcao):
                chamar()  # sem argtypes: ctypes.ArgumentError, "int too long to convert"

    def test_handles_devolvidos_nao_sao_cortados(self):
        from core import actions
        self.assertEqual(
            [wintypes.DWORD, ctypes.POINTER(context.GUITHREADINFO)],
            list(context.user32.GetGUIThreadInfo.argtypes),
        )
        self.assertEqual(
            [wintypes.UINT, wintypes.HANDLE],
            list(actions._u32.SetClipboardData.argtypes),
        )
        self.assertEqual(
            [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT],
            list(pill._user32.SetWindowPos.argtypes),
        )
        for funcao in (
            context.user32.GetForegroundWindow,
            actions._u32.SetClipboardData,
            context.kernel32.OpenProcess,
            single_instance._k32.CreateMutexW,
            single_instance._u32.FindWindowW,
            pill._user32.GetForegroundWindow,
            pill._user32.GetParent,
            pill._user32.MonitorFromWindow,
            pill._user32.MonitorFromPoint,
            spotlight._user32.MonitorFromWindow,
            spotlight._user32.MonitorFromPoint,
            dwm._user32.GetAncestor,
            dwm._user32.FindWindowW,
            dwm._user32.GetParent,
        ):
            with self.subTest(funcao.__name__):
                self.assertIn(funcao.restype, (wintypes.HWND, wintypes.HANDLE, wintypes.HMONITOR))


@unittest.skipUnless(sys.platform == "win32", "Win32")
class TestJanelaSemWinDLLPorChamada(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.update()
        self.addCleanup(self.root.destroy)

    def test_classificam_a_janela_e_monitor_sem_carregar_dll(self):
        hwnd = self.root.winfo_id()
        with patch("ctypes.WinDLL", side_effect=AssertionError("WinDLL carregado por chamada")):
            self.assertTrue(ContextManager.eh_janela_do_willy(hwnd))
            self.assertTrue(ContextManager.eh_janela_do_shell(hwnd))  # escondida não é app
            self.assertIsNotNone(spotlight._monitor_ativo(hwnd, (0, 0)))
            dwm.aplicar_dwm_caption_color(self.root)


@unittest.skipUnless(sys.platform == "win32", "Win32")
class TestMutexDaSegundaInstancia(unittest.TestCase):
    def test_segunda_instancia_fecha_o_handle_e_o_mutex_some_com_a_primeira(self):
        nome = rf"Local\Willy_Teste_Prototipos_{os.getpid()}"
        primeira, segunda = SingleInstanceManager(nome), SingleInstanceManager(nome)
        self.assertTrue(primeira.acquire())
        self.assertFalse(segunda.acquire())
        self.assertIsNone(segunda.mutex_handle)
        primeira.release()
        # Com o handle da segunda aberto, o mutex seguia existindo e esta se recusava.
        terceira = SingleInstanceManager(nome)
        self.assertTrue(terceira.acquire())
        terceira.release()


if __name__ == "__main__":
    unittest.main()
