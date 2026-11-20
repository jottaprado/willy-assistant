"""
Aba Ajustes: o teste de microfone para quando a aba some, e o Salvar recusa atalho do sistema.

- O teste de microfone seguia com o microfone aberto depois de trocar de aba, esconder ou
  minimizar a janela.
- A aba Atalhos (o Keycap) recusava Ctrl+C e companhia; os campos de texto do Ajustes
  aceitavam, e o Willy registrava a combinação como atalho global do Windows inteiro.
"""

import gc
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import customtkinter as ctk

from tests.willy_isolado import destruir_tk
from ui.tabs import tab_settings
from ui.tabs.tab_settings import build_tab_settings


class _BaseTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.geometry("700x500+-6000+100")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _bombear(self, segundos=0.3):
        fim = time.time() + segundos
        while time.time() < fim:
            self.root.update()
            time.sleep(0.01)


class TestTesteDeMicrofoneParaQuandoAAbaSome(_BaseTk):
    def setUp(self):
        self.aba = build_tab_settings(self.root, callbacks={})
        self.aba.grid(row=0, column=0, sticky="nsew")
        self.addCleanup(self.aba.destroy)
        self.stream = MagicMock()
        self.abriu = threading.Event()

        def _negociar(*_args):
            self.abriu.set()
            return self.stream, 16000

        p = patch.object(tab_settings, "negociar_stream", side_effect=_negociar)
        p.start()
        self.addCleanup(p.stop)
        self._bombear()
        # O lixo dos testes anteriores é coletado aqui, na thread principal. Coletado na thread
        # do teste, o Font.__del__ do tkinter chama o Tcl de fora da thread principal e, sem
        # mainloop, cada um espera ~1 s: a thread passava do prazo (medido no CI do Bloco 6B).
        gc.collect()
        self.aba._iniciar_teste_microfone()
        self.assertTrue(self.abriu.wait(2), "o teste não abriu o microfone")
        self.addCleanup(self.aba._parar_teste_se_ativo)

    def _assert_fechou_o_microfone(self):
        self._bombear()
        self.assertFalse(self.aba._mic_testing)
        self.stream.close.assert_called_once_with()

    def test_trocar_de_aba(self):
        self.aba.grid_forget()  # o que o mudar_aba faz com a aba que sai
        self._assert_fechou_o_microfone()

    def test_esconder_a_janela(self):
        self.root.withdraw()
        self.addCleanup(self.root.deiconify)
        self._assert_fechou_o_microfone()

    def test_aba_na_tela_segue_testando(self):
        self._bombear()
        self.assertTrue(self.aba._mic_testing)
        self.stream.close.assert_not_called()


class TestSalvarRecusaAtalhoDoSistema(_BaseTk):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Uma aba para a classe: montar a de Ajustes leva segundos.
        cls.salvar, cls.autostart = MagicMock(), MagicMock()
        cls.aba = build_tab_settings(cls.root, callbacks={"on_save_settings": cls.salvar,
                                                          "on_toggle_autostart": cls.autostart})

    def setUp(self):
        self.salvar.reset_mock()
        self.autostart.reset_mock()
        self.aba.recarregar_atalhos({})  # todos os campos com o padrão

    def _digitar(self, entry, combo):
        entry.delete(0, "end")
        entry.insert(0, combo)

    def test_ctrl_c_no_ditado_nao_salva_nada(self):
        self._digitar(self.aba.entry_hk_voice, "ctrl+c")
        self.aba.salvar_configuracoes()
        self.salvar.assert_not_called()
        self.autostart.assert_not_called()
        aviso = self.aba.btn_salvar_config.cget("text")
        self.assertIn("Ditado Principal", aviso)
        self.assertIn("ctrl+c", aviso)

    def test_mesma_combinacao_em_outra_ordem_e_grafia(self):
        self._digitar(self.aba.entry_hk_captions, "Tab+Alt")
        self.aba.salvar_configuracoes()
        self.salvar.assert_not_called()
        self.assertIn("Teleprompter", self.aba.btn_salvar_config.cget("text"))

    def test_outros_nomes_que_o_registro_aceita(self):
        # O parse_hotkey lê "menu" como Alt e "windows"/"cmd" como Win.
        for combo in ("menu+f4", "windows+l", "cmd+d"):
            with self.subTest(combo):
                self.salvar.reset_mock()
                self._digitar(self.aba.entry_hk_voice, combo)
                self.aba.salvar_configuracoes()
                self.salvar.assert_not_called()

    def test_campo_que_nao_e_dos_cinco_primeiros_tambem(self):
        self._digitar(self.aba.entry_hk_undo, "ctrl+z")
        self.aba.salvar_configuracoes()
        self.salvar.assert_not_called()

    def test_atalho_valido_salva_com_os_atalhos(self):
        self._digitar(self.aba.entry_hk_voice, "ctrl+alt+v")
        self.aba.salvar_configuracoes()
        self.salvar.assert_called_once()
        dados = self.salvar.call_args.args[0]
        self.assertEqual("ctrl+alt+v", dados["VOICE_HOTKEY"])
        self.assertEqual(14, len([c for c in dados if c.endswith("_HOTKEY")]))  # com o Ctrl+Alt+N do espanhol

    def test_aviso_volta_ao_normal(self):
        timers = []
        self._digitar(self.aba.entry_hk_voice, "ctrl+c")
        with patch.object(self.aba, "_safe_after", side_effect=lambda ms, f: timers.append(f)):
            self.aba.salvar_configuracoes()
        timers[-1]()
        self.assertEqual("Salvar e Aplicar Ajustes", self.aba.btn_salvar_config.cget("text"))


if __name__ == "__main__":
    unittest.main()
