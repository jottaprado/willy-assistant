"""
Testes unitários para o módulo core.autostart.AutoStartManager.
"""

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

from core.autostart import APP_NAME, AutoStartManager


class TestAutoStartManager(unittest.TestCase):

    def test_get_app_path_returns_string(self):
        path = AutoStartManager.get_app_path()
        self.assertIsInstance(path, str)
        self.assertTrue(len(path) > 0)

    def test_is_enabled_returns_true_when_registry_value_non_empty(self):
        """AUD-097: Verifica deterministicamente os três ramos de AutoStartManager.is_enabled()."""
        cm_key = MagicMock()
        cm_key.__enter__.return_value = "HKEY_MOCK"
        cm_key.__exit__.return_value = False

        with patch("winreg.OpenKey", return_value=cm_key) as mock_open, \
             patch("winreg.QueryValueEx", return_value=('"C:\\Willy\\Willy.exe"', 1)) as mock_query:
            self.assertTrue(AutoStartManager.is_enabled())
            mock_open.assert_called_once()
            mock_query.assert_called_once_with("HKEY_MOCK", APP_NAME)

        with patch("winreg.OpenKey", return_value=cm_key), \
             patch("winreg.QueryValueEx", return_value=("", 1)):
            self.assertFalse(AutoStartManager.is_enabled())

        with patch("winreg.OpenKey", side_effect=FileNotFoundError):
            self.assertFalse(AutoStartManager.is_enabled())

    def test_set_enabled_with_mock(self):
        with patch("winreg.OpenKey", MagicMock()), patch("winreg.SetValueEx", MagicMock()) as mock_set:
            ok = AutoStartManager.set_enabled(True)
            self.assertTrue(ok)
            mock_set.assert_called_once()

    def test_set_disabled_with_mock(self):
        with patch("winreg.OpenKey", MagicMock()), patch("winreg.DeleteValue", MagicMock()) as mock_del:
            ok = AutoStartManager.set_enabled(False)
            self.assertTrue(ok)
            mock_del.assert_called_once()

    def test_get_app_path_prefere_pythonw_quando_disponivel(self):
        """AUD-023: Em execução não-empacotada, get_app_path deve usar pythonw.exe quando existir."""
        with patch("core.autostart.sys.executable", r"C:\Python311\python.exe"), \
             patch("core.autostart.os.path.exists", side_effect=lambda p: p.endswith("pythonw.exe")):
            cmd = AutoStartManager.get_app_path()
        self.assertIn(r'"C:\Python311\pythonw.exe"', cmd)

    def test_is_enabled_e_set_enabled_logam_erros_inesperados_no_stderr(self):
        """AUD-199 e AUD-200: Erros de permissão/sistema no Registro devem ser logados em sys.stderr."""
        buf_read = io.StringIO()
        with patch("winreg.OpenKey", side_effect=PermissionError("Acesso negado leitura")), \
             redirect_stderr(buf_read):
            self.assertFalse(AutoStartManager.is_enabled())
        self.assertIn("[AutoStartManager]", buf_read.getvalue())
        self.assertIn("Acesso negado leitura", buf_read.getvalue())

        buf_write = io.StringIO()
        with patch("winreg.OpenKey", side_effect=PermissionError("Acesso negado escrita")), \
             redirect_stderr(buf_write):
            self.assertFalse(AutoStartManager.set_enabled(True))
        self.assertIn("[AutoStartManager]", buf_write.getvalue())
        self.assertIn("Acesso negado escrita", buf_write.getvalue())


if __name__ == "__main__":
    unittest.main()
