"""
"Reusar" no Histórico cola no app em que a pessoa estava.

O botão prometia "Copiar e colar no app anterior" e só copiava, igual ao "Copiar" ao lado.
Agora o Willy guarda a última janela de fora dele, devolve o foco a ela, esconde o painel e
cola; sem essa janela, copia e diz para colar à mão.
"""

import ast
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.actions import ActionManager
from core.context import ContextManager
from tests.willy_isolado import _funcoes_do_willy, destruir_tk
from ui.tabs.tab_history import HistoryTab

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP, WILLY, BARRA, CAMPO = 0x1A, 0x2B, 0x3C, 0x4D


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def monotonic(self):
        return self.agora

    def sleep(self, s):
        self.agora += s


class ContextoFalso:
    """Primeiro plano controlado pelo teste; focus_window o passa para a janela pedida."""

    def __init__(self, primeiro_plano=APP, foco_chega=True, foco_aceito=True):
        self.primeiro_plano, self.foco_chega, self.foco_aceito = primeiro_plano, foco_chega, foco_aceito
        self.eventos = []

    def get_foreground_hwnd(self):
        return self.primeiro_plano

    def eh_janela_do_willy(self, hwnd):
        return hwnd == WILLY

    def eh_janela_do_shell(self, hwnd):
        return hwnd == BARRA

    def foco_do_teclado(self, hwnd):
        return CAMPO if hwnd == APP else 0

    def focus_window(self, hwnd, hwnd_focus=None):
        self.eventos.append(("foco", hwnd) if hwnd_focus is None else ("foco", hwnd, hwnd_focus))
        if self.foco_aceito and self.foco_chega:
            self.primeiro_plano = hwnd
        return self.foco_aceito


class TestReusar(unittest.TestCase):
    def _willy(self, contexto, colou=True, janela_antes=APP):
        self.contexto, self.ui, self.som = contexto, MagicMock(), MagicMock()
        self.colar = MagicMock(return_value=colou)
        self.dashboard = MagicMock()
        self.dashboard.esconder.side_effect = lambda: contexto.eventos.append(("esconder",))
        self.copiar = MagicMock(return_value=True)
        threading = SimpleNamespace(Thread=lambda target, daemon: SimpleNamespace(start=target))
        escopo = _funcoes_do_willy(
            "lembrar_janela_fora_do_willy", "reusar_no_app_anterior",
            ContextManager=contexto, dashboard=self.dashboard, atualizar_ui=self.ui, sound_mgr=self.som,
            default_injector=SimpleNamespace(paste_text=self.colar), time=Relogio(), threading=threading,
            ActionManager=SimpleNamespace(secure_copy=self.copiar),
            _janela_antes_do_willy=janela_antes, _foco_antes_do_willy=0, last_injected_text=None)
        self.escopo = escopo
        return escopo

    def test_cola_no_app_de_antes(self):
        w = self._willy(ContextoFalso(primeiro_plano=WILLY))
        self.assertTrue(w["reusar_no_app_anterior"]("um prompt"))
        self.colar.assert_called_once_with("um prompt", auto_send=False)
        self.ui.assert_called_once_with("success", "Colado no app anterior")
        self.assertEqual("um prompt", w["last_injected_text"], "Ctrl+Alt+Z tem que desfazer")

    def test_o_foco_volta_antes_de_esconder_o_painel(self):
        # Só o processo em primeiro plano passa o foco: depois de esconder, o Willy já não é.
        self._willy(ContextoFalso(primeiro_plano=WILLY))["reusar_no_app_anterior"]("x")
        self.assertEqual([("foco", APP), ("esconder",)], self.contexto.eventos)

    def test_sem_app_de_antes_nao_esconde_nem_cola(self):
        w = self._willy(ContextoFalso(primeiro_plano=WILLY), janela_antes=0)
        self.assertFalse(w["reusar_no_app_anterior"]("x"))
        self.dashboard.esconder.assert_not_called()
        self.colar.assert_not_called()

    def test_app_fechado_nao_esconde_nem_cola(self):
        w = self._willy(ContextoFalso(primeiro_plano=WILLY, foco_aceito=False))
        self.assertFalse(w["reusar_no_app_anterior"]("x"))
        self.dashboard.esconder.assert_not_called()

    def test_foco_que_nao_chega_copia_em_vez_de_colar_em_outra_janela(self):
        w = self._willy(ContextoFalso(primeiro_plano=WILLY, foco_chega=False))
        self.assertTrue(w["reusar_no_app_anterior"]("um prompt"))
        self.colar.assert_not_called()
        self.copiar.assert_called_once_with("um prompt")
        self.ui.assert_called_once_with("error", "Não voltei ao app: texto copiado")
        self.assertIsNone(w["last_injected_text"], "Cópia por falta de foco não pode armar Ctrl+Alt+Z")

    def test_colar_que_falha_avisa(self):
        w = self._willy(ContextoFalso(primeiro_plano=WILLY), colou=False)
        w["reusar_no_app_anterior"]("x")
        self.ui.assert_called_once_with("error", "Não consegui colar. Tente de novo")
        self.assertIsNone(w["last_injected_text"])

    def test_lembra_so_janelas_de_fora_do_willy_e_do_windows(self):
        contexto = ContextoFalso(primeiro_plano=APP)
        w = self._willy(contexto, janela_antes=0)
        w["lembrar_janela_fora_do_willy"]()
        self.assertEqual(APP, w["_janela_antes_do_willy"])
        self.assertEqual(CAMPO, w["_foco_antes_do_willy"], "o controle em que a pessoa digitava")
        for janela in (WILLY, BARRA, 0):
            contexto.primeiro_plano = janela
            w["lembrar_janela_fora_do_willy"]()
            self.assertEqual(APP, w["_janela_antes_do_willy"], f"trocou para {janela:#x}")


class TestLigacoesNoWilly(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            self.arvore = ast.parse(f.read())

    def test_a_aba_recebe_o_reusar(self):
        valores = [v for n in ast.walk(self.arvore) if isinstance(n, ast.Dict)
                   for k, v in zip(n.keys, n.values)
                   if isinstance(k, ast.Constant) and k.value == "on_reuse_text"]
        self.assertEqual(["reusar_no_app_anterior"], [getattr(v, "id", None) for v in valores])

    def test_o_laco_do_main_lembra_a_janela(self):
        (laco,) = [n for n in ast.walk(self.arvore) if isinstance(n, ast.FunctionDef) and n.name == "verificar_solicitacao"]
        chamadas = {getattr(n.func, "id", None) for n in ast.walk(laco) if isinstance(n, ast.Call)}
        self.assertIn("lembrar_janela_fora_do_willy", chamadas)


class TestBotaoDoHistorico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        cls.root = ctk.CTk()
        cls.root.withdraw()
        cls.aba = HistoryTab(cls.root, callbacks={}, history_items=[])

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.aba, cls.root)

    def _aba(self, reusar=None):
        self.aba.callbacks = {} if reusar is None else {"on_reuse_text": reusar}
        return self.aba

    def test_com_app_de_antes_nao_copia_nem_mostra_toast(self):
        import customtkinter as ctk
        aba = self._aba(MagicMock(return_value=True))
        btn = ctk.CTkButton(aba, text="")
        self.addCleanup(btn.destroy)
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar, \
                patch.object(aba, "_mostrar_toast") as toast:
            aba._reusar_com_feedback("um prompt", btn)
        aba.callbacks["on_reuse_text"].assert_called_once_with("um prompt")
        copiar.assert_not_called()
        toast.assert_not_called()

    def test_sem_app_de_antes_copia_diz_para_colar_e_nao_quebra_se_botao_destruido(self):
        import customtkinter as ctk
        aba = self._aba(MagicMock(return_value=False))
        btn = ctk.CTkButton(aba, text="")
        agendados = []
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar, \
                patch.object(aba, "_mostrar_toast") as toast, \
                patch.object(aba, "_safe_after", side_effect=lambda ms, fn, *a: agendados.append((ms, fn, a))):
            aba._reusar_com_feedback("um prompt", btn)
        # Sem os Ajustes no teste, conta como modo privado: fora do Win+V.
        copiar.assert_called_once_with("um prompt", ocultar_do_historico=True)
        self.assertIn("Ctrl+V", toast.call_args.args[0])
        self.assertEqual(1, len(agendados))
        # Se o cartão for destruído antes de 1,5s (ex.: filtro ou recarga), o callback agendado
        # por _reusar_com_feedback não pode levantar TclError (usa _trocar_icone com guarda winfo_exists).
        btn.destroy()
        agendados[0][1](*agendados[0][2])


@unittest.skipUnless(sys.platform == "win32", "janelas do Win32")
class TestDetectoresDeJanela(unittest.TestCase):
    def test_a_barra_de_tarefas_e_do_shell(self):
        import ctypes
        barra = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if not barra:
            self.skipTest("sem barra de tarefas nesta sessão")
        self.assertTrue(ContextManager.eh_janela_do_shell(barra))
        self.assertFalse(ContextManager.eh_janela_do_willy(barra))

    def test_uma_janela_do_proprio_processo_e_do_willy(self):
        import ctypes
        import tkinter as tk
        root = tk.Tk()
        try:
            root.geometry("200x100+-4000+-4000")  # visível, fora da tela
            root.update()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            self.assertTrue(ContextManager.eh_janela_do_willy(hwnd))
            self.assertFalse(ContextManager.eh_janela_do_shell(hwnd), "uma janela comum visível é um app")
            root.withdraw()
            root.update()
            self.assertTrue(ContextManager.eh_janela_do_shell(hwnd), "janela escondida não é para onde colar")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
