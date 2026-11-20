"""
Captura de atalho na aba Atalhos: o conflito é detectado, e a tecla de espaço sai "space".

A detecção comparava a combinação capturada com as CHAVES do dicionário de atalhos
("VOICE_HOTKEY"), e nunca achava conflito; com ele, salvava assim mesmo. Com a mesma
combinação em dois atalhos, o orquestrador a dá ao primeiro na ordem dele: escolher
Ctrl+Espaço para o prompt tirava o atalho do ditado. E a captura escrevia "ctrl+espaço",
diferente do "ctrl+space" dos padrões e do .env, que o orquestrador compara como texto.
"""

import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import customtkinter as ctk

import core.config as config_mod
import core.hotkey as hotkey_mod
import ui.components.keycap as keycap_mod
from core.hotkey import WM_HOTKEY, Win32HotKeyManager, user32
from core.system.hotkey_orchestrator import HotkeyOrchestrator
from core.text_processing import TextProcessor
from tests.test_recarregar_atalhos import ConfigFalsa, GerenciadorFalso
from tests.willy_isolado import destruir_tk
from ui.components.keycap import Keycap, teclas_da_combinacao
from ui.tabs.tab_settings import build_tab_settings
from ui.tabs.tab_shortcuts import build_tab_shortcuts

CTRL = 0x4


class _BaseTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)


class TestComparacao(unittest.TestCase):
    def test_ordem_caixa_e_nome_do_espaco_nao_importam(self):
        self.assertEqual(teclas_da_combinacao("ctrl+alt+space"), teclas_da_combinacao("Alt+Ctrl+Espaço"))
        self.assertEqual(teclas_da_combinacao("ctrl+shift+enter"), teclas_da_combinacao("shift+ctrl+return"))

    def test_combinacoes_diferentes(self):
        self.assertNotEqual(teclas_da_combinacao("ctrl+space"), teclas_da_combinacao("ctrl+shift+space"))

    def test_fonte_unica_de_normalizacao_entre_modulos(self):
        # AUD-056: keycap.py e config.py delegam para core.hotkey
        self.assertIs(keycap_mod.teclas_da_combinacao, hotkey_mod.teclas_da_combinacao)
        self.assertIs(keycap_mod.tecla_registravel, hotkey_mod.tecla_registravel)
        self.assertIs(config_mod.tecla_do_atalho, hotkey_mod.tecla_do_atalho)


class TestKeycap(_BaseTk):
    def _keycap(self, atual="ctrl+alt+p", chave="PROMPT_HOTKEY"):
        self.mudou = MagicMock()
        atalhos = {"VOICE_HOTKEY": "ctrl+space", "PROMPT_HOTKEY": "ctrl+alt+p", "UNDO_HOTKEY": "alt+ctrl+z"}
        k = Keycap(self.root, keys=atual, on_change=self.mudou, existing_hotkeys=atalhos,
                   chave_propria=chave, nomes_atalhos={"VOICE_HOTKEY": "Ditado Inteligente"})
        self.addCleanup(k.destroy)
        return k

    def _aviso(self, k):
        return k.lbl_conflito.cget("text") if k.lbl_conflito else None

    def test_combinacao_de_outro_atalho_nao_salva_e_avisa(self):
        k = self._keycap()
        k.finalizar_captura("ctrl+space")
        self.mudou.assert_not_called()
        self.assertEqual("ctrl+alt+p", k.get_hotkey(), "o Keycap tem que voltar para a combinação de antes")
        self.assertEqual("Conflito com atalho do Willy: Ditado Inteligente. "
                         "Escolha outra ou mude a de Ditado Inteligente antes", self._aviso(k))

    def test_outra_ordem_das_teclas_tambem_conflita(self):
        k = self._keycap()
        k.finalizar_captura("ctrl+alt+z")  # o .env tem "alt+ctrl+z", digitado nos Ajustes
        self.mudou.assert_not_called()
        self.assertIn("UNDO_HOTKEY", self._aviso(k))  # sem nome cadastrado, aparece o campo

    def test_a_propria_combinacao_nao_conflita(self):
        k = self._keycap()
        k.finalizar_captura("ctrl+alt+p")
        self.mudou.assert_called_once_with("ctrl+alt+p")
        self.assertIsNone(self._aviso(k))

    def test_combinacao_livre_salva_e_tira_o_aviso(self):
        k = self._keycap()
        k.finalizar_captura("ctrl+space")
        k.finalizar_captura("ctrl+alt+k")
        self.mudou.assert_called_once_with("ctrl+alt+k")
        self.assertEqual("ctrl+alt+k", k.get_hotkey())
        self.assertIsNone(self._aviso(k))

    def test_atalho_do_sistema_nao_salva(self):
        k = self._keycap()
        k.finalizar_captura("ctrl+c")
        self.mudou.assert_not_called()
        self.assertIn("Copiar do sistema", self._aviso(k))

    def test_aviso_some_quando_a_combinacao_muda_por_fora_ou_a_captura_e_cancelada(self):
        # Achado do juiz: o aviso ficava depois de "Restaurar Padrões" e do Esc.
        for desfecho in (lambda k: k.set_keys("ctrl+alt+m"), lambda k: k.cancelar_captura()):
            with self.subTest():
                k = self._keycap()
                k.finalizar_captura("ctrl+space")
                self.assertIsNotNone(self._aviso(k))
                desfecho(k)
                self.assertIsNone(self._aviso(k))

    def test_tecla_de_espaco_capturada_sai_space(self):
        k = self._keycap(atual="ctrl+alt+x", chave="TRANSLATE_HOTKEY")
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="space", state=CTRL | 0x20000))
        self.mudou.assert_called_once_with("ctrl+alt+space")

    def test_keycap_aceita_f13_sem_modificador_pontuacao_oem_e_bloqueia_ctrl_esc(self):
        # AUD-055: F13-F24 sem modificador, ',', '-', '.' com modificador e bloqueio de ctrl+esc / ctrl+shift+esc
        k = self._keycap()
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="F13", state=0))
        self.mudou.assert_called_once_with("f13")

        self.mudou.reset_mock()
        k.iniciar_captura()
        k._on_key_press(SimpleNamespace(keysym="comma", state=CTRL))
        self.mudou.assert_called_once_with("ctrl+,")

        self.mudou.reset_mock()
        k.finalizar_captura("ctrl+esc")
        self.mudou.assert_not_called()
        self.assertIn("sistema", (self._aviso(k) or "").lower())

        k.finalizar_captura("ctrl+shift+esc")
        self.mudou.assert_not_called()
        self.assertIn("sistema", (self._aviso(k) or "").lower())


def _keycaps(widget):
    achados = []
    for filho in widget.winfo_children():
        if isinstance(filho, Keycap):
            achados.append(filho)
        achados += _keycaps(filho)
    return achados


class TestAbaAtalhos(_BaseTk):
    def setUp(self):
        self.salvos = []
        self.aba = build_tab_shortcuts(self.root, callbacks={
            "get_settings": lambda: {"voice_hotkey": "ctrl+space", "speak_hotkey": "ctrl+alt+s"},
            "on_save_settings": self.salvos.append,
        })
        self.addCleanup(self.aba.destroy)
        self.voz = _keycaps(self.aba)[0]  # a primeira linha é o ditado

    def test_capturar_a_combinacao_da_traducao_no_ditado_avisa_pelo_nome(self):
        self.voz.finalizar_captura("ctrl+alt+space")
        self.assertEqual([], self.salvos)
        self.assertIn("Tradução Simultânea", self.voz.lbl_conflito.cget("text"))

    def test_atalho_sem_linha_na_aba_tambem_conta(self):
        self.voz.finalizar_captura("ctrl+alt+s")
        self.assertEqual([], self.salvos)
        self.assertIn("Leitura em Voz Alta", self.voz.lbl_conflito.cget("text"))

    def test_combinacao_livre_e_salva(self):
        self.voz.finalizar_captura("ctrl+alt+v")
        self.assertEqual([{"VOICE_HOTKEY": "ctrl+alt+v"}], self.salvos)

    def test_recapturar_a_propria_combinacao_nao_conflita(self):
        self.voz.finalizar_captura("ctrl+space")
        self.assertEqual([{"VOICE_HOTKEY": "ctrl+space"}], self.salvos)
        self.assertIsNone(self.voz.lbl_conflito)

    def test_shortcuts_tab_busca_sem_acento_falha_equivalente_e_comandos_de_voz_completos(self):
        # AUD-075: busca insensível a acento ("traducao", "reuniao")
        self.aba.filtrar("traducao")
        secoes_visiveis = [
            s["titulo"] for s in self.aba.secoes if s["frame"].winfo_manager()
        ]
        self.assertEqual(["DITADO"], secoes_visiveis)
        self.aba.filtrar("")

        # AUD-076: seção de comandos de voz inclui chaves e ponto com / ponto br
        sec_voz = next(s for s in self.aba.secoes if s["titulo"] == "COMANDOS DE VOZ PARA PONTUAÇÃO")
        textos_voz = " ".join(it["texto"] for it in sec_voz["itens"])
        self.assertIn("chaves", textos_voz)
        self.assertIn("ponto com", textos_voz)
        self.assertEqual(len(sec_voz["itens"]), len(TextProcessor.VOICE_COMMANDS))

        # AUD-075: _mostrar_falhas detecta dono mesmo com ordem diferente de modificadores ("alt+ctrl+space" == TRANSLATE_HOTKEY "ctrl+alt+space")
        aba_falha = build_tab_shortcuts(self.root, callbacks={
            "get_settings": lambda: {
                "translate_hotkey": "ctrl+alt+space",
                "prompt_hotkey": "alt+ctrl+space",
            },
            "get_hotkey_failures": lambda: {"PROMPT_HOTKEY": "alt+ctrl+space"},
        })
        self.addCleanup(aba_falha.destroy)
        aviso_prompt = aba_falha.avisos_de_falha["PROMPT_HOTKEY"].cget("text")
        self.assertIn("Tradução Simultânea", aviso_prompt)


class TestConsistenciaOrchestratorManagerAjustes(_BaseTk):
    def test_orchestrator_deduplica_combinacoes_equivalentes_em_ordem_diferente(self):
        # AUD-046: "ctrl+alt+p" e "alt+ctrl+p" têm a mesma tecla canônica; só o primeiro deve ir ao gerenciador
        mgr = GerenciadorFalso()
        cfg = ConfigFalsa(hotkey="ctrl+alt+p", master_hotkey="alt+ctrl+p")
        orq = HotkeyOrchestrator(mgr, cfg, {"voice": lambda: "voz", "master": lambda: "mestre"})
        falhas = orq.registrar_todos()
        self.assertEqual(len(mgr.pendentes), 1)
        self.assertEqual(falhas, ["ctrl+alt+p"])

    @unittest.skipUnless(sys.platform == "win32", "RegisterHotKey é do Windows")
    def test_win32_hotkey_manager_register_apos_start_registra_na_thread(self):
        # AUD-031: register() chamado com o manager já em execução registra na thread de mensagens
        disparou = threading.Event()
        mgr = Win32HotKeyManager()
        self.addCleanup(mgr.stop)
        mgr.start()
        hk_id = mgr.register("ctrl+alt+shift+f12", disparou.set)
        self.assertTrue(user32.PostThreadMessageW(mgr.thread_id, WM_HOTKEY, hk_id, 0))
        self.assertTrue(disparou.wait(timeout=1.5))

        # Prova não-tautológica: como WM_REGISTRAR_PERMANENTE foi processado antes do WM_HOTKEY
        # na fila da thread, RegisterHotKey foi realmente chamado no Windows e um segundo
        # gerenciador tentando registrar a mesma combinação recebe falha do SO.
        segundo = Win32HotKeyManager()
        self.addCleanup(segundo.stop)
        segundo.register("ctrl+alt+shift+f12", lambda: None)
        segundo.start()
        self.assertEqual(segundo.falhas, ["ctrl+alt+shift+f12"])

    def test_settings_tab_recusa_atalho_duplicado_e_invalido(self):
        # AUD-073: SettingsTab bloqueia atalhos duplicados entre ações do Willy e strings inválidas
        salvar = MagicMock()
        aba = build_tab_settings(self.root, callbacks={"on_save_settings": salvar})
        self.addCleanup(aba.destroy)

        # 1. Duplicado (mesma tecla em ordem diferente de modificadores)
        aba.recarregar_atalhos({})
        aba.entry_hk_prompt.delete(0, "end")
        aba.entry_hk_prompt.insert(0, "space+ctrl")  # igual a VOICE_HOTKEY ("ctrl+space")
        aba.salvar_configuracoes()
        salvar.assert_not_called()
        self.assertIn("Não salvei", aba.btn_salvar_config.cget("text"))

        # 2. String inválida / sem modificador
        aba.recarregar_atalhos({})
        aba.entry_hk_voice.delete(0, "end")
        aba.entry_hk_voice.insert(0, "tecla_inexistente")
        aba.salvar_configuracoes()
        salvar.assert_not_called()
        self.assertIn("Não salvei", aba.btn_salvar_config.cget("text"))


if __name__ == "__main__":
    unittest.main()
