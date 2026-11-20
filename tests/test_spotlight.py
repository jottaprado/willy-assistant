"""
Testes unitários para o Mini-Spotlight de Histórico Rápido.
"""

import gc
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.overlays import spotlight as sp
from ui.overlays.spotlight import HistorySpotlight


class TestHistorySpotlight(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def setUp(self):
        self.mock_paste = MagicMock()
        self.spotlight = HistorySpotlight(master=self.root, on_paste_callback=self.mock_paste)

    def tearDown(self):
        destruir_tk(self.spotlight)

    def _esperar_colagem(self, segundos=1.0):
        """A colagem vai numa thread, depois de devolver o foco ao app: não é na hora."""
        fim = time.time() + segundos
        while not self.mock_paste.called and time.time() < fim:
            self.root.update()
            time.sleep(0.01)

    def test_spotlight_filtering(self):
        sample_history = [
            {"text": "Primeiro ditado geral", "mode": "transcribe", "timestamp": "10:00:00"},
            {"text": "Segundo prompt de agente", "mode": "prompt", "timestamp": "10:05:00"},
            {"text": "Terceiro resumo de reuniao", "mode": "meeting", "timestamp": "10:10:00"},
        ]

        self.spotlight.items = list(reversed(sample_history))

        # Sem filtro retorna todos (até 8)
        self.spotlight._filtrar_itens("")
        self.assertEqual(len(self.spotlight.filtered_items), 3)

        # Filtro por texto
        self.spotlight._filtrar_itens("prompt")
        self.assertEqual(len(self.spotlight.filtered_items), 1)
        self.assertEqual(self.spotlight.filtered_items[0]["mode"], "prompt")

        # Filtro por modo
        self.spotlight._filtrar_itens("meeting")
        self.assertEqual(len(self.spotlight.filtered_items), 1)

    def test_spotlight_busca_raw_text_e_rotulos_send_transform(self):
        """AUD-065: _filtrar_itens busca em raw_text normalizado e modo_cores inclui send e transform."""
        self.spotlight.items = [
            {"text": "Good morning, team.", "raw_text": "Bom dia, programação", "mode": "send", "timestamp": "10:00:00"},
            {"text": "Texto reescrito formalmente", "raw_text": "reescreve aí", "mode": "transform", "timestamp": "10:05:00"},
        ]
        self.spotlight._filtrar_itens("programacao")
        self.assertEqual(len(self.spotlight.filtered_items), 1)
        self.assertEqual(self.spotlight.filtered_items[0]["mode"], "send")
        self.assertEqual(self.spotlight.pool_cards[0]["lbl_tag"].cget("text"), "🚀 Enviar")

        self.spotlight._filtrar_itens("reescreve ai")
        self.assertEqual(len(self.spotlight.filtered_items), 1)
        self.assertEqual(self.spotlight.filtered_items[0]["mode"], "transform")
        self.assertEqual(self.spotlight.pool_cards[0]["lbl_tag"].cget("text"), "🪄 Transformar")

    def test_spotlight_navigation_and_selection(self):
        sample_history = [
            {"text": "Texto A", "mode": "transcribe", "timestamp": "10:00:00"},
            {"text": "Texto B", "mode": "transcribe", "timestamp": "10:01:00"},
            {"text": "Texto C", "mode": "transcribe", "timestamp": "10:02:00"},
        ]
        self.spotlight.items = sample_history
        self.spotlight._filtrar_itens("")

        self.assertEqual(self.spotlight.selected_index, 0)
        self.spotlight._navegar_baixo()
        self.assertEqual(self.spotlight.selected_index, 1)
        self.spotlight._navegar_baixo()
        self.assertEqual(self.spotlight.selected_index, 2)
        # Loop para o topo
        self.spotlight._navegar_baixo()
        self.assertEqual(self.spotlight.selected_index, 0)

        # Confirma seleção disparando o handler Tcl registrado em <Return> na entry_busca
        script_return = self.spotlight.entry_busca._entry.bind("<Return>")
        self.assertTrue(script_return, "entry_busca precisa ter binding <Return> registrado")
        cmd_tcl = script_return.split("[", 1)[1].split()[0]
        self.spotlight.tk.call(cmd_tcl, *(["0"] * 19))
        self._esperar_colagem()
        self.mock_paste.assert_called_once_with("Texto A")

    def _clicar(self, widget):
        """Clique de verdade do Tk: dispara TODOS os handlers ligados ao widget."""
        alvo = getattr(widget, "_canvas", widget)
        alvo.event_generate("<Button-1>", x=4, y=4, when="now")

    def test_um_clique_cola_uma_vez_depois_de_varias_buscas(self):
        """O bind era refeito a cada render (o CTk força add=True): 1 clique colava 16 vezes."""
        self.spotlight.items = [
            {"text": "Texto A", "mode": "transcribe", "timestamp": "10:00:00"},
            {"text": "Texto B", "mode": "prompt", "timestamp": "10:01:00"},
        ]
        for _ in range(5):  # cinco aberturas com setas e busca
            self.spotlight._filtrar_itens("")
            self.spotlight._navegar_baixo()
            self.spotlight._navegar_cima()
        self.spotlight.selected_index = 0
        self.spotlight.deiconify()
        self.spotlight.update()

        self._clicar(self.spotlight.pool_cards[1]["frame"])

        self._esperar_colagem()
        self.mock_paste.assert_called_once_with("Texto B")

    def test_clique_no_rotulo_do_modo_tambem_seleciona(self):
        self.spotlight.items = [{"text": "Texto A", "mode": "transcribe", "timestamp": "10:00:00"}]
        self.spotlight._filtrar_itens("")
        self.spotlight.deiconify()
        self.spotlight.update()

        self._clicar(self.spotlight.pool_cards[0]["lbl_tag"])

        self._esperar_colagem()
        self.mock_paste.assert_called_once_with("Texto A")


ITENS = [{"text": "Texto A", "mode": "transcribe", "timestamp": "10:00:00"}]
APP = 0xABC  # o hwnd do app em que a pessoa estava


class _SpotlightAberto(unittest.TestCase):
    """O Spotlight aberto por mostrar(), sem tocar no foco de verdade da máquina."""

    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        # O deiconify do CTkToplevel agenda afters (ícone, barra de título): rodam aqui, com
        # a raiz viva, e não depois do destroy, quando viram "bgerror failed".
        fim = time.time() + 0.5
        while time.time() < fim:
            cls.root.update()
            time.sleep(0.01)
        destruir_tk(cls.root)

    def setUp(self):
        # O lixo dos testes anteriores é coletado aqui, na thread principal. Coletado na thread
        # do teste, o Font.__del__ do tkinter chama o Tcl de fora da thread principal e, sem
        # mainloop, cada um espera ~1 s: a thread passava do prazo (medido no CI do Bloco 6B).
        gc.collect()
        self.eventos = []
        self.colou = threading.Event()

        def _colar(texto):
            self.eventos.append(("colou", texto, threading.current_thread() is threading.main_thread()))
            self.colou.set()

        self.s = HistorySpotlight(master=self.root)
        self.addCleanup(self.s.destroy)
        self.s.focus_force = MagicMock()  # o focus_force de verdade tiraria o foco do editor
        cm = sp.ContextManager
        for nome, valor in (("get_foreground_hwnd", MagicMock(return_value=APP)),
                            ("eh_janela_do_willy", MagicMock(return_value=False)),
                            ("focus_window", MagicMock(side_effect=self._focou))):
            p = patch.object(cm, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        self.colar = _colar

    def _focou(self, hwnd):
        self.eventos.append(("focou", hwnd, self.s.state()))
        return True

    def _bombear(self, segundos):
        fim = time.time() + segundos
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)


class TestColaNoAppDeAntes(_SpotlightAberto):
    def test_lembra_o_app_antes_de_tomar_o_foco(self):
        self.s.focus_force.side_effect = lambda: self.eventos.append(("tomou_o_foco",))
        sp.ContextManager.get_foreground_hwnd.side_effect = lambda: (self.eventos.append(("leu",)), APP)[1]
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        self.assertEqual([("leu",), ("tomou_o_foco",)], self.eventos)
        self.assertEqual(APP, self.s._janela_anterior)

    def test_atalho_de_novo_com_ele_aberto_mantem_o_app(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        # Agora o primeiro plano é o próprio Spotlight, que é do Willy.
        sp.ContextManager.get_foreground_hwnd.return_value = 0x5907
        sp.ContextManager.eh_janela_do_willy.return_value = True
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        self.assertEqual(APP, self.s._janela_anterior)

    def test_janela_do_willy_nao_e_onde_colar(self):
        sp.ContextManager.eh_janela_do_willy.return_value = True
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        self.assertEqual(0, self.s._janela_anterior)

    def test_esconde_devolve_o_foco_e_so_entao_cola_fora_da_thread_da_interface(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        self.s._confirmar_selecao()
        self.assertTrue(self.colou.wait(1), "não colou")
        self.assertEqual([("focou", APP, "withdrawn"), ("colou", "Texto A", False)], self.eventos)

    def test_cola_depois_do_atraso(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        inicio = time.perf_counter()
        self.s._confirmar_selecao()
        self.assertTrue(self.colou.wait(1))
        # ~60 ms: o Windows precisa desse tempo para trocar a janela ativa antes do Ctrl+V
        self.assertGreaterEqual(time.perf_counter() - inicio, 0.05)

    def test_sem_app_anterior_cola_sem_mexer_no_foco(self):
        sp.ContextManager.eh_janela_do_willy.return_value = True
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        self.s._confirmar_selecao()
        self.assertTrue(self.colou.wait(1))
        sp.ContextManager.focus_window.assert_not_called()


class TestAbreNoMonitorDoApp(_SpotlightAberto):
    def test_centra_na_area_do_monitor_do_app_com_a_escala_dele(self):
        segundo = (1920, 0, 3840, 1040)
        with patch.object(sp, "_monitor_ativo", return_value=(segundo, 1.25)) as monitor, \
                patch.object(sp.ctk.ScalingTracker, "window_scaling", 1.0):
            self.s.mostrar(ITENS, on_paste_callback=self.colar)
        monitor.assert_called_once()
        self.assertEqual(APP, monitor.call_args.args[0])
        # 540x360 a 125% = 675x450: centrado na largura, a um terço da altura
        x, y = (int(v) for v in self.s.tk.call("wm", "geometry", self.s._w).split("+")[1:])
        self.assertEqual((1920 + (1920 - 675) // 2, (1040 - 450) // 3), (x, y))

    def test_sem_a_api_cai_na_tela_primaria(self):
        with patch.object(sp, "_monitor_ativo", return_value=None), \
                patch.object(sp.ctk.ScalingTracker, "window_scaling", 1.0):
            self.s.mostrar(ITENS, on_paste_callback=self.colar)
        x, y = (int(v) for v in self.s.tk.call("wm", "geometry", self.s._w).split("+")[1:])
        tela = (0, 0, self.s.winfo_screenwidth(), self.s.winfo_screenheight())
        self.assertEqual(sp.posicao_centralizada(tela, 540, 360), (x, y))

    def test_posicao_centralizada(self):
        self.assertEqual((-1230, 371 + (1032 - 360) // 3), sp.posicao_centralizada((-1920, 371, 0, 1403), 540, 360))

    @unittest.skipUnless(sp.sys.platform == "win32", "Win32")
    def test_monitor_ativo_aceita_hmonitor_de_64_bits_no_shcore_real(self):
        """Com HMONITOR de 64 bits (bit 31 estendido: 0xFFFFFFFF8C540855), GetDpiForMonitor sem
        argtypes levantava ArgumentError e _monitor_ativo devolvia None."""
        hmon_64 = 0xFFFFFFFF8C540855

        def _preencher_info(h, ptr):
            self.assertEqual(hmon_64, h)
            info = ptr._obj
            info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom = -1920, 371, 0, 1403
            return 1

        with patch.object(sp._user32, "MonitorFromWindow", return_value=hmon_64),                 patch.object(sp._user32, "GetMonitorInfoW", side_effect=_preencher_info):
            # Chama o _shcore.GetDpiForMonitor REAL do Windows com o handle de 64 bits:
            resultado = sp._monitor_ativo(APP, (0, 0))
        self.assertIsNotNone(resultado)
        self.assertEqual((-1920, 371, 0, 1403), resultado[0])


class TestFechaQuandoOFocoSai(_SpotlightAberto):
    def test_foco_em_outra_janela_do_willy_fecha(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        with patch.object(self.s, "focus_get", return_value=self.root):
            self.s._verificar_foco()
        self.assertEqual("withdrawn", self.s.state())

    def test_foco_dentro_do_spotlight_nao_fecha(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        with patch.object(self.s, "focus_get", return_value=self.s.entry_busca):
            self.s._verificar_foco()
        self.assertNotEqual("withdrawn", self.s.state())

    def test_varios_focusout_conferem_uma_vez(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        with patch.object(self.s, "_verificar_foco") as verificar:
            for _ in range(3):
                self.s._ao_perder_foco(None)
            self._bombear(sp.ESPERA_DO_FOCO_MS / 1000 + 0.2)
        self.assertEqual(1, verificar.call_count)

    def test_fechar_cancela_a_conferencia_pendente(self):
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        # Antes do <FocusOut>: o after guarda o método que existia quando foi agendado.
        with patch.object(self.s, "_verificar_foco") as verificar:
            self.s._ao_perder_foco(None)
            self.s.fechar()
            self._bombear(sp.ESPERA_DO_FOCO_MS / 1000 + 0.2)
        verificar.assert_not_called()

    def test_abrir_de_novo_cancela_a_conferencia_pendente(self):
        # O atalho apertado com o Spotlight já aberto: a conferência de antes não pode fechá-lo.
        self.s.mostrar(ITENS, on_paste_callback=self.colar)
        with patch.object(self.s, "_verificar_foco") as verificar:
            self.s._ao_perder_foco(None)
            self.s.mostrar(ITENS, on_paste_callback=self.colar)
            self._bombear(sp.ESPERA_DO_FOCO_MS / 1000 + 0.2)
        verificar.assert_not_called()

    def test_destruido_com_conferencia_pendente_nao_deixa_after_quebrado(self):
        # O destroy do tkinter apaga o comando do after, que dispara depois num nome que não
        # existe mais: o Tcl reporta isso pelo bgerror.
        erros = []
        self.root.tk.createcommand("bgerror", lambda *msg: erros.append(msg))
        self.addCleanup(self.root.tk.deletecommand, "bgerror")
        outro = HistorySpotlight(master=self.root)
        self._bombear(0.3)  # os afters do próprio CTkToplevel rodam antes
        outro._ao_perder_foco(None)
        outro.destroy()
        self._bombear(sp.ESPERA_DO_FOCO_MS / 1000 + 0.2)
        self.assertEqual([], erros)


class TestIconeDaBandeja(unittest.TestCase):
    def test_icone_fica_visivel_e_on_ready_roda(self):
        """Com setup próprio, o pystray não liga visible: o ícone nunca aparecia."""
        from unittest.mock import patch

        from ui.overlays.tray import TrayManager

        icone = MagicMock()
        icone.visible = False
        icone.run.side_effect = lambda setup: setup(icone)
        on_ready = MagicMock()

        with patch("ui.overlays.tray.pystray.Icon", return_value=icone):
            TrayManager(callbacks={}, base_dir=".").start(on_ready=on_ready)

        self.assertTrue(icone.visible)
        on_ready.assert_called_once_with(icone)


if __name__ == "__main__":
    unittest.main()

