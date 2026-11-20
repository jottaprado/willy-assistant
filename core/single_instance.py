"""
Módulo de Instância Única (Single Instance) via Windows Named Mutex.
Garante que apenas um processo do Willy esteja ativo simultaneamente e restaura a janela ao abrir novamente.
"""

import ctypes
import os
import sys
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183

# WinDLL próprios, com os protótipos de 64 bits: pelo ctypes.windll global, sem restype, o HANDLE
# do mutex voltava num int de 32 bits. E use_last_error: o GetLastError chamado à parte, depois,
# podia ler o erro de outra chamada que o próprio Python fez no meio, e não o do CreateMutexW.
if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    for _funcao, _argtypes, _restype in (
        (_k32.CreateMutexW, [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        (_k32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
        (_u32.FindWindowW, [wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND),
        (_u32.IsIconic, [wintypes.HWND], wintypes.BOOL),
        (_u32.ShowWindow, [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        (_u32.SetForegroundWindow, [wintypes.HWND], wintypes.BOOL),
    ):
        _funcao.argtypes, _funcao.restype = _argtypes, _restype
else:
    _k32 = _u32 = None


class SingleInstanceManager:
    """Gerenciador de instância única usando Named Mutex da Win32 API."""

    def __init__(self, mutex_name: str = "Local\\WillyApp_SingleInstance_Mutex_98a7"):
        self.mutex_name = mutex_name
        self.mutex_handle = None

    def acquire(self) -> bool:
        """
        Tenta adquirir o Named Mutex exclusivo.
        Retorna True se for a única instância ativa, ou False se já houver outra rodando.
        """
        if sys.platform != "win32":
            return True

        try:
            handle = _k32.CreateMutexW(None, False, self.mutex_name)
            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                # O handle aberto é o do mutex da outra instância: sem fechar, ele vazava até
                # o processo sair, e o mutex não sumia com o release() de quem o criou.
                if handle:
                    _k32.CloseHandle(handle)
                return False
            self.mutex_handle = handle
            return True
        except Exception:  # noqa: BLE001 — fallback fail-open na criação de mutex Win32
            return True

    def signal_and_restore(self, user_data_dir: str | None = None, window_title: str = "Willy") -> None:
        """Sinaliza a instância existente para restaurar o dashboard e focar a janela."""
        from core.config import FLAG_SHOW_DASHBOARD

        flag_file = (
            os.path.join(user_data_dir, os.path.basename(FLAG_SHOW_DASHBOARD))
            if user_data_dir
            else FLAG_SHOW_DASHBOARD
        )
        try:
            pasta = os.path.dirname(os.path.abspath(flag_file))
            if pasta:
                os.makedirs(pasta, exist_ok=True)
            with open(flag_file, "w", encoding="utf-8") as f:
                f.write("show")
        except OSError as e:
            print(f"[SingleInstance] Falha ao gravar {flag_file}: {e!r}", file=sys.stderr)

        if sys.platform == "win32":
            try:
                classe_janela = "TkTopLevel" if window_title == "Willy" else None
                hwnd = _u32.FindWindowW(classe_janela, window_title)
                if hwnd:
                    if _u32.IsIconic(hwnd):
                        _u32.ShowWindow(hwnd, 9)  # SW_RESTORE apenas se minimizada
                    _u32.SetForegroundWindow(hwnd)
            except Exception as e:  # noqa: BLE001 — fronteira Win32 FindWindowW/SetForegroundWindow
                print(f"[SingleInstance] Falha ao focar janela existente: {e!r}", file=sys.stderr)

    def release(self) -> None:
        """Libera o handle do Mutex ao fechar o aplicativo."""
        if self.mutex_handle and sys.platform == "win32":
            try:
                _k32.CloseHandle(self.mutex_handle)
            except Exception:  # noqa: BLE001, S110 — liberação best-effort de handle Win32 no encerramento
                pass
            self.mutex_handle = None

