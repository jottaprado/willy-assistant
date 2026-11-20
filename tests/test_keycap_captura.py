"""
Captura de atalho no Keycap: Num Lock não vira Alt, uma captura por vez, e a captura não
mexe nos handlers de tecla dos outros widgets.

- No Tk do Windows, 0x8 no event.state é o Num Lock. Lido como Alt, punha "alt+" em todo
  atalho gravado com o Num Lock ligado (Ctrl+Espaço virava Ctrl+Alt+Espaço).
- Clicar num segundo Keycap com outro capturando deixava os dois gravando a mesma tecla.
- O <KeyPress> era ligado no toplevel e o unbind tirava junto os handlers de tecla de
  qualquer outro widget da janela.
"""

import time
import tkinter
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.components.keycap import Keycap

CTRL, NUMLOCK, ALT = 0x4, 0x8, 0x20000


class _BaseTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.geometry("300x200+-6000+100")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _keycap(self, master=None):
        mudou = MagicMock()
        k = Keycap(master or self.root, keys="ctrl+alt+p", on_change=mudou)
        self.addCleanup(k.destroy)
        return k, mudou

    def _bombear(self, segundos=0.2):
        fim = time.time() + segundos
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)


class TestModificadores(_BaseTk):
    def test_num_lock_ligado_nao_vira_alt(self):
        k, mudou = self._keycap()
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="space", state=CTRL | NUMLOCK))
        mudou.assert_called_once_with("ctrl+space")

    def test_alt_de_verdade_continua_valendo(self):
        k, mudou = self._keycap()
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="space", state=CTRL | ALT | NUMLOCK))
        mudou.assert_called_once_with("ctrl+alt+space")


class TestTeclaQueORegistroConhece(_BaseTk):
    """O Keycap gravava o nome do Tk ("prior", "comma"), que o parse_hotkey recusa ao registrar."""

    def test_page_up_vira_o_nome_do_registro(self):
        k, mudou = self._keycap()
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="Prior", state=CTRL))
        mudou.assert_called_once_with("ctrl+pageup")

    def test_pontuacao_e_recusada_com_aviso(self):
        k, mudou = self._keycap()
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="semicolon", state=CTRL))
        mudou.assert_not_called()
        self.assertIn("não serve para atalho", k.lbl_conflito.cget("text"))
        self.assertEqual("ctrl+alt+p", k.get_hotkey(), "trocou a combinação que valia")

        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="comma", state=CTRL))
        mudou.assert_called_once_with("ctrl+,")


class TestCancelaQuandoPerdeOFoco(_BaseTk):
    def test_foco_em_outro_lugar_cancela(self):
        k, mudou = self._keycap()
        k.pack()
        self._bombear()
        k.iniciar_captura()
        k.event_generate("<FocusOut>")
        self.assertFalse(k.is_capturing)
        mudou.assert_not_called()


class TestUmaCapturaPorVez(_BaseTk):
    def test_segundo_keycap_cancela_o_primeiro(self):
        k1, _ = self._keycap()
        k2, _ = self._keycap()
        k1.iniciar_captura()
        k2.iniciar_captura()
        self.assertFalse(k1.is_capturing)
        self.assertTrue(k2.is_capturing)
        self.assertIs(k2, Keycap._captura_ativa)

    def test_captura_encerrada_libera_a_vez(self):
        k, _ = self._keycap()
        k.iniciar_captura()
        k.cancelar_captura()
        self.assertIsNone(Keycap._captura_ativa)

    def test_keycap_destruido_capturando_nao_trava_a_proxima_captura(self):
        # A aba de Atalhos refeita no meio de uma captura destrói o Keycap que capturava.
        k1 = Keycap(self.root, keys="ctrl+alt+p", on_change=MagicMock())
        k1.iniciar_captura()
        k1.destroy()
        self.assertIsNone(Keycap._captura_ativa, "o Keycap destruído ficou como dono da captura")
        k2, _ = self._keycap()
        k2.iniciar_captura()
        self.assertIs(k2, Keycap._captura_ativa)


class TestNaoMexeNosOutros(_BaseTk):
    def test_handler_de_tecla_da_janela_sobrevive_a_captura(self):
        alheio = self.root.bind("<KeyPress>", lambda e: None, add="+")
        self.addCleanup(lambda: self.root.unbind("<KeyPress>"))
        k, _ = self._keycap()
        k.iniciar_captura()
        k.cancelar_captura()
        k.iniciar_captura()
        k.finalizar_captura("ctrl+alt+k")
        self.assertIn(alheio, self.root.bind("<KeyPress>"), "a captura apagou o <KeyPress> de outro widget")


class TestCancelaQuandoSome(_BaseTk):
    def test_aba_escondida_cancela_a_captura(self):
        aba = tkinter.Frame(self.root)
        aba.pack()
        self.addCleanup(aba.destroy)
        k, mudou = self._keycap(aba)
        k.pack()
        self._bombear()
        k.iniciar_captura()
        aba.pack_forget()  # trocar de aba é um grid_forget/pack_forget do frame da aba
        self._bombear()
        self.assertFalse(k.is_capturing)
        mudou.assert_not_called()


if __name__ == "__main__":
    unittest.main()
