"""
O dashboard ocupa a largura toda em qualquer tamanho de janela, inclusive em tela cheia.

Medido em 2026-10-22 com o dashboard maximizado num monitor de 1920: a coluna do conteúdo
era travada em 880 px a partir de 1184 de janela e um espaçador vazio levava o resto. Cada
aba terminava 800 px antes da borda, com a barra de rolagem no meio da tela, e o texto dos
cards quebrava em 640 px fixos.

A geometria aqui é medida de verdade: o Tk só calcula o layout de janela mapeada, então a
janela abre FORA de qualquer monitor (x=-8000) e o foco volta para quem estava na frente.
Tudo roda em 100% e em 125% de escala: margem e barra lateral são unidades do CTk, a tela é
pixel, e a primeira versão misturava os dois (só batia em 100%).
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
import unittest

import customtkinter as ctk
from customtkinter.windows.widgets.scaling import ScalingTracker

from tests.config_isolada import isolar_config
from ui.dashboard import WillyDashboard
from ui.theme import margem_conteudo

TEXTO_LONGO = (
    "Refatore o módulo de áudio para negociar a taxa do dispositivo, reamostrar para 16 kHz "
    "antes de mandar para a Groq e documentar no README por que a taxa nativa estourava o "
    "limite de 25 MB em reuniões longas, com um teste que prove o limite."
)
ABAS = ("onboarding", "history", "snippets", "shortcuts", "vocab", "diagnostics", "settings")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# As classes de geometria real só rodam no processo próprio que o
# TestGeometriaEmProcessoProprio abre (ver o motivo lá).
EM_PROCESSO_PROPRIO = os.environ.get("WILLY_GEOMETRIA_EM_PROCESSO_PROPRIO") == "1"


class TestMargemConteudo(unittest.TestCase):
    def test_janela_padrao_fica_com_a_margem_de_sempre(self):
        self.assertEqual(32, margem_conteudo(940 - 240))

    def test_cresce_com_a_largura_ate_o_teto(self):
        self.assertEqual(32, margem_conteudo(960))
        self.assertEqual(76, margem_conteudo(1400))
        self.assertEqual(96, margem_conteudo(1920 - 240))
        self.assertEqual(96, margem_conteudo(3840 - 240))


def _labels_longos(widget, achados):
    for filho in widget.winfo_children():
        if isinstance(filho, ctk.CTkLabel) and len(str(filho.cget("text"))) > 120:
            achados.append(filho)
        _labels_longos(filho, achados)
    return achados


def _labels_com_quebra(widget, achados):
    for filho in widget.winfo_children():
        if isinstance(filho, ctk.CTkLabel) and filho.cget("wraplength"):
            achados.append(filho)
        _labels_com_quebra(filho, achados)
    return achados


@unittest.skipUnless(sys.platform == "win32" and EM_PROCESSO_PROPRIO,
                     "roda em processo próprio, pelo TestGeometriaEmProcessoProprio")
class TestDashboardEmTelaCheia(unittest.TestCase):
    ESCALA = 1.0
    # Janela de 1920 px de largura, em unidades do CTk (o geometry() do CTk aplica a escala).
    LARGURA, ALTURA = 1920, 1040

    @classmethod
    def setUpClass(cls):
        isolar_config(cls)
        cls._escala_antes = (ScalingTracker.widget_scaling, ScalingTracker.window_scaling)
        # Só muda a escala se precisa: o set_*_scaling do CTk redesenha todas as janelas
        # registradas no processo, inclusive as que outros testes deixaram para trás.
        if cls._escala_antes != (cls.ESCALA, cls.ESCALA):
            ctk.set_widget_scaling(cls.ESCALA)
            ctk.set_window_scaling(cls.ESCALA)
        cls.MARGEM_PX = round(margem_conteudo(cls.LARGURA - 240) * cls.ESCALA)
        u32 = ctypes.WinDLL("user32")
        u32.GetForegroundWindow.restype = wt.HWND
        u32.SetForegroundWindow.argtypes = [wt.HWND]
        historico = [
            {"text": TEXTO_LONGO, "mode": "transcribe", "timestamp": "22/10/2026 10:00", "words": 40}
            for _ in range(3)
        ]
        snippets = [{"trigger": "assinatura", "title": "Assinatura", "content": TEXTO_LONGO}]
        quem_estava_na_frente = u32.GetForegroundWindow()
        cls.dash = WillyDashboard(callbacks={
            "get_history": lambda: historico,
            "get_snippets": lambda: snippets,
            "get_app_rules": list,
        })
        # Sem isto o Windows limita a janela ao tamanho da tela virtual: no runner do CI
        # (tela pequena) a janela de 1920 px encolhia e as margens saíam as de uma janela
        # estreita. O Tk repassa o wm maxsize ao WM_GETMINMAXINFO e o limite some.
        cls.dash.maxsize(20000, 20000)
        cls.dash.geometry(f"{cls.LARGURA}x{cls.ALTURA}+-8000+100")
        cls.dash.update()
        if quem_estava_na_frente and u32.GetForegroundWindow() != quem_estava_na_frente:
            u32.SetForegroundWindow(quem_estava_na_frente)

    @classmethod
    def tearDownClass(cls):
        cls.dash.destroy()
        if cls._escala_antes != (cls.ESCALA, cls.ESCALA):
            ctk.set_widget_scaling(cls._escala_antes[0])
            ctk.set_window_scaling(cls._escala_antes[1])

    def setUp(self):
        self._redimensionar(self.LARGURA, self.ALTURA)

    def _redimensionar(self, largura, altura):
        self.dash.geometry(f"{largura}x{altura}+-8000+100")
        self._bombear(0.3)
        pedida = round(largura * self.ESCALA)
        self.assertAlmostEqual(pedida, self.dash.winfo_width(), delta=2,
                               msg="a janela não ficou com a largura pedida (limite da tela?)")

    def _bombear(self, segundos):
        fim = time.time() + segundos
        while time.time() < fim:
            self.dash.update()
            time.sleep(0.01)

    def _borda_direita(self, w):
        return w.winfo_rootx() + w.winfo_width()

    def _mostrar(self, aba):
        self.dash.mudar_aba(aba)
        self._bombear(0.3)
        f = self.dash.frames_abas[aba]
        externo = getattr(f, "_parent_frame", f)
        rolavel = f.scroll_historico if aba == "history" else f
        return externo, rolavel

    def test_main_container_tem_uma_coluna_que_cresce(self):
        coluna = self.dash.main_container.grid_columnconfigure(0)
        self.assertEqual(1, int(coluna["weight"]))
        self.assertEqual(0, int(coluna["minsize"]))
        self.assertEqual([], self.dash.main_container.grid_slaves(column=1), "nada de espaçador")

    def test_cada_aba_vai_da_margem_ate_a_borda_com_a_barra_na_borda(self):
        borda_janela = self._borda_direita(self.dash.main_container)
        for aba in ABAS:
            with self.subTest(aba=aba):
                externo, rolavel = self._mostrar(aba)
                self.assertAlmostEqual(self.MARGEM_PX, externo.winfo_rootx() - self.dash.main_container.winfo_rootx(),
                                       delta=1)
                self.assertEqual(borda_janela, self._borda_direita(externo))
                self.assertEqual(borda_janela, self._borda_direita(rolavel._scrollbar))
                # O conteúdo termina a uma margem da borda, sem encostar na barra.
                folga = borda_janela - self._borda_direita(rolavel._parent_canvas)
                self.assertAlmostEqual(self.MARGEM_PX, folga, delta=2)

    def test_cabecalho_do_historico_alinha_com_a_lista(self):
        _, rolavel = self._mostrar("history")
        aba = self.dash.frames_abas["history"]
        for bloco in (aba.page_header, aba.search_field, aba.stats_box):
            with self.subTest(bloco=type(bloco).__name__):
                self.assertAlmostEqual(self._borda_direita(rolavel._parent_canvas),
                                       self._borda_direita(bloco), delta=2)

    def test_texto_dos_cards_quebra_na_largura_e_nao_em_640(self):
        for aba in ("history", "snippets"):
            with self.subTest(aba=aba):
                _, rolavel = self._mostrar(aba)
                (label, *_) = _labels_longos(rolavel, [])
                largura_px = label.master.winfo_width()
                self.assertGreater(largura_px, 1000)
                self.assertAlmostEqual(largura_px, label._apply_widget_scaling(label.cget("wraplength")), delta=2)

    def test_descricao_dos_atalhos_ocupa_a_linha(self):
        # As descrições dos atalhos são curtas: acha pelo wraplength ligado, não pelo tamanho.
        _, rolavel = self._mostrar("shortcuts")
        descricoes = _labels_com_quebra(rolavel, [])
        self.assertTrue(descricoes, "a aba de atalhos deveria ter descrições com quebra de linha")
        for label in descricoes:
            self.assertGreater(label._apply_widget_scaling(label.cget("wraplength")), 1000)

    def test_voltar_ao_tamanho_padrao_volta_a_margem_minima(self):
        self._redimensionar(940, 670)
        externo, rolavel = self._mostrar("history")
        self.assertAlmostEqual(round(32 * self.ESCALA), externo.winfo_rootx() - self.dash.main_container.winfo_rootx(),
                               delta=1)
        self.assertEqual(self._borda_direita(self.dash.main_container), self._borda_direita(rolavel._scrollbar))
        (label, *_) = _labels_longos(rolavel, [])
        self.assertAlmostEqual(label.master.winfo_width(), label._apply_widget_scaling(label.cget("wraplength")),
                               delta=2)



class TestDashboardEmTelaCheiaA125(TestDashboardEmTelaCheia):
    """Windows em 125%: 1536 unidades = 1920 px, margem de 65 unidades = 81 px."""

    ESCALA = 1.25
    LARGURA, ALTURA = 1536, 832



@unittest.skipUnless(sys.platform == "win32", "mede a janela de verdade pelo Win32")
class TestGeometriaEmProcessoProprio(unittest.TestCase):
    """Roda as duas classes de geometria real num processo novo, com prazo.

    No mesmo processo da suíte, a classe de 125% travou e derrubou o Python (falha de
    segmentação) em parte das rodadas completas, sempre neste arquivo e nunca rodando
    ele sozinho. O set_widget_scaling do CTk percorre todas as janelas registradas no
    ScalingTracker, e os testes de Tk anteriores deixam lá janelas de interpretadores já
    destruídos (destruir o root não passa pelo destroy() dos widgets CTk). Num processo
    novo não há nada disso, e o prazo transforma qualquer travamento em falha com mensagem
    em vez de CI pendurado.
    """

    def test_geometria_real_em_100_e_125_porcento(self):
        env = dict(os.environ, WILLY_GEOMETRIA_EM_PROCESSO_PROPRIO="1")
        modulo = "tests.test_dashboard_responsivo"
        try:
            r = subprocess.run(
                [sys.executable, "-m", "unittest", "-v",
                 f"{modulo}.TestDashboardEmTelaCheia", f"{modulo}.TestDashboardEmTelaCheiaA125"],
                cwd=RAIZ, env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300, check=False,
            )
        except subprocess.TimeoutExpired as e:
            self.fail(f"a geometria real passou de 300 s: {str(e.stderr or '')[-3000:]}")
        self.assertEqual(0, r.returncode, r.stderr[-4000:])
        # As 12 verificações rodaram de fato: sem a variável de ambiente elas seriam puladas
        # e o processo sairia com 0 do mesmo jeito.
        self.assertIn("Ran 12 tests", r.stderr)
        self.assertNotIn("skipped=", r.stderr.strip().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
