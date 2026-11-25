"""
O avatar da barra lateral é o robô do Willy, o mesmo do ícone do app e da bandeja.

Em 23/09 ele foi trocado, sem registro, por um ícone azul chapado de 56px (willy_avatar_*.png)
e encolhido para 28px. Estes testes travam o robô e o tamanho que cabe no cabeçalho.
"""

import os
import unittest

import numpy as np
from PIL import Image

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAvatarDaBarraLateral(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls.dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list})
        cls.dash.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def test_avatar_e_o_robo_do_willy(self):
        img = self.dash.robot_ctk_img
        self.assertIsNotNone(img, "sem avatar no cabeçalho")

        with Image.open(os.path.join(RAIZ, "assets", "willy_robot.png")) as robo:
            esperado = np.asarray(robo.convert("RGBA").resize((96, 96), Image.Resampling.LANCZOS), dtype=np.int16)
        mostrado = np.asarray(img.cget("light_image").convert("RGBA"), dtype=np.int16)

        self.assertEqual(esperado.shape, mostrado.shape)
        self.assertLess(np.abs(esperado - mostrado).mean(), 1.0, "o avatar não é o robô do Willy")

    def test_avatar_ocupa_a_coluna_de_40px_do_cabecalho(self):
        """40px cobrem as duas linhas (nome + status) sem tirar o "Willy" do eixo dos itens."""
        self.assertEqual((40, 40), self.dash.robot_ctk_img.cget("size"))

    def test_dashboard_delega_atributos_dinamicamente_sem_copia_estatica(self):
        """AUD-058: WillyDashboard delega widgets e métodos às abas sem cópia estática em self.__dict__."""
        dash = self.dash
        self.assertNotIn("entry_key", dash.__dict__)
        self.assertIs(dash.entry_key, dash.tab_settings.entry_key)
        self.assertIs(dash.entry_busca, dash.tab_history.entry_busca)
        self.assertIs(dash.txt_vocab, dash.tab_vocab.txt_vocab)
        self.assertIs(dash.btn_test_mic, dash.tab_diagnostics.btn_test_mic)


class TestT21DashboardNavegacaoETema(unittest.TestCase):
    def test_theme_e_ui_init_definem_all_explicito(self):
        """AUD-053: ui.theme e ui.__init__ expõem __all__ explícito."""
        import ui
        from ui import theme

        self.assertTrue(hasattr(theme, "__all__"))
        self.assertTrue(hasattr(ui, "__all__"))
        self.assertIn("APPLE_BG_APP", ui.__all__)
        self.assertIn("carregar_icone", ui.__all__)
        self.assertIn("diretorios_de_assets", ui.__all__)
        self.assertIn("localizar_asset", ui.__all__)

    def test_status_tooltip_unificado_com_tooltip(self):
        """AUD-057: StatusToolTip em ui.navigation.sidebar é alias de ToolTip."""
        from ui.components.tooltip import ToolTip
        from ui.navigation.sidebar import StatusToolTip

        self.assertIs(StatusToolTip, ToolTip)

    def test_carregar_icone_fluent_delega_para_carregar_icone(self):
        """AUD-061: carregar_icone_fluent delega para carregar_icone."""
        from unittest.mock import patch

        from ui.navigation import sidebar

        with patch.object(sidebar, "carregar_icone", return_value="ICONE_MOCK") as mock_ci:
            res = sidebar.carregar_icone_fluent("history")
        self.assertEqual(res, "ICONE_MOCK")
        mock_ci.assert_called_once_with("history", active=False, variant="secondary", size=(16, 16))

    def test_localizar_asset_suporta_meipass_e_frozen(self):
        """AUD-081: localizar_asset busca em _MEIPASS e sys.executable quando empacotado."""
        import sys
        import tempfile
        from unittest.mock import patch

        from ui.theme import localizar_asset

        with tempfile.TemporaryDirectory() as tmpdir:
            icons_dir = os.path.join(tmpdir, "assets", "icons")
            os.makedirs(icons_dir, exist_ok=True)
            fake_icon = os.path.join(icons_dir, "custom_test_light.png")
            with open(fake_icon, "wb") as f:
                f.write(b"fake")

            with patch.object(sys, "_MEIPASS", tmpdir, create=True):
                achado = localizar_asset("assets", "icons", "custom_test_light.png")
            self.assertEqual(achado, fake_icon)

    def test_tray_get_icon_image_fecha_handle_com_context_manager(self):
        """AUD-067: TrayManager.get_icon_image abre imagem com context manager."""
        import tempfile
        from unittest.mock import MagicMock, patch

        from ui.overlays.tray import TrayManager

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir, exist_ok=True)
            img_path = os.path.join(assets_dir, "willy_robot.png")
            Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(img_path)

            tm = TrayManager(callbacks={}, base_dir=tmpdir)
            real_img = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
            cm_img = MagicMock()
            cm_img.__enter__.return_value = real_img
            cm_img.__exit__.return_value = False

            with patch("ui.overlays.tray.Image.open", return_value=cm_img) as mock_open:
                out = tm.get_icon_image(active=True)

            mock_open.assert_called_once_with(img_path)
            cm_img.__enter__.assert_called_once()
            cm_img.__exit__.assert_called_once()
            self.assertEqual(out.size, (64, 64))

    def test_dwm_nao_usa_findwindoww_por_titulo_e_loga_erro_inesperado(self):
        """AUD-060: aplicar_dwm_caption_color não usa FindWindowW(None, 'Willy') e loga falha inesperada."""
        import io
        from unittest.mock import MagicMock, patch

        from ui.navigation import dwm

        fake_u32 = MagicMock()
        fake_u32.GetAncestor.return_value = 0
        fake_u32.GetParent.return_value = 12345
        fake_dwm = MagicMock()
        fake_dwm.DwmSetWindowAttribute.side_effect = RuntimeError("falha dwm")

        win = MagicMock()
        win.winfo_id.return_value = 999
        buf = io.StringIO()
        with (
            patch.object(dwm, "_user32", fake_u32),
            patch.object(dwm, "_dwmapi", fake_dwm),
            patch("sys.stderr", buf),
        ):
            dwm.aplicar_dwm_caption_color(win)

        fake_u32.FindWindowW.assert_not_called()
        fake_u32.GetParent.assert_called_once_with(999)
        self.assertIn("falha dwm", buf.getvalue())

    def test_construir_callbacks_padrao_completo(self):
        """AUD-059: construir_callbacks_padrao aponta para métodos reais existentes em ConfigManager."""
        from core import ConfigManager, SnippetManager
        from tests.config_isolada import isolar_config
        from ui.dashboard import construir_callbacks_padrao

        isolar_config(self)
        cfg = ConfigManager()
        snip = SnippetManager()
        cbs = construir_callbacks_padrao(cfg, snip)
        esperados_no_cfg = {
            "get_history": "load_history",
            "get_analytics": "get_analytics_metrics",
            "get_replacements": "load_replacements",
            "on_save_replacement": "add_replacement",
            "on_delete_replacement": "delete_replacement",
            "get_app_rules": "get_app_context_rules",
            "on_save_app_rules": "save_app_context_rules",
            "on_learn_correction": "learn_correction",
            "on_export_profile": "export_profile",
            "on_import_profile": "import_profile",
            "on_open_outputs": "open_outputs_folder",
            "get_vocab": "load_vocab_text",
            "on_save_settings": "save_settings",
            "on_save_vocab": "save_vocab_text",
            "on_clear_history": "clear_history",
        }
        for chave, metodo in esperados_no_cfg.items():
            self.assertTrue(hasattr(ConfigManager, metodo), f"ConfigManager não tem {metodo}")
            self.assertEqual(cbs[chave], getattr(cfg, metodo), f"{chave} não aponta para cfg.{metodo}")
        self.assertEqual(cbs["on_play_audio"], ConfigManager.open_file)
        self.assertEqual(cbs["on_open_file"], ConfigManager.open_file)
        self.assertEqual(cbs["on_summarize_profile"], cfg.resumir_perfil)
        self.assertIsNone(cbs["get_settings"]()["modelo_llm_substituido"])
        self.assertIsNone(cbs["get_last_external_app"]())

    def test_t5_construir_callbacks_padrao_expoe_cofre_ilegivel_em_get_settings(self):
        """T5 (R2): get_settings de construir_callbacks_padrao reflete cfg.cofre_ilegivel (False e True)."""
        from core import ConfigManager, SnippetManager
        from tests.config_isolada import isolar_config
        from ui.dashboard import construir_callbacks_padrao

        class _CofreLocal:
            def __init__(self, chave=""):
                self.chave = chave
                self.falha = False

            def get_password(self, _srv, _usr):
                if self.falha:
                    raise RuntimeError("cofre indisponível")
                return self.chave

            def set_password(self, _srv, _usr, valor):
                self.chave = valor

        isolar_config(self)
        cofre = _CofreLocal(chave="gsk_teste_isolado")
        cfg = ConfigManager(cofre=cofre)
        cbs = construir_callbacks_padrao(cfg, SnippetManager())
        self.assertIs(False, cbs["get_settings"]()["cofre_ilegivel"])

        cofre.falha = True
        cfg.recarregar_chave_do_cofre()
        self.assertIs(True, cbs["get_settings"]()["cofre_ilegivel"])

    def test_t6_construir_callbacks_padrao_nao_finge_sucesso_nos_stubs_isolados(self):
        """T6: No modo isolado, stubs não simulam reformatação, transcrição nem validação de chave."""
        from core import ConfigManager, SnippetManager
        from tests.config_isolada import isolar_config
        from ui.dashboard import construir_callbacks_padrao

        isolar_config(self)
        cbs = construir_callbacks_padrao(ConfigManager(), SnippetManager())
        self.assertNotIn("on_reformat_text", cbs)
        with self.assertRaises(RuntimeError) as ctx:
            cbs["on_transcribe_file"]("amostra_teste.wav")
        self.assertIn("modo isolado", str(ctx.exception))
        self.assertEqual(
            (False, "Validação indisponível no modo isolado.", 0.0, {}),
            cbs["on_validate_groq_key"]("x"),
        )


if __name__ == "__main__":
    unittest.main()
