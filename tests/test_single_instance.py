"""
Testes unitários para o módulo core.single_instance.SingleInstanceManager.
"""

import os
import shutil
import tempfile
import unittest

from core.single_instance import SingleInstanceManager


class TestSingleInstance(unittest.TestCase):

    def test_mutex_acquire_and_contention(self):
        test_mutex_name = f"Local\\Willy_Test_Mutex_{os.getpid()}"
        inst1 = SingleInstanceManager(mutex_name=test_mutex_name)
        inst2 = SingleInstanceManager(mutex_name=test_mutex_name)

        # Primeira instância adquire
        ok1 = inst1.acquire()
        self.assertTrue(ok1)

        # Segunda instância tenta adquirir o mesmo mutex -> deve falhar
        ok2 = inst2.acquire()
        self.assertFalse(ok2)

        # Libera o mutex
        inst1.release()

    def test_signal_file_creation(self):
        tmp = tempfile.mkdtemp()
        try:
            mgr = SingleInstanceManager()
            mgr.signal_and_restore(tmp, window_title="NonExistentWindow12345")
            flag = os.path.join(tmp, ".show_dashboard")
            self.assertTrue(os.path.exists(flag))
            with open(flag, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, "show")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_signal_and_restore_usa_flag_show_dashboard_loga_erro_e_verifica_is_iconic(self):
        """AUD-035 e AUD-204: signal_and_restore loga falha de arquivo, filtra classe TkTopLevel e checa IsIconic."""
        import contextlib
        import io
        from unittest.mock import patch

        from core import single_instance

        mgr = SingleInstanceManager()
        stderr_buf = io.StringIO()
        with (
            patch("builtins.open", side_effect=PermissionError("sem permissao")),
            contextlib.redirect_stderr(stderr_buf),
        ):
            mgr.signal_and_restore("C:/caminho_bloqueado", window_title="NonExistentWindow12345")
        self.assertIn("[SingleInstance]", stderr_buf.getvalue())
        self.assertIn("sem permissao", stderr_buf.getvalue())

        tmp = tempfile.mkdtemp()
        try:
            with (
                patch.object(single_instance._u32, "FindWindowW", return_value=0xABCD) as mock_find,
                patch.object(single_instance._u32, "IsIconic", return_value=0) as mock_iconic,
                patch.object(single_instance._u32, "ShowWindow") as mock_show,
                patch.object(single_instance._u32, "SetForegroundWindow") as mock_fg,
            ):
                mgr.signal_and_restore(tmp, window_title="Willy")
                mock_find.assert_called_once_with("TkTopLevel", "Willy")
                mock_iconic.assert_called_once_with(0xABCD)
                mock_show.assert_not_called()
                mock_fg.assert_called_once_with(0xABCD)

                mock_iconic.return_value = 1
                mgr.signal_and_restore(tmp, window_title="Willy")
                mock_show.assert_called_once_with(0xABCD, 9)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

