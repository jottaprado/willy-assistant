"""
WillyDashboard.mostrar(): volta como estava, foca a própria janela e refaz a lista uma vez.

- O state("normal") e o SW_RESTORE tiravam a janela de maximizada a cada abertura pela
  bandeja. E o Tk esquece o "zoomed" ao esconder (medido): o esconder() o guarda.
- O FindWindowW(None, "Willy") focava a primeira janela com esse título, que podia ser uma
  pasta "Willy" aberta no Explorer.
- A lista pendente é refeita uma vez, pelo recarregar_dados do fim (medido: o <Map> do
  deiconify chega depois dele; zerar a pendência antes não depende dessa ordem).
- Voltando da bandeja, o Vocabulário editado por fora (Bloco de Notas) é relido.
"""

import ctypes
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.dashboard import WillyDashboard


@unittest.skipUnless(sys.platform == "win32", "estados de janela e HWND do Windows")
class TestMostrar(unittest.TestCase):
    # Um dashboard para a classe: montar um leva segundos.
    @classmethod
    def setUpClass(cls):
        cls.vocab = ["Groq"]
        isolar_config(cls)
        cls.dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list, "get_vocab": lambda: cls.vocab[0]})
        cls.dash.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def setUp(self):
        import ui.dashboard as dash_mod
        # Sem roubar o foco de quem roda os testes; o HWND passado fica registrado.
        self.focou = MagicMock(return_value=1)
        self.achou = MagicMock(return_value=0)
        p_foco = patch.object(dash_mod._user32, "SetForegroundWindow", self.focou)
        p_foco.start()
        self.addCleanup(p_foco.stop)
        p_achou = patch.object(ctypes.windll.user32, "FindWindowW", self.achou)
        p_achou.start()
        self.addCleanup(p_achou.stop)
        p = patch.object(self.dash, "focus_force")
        p.start()
        self.addCleanup(p.stop)
        self.dash.mostrar()
        self.dash.state("normal")
        self._bombear()

    def tearDown(self):
        self.dash.state("normal")
        self.dash.withdraw()
        self._bombear()

    def _bombear(self, segundos=0.3):
        fim = time.time() + segundos
        while time.time() < fim:
            self.dash.update()
            time.sleep(0.01)

    def _maximizar(self):
        self.dash.state("zoomed")
        self._bombear()
        self.assertEqual("zoomed", self.dash.state())

    def test_maximizada_escondida_volta_maximizada(self):
        self._maximizar()
        self.dash.esconder()
        self._bombear()
        self.dash.mostrar()
        self._bombear()
        self.assertEqual("zoomed", self.dash.state())

    def test_maximizada_minimizada_volta_maximizada(self):
        self._maximizar()
        self.dash.iconify()
        self._bombear()
        self.dash.mostrar()
        self._bombear()
        self.assertEqual("zoomed", self.dash.state())

    def test_maximizada_na_tela_continua_maximizada(self):
        self._maximizar()
        self.dash.mostrar()
        self._bombear()
        self.assertEqual("zoomed", self.dash.state())

    def test_normal_escondida_volta_normal(self):
        self.dash.esconder()
        self._bombear()
        self.dash.mostrar()
        self._bombear()
        self.assertEqual("normal", self.dash.state())

    def test_desmaximizada_depois_e_minimizada_volta_normal(self):
        # O "estava maximizada" do último esconder() não vale para quem minimizou depois.
        self._maximizar()
        self.dash.esconder()
        self.dash.mostrar()
        self.dash.state("normal")
        self._bombear()
        self.dash.iconify()
        self._bombear()
        self.dash.mostrar()
        self._bombear()
        self.assertEqual("normal", self.dash.state())

    def test_foca_a_propria_janela_e_nao_procura_pelo_titulo(self):
        import ui.dashboard as dash_mod
        self.focou.reset_mock()
        self.dash.mostrar()
        self.focou.assert_called_once_with(int(self.dash.wm_frame(), 16))
        self.achou.assert_not_called()
        self.assertNotIn("FindWindowW", dash_mod._user32.__dict__)

    def test_minimizada_pelo_win32_e_restaurada_com_sw_restore(self):
        import ui.dashboard as dash_mod
        hwnd = int(self.dash.wm_frame(), 16)
        self.dash.iconify()
        self._bombear()
        self.assertTrue(dash_mod._user32.IsIconic(hwnd))
        with patch.object(self.dash, "state", return_value="normal"):
            self.dash.mostrar()
        self.assertFalse(dash_mod._user32.IsIconic(hwnd))

    def test_voltando_da_bandeja_rele_o_vocabulario_editado_por_fora(self):
        self.vocab[0] = "Groq"
        self.dash.recarregar_dados(completo=True)
        self.dash.esconder()
        self._bombear()
        self.vocab[0] = "Groq Kubernetes"  # o Bloco de Notas, aberto pela bandeja
        self.dash.mostrar()
        self.assertEqual("Groq Kubernetes", self.dash.txt_vocab.get("1.0", "end").strip())

    def test_lista_pendente_e_refeita_uma_vez(self):
        self.dash.active_tab = "history"
        self.dash.esconder()
        self._bombear()
        self.dash._historico_pendente = True
        with patch.object(self.dash, "atualizar_lista_historico") as refazer:
            self.dash.mostrar()
            self._bombear()
        self.assertEqual(1, refazer.call_count)
        self.assertFalse(self.dash._historico_pendente)


if __name__ == "__main__":
    unittest.main()
