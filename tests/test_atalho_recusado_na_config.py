"""
Atalho recusado pelo Windows não fica salvo, e as abas mostram o que vale.

Trocar um atalho para uma combinação que outro programa já usa fazia o orquestrador voltar
à anterior, mas só na memória: os Ajustes já tinham gravado a recusada no .env, e a partida
seguinte a tentava de novo, sem anterior para onde voltar. A aba Atalhos e os campos dos
Ajustes seguiam mostrando a recusada, e o próximo "Salvar" dos Ajustes a gravava outra vez.
"""

import os
import unittest
from typing import ClassVar
from unittest.mock import MagicMock

from dotenv import dotenv_values

from core.config import ConfigManager
from core.system.hotkey_orchestrator import ATALHOS, HotkeyOrchestrator
from tests.config_isolada import isolar_config
from tests.test_recarregar_atalhos import GerenciadorFalso
from tests.willy_isolado import _funcao_do_willy, _keycaps, destruir_tk
from ui.dashboard import WillyDashboard

ANTIGO, RECUSADO = "ctrl+space", "ctrl+alt+x"


class TestVoltaChegaAoEnv(unittest.TestCase):
    """Com o ConfigManager de verdade, num .env temporário."""

    def setUp(self):
        pasta = isolar_config(self)
        self.env = os.path.join(pasta, ".env")
        with open(self.env, "w", encoding="utf-8") as f:
            f.write(f"GROQ_API_KEY=gsk_teste\nVOICE_HOTKEY={ANTIGO}\n")

    def test_troca_recusada_nos_ajustes_some_do_env(self):
        config = ConfigManager()
        orq = HotkeyOrchestrator(GerenciadorFalso(ocupados={RECUSADO}), config, {"voice": lambda: None})
        orq.registrar_todos()

        dados = {"VOICE_HOTKEY": RECUSADO}
        config.save_settings(dados)  # como o dashboard_save_settings: grava, depois recarrega
        orq.recarregar_se_necessario(dados)

        self.assertEqual(ANTIGO, config.hotkey)
        self.assertEqual(ANTIGO, dotenv_values(self.env)["VOICE_HOTKEY"])
        self.assertEqual(ANTIGO, ConfigManager().hotkey, "a próxima partida leria a recusada")


class TestAbasMostramOQueVale(unittest.TestCase):
    """Dashboard de verdade: a troca pela aba Atalhos é recusada e volta à anterior."""

    # Um dashboard para a classe: montar um leva segundos.
    config: ClassVar[dict] = {}
    salvos: ClassVar[list] = []

    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        callbacks = {
            "get_history": list,
            "get_app_rules": list,
            "get_settings": lambda: dict(cls.config),
            # Como o willy: grava, o Windows recusa, e a config volta à anterior.
            "on_save_settings": cls.salvos.append,
        }
        cls.config["voice_hotkey"] = ANTIGO
        cls.dash = WillyDashboard(callbacks=callbacks)
        cls.dash.withdraw()
        cls.voz = _keycaps(cls.dash.frames_abas["shortcuts"])[0]  # a primeira linha é o ditado

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def setUp(self):
        self.config["voice_hotkey"] = ANTIGO
        self.dash.sincronizar_atalhos()
        self.salvos.clear()
        self.assertEqual(ANTIGO, self.voz.get_hotkey())

    def _trocar_na_aba_atalhos(self, combo):
        self.voz.finalizar_captura(combo)
        self.assertEqual([{"VOICE_HOTKEY": combo}], self.salvos)

    def test_aba_atalhos_volta_a_mostrar_a_anterior(self):
        self._trocar_na_aba_atalhos(RECUSADO)
        self.assertEqual(RECUSADO, self.voz.get_hotkey())

        self.dash.sincronizar_atalhos()
        self.assertEqual(ANTIGO, self.voz.get_hotkey())
        self.assertEqual(ANTIGO, self.voz.existing_hotkeys["VOICE_HOTKEY"])

    def test_campo_dos_ajustes_mostra_a_anterior(self):
        self.dash.tab_settings.entry_hk_voice.delete(0, "end")
        self.dash.tab_settings.entry_hk_voice.insert(0, RECUSADO)
        self.dash.sincronizar_atalhos()
        self.assertEqual(ANTIGO, self.dash.tab_settings.entry_hk_voice.get())

    def test_troca_aceita_aparece_nas_duas_abas(self):
        # Sem isto, trocar na aba Atalhos e depois salvar os Ajustes regravava a antiga.
        self._trocar_na_aba_atalhos("ctrl+alt+v")
        self.config["voice_hotkey"] = "ctrl+alt+v"
        self.dash.sincronizar_atalhos()
        self.assertEqual("ctrl+alt+v", self.voz.get_hotkey())
        self.assertEqual("ctrl+alt+v", self.dash.tab_settings.entry_hk_voice.get())

    def test_campo_vazio_na_config_aparece_vazio(self):
        # Vazio não registra atalho nenhum; mostrar o padrão dizia que ele valia.
        self.config["voice_hotkey"] = ""
        self.dash.sincronizar_atalhos()
        self.assertEqual("", self.voz.get_hotkey())
        self.assertEqual("", self.dash.tab_settings.entry_hk_voice.get())

    def test_recarregar_tudo_tambem_atualiza_a_aba_atalhos(self):
        # Na abertura e no perfil importado. O recarregar leve (depois de cada ditado) não
        # mexe nos atalhos: a troca recusada já chega pelo sincronizar_atalhos.
        self.config["voice_hotkey"] = "ctrl+alt+b"
        self.dash.recarregar_dados(completo=True)
        self.assertEqual("ctrl+alt+b", self.voz.get_hotkey())

    def test_recarregar_atalhos_escreve_os_treze_campos_reais(self):
        nomes = ("voice", "trans", "trans_es", "prompt", "meeting", "master", "transform", "profile",
                 "history", "undo", "send", "speak", "sticky", "captions")
        aba = self.dash.tab_settings
        aba.recarregar_atalhos({
            "voice_hotkey": "ctrl+alt+v",
            "master_hotkey": "ctrl+alt+m",
            "translate_es_hotkey": "ctrl+alt+y",
        })
        self.assertEqual(len(ATALHOS), len(nomes))
        for n in nomes:
            self.assertTrue(hasattr(aba, f"entry_hk_{n}"), f"campo real entry_hk_{n} ausente na SettingsTab")
        self.assertEqual("ctrl+alt+v", aba.entry_hk_voice.get())
        self.assertEqual("ctrl+alt+m", aba.entry_hk_master.get())
        self.assertEqual("ctrl+alt+y", aba.entry_hk_trans_es.get())
        self.assertEqual("ctrl+alt+z", aba.entry_hk_undo.get())  # sem valor, o padrão


class TestSalvarAjustesNoWilly(unittest.TestCase):
    def _salvar(self, recarregou):
        self.dashboard = MagicMock()
        self.despachos = MagicMock()
        orq = MagicMock()
        orq.recarregar_se_necessario.return_value = recarregou
        salvar = _funcao_do_willy(
            "dashboard_save_settings", config_mgr=MagicMock(groq_api_key="gsk_x"),
            groq_service=MagicMock(), audio_mgr=MagicMock(), hotkey_orchestrator=orq,
            dashboard=self.dashboard, safe_dispatch_ui=self.despachos, sincronizar_bandeja=MagicMock(),
            pill=None, transcription_pipeline=MagicMock(fila=[]), atualizar_ui=MagicMock())
        salvar({"VOICE_HOTKEY": RECUSADO})
        return [c.args[0] for c in self.despachos.call_args_list]

    def test_depois_de_recarregar_os_atalhos_as_abas_releem(self):
        despachados = self._salvar(recarregou=True)
        self.assertIn(self.dashboard.sincronizar_atalhos, despachados)

    def test_sem_atalho_no_ajuste_nao_mexe_nas_abas(self):
        despachados = self._salvar(recarregou=False)
        self.assertNotIn(self.dashboard.sincronizar_atalhos, despachados)


if __name__ == "__main__":
    unittest.main()
