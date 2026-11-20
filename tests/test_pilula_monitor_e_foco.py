"""
A pílula aparece no monitor de quem está ditando, e sem tirar o foco dessa pessoa.

Medido em 2026-10-22 numa máquina com dois monitores (primário em retrato à direita, o de
trabalho em paisagem à esquerda): o Willy instalado posicionava a pílula sempre no rodapé
do PRIMÁRIO, em (370, 1790), enquanto o dashboard e o Firefox estavam no outro monitor.
A pílula aparecia, só que fora do campo de visão, e o relato era "nada aparece na tela".
"""

import ctypes
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from ui.overlays import pill as pill_mod
from ui.overlays.pill import FloatingPill, calcular_posicao

# Layout medido: monitor de trabalho à esquerda, primário em retrato à direita.
AREA_ESQUERDA = (-1920, 371, 0, 1403)
AREA_PRIMARIO = (0, 0, 1080, 1872)
HWND_FIREFOX = 0x2C1A7E
HWND_PILULA = 0xABC
HMON_ESQUERDA, HMON_PRIMARIO = 1, 2


class TestCalcularPosicao(unittest.TestCase):
    def test_centro_inferior_no_monitor_da_esquerda(self):
        self.assertEqual((-1130, 1321), calcular_posicao("centro_inferior", AREA_ESQUERDA, (0, 0), 340, 48))

    def test_centro_inferior_no_primario_fica_onde_sempre_ficou(self):
        # Antes: x=(1080-340)//2, y=1920-130. Com barra de tarefas de 48 px, o mesmo ponto.
        self.assertEqual((370, 1790), calcular_posicao("centro_inferior", AREA_PRIMARIO, (0, 0), 340, 48))

    def test_topo(self):
        self.assertEqual((-1130, 411), calcular_posicao("topo", AREA_ESQUERDA, (0, 0), 340, 48))

    def test_seguir_cursor_no_monitor_da_esquerda_nao_pula_pro_primario(self):
        # Antes o x era preso em [20, largura do primário]: cursor em x<0 jogava a pílula em x=20.
        x, y = calcular_posicao("seguir_cursor", AREA_ESQUERDA, (-1900, 500), 340, 48)
        self.assertEqual((-1900, 430), (x, y))
        x, _ = calcular_posicao("seguir_cursor", AREA_ESQUERDA, (-10, 500), 340, 48)
        self.assertEqual(-360, x, "a pílula não pode passar da borda direita do monitor do cursor")


class User32Falso:
    """O pedaço do user32 que a pílula usa, com dois monitores e uma janela na frente."""

    def __init__(self, primeiro_plano=HWND_FIREFOX, rouba_no_show=False):
        self.primeiro_plano = primeiro_plano
        self.rouba_no_show = rouba_no_show
        self.janelas = {HWND_FIREFOX: HMON_ESQUERDA}
        self.chamadas = []

    def GetForegroundWindow(self):
        return self.primeiro_plano

    def MonitorFromWindow(self, hwnd, flags):
        return self.janelas.get(hwnd, HMON_PRIMARIO)

    def MonitorFromPoint(self, ponto, flags):
        return HMON_ESQUERDA if ponto.x < 0 else HMON_PRIMARIO

    def GetMonitorInfoW(self, hmon, ref_info):
        info = ref_info._obj
        r = AREA_ESQUERDA if hmon == HMON_ESQUERDA else AREA_PRIMARIO
        info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom = r
        return 1

    def ShowWindow(self, hwnd, cmd):
        self.chamadas.append(("ShowWindow", hwnd, cmd))
        if self.rouba_no_show:
            self.primeiro_plano = hwnd
        return 1

    def SetWindowPos(self, hwnd, *args):
        self.chamadas.append(("SetWindowPos", hwnd) + args)
        return 1

    def SetForegroundWindow(self, hwnd):
        self.chamadas.append(("SetForegroundWindow", hwnd))
        self.primeiro_plano = hwnd
        return 1


class _BasePilula(unittest.TestCase):
    posicao = "centro_inferior"

    @classmethod
    def setUpClass(cls):
        # Um Tk por classe, como o resto da suíte: um por teste falha de forma intermitente
        # no Windows ("tk wasn't installed properly" ao carregar o ttk.tcl).
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.pill = FloatingPill(self.root, position_getter=lambda: self.posicao)
        self.pill._hwnd = HWND_PILULA
        self.pill.root.deiconify = MagicMock()

    def tearDown(self):
        self.pill.destroy()

    def _xy(self):
        geo = self.pill.root.geometry()  # "340x48+-1130+1321"
        _, x, y = geo.replace("+-", "+~").split("+")
        return int(x.replace("~", "-")), int(y.replace("~", "-"))


class TestMonitorDaPessoa(_BasePilula):
    def test_aparece_no_monitor_da_janela_em_primeiro_plano(self):
        with patch.object(pill_mod, "_user32", User32Falso()), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.reposicionar()
        self.assertEqual((-1130, 1321), self._xy())

    def test_sem_janela_na_frente_vale_o_monitor_do_cursor(self):
        with patch.object(pill_mod, "_user32", User32Falso(primeiro_plano=None)), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(-500, 900)):
            self.pill.reposicionar()
        self.assertEqual((-1130, 1321), self._xy())

    def test_a_propria_pilula_na_frente_nao_conta(self):
        with patch.object(pill_mod, "_user32", User32Falso(primeiro_plano=HWND_PILULA)), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.reposicionar()
        self.assertEqual((370, 1790), self._xy())


class TestSeguirCursor(_BasePilula):
    posicao = "seguir_cursor"

    def test_vale_o_monitor_do_cursor_mesmo_com_a_janela_em_outro(self):
        # Firefox na esquerda, cursor no primário: quem escolheu seguir o cursor quer o cursor.
        with patch.object(pill_mod, "_user32", User32Falso()), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.reposicionar()
        self.assertEqual((330, 830), self._xy())


class TestMostrarSemFoco(_BasePilula):
    def test_oculta_reposiciona_e_mostra_sem_ativar(self):
        # "error" não chama reposicionar por conta própria (listening chama): é o caso do
        # aviso de microfone indisponível, que aparece direto, sem passar por "ouvindo".
        u = User32Falso()
        with patch.object(pill_mod, "_user32", u), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.show_state("error", "Microfone indisponível")
        self.assertIn(("ShowWindow", HWND_PILULA, 4), u.chamadas)  # SW_SHOWNOACTIVATE
        self.assertEqual((-1130, 1321), self._xy())
        self.pill.root.deiconify.assert_not_called()
        self.assertNotIn("SetForegroundWindow", [c[0] for c in u.chamadas])

    def test_se_a_pilula_tomar_o_primeiro_plano_ele_volta_pra_pessoa(self):
        u = User32Falso(rouba_no_show=True)
        with patch.object(pill_mod, "_user32", u), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.show_state("listening")
        self.assertIn(("SetForegroundWindow", HWND_FIREFOX), u.chamadas)
        self.assertEqual(HWND_FIREFOX, u.primeiro_plano)

    def test_nao_devolve_foco_para_a_propria_pilula(self):
        u = User32Falso(primeiro_plano=HWND_PILULA, rouba_no_show=True)
        with patch.object(pill_mod, "_user32", u), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.show_state("listening")
        self.assertNotIn("SetForegroundWindow", [c[0] for c in u.chamadas])

    def test_aviso_aparece(self):
        # "warning" não tinha ramo: os avisos de sem seleção, sem janela para fixar e de
        # atalho em uso sumiam calados.
        u = User32Falso()
        with patch.object(pill_mod, "_user32", u), \
             patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)):
            self.pill.show_state("warning", "Atalho em uso: ctrl+space")
        self.assertIn(("ShowWindow", HWND_PILULA, 4), u.chamadas)
        self.assertEqual("Atalho em uso: ctrl+space", self.pill.canvas.itemcget(self.pill.text, "text"))

    def test_ja_visivel_nao_pula_de_monitor(self):
        self.pill.root.geometry("340x48+370+1790")
        self.pill.root.update_idletasks()
        u = User32Falso()
        with patch.object(pill_mod, "_user32", u), \
             patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.show_state("processing")
        self.assertEqual((370, 1790), self._xy())


class TestAvisosPorCima(_BasePilula):
    """Aviso no meio de uma gravação volta para o "ouvindo": a gravação continua.

    Achado do verificador adversarial: com o ramo "warning" novo, Ctrl+Alt+T sem seleção no
    meio de uma reunião escondia as barras e retirava a pílula depois de 3,5 s, com a
    reunião ainda gravando, até o fim dela.
    """

    def setUp(self):
        super().setUp()
        self.withdraw = MagicMock()
        self.pill.root.withdraw = self.withdraw
        self._patches = [
            patch.object(pill_mod, "_user32", User32Falso()),
            patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)),
            patch.object(pill_mod, "DURACAO_AVISO_MS", 20),
            patch.object(pill_mod, "DURACAO_INFO_MS", 20),
            patch.object(pill_mod, "DURACAO_ERRO_MS", 20),
            patch.object(pill_mod, "DURACAO_SUCESSO_MS", 20),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    def _esperar_o_aviso(self):
        fim = time.time() + 0.2
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)

    def _barras_visiveis(self):
        return all(self.pill.canvas.itemcget(b, "state") == "normal" for b in self.pill.bars)

    def test_aviso_durante_a_gravacao_volta_para_ouvindo(self):
        self.pill.show_state("listening", "", "meeting")
        self.pill.show_state("warning", "Selecione um texto antes de transformar")
        self._esperar_o_aviso()
        self.assertEqual("listening", self.pill.current_state)
        self.assertTrue(self._barras_visiveis())
        self.withdraw.assert_not_called()

    def test_dois_avisos_seguidos_ainda_voltam_para_ouvindo(self):
        self.pill.show_state("listening")
        self.pill.show_state("warning", "um")
        self.pill.show_state("idle", "Teleprompter ativo")
        self._esperar_o_aviso()
        self.assertEqual("listening", self.pill.current_state)
        self.withdraw.assert_not_called()

    def test_aviso_sem_gravacao_esconde(self):
        self.pill.show_state("warning", "Nenhuma janela detectada para fixar")
        self._esperar_o_aviso()
        self.withdraw.assert_called()

    def test_gravacao_que_acaba_durante_o_aviso_nao_volta_a_ouvir(self):
        self.pill.show_state("listening")
        self.pill.show_state("warning", "x")
        self.pill.show_state("processing")
        self._esperar_o_aviso()
        self.assertEqual("processing", self.pill.current_state)

    def test_info_durante_o_processamento_volta_para_processando(self):
        self.pill.show_state("processing")
        self.pill.show_state("idle", "Leitura concluída")
        self.assertEqual("Leitura concluída", self.pill.canvas.itemcget(self.pill.text, "text"))
        self._esperar_o_aviso()
        self.assertEqual("processing", self.pill.current_state)
        self.withdraw.assert_not_called()

    def test_idle_sem_mensagem_nao_apaga_o_processando(self):
        self.pill.show_state("processing")
        texto = self.pill.canvas.itemcget(self.pill.text, "text")
        self.pill.show_state("idle")
        self.assertEqual("processing", self.pill.current_state)
        self.assertEqual(texto, self.pill.canvas.itemcget(self.pill.text, "text"))
        self.withdraw.assert_not_called()

    def test_idle_sem_mensagem_encerra_a_leitura_em_voz_alta(self):
        self.pill.show_state("speaking")
        self.pill.show_state("idle")
        self.withdraw.assert_called_once()

    def test_tirar_o_mouse_durante_o_aviso_nao_deixa_volta_orfa(self):
        # Achado do segundo verificador: o _on_leave agendava um timer novo sem cancelar o
        # anterior. Com a volta pendente órfã, a pílula terminava presa em "ouvindo".
        # O ponteiro já está sobre a pílula quando o aviso chega (o _on_enter veio antes e não
        # tinha o que cancelar); ao sair, o _on_leave agenda por cima da volta do aviso.
        with patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.show_state("listening")
            self.pill._on_enter()
            self.pill.show_state("warning", "x")
            self.pill._on_leave()
            self.pill.show_state("processing")
            self.pill.show_state("success", "ok")
        self._esperar_o_aviso()
        self.assertEqual("success", self.pill.current_state)

    def test_tirar_o_mouse_durante_a_gravacao_nao_esconde(self):
        with patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.show_state("listening")
            self.pill._on_enter()
            self.pill._on_leave()
        self._esperar_o_aviso()
        self.withdraw.assert_not_called()

    def test_cronometro_nao_apaga_o_aviso(self):
        self.pill.show_state("listening", "", "meeting")
        self.pill.show_state("warning", "Selecione um texto antes de transformar")
        self.pill.update_status_text("🎙️ Gravando Reunião... 00:07", "#ff9f0a")
        self.assertEqual("Selecione um texto antes de transformar",
                         self.pill.canvas.itemcget(self.pill.text, "text"))

    def test_perfil_trocado_no_meio_da_gravacao_volta_para_ouvindo(self):
        self.pill.show_state("listening")
        self.pill.show_state("profile_changed", "Perfil: Executivo")
        self._esperar_o_aviso_longo()
        self.assertEqual("listening", self.pill.current_state)
        self.withdraw.assert_not_called()

    # Erro e sucesso que não encerram a gravação (Ctrl+Alt+Z sem ditado, "Ditado desfeito",
    # "Aguarde o processo atual") escondiam a pílula com a gravação em curso.

    def test_erro_por_cima_durante_a_gravacao_volta_para_ouvindo(self):
        self.pill.show_state("listening", "", "meeting")
        self.pill.show_state("error", "Nenhum ditado para desfazer", por_cima=True)
        self.assertEqual("Nenhum ditado para desfazer", self.pill.canvas.itemcget(self.pill.text, "text"))
        self._esperar_o_aviso()
        self.assertEqual("listening", self.pill.current_state)
        self.assertTrue(self._barras_visiveis())
        self.withdraw.assert_not_called()

    def test_sucesso_por_cima_durante_a_gravacao_volta_para_ouvindo(self):
        self.pill.show_state("listening")
        self.pill.show_state("success", "Ditado desfeito! ↩️", por_cima=True)
        self._esperar_o_aviso()
        self.assertEqual("listening", self.pill.current_state)
        self.withdraw.assert_not_called()

    def test_erro_por_cima_durante_o_processamento_volta_para_processando(self):
        self.pill.show_state("processing")
        self.pill.show_state("error", "Aguarde o processo atual...", por_cima=True)
        self._esperar_o_aviso()
        self.assertEqual("processing", self.pill.current_state)
        self.withdraw.assert_not_called()

    def test_erro_por_cima_sem_gravacao_esconde(self):
        self.pill.show_state("error", "Nenhum ditado para desfazer", por_cima=True)
        self._esperar_o_aviso()
        self.withdraw.assert_called()

    def test_fim_do_pipeline_continua_encerrando(self):
        for estado in ("success", "error"):
            with self.subTest(estado=estado):
                self.withdraw.reset_mock()
                self.pill.show_state("listening")
                self.pill.show_state("processing")
                self.pill.show_state(estado, "fim")
                self._esperar_o_aviso()
                self.assertEqual(estado, self.pill.current_state)
                self.withdraw.assert_called()

    def test_erro_sem_por_cima_no_meio_da_gravacao_ainda_encerra(self):
        # Sem por_cima, o erro encerra como sempre: quem o manda sabe que a gravação acabou.
        self.pill.show_state("listening")
        self.pill.show_state("error", "Microfone indisponível")
        self._esperar_o_aviso()
        self.assertEqual("error", self.pill.current_state)
        self.withdraw.assert_called()

    def test_cronometro_nao_apaga_o_erro_por_cima(self):
        self.pill.show_state("listening", "", "meeting")
        self.pill.show_state("error", "Nenhum ditado para desfazer", por_cima=True)
        self.pill.update_status_text("🎙️ Gravando Reunião... 00:07", "#ff9f0a")
        self.assertEqual("Nenhum ditado para desfazer", self.pill.canvas.itemcget(self.pill.text, "text"))

    def test_depois_da_volta_o_cronometro_reescreve(self):
        self.pill.show_state("listening", "", "meeting")
        self.pill.show_state("error", "Nenhum ditado para desfazer", por_cima=True)
        self._esperar_o_aviso()
        self.pill.update_status_text("🎙️ Gravando Reunião... 00:08", "#ff9f0a")
        self.assertEqual("🎙️ Gravando Reunião... 00:08", self.pill.canvas.itemcget(self.pill.text, "text"))

    def _esperar_o_aviso_longo(self):
        with patch.object(pill_mod, "DURACAO_AVISO_MS", 20):
            fim = time.time() + 1.7  # profile_changed tem 1,4 s fixos
            while time.time() < fim:
                self.root.update()
                time.sleep(0.01)


class TestDitadoNovoVaiParaOMonitorDeQuemDita(_BasePilula):
    def test_com_a_pilula_ainda_visivel_de_um_estado_curto(self):
        # Achado do segundo verificador: sem reposicionar no "listening", um ditado novo
        # aberto durante os 0,9 s do "sucesso" anterior ficava no monitor antigo a gravação toda.
        self.pill.root.geometry("340x48+370+1790")
        self.pill.root.update_idletasks()
        with patch.object(pill_mod, "_user32", User32Falso()),              patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)),              patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.show_state("success", "ok")
            self.pill.show_state("listening")
        self.assertEqual((-1130, 1321), self._xy())

    def test_a_volta_de_um_aviso_nao_muda_de_monitor(self):
        self.pill.root.geometry("340x48+370+1790")
        self.pill.root.update_idletasks()
        with patch.object(pill_mod, "_user32", User32Falso()),              patch.object(self.pill.root, "winfo_pointerxy", return_value=(500, 900)),              patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill._persistente = ("listening", "", "transcribe", True)
            self.pill._voltar(self.pill._persistente)
        self.assertEqual((370, 1790), self._xy())


class TestLarguraNaoMudaDeMonitor(_BasePilula):
    def test_texto_longo_com_a_pilula_visivel_mantem_o_centro(self):
        # Achado do verificador: mudar a largura chamava reposicionar com a pílula visível,
        # que relia o monitor da janela em primeiro plano. Firefox na esquerda, pílula no
        # primário: ela pulava de monitor no meio do ditado.
        self.pill.root.geometry("340x48+370+1790")
        self.pill.root.update_idletasks()
        with patch.object(pill_mod, "_user32", User32Falso()), \
             patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.update_status_text("x" * 60)
        self.assertEqual(490, self.pill.width)
        self.assertEqual((370 + (340 - 490) // 2, 1790), self._xy())


@unittest.skipUnless(sys.platform == "win32", "mede a janela de verdade pelo Win32")
class TestPilulaNaTelaDeVerdade(unittest.TestCase):
    """Sem falsos: a pílula fica visível para o Windows e some e volta pelo ciclo de estados.

    O diagnóstico de 2026-10-22 dizia que, sem deiconify, o Tk ficava 'withdrawn' e não
    mapeava o canvas. Medido aqui: depois do ShowWindow o Tk passa a 'normal', o canvas é
    mapeado e o withdraw do timer esconde de novo.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        from ctypes import wintypes
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.u32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.u32.IsWindowVisible.restype = wintypes.BOOL
        self.u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u32.GetWindowLongW.restype = wintypes.LONG
        self.u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u32.GetWindowRect.restype = wintypes.BOOL
        self.pill = FloatingPill(self.root)

    def tearDown(self):
        self.pill.destroy()

    def _bombear(self, segundos):
        fim = time.time() + segundos
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)

    def _visivel_no_windows(self):
        return bool(self.u32.IsWindowVisible(self.pill._hwnd))

    def test_ciclo_ouvindo_processando_sucesso_oculta_e_volta(self):
        self.assertFalse(self._visivel_no_windows())

        self.pill.show_state("listening")
        self._bombear(0.2)
        self.assertTrue(self._visivel_no_windows())
        self.assertEqual("normal", self.pill.root.state())
        self.assertTrue(self.pill.canvas.winfo_ismapped())
        exstyle = self.u32.GetWindowLongW(self.pill._hwnd, -20)
        self.assertTrue(
            bool(exstyle & 0x08000000),
            "HWND da pílula precisa ter WS_EX_NOACTIVATE (0x08000000) aplicado no Win32 real",
        )

        fg = pill_mod._user32.GetForegroundWindow()
        if fg and fg != self.pill._hwnd:
            self.assertEqual(
                pill_mod._user32.MonitorFromWindow(fg, pill_mod.MONITOR_DEFAULTTONEAREST),
                pill_mod._user32.MonitorFromWindow(self.pill._hwnd, pill_mod.MONITOR_DEFAULTTONEAREST),
                "a pílula tem que aparecer no monitor da janela em primeiro plano",
            )

        self.pill.show_state("processing")
        self._bombear(0.1)
        self.assertTrue(self._visivel_no_windows())

        self.pill.show_state("success", "ok")
        self._bombear(1.2)  # timer de 900 ms
        self.assertFalse(self._visivel_no_windows())
        self.assertEqual("withdrawn", self.pill.root.state())

        self.pill.show_state("listening")
        self._bombear(0.2)
        self.assertTrue(self._visivel_no_windows(), "depois de ocultar pelo timer, tem que voltar")

    def test_apos_withdraw_reposicionar_e_setwindowpos_atualizam_hwnd_real(self):
        from ctypes import wintypes

        pos = ["topo"]
        self.pill._get_position = lambda: pos[0]
        self.pill.show_state("listening")
        self._bombear(0.1)

        rc_topo = wintypes.RECT()
        self.u32.GetWindowRect(self.pill._hwnd, ctypes.byref(rc_topo))

        # Oculta a pílula (como no fim de um ditado) e troca a posição para centro_inferior.
        self.pill.root.withdraw()
        self._bombear(0.05)

        pos[0] = "centro_inferior"
        self.pill.show_state("error", "Transcrito, mas não consegui copiar. O texto ficou no histórico")
        self._bombear(0.1)

        rc_baixo = wintypes.RECT()
        self.u32.GetWindowRect(self.pill._hwnd, ctypes.byref(rc_baixo))
        self.assertGreater(
            rc_baixo.top, rc_topo.top,
            "o ShowWindow não pode reverter a geometria do HWND para o topo após withdraw()",
        )
        self.assertGreater(
            rc_baixo.right - rc_baixo.left, 340,
            "a largura elástica também precisa chegar ao HWND real após withdraw()",
        )
        # HWND_TOPMOST (-1) precisa funcionar em 64 bits (sem ERROR_INVALID_WINDOW_HANDLE = 1400).
        ok = pill_mod._user32.SetWindowPos(self.pill._hwnd, -1, 0, 0, 0, 0, 0x0013)
        self.assertTrue(bool(ok), "SetWindowPos com HWND_TOPMOST (-1) deve retornar True em 64 bits")


if __name__ == "__main__":
    unittest.main()
