"""
Depois de cada ditado o Dashboard relê só o histórico e os KPIs.

O recarregar_dados relia tudo: os Ajustes voltavam ao que estava gravado e o texto do
Vocabulário era trocado pelo do disco, apagando o que a pessoa estava editando quando um
ditado terminava (e a lista de microfones era montada de novo a cada ditado). O completo fica
para a abertura e para o perfil importado, que relê todas as abas.
"""

import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from tests.config_isolada import isolar_config
from tests.willy_isolado import _funcao_do_willy, destruir_tk
from ui.dashboard import WillyDashboard


class TestRecarregar(unittest.TestCase):
    # Um dashboard para a classe: montar um leva segundos.
    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls.estado = {"historico": [], "vocab": "termo gravado", "silent_mode": False}
        cls.cb = {
            "get_history": lambda: list(cls.estado["historico"]),
            "get_settings": lambda: {"silent_mode": cls.estado["silent_mode"]},
            "get_vocab": lambda: cls.estado["vocab"],
            "get_snippets": MagicMock(return_value=[]),
            "get_replacements": MagicMock(return_value={}),
            "get_analytics": MagicMock(return_value={}),
            "get_app_rules": list,
        }
        cls.dash = WillyDashboard(callbacks=cls.cb)
        cls.dash.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def setUp(self):
        self.estado.update(historico=[], vocab="termo gravado", silent_mode=False)
        self.dash.recarregar_dados(completo=True)
        for cb in ("get_snippets", "get_replacements", "get_analytics"):
            self.cb[cb].reset_mock()
        # A pessoa no meio da edição: um termo novo e o modo silencioso ligado, sem salvar.
        self.dash.txt_vocab.insert("end", "\ntermo que estou digitando")
        self.dash.tab_settings.switch_mudo.select()

    def _vocab(self):
        return self.dash.txt_vocab.get("1.0", "end").strip()

    def test_depois_do_ditado_nao_mexe_no_que_esta_sendo_editado(self):
        self.estado["historico"] = [{"text": "ditado novo", "mode": "transcribe"}]
        self.dash.recarregar_dados()
        self.assertIn("termo que estou digitando", self._vocab())
        self.assertEqual(1, self.dash.tab_settings.switch_mudo.get(), "o Ajustes voltou ao gravado")
        self.cb["get_snippets"].assert_not_called()
        self.cb["get_replacements"].assert_not_called()

    def test_depois_do_ditado_le_o_historico_e_os_kpis(self):
        self.estado["historico"] = [{"text": "ditado novo", "mode": "transcribe"}]
        with patch.object(self.dash, "state", return_value="normal"):
            self.dash.recarregar_dados()
        self.assertEqual(["ditado novo"], [it["text"] for it in self.dash.history_items])
        self.cb["get_analytics"].assert_called()

    def test_completo_rele_todas_as_abas(self):
        self.estado["vocab"] = "termo do perfil"
        self.dash.recarregar_dados(completo=True)
        self.assertEqual("termo do perfil", self._vocab())
        self.assertEqual(0, self.dash.tab_settings.switch_mudo.get())
        self.cb["get_snippets"].assert_called()
        self.cb["get_replacements"].assert_called()

    def test_ajuste_trocado_pela_bandeja_atualiza_so_os_ajustes(self):
        self.estado["silent_mode"] = True
        self.dash.tab_settings.switch_mudo.deselect()
        self.dash.recarregar_ajustes()
        self.assertEqual(1, self.dash.tab_settings.switch_mudo.get())
        self.assertIn("termo que estou digitando", self._vocab())

    def test_a_abertura_rele_tudo(self):
        with patch.object(WillyDashboard, "recarregar_dados") as recarregar:
            dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list})
        try:
            recarregar.assert_called_once_with(completo=True)
        finally:
            dash.destroy()


class TestBandejaAtualizaSoOsAjustes(unittest.TestCase):
    # Trocam um ajuste por fora da aba: a aba Ajustes tem que mostrar, o resto fica.
    CHAMADAS: ClassVar[dict] = {
        "toggle_modo_envio": (), "toggle_polimento_ia": (), "toggle_modo_silencioso": (),
        "definir_posicao_pilula": ("topo",), "definir_modelo_ia": ("modelo",),
        "on_profile_toggle_hotkey": (),
    }

    def setUp(self):
        from tests.config_isolada import isolar_config
        isolar_config(self)

    def test_cada_troca_pela_bandeja(self):
        from unittest.mock import create_autospec

        from core.config import ConfigManager
        from core.groq_service import GroqService
        from core.sound import SoundManager
        from ui.overlays.pill import FloatingPill

        config_mgr = ConfigManager()
        for nome, args in self.CHAMADAS.items():
            with self.subTest(nome):
                dashboard = create_autospec(WillyDashboard, instance=True)
                pill = create_autospec(FloatingPill, instance=True)
                groq_service = create_autospec(GroqService, instance=True)
                sound_mgr = create_autospec(SoundManager, instance=True)
                despachar = MagicMock()
                funcao = _funcao_do_willy(
                    nome, config_mgr=config_mgr, sincronizar_bandeja=MagicMock(), dashboard=dashboard,
                    safe_dispatch_ui=despachar, pill=pill, groq_service=groq_service,
                    sound_mgr=sound_mgr, atualizar_ui=MagicMock())
                funcao(*args)
                despachados = [c.args[0] for c in despachar.call_args_list]
                self.assertIn(dashboard.recarregar_ajustes, despachados)
                self.assertNotIn(dashboard.recarregar_dados, despachados)

    def test_on_profile_toggle_hotkey_cicla_dev_executivo_puro_dev(self):
        from core.config import ConfigManager
        config_mgr = ConfigManager()
        config_mgr.save_settings({"PROCESSING_PROFILE": "dev"})
        funcao = _funcao_do_willy(
            "on_profile_toggle_hotkey", config_mgr=config_mgr, sincronizar_bandeja=MagicMock(),
            dashboard=None, safe_dispatch_ui=MagicMock(), sound_mgr=MagicMock(), atualizar_ui=MagicMock())
        funcao()
        self.assertEqual("executivo", config_mgr.processing_profile)
        funcao()
        self.assertEqual("puro", config_mgr.processing_profile)
        funcao()
        self.assertEqual("dev", config_mgr.processing_profile)

    def test_toggle_modo_envio_alterna_auto_silence(self):
        from core.config import ConfigManager
        config_mgr = ConfigManager()
        config_mgr.save_settings({"AUTO_SILENCE": True})
        funcao = _funcao_do_willy(
            "toggle_modo_envio", config_mgr=config_mgr, sincronizar_bandeja=MagicMock(),
            dashboard=None, safe_dispatch_ui=MagicMock())
        funcao()
        self.assertFalse(config_mgr.auto_silence)
        funcao()
        self.assertTrue(config_mgr.auto_silence)


if __name__ == "__main__":
    unittest.main()
