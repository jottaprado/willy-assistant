"""
Integração com Desktop Window Manager (DWM) da Win32 API.
Configura cores de caption (DWMWA_CAPTION_COLOR = 35) e modo escuro nativo no Windows 11.
"""

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes

import customtkinter as ctk

from ui.theme import APPLE_BG_SIDEBAR


def _carregar_win32():
    """WinDLL próprios de user32 e dwmapi com protótipos de 64 bits."""
    if sys.platform != "win32":
        return None, None
    u = ctypes.WinDLL("user32")
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.GetParent.argtypes = [wintypes.HWND]
    u.GetParent.restype = wintypes.HWND

    d = ctypes.WinDLL("dwmapi")
    d.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    d.DwmSetWindowAttribute.restype = ctypes.c_long
    return u, d


_user32, _dwmapi = _carregar_win32()


def aplicar_dwm_caption_color(window) -> None:
    """Aplica a cor da barra de título via DWM (DWMWA_CAPTION_COLOR = 35) no Windows 11."""
    if sys.platform != "win32" or _user32 is None or _dwmapi is None:
        return
    try:
        window.update_idletasks()
        wid = window.winfo_id()
        hwnd = _user32.GetAncestor(wid, 2)  # GA_ROOT
        if not hwnd or hwnd == 0:
            hwnd = _user32.GetParent(wid)
        if not hwnd or hwnd == 0:
            try:
                hwnd = int(window.wm_frame(), 16)
            except (ValueError, TypeError, tk.TclError):
                hwnd = 0
        if not hwnd or hwnd == 0:
            return

        mode = ctk.get_appearance_mode().lower()
        is_dark = (mode == "dark")
        cor_hex = APPLE_BG_SIDEBAR[1] if is_dark else APPLE_BG_SIDEBAR[0]
        h = cor_hex.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        bgr = (b << 16) | (g << 8) | r

        dark_flag = wintypes.BOOL(1 if is_dark else 0)
        _dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag))

        caption_color = wintypes.DWORD(bgr)
        _dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
    except tk.TclError:
        # Janela pode ter sido destruída antes do after(50) disparar.
        pass
    except Exception as e:  # noqa: BLE001 — fronteira defensiva: DwmSetWindowAttribute Win32/ctypes
        print(f"[DWM] Erro ao aplicar cor da barra de título: {e}", file=sys.stderr)
