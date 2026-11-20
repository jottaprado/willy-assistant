"""
Módulo de Inicialização com o Windows do Willy.
Gerencia a chave de registro HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
para inicialização automática silenciosa ao ligar o computador.
"""

import os
import sys

REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Willy"


class AutoStartManager:
    """Gerencia a inicialização automática do Willy com o Windows."""

    @staticmethod
    def get_app_path() -> str:
        """Retorna o comando de execução adequado para o executável ou script."""
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        else:
            main_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "willy.py"))
            exe = sys.executable
            if exe.lower().endswith("python.exe"):
                pythonw = exe[:-10] + "pythonw.exe"
                if os.path.exists(pythonw):
                    exe = pythonw
            return f'"{exe}" "{main_script}"'

    @classmethod
    def is_enabled(cls) -> bool:
        """Verifica se o Willy está configurado para iniciar com o Windows."""
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, APP_NAME)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception as e:  # noqa: BLE001 — fronteira Win32 Registry (winreg)
            print(
                f"[AutoStartManager] Erro ao consultar chave de inicialização no Registro: {e!r}",
                file=sys.stderr,
            )
            return False

    @classmethod
    def set_enabled(cls, enable: bool) -> bool:
        """Habilita ou desabilita a inicialização com o Windows."""
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    cmd = cls.get_app_path()
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except Exception as e:  # noqa: BLE001 — fronteira Win32 Registry (winreg)
            print(
                f"[AutoStartManager] Erro ao atualizar chave de inicialização no Registro (enable={enable}): {e!r}",
                file=sys.stderr,
            )
            return False
