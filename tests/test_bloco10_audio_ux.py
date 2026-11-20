"""
Bloco 10, fase 2: o Esc no segurar-para-falar e a aba Atalhos com os 13 atalhos, e as guardas do
corte por silêncio.

- O "tá" dito logo ao apertar, seguido de silêncio, continua cancelado aos 7 s, e o fim do ditado
  com ruído que oscila devagar continua chegando até 16,6 s depois: as versões do Bloco 10 que
  mudavam isso cortavam fala ou mandavam ruído que a main não corta nem manda (juiz do Bloco 10,
  quatro rodadas). As guardas desses cenários ficam aqui, para a próxima tentativa.
- Segurando o atalho, o Esc chega ao Windows como Ctrl+Esc, que o Esc temporário não pega, e soltar
  o atalho enviava o ditado que a pessoa queria cancelar.
- A aba Atalhos listava 10 dos 13. O Ctrl+Alt+L das legendas, recusado pelo Windows em todas as
  partidas do dono, dava o aviso a cada abertura, e a aba nem tinha a linha para trocá-lo.

Nenhum teste aqui aperta tecla de verdade: o teclado do monitorar_hold é um user32 falso, e os
atalhos vão a um gerenciador falso.
"""

import ast
import math
import os
import random
import unittest
from types import SimpleNamespace
from typing import ClassVar, Optional
from unittest.mock import MagicMock

import customtkinter as ctk
from dotenv import dotenv_values

from core.config import ConfigManager
from core.hotkey import Win32HotKeyManager
from core.system.hotkey_orchestrator import ATALHOS, HOTKEY_FIELDS, HotkeyOrchestrator
from tests.config_isolada import isolar_config
from tests.test_bloco9_audio_transcricao_ux import (
    SOLTAR_OS_ESC,
    _CenaContinua,
)
from tests.test_recarregar_atalhos import GerenciadorFalso
from tests.test_silencio_na_c920 import MICROFONES, SIGMA_C920, _Cena, _Gravacao
from tests.test_ux_pasta_hold_ctrl_k import PASSOS_DA_ESPERA
from tests.willy_isolado import _constante_do_willy, _funcao_do_willy, _keycaps, _todos
from ui.tabs.tab_shortcuts import build_tab_shortcuts

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUIDO_C920, FALA_C920 = MICROFONES["c920"]


def _ruido_que_oscila(dt, tau, mediana=0.032, sigma=SIGMA_C920, sigma_quadro=0.06):
    """O ruído que oscila devagar: o nível segue um AR(1) no log com constante de tempo `tau` (um
    ar-condicionado, o trânsito), com a distribuição da C920, mais a variação de um quadro (~6% em
    10 ms). Uma chamada por quadro de `dt`, como o _Cena.quadros faz."""
    estado = {"x": None}
    phi = math.exp(-dt / tau)
    variacao = sigma_quadro * math.sqrt(0.01 / dt)

    def ruido(rng):
        if estado["x"] is None:
            estado["x"] = rng.gauss(0, sigma)
        else:
            estado["x"] = phi * estado["x"] + math.sqrt(1 - phi * phi) * rng.gauss(0, sigma)
        return mediana * math.exp(estado["x"] + rng.gauss(0, variacao))
    return ruido


# ---------------------------------------------------------------------------------------------
# O começo da gravação: o clique de soltar a tecla e o eco do bipe não são fala
# ---------------------------------------------------------------------------------------------
class TestComecoDaGravacao(unittest.TestCase):
    """Juiz do Bloco 10, 4ª rodada: com o começo ignorado do pico em 80 ms (para a palavra curta dita
    logo ao apertar), o clique de soltar a tecla num toque rápido (0,10 a 0,30 s) e o eco do bipe numa
    sala quieta contavam como fala. A gravação parava aos ~2,9 s e mandava ruído à Groq, ou parava
    antes de a pessoa começar a falar, aos 3,5 s. O começo ignorado voltou aos 0,4 s."""

    @staticmethod
    def _toque(cena, eco=False):
        cena.inicio_do_willy()  # o clique de apertar e o bipe
        if eco:
            # O bipe ecoando na sala: a cauda dele, mais baixa, por ~250 ms.
            cena.som(0.17, 0.25, lambda rng: rng.uniform(0.04, 0.12))
        else:
            # O clique de soltar a tecla num toque rápido.
            cena.som(cena.rng.uniform(0.10, 0.30), cena.rng.uniform(0.03, 0.05), lambda rng: rng.uniform(0.15, 0.4))

    def test_sem_fala_cancela(self):
        for microfone in ("c920", "quieto"):
            for eco in (False, True):
                for semente in range(20):
                    with self.subTest(microfone=microfone, eco=eco, semente=semente):
                        ruido, fala = MICROFONES[microfone]
                        cena = _Cena(random.Random(f"bloco10-toque-{microfone}-{eco}-{semente}"), ruido, fala)
                        self._toque(cena, eco)
                        disparou, _ = _Gravacao(0.02).rodar(cena, total_s=9.0)
                        self.assertIsNotNone(disparou)
                        self.assertEqual("cancelou", disparou[0])

    def test_fala_que_comeca_aos_3_5_s_nao_se_perde(self):
        for microfone in ("c920", "quieto"):
            for eco in (False, True):
                for semente in range(20):
                    with self.subTest(microfone=microfone, eco=eco, semente=semente):
                        ruido, fala = MICROFONES[microfone]
                        cena = _Cena(random.Random(f"bloco10-toque-tarde-{microfone}-{eco}-{semente}"), ruido, fala)
                        self._toque(cena, eco)
                        cena.falar(3.5, 2.0)
                        disparou, ultima = _Gravacao(0.02).rodar(cena, total_s=12.0)
                        self.assertIsNotNone(disparou)
                        self.assertEqual("parou", disparou[0])
                        self.assertGreaterEqual(disparou[1], ultima, "parou antes da fala")


# ---------------------------------------------------------------------------------------------
# Ruído que oscila devagar: nenhuma fala perdida
# ---------------------------------------------------------------------------------------------
class TestNenhumaFalaPerdidaComRuidoQueOscila(unittest.TestCase):
    """Os cenários em que as versões que contavam o ruído liso como silêncio cortavam fala (juiz do
    Bloco 10): pelo callback_audio de verdade, nenhum corte que a main não tenha. A regra foi tirada,
    e estas guardas ficam para a próxima tentativa."""

    def test_fala_baixa_depois_de_uma_pausa_nao_e_cortada(self):
        # Juiz do Bloco 10, pelo callback de verdade: fala a 0,08, 1,5 s de pausa e mais fala, sobre o
        # ruído AR de 1 s. Com a regra da 1ª versão, 11 destas 40 eram cortadas no meio da 2ª
        # frase; na main, nenhuma.
        for semente in range(40):
            with self.subTest(semente=semente):
                cena = _Cena(random.Random(f"bloco10-pausa-1.0-0.08-1.5-{semente}"), _ruido_que_oscila(0.02, 1.0), 0.08)
                cena.inicio_do_willy()
                cena.falar(cena.falar(0.4, 4.0) + 1.5, 3.0)
                disparou, ultima = _Gravacao(0.02).rodar(cena, total_s=30.0)
                self.assertIsNotNone(disparou)
                self.assertEqual("parou", disparou[0])
                self.assertGreaterEqual(disparou[1], ultima, "cortou a fala depois da pausa")

    def test_hesitacao_lisa_depois_de_uma_pausa_nao_e_cortada(self):
        # Juiz do Bloco 10, 2ª rodada: 1 s de pausa e um "ééé" de 2,5 s, liso, entre os limiares, e a
        # frase seguinte. Com a regra da 2ª versão, 25 destas 40 eram cortadas. Na main, 8: o "ééé"
        # abaixo do limiar de silêncio, que soma com a pausa. Elas ficam de fora.
        da_main = {2, 6, 8, 9, 21, 23, 28, 33}
        for semente in sorted(set(range(40)) - da_main):
            with self.subTest(semente=semente):
                cena = _Cena(random.Random(f"bloco10-hesitacao-1.0-{semente}"), _ruido_que_oscila(0.02, 1.0), FALA_C920)
                cena.inicio_do_willy()
                fim = cena.falar(0.4, 3.0)
                cena.som(fim + 1.0, 2.5, lambda rng: 0.055 * math.exp(rng.gauss(0, 0.03)), fala=True)
                cena.falar(fim + 3.8, 2.0)
                disparou, ultima = _Gravacao(0.02).rodar(cena, total_s=30.0)
                self.assertIsNotNone(disparou)
                self.assertEqual("parou", disparou[0])
                self.assertGreaterEqual(disparou[1], ultima, "cortou na hesitação")

    def test_ventilador_que_liga_antes_da_fala_nao_encerra_a_gravacao(self):
        # Juiz do Bloco 10: o ventilador (ruído AR 2,5 x mais alto a partir de 1,5 s) é liso, e a
        # gravação terminava antes de a pessoa falar, aos 4 s: 1 destas 120 com a regra da 1ª versão;
        # na main, nenhuma.
        for semente in range(120):
            with self.subTest(semente=semente):
                cena = _Cena(random.Random(f"bloco10-ventilador-0.5-{semente}"), _ruido_que_oscila(0.02, 0.5), FALA_C920)
                cena.inicio_do_willy()
                cena.ganho_do_ruido(lambda t: 2.5 if t >= 1.5 else 1.0)
                cena.falar(4.0, 3.0)
                disparou, ultima = _Gravacao(0.02).rodar(cena, total_s=30.0)
                self.assertIsNotNone(disparou)
                self.assertEqual("parou", disparou[0])
                self.assertGreaterEqual(disparou[1], ultima, "encerrou antes ou no meio da fala")

    def test_fala_continua_com_ruido_que_oscila_nao_e_cortada(self):
        # 20 s de fala quase sem pausa sobre o ruído que oscila: nenhum corte.
        for semente in range(8):
            with self.subTest(semente=semente):
                cena = _CenaContinua(random.Random(f"bloco10-continua-{semente}"), _ruido_que_oscila(0.02, 0.5),
                                     FALA_C920)
                cena.falar_sem_pausa(0.3, 20.0)
                disparou, ultima = _Gravacao(0.02).rodar(cena, total_s=30.0)
                self.assertIsNotNone(disparou)
                self.assertEqual("parou", disparou[0])
                self.assertGreaterEqual(disparou[1], ultima, "cortou a fala contínua")


# ---------------------------------------------------------------------------------------------
# O Esc no segurar-para-falar
# ---------------------------------------------------------------------------------------------
CTRL, ALT, SHIFT, ESC = 0x11, 0x12, 0x10, 0x1B


class User32ComEsc:
    """O teclado do monitorar_hold. A tecla principal `vk` fica apertada pelas primeiras
    `leituras_da_tecla` consultas a ela; o Esc fica apertado a partir da consulta `esc_na_leitura`
    a ele (contando de 1); as `presas`, o tempo todo. Nenhuma tecla de verdade é lida."""

    def __init__(self, vk, leituras_da_tecla, esc_na_leitura=None, presas=(CTRL, ALT, SHIFT)):
        self.vk, self.leituras_da_tecla, self.esc_na_leitura = vk, leituras_da_tecla, esc_na_leitura
        self.presas, self.consultas_ao_esc, self.ordem = set(presas), 0, []

    def GetAsyncKeyState(self, vk):
        self.ordem.append(vk)
        if vk == ESC:
            self.consultas_ao_esc += 1
            return 0x8000 if self.esc_na_leitura and self.consultas_ao_esc >= self.esc_na_leitura else 0
        if vk == self.vk and self.leituras_da_tecla > 0:
            self.leituras_da_tecla -= 1
            return 0x8000
        return 0x8000 if vk in self.presas else 0


class TestEscNoSegurar(unittest.TestCase):
    def _monitorar(self, user32, combo="ctrl+alt+p", modo="prompt"):
        self.parar, self.cancelar = MagicMock(), MagicMock()
        self.audio = SimpleNamespace(is_recording=True, is_awake=True, recording_start_time=100.0, recording_mode=modo)
        self.sleeps = []
        _funcao_do_willy(
            "monitorar_hold", Win32HotKeyManager=Win32HotKeyManager, parar_gravacao=self.parar,
            cancelar_por_esc=self.cancelar, _VK_ESCAPE=_constante_do_willy("_VK_ESCAPE"),
            _user32=user32, ctypes=SimpleNamespace(windll=SimpleNamespace(user32=user32)),
            time=SimpleNamespace(sleep=self.sleeps.append), audio_mgr=self.audio)(combo)

    def test_vk_escape(self):
        self.assertEqual(0x1B, _constante_do_willy("_VK_ESCAPE"))

    def test_esc_na_espera_dos_650_ms_cancela_e_nao_envia(self):
        # Segurando Ctrl+Espaço e apertando o Esc antes de o monitor saber que é segurar.
        for passo in (1, 10, PASSOS_DA_ESPERA):
            with self.subTest(passo=passo):
                user32 = User32ComEsc(0x20, leituras_da_tecla=1000, esc_na_leitura=passo)
                self._monitorar(user32, "ctrl+space", "transcribe")
                self.cancelar.assert_called_once_with()
                self.parar.assert_not_called()
                self.assertEqual(passo, len(self.sleeps))
                self.assertNotIn(0x20, user32.ordem, "leu a tecla do atalho depois do Esc")

    def test_esc_durante_o_segurar_cancela_e_soltar_nao_envia(self):
        for combo, vk in (("ctrl+space", 0x20), ("ctrl+alt+p", ord("P")), ("ctrl+shift+enter", 0x0D),
                          ("ctrl+alt+space", 0x20), ("ctrl+alt+t", ord("T"))):
            with self.subTest(combo=combo):
                # A tecla fica apertada por 5 leituras e o Esc chega na 30ª consulta (4ª do segurar).
                user32 = User32ComEsc(vk, leituras_da_tecla=5, esc_na_leitura=PASSOS_DA_ESPERA + 4)
                self._monitorar(user32, combo)
                self.cancelar.assert_called_once_with()
                self.parar.assert_not_called()

    def test_esc_e_soltar_no_mesmo_passo_cancela(self):
        # Na 2ª leitura do segurar a tecla já está solta e o Esc apertado: vale o cancelar.
        user32 = User32ComEsc(ord("P"), leituras_da_tecla=2, esc_na_leitura=PASSOS_DA_ESPERA + 2)
        self._monitorar(user32)
        self.cancelar.assert_called_once_with()
        self.parar.assert_not_called()

    def test_sem_esc_soltar_envia(self):
        user32 = User32ComEsc(ord("P"), leituras_da_tecla=4)
        self._monitorar(user32)
        self.parar.assert_called_once_with()
        self.cancelar.assert_not_called()
        # O Esc é lido em todos os passos, da espera e do segurar.
        self.assertGreaterEqual(user32.consultas_ao_esc, PASSOS_DA_ESPERA + 3)

    def test_toque_rapido_deixa_o_esc_para_o_atalho_temporario(self):
        # Sem segurar, o monitor sai aos 650 ms; o Esc depois disso é o atalho "esc" da gravação.
        user32 = User32ComEsc(ord("P"), leituras_da_tecla=0)
        self._monitorar(user32)
        self.assertEqual(PASSOS_DA_ESPERA, user32.consultas_ao_esc)
        self.parar.assert_not_called()
        self.cancelar.assert_not_called()

    def test_reuniao_nao_se_cancela_com_esc(self):
        user32 = User32ComEsc(ord("R"), leituras_da_tecla=3, esc_na_leitura=1)
        self._monitorar(user32, "ctrl+alt+r", "meeting")
        self.cancelar.assert_not_called()
        self.parar.assert_called_once_with()  # o segurar segue como antes


class TestEscComOsModificadores(unittest.TestCase):
    """O Esc com os modificadores do atalho que começou a gravação, onde o Windows deixa."""

    def test_variantes(self):
        # Ctrl+Esc e Ctrl+Shift+Esc o Windows guarda para si: ficam com o monitorar_hold.
        casos = {"ctrl+alt+p": "ctrl+alt+esc", "ctrl+alt+space": "ctrl+alt+esc", "ctrl+alt+t": "ctrl+alt+esc",
                 "alt+shift+p": "shift+alt+esc", "win+alt+d": "alt+win+esc", "ctrl+space": None,
                 "ctrl+shift+enter": None, "ctrl+shift+p": None, "f9": None, "ctrl+": None}
        for combo, esperado in casos.items():
            with self.subTest(combo=combo):
                self.assertEqual(esperado, Win32HotKeyManager.com_os_modificadores_de(combo, "esc"))

    def test_variante_e_um_atalho_valido(self):
        for combo in ("ctrl+alt+p", "alt+shift+p", "win+alt+d"):
            variante = Win32HotKeyManager.com_os_modificadores_de(combo, "esc")
            self.assertEqual(Win32HotKeyManager.parse_hotkey(combo)[0], Win32HotKeyManager.parse_hotkey(variante)[0])
            self.assertEqual(ESC, Win32HotKeyManager.parse_hotkey(variante)[1])

    def setUp(self):
        self.ordem = []
        self.hotkeys = SimpleNamespace(
            registrar_temporario=lambda nome, combo, callback: self.ordem.append(("registrar", nome, combo)),
            soltar_temporario=lambda nome: self.ordem.append(("soltar", nome)))

    def _iniciar(self, modo, atalho):
        audio = MagicMock(is_recording=False, is_processing=False, is_awake=True, system_device_index=None)
        audio.ensure_stream.return_value = True
        audio.start_recording.side_effect = lambda m: self.ordem.append(("gravar", m)) or True
        globais = {"audio_mgr": audio, "sound_mgr": MagicMock(), "atualizar_ui": MagicMock(), "hotkey_mgr": self.hotkeys,
                       "config_mgr": SimpleNamespace(wake_word_enabled=False, auto_silence=True),
                       "_ATALHO_DO_CANCELAR": _constante_do_willy("_ATALHO_DO_CANCELAR"),
                       "_ATALHO_DO_CANCELAR_SEGURANDO": _constante_do_willy("_ATALHO_DO_CANCELAR_SEGURANDO"),
                       "Optional": Optional, "Win32HotKeyManager": Win32HotKeyManager, "ContextManager": MagicMock(),
                       "callback_audio": "cb", "cancelar_por_esc": "cancelar_por_esc", "_soltar_esc_sem_gravacao": MagicMock(),
                       "pill": None, "_janela_antes_do_willy": 0, "_foco_antes_do_willy": 0}
        _funcao_do_willy("iniciar_gravacao", **globais)(modo, atalho)
        return self.ordem

    def test_registra_o_esc_com_os_modificadores_antes_de_gravar(self):
        self.assertEqual([("registrar", "cancelar_gravacao", "esc"),
                          ("registrar", "cancelar_gravacao_segurando", "ctrl+alt+esc"), ("gravar", "prompt")],
                         self._iniciar("prompt", "ctrl+alt+p"))

    def test_ctrl_esc_reservado_fica_so_com_o_monitor(self):
        for modo, atalho in (("transcribe", "ctrl+space"), ("send", "ctrl+shift+enter"), ("transcribe", None)):
            with self.subTest(atalho=atalho):
                self.ordem.clear()
                self.assertEqual([("registrar", "cancelar_gravacao", "esc"), ("gravar", modo)],
                                 self._iniciar(modo, atalho))

    def test_reuniao_nao_pega_nenhum_esc(self):
        self.assertEqual([("gravar", "meeting")], self._iniciar("meeting", "ctrl+alt+r"))

    def test_soltar_o_esc_solta_os_dois(self):
        _funcao_do_willy("_soltar_esc", hotkey_mgr=self.hotkeys,
                         _ATALHO_DO_CANCELAR=_constante_do_willy("_ATALHO_DO_CANCELAR"),
                         _ATALHO_DO_CANCELAR_SEGURANDO=_constante_do_willy("_ATALHO_DO_CANCELAR_SEGURANDO"))()
        self.assertEqual(SOLTAR_OS_ESC, self.ordem)

    def test_handlers_passam_o_atalho_deles(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            funcoes = {n.name: n for n in ast.parse(f.read()).body if isinstance(n, ast.FunctionDef)}
        esperado = {"on_voice_hotkey": "hotkey", "on_translate_hotkey": "translate_hotkey",
                    "on_prompt_hotkey": "prompt_hotkey", "on_send_hotkey": "send_hotkey",
                    "on_transform_hotkey": "transform_hotkey"}
        for handler, atributo in esperado.items():
            with self.subTest(handler=handler):
                (chamada,) = [c for c in ast.walk(funcoes[handler]) if isinstance(c, ast.Call)
                              and getattr(c.func, "id", None) == "iniciar_gravacao"]
                argumentos = list(chamada.args[1:]) + [k.value for k in chamada.keywords if k.arg == "atalho"]
                self.assertEqual([atributo], [getattr(a, "attr", None) for a in argumentos])


# ---------------------------------------------------------------------------------------------
# A aba Atalhos com os 13, o aviso de atalho recusado e a alternativa do Ctrl+Alt+L
# ---------------------------------------------------------------------------------------------
AVISO_DO_WINDOWS = "⚠️ Em uso por outro programa no Windows — clique no atalho ao lado para trocar"


class TestAbaAtalhosCompleta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _aba(self, settings=None, falhas=None, salvos=None):
        callbacks = {"get_settings": lambda: dict(settings or {})}
        if falhas is not None:
            callbacks["get_hotkey_failures"] = lambda: dict(falhas)
        if salvos is not None:
            callbacks["on_save_settings"] = salvos.append
        aba = build_tab_shortcuts(self.root, callbacks=callbacks)
        self.addCleanup(aba.destroy)
        return aba

    def test_os_13_atalhos_tem_linha(self):
        aba = self._aba()
        self.assertEqual(sorted(HOTKEY_FIELDS), sorted(k.chave_propria for k in _keycaps(aba)))

    def test_as_tres_linhas_novas(self):
        aba = self._aba({"SPEAK_HOTKEY": "ctrl+alt+s", "STICKY_HOTKEY": "ctrl+alt+f", "CAPTIONS_HOTKEY": "ctrl+alt+j"})
        por_campo = {k.chave_propria: k for k in _keycaps(aba)}
        self.assertEqual("ctrl+alt+s", por_campo["SPEAK_HOTKEY"].get_hotkey())
        self.assertEqual("ctrl+alt+f", por_campo["STICKY_HOTKEY"].get_hotkey())
        self.assertEqual("ctrl+alt+j", por_campo["CAPTIONS_HOTKEY"].get_hotkey())
        for termo, titulo in (("voz alta", "Leitura em Voz Alta"), ("fixar", "Fixar Janela Alvo"),
                              ("teleprompter", "Legendas Ao Vivo / Teleprompter")):
            with self.subTest(termo=termo):
                aba.filtrar(termo)
                visiveis = [i for s in aba.secoes for i in s["itens"] if i["widget"].winfo_manager()]
                self.assertEqual(1, len(visiveis))
                self.assertIn(titulo.lower(), visiveis[0]["texto"])
        aba.filtrar("")

    def test_o_conflito_do_keycap_conhece_os_13(self):
        # Capturar na linha do ditado a combinação da leitura em voz alta: o aviso diz o nome dela.
        aba = self._aba({"SPEAK_HOTKEY": "ctrl+alt+s"})
        voz = next(k for k in _keycaps(aba) if k.chave_propria == "VOICE_HOTKEY")
        self.assertEqual("Leitura em Voz Alta", voz.nomes_atalhos["SPEAK_HOTKEY"])
        self.assertEqual("Legendas Ao Vivo / Teleprompter", voz.nomes_atalhos["CAPTIONS_HOTKEY"])

    def test_restaurar_padroes_leva_os_13(self):
        salvos = []
        aba = self._aba({"CAPTIONS_HOTKEY": "ctrl+alt+j"}, salvos=salvos)
        botao = next(w for w in _todos(aba) if isinstance(w, ctk.CTkButton) and w.cget("text") == "Restaurar Padrões")
        botao.invoke()
        self.assertEqual(1, len(salvos))
        self.assertEqual(sorted(HOTKEY_FIELDS), sorted(salvos[0]))
        captions = next(k for k in _keycaps(aba) if k.chave_propria == "CAPTIONS_HOTKEY")
        self.assertEqual("ctrl+alt+l", captions.get_hotkey())

    def test_atalho_recusado_mostra_o_aviso_na_linha_dele(self):
        aba = self._aba({"CAPTIONS_HOTKEY": "ctrl+alt+l"}, falhas={"CAPTIONS_HOTKEY": "ctrl+alt+l"})
        aviso = aba.avisos_de_falha["CAPTIONS_HOTKEY"]
        self.assertEqual(AVISO_DO_WINDOWS, aviso.cget("text"))
        self.assertEqual("pack", aviso.winfo_manager())
        outros = [k for k, lbl in aba.avisos_de_falha.items() if k != "CAPTIONS_HOTKEY" and lbl.winfo_manager()]
        self.assertEqual([], outros)

    def test_sem_falha_nenhum_aviso(self):
        for falhas in (None, {}):
            with self.subTest(falhas=falhas):
                aba = self._aba(falhas=falhas)
                self.assertEqual(sorted(HOTKEY_FIELDS), sorted(aba.avisos_de_falha))
                self.assertEqual([], [k for k, lbl in aba.avisos_de_falha.items() if lbl.winfo_manager()])

    def test_trocado_depois_da_recusa_nao_fica_marcado(self):
        aba = self._aba({"CAPTIONS_HOTKEY": "ctrl+alt+k"}, falhas={"CAPTIONS_HOTKEY": "ctrl+alt+l"})
        self.assertEqual("", aba.avisos_de_falha["CAPTIONS_HOTKEY"].winfo_manager())

    def test_sincronizar_relê_as_falhas(self):
        falhas = {"CAPTIONS_HOTKEY": "ctrl+alt+l"}
        callbacks_falhas = dict(falhas)
        aba = build_tab_shortcuts(self.root, callbacks={"get_settings": dict,
                                                        "get_hotkey_failures": lambda: dict(callbacks_falhas)})
        self.addCleanup(aba.destroy)
        self.assertEqual("pack", aba.avisos_de_falha["CAPTIONS_HOTKEY"].winfo_manager())
        callbacks_falhas.clear()  # trocou para uma livre: o orquestrador registrou tudo
        aba.sincronizar_atalhos({"CAPTIONS_HOTKEY": "ctrl+alt+j"})
        self.assertEqual("", aba.avisos_de_falha["CAPTIONS_HOTKEY"].winfo_manager())
        callbacks_falhas["VOICE_HOTKEY"] = "ctrl+space"
        aba.sincronizar_atalhos({"CAPTIONS_HOTKEY": "ctrl+alt+j"})
        self.assertEqual(AVISO_DO_WINDOWS, aba.avisos_de_falha["VOICE_HOTKEY"].cget("text"))

    def test_mesma_combinacao_de_outro_atalho_do_willy_diz_qual(self):
        # Um .env editado à mão com dois atalhos na mesma combinação: o outro "programa" é o Willy.
        aba = self._aba({"STICKY_HOTKEY": "ctrl+alt+s", "SPEAK_HOTKEY": "ctrl+alt+s"},
                        falhas={"STICKY_HOTKEY": "ctrl+alt+s"})
        self.assertEqual("⚠️ Mesma combinação de Leitura em Voz Alta — clique no atalho ao lado para trocar",
                         aba.avisos_de_falha["STICKY_HOTKEY"].cget("text"))

    def test_os_dois_recusados_e_outro_programa(self):
        # Juiz do Bloco 10, 13ª rodada: com os dois atalhos da mesma combinação recusados, quem a tem
        # é outro programa, e não o Willy.
        aba = self._aba({"STICKY_HOTKEY": "ctrl+alt+s", "SPEAK_HOTKEY": "ctrl+alt+s"},
                        falhas={"STICKY_HOTKEY": "ctrl+alt+s", "SPEAK_HOTKEY": "ctrl+alt+s"})
        for chave in ("STICKY_HOTKEY", "SPEAK_HOTKEY"):
            with self.subTest(chave=chave):
                self.assertEqual(AVISO_DO_WINDOWS, aba.avisos_de_falha[chave].cget("text"))

    def test_falha_do_callback_nao_derruba_a_aba(self):
        aba = build_tab_shortcuts(self.root, callbacks={"get_hotkey_failures": MagicMock(side_effect=RuntimeError)})
        self.addCleanup(aba.destroy)
        self.assertEqual([], [k for k, lbl in aba.avisos_de_falha.items() if lbl.winfo_manager()])


class TestWillyLigaAsFalhasNaAba(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            self.arvore = ast.parse(f.read())

    def test_callback_das_falhas(self):
        (valor,) = [v for n in ast.walk(self.arvore) if isinstance(n, ast.Dict)
                    for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value == "get_hotkey_failures"]
        orquestrador = SimpleNamespace(atalhos_com_falha=lambda: {"CAPTIONS_HOTKEY": "ctrl+alt+l"})
        funcao = eval(compile(ast.Expression(valor), "willy.py", "eval"), {"hotkey_orchestrator": orquestrador})
        self.assertEqual({"CAPTIONS_HOTKEY": "ctrl+alt+l"}, funcao())
        self.assertEqual({}, eval(compile(ast.Expression(valor), "willy.py", "eval"), {"hotkey_orchestrator": None})())

    def test_a_aba_rele_depois_do_registro_da_partida(self):
        # A aba é montada antes do registro: sem reler, ela mostrava o Ctrl+Alt+L trocado e sem aviso.
        (partida,) = [f for f in self.arvore.body if isinstance(f, ast.FunctionDef)
                      and any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "HotkeyOrchestrator"
                              for c in ast.walk(f))]
        corpo = [ast.unparse(n) for n in partida.body]
        registro = corpo.index("hotkey_orchestrator.registrar_todos()")
        self.assertEqual("if dashboard:\n    safe_dispatch_ui(dashboard.sincronizar_atalhos)", corpo[registro + 1])


class TestAlternativaDoCtrlAltL(unittest.TestCase):
    """Na partida, o Ctrl+Alt+L padrão das legendas recusado pelo Windows passa ao Ctrl+Alt+J."""

    PADROES: ClassVar[dict] = {"master_hotkey": "ctrl+shift+space", "translate_hotkey": "ctrl+alt+space",
               "meeting_hotkey": "ctrl+alt+r", "prompt_hotkey": "ctrl+alt+p", "transform_hotkey": "ctrl+alt+t",
               "profile_hotkey": "ctrl+alt+e", "history_hotkey": "ctrl+alt+h", "undo_hotkey": "ctrl+alt+z",
               "send_hotkey": "ctrl+shift+enter", "speak_hotkey": "ctrl+alt+s", "sticky_hotkey": "ctrl+alt+f",
               "captions_hotkey": "ctrl+alt+l", "hotkey": "ctrl+space", "translate_es_hotkey": ""}

    def _orquestrador(self, ocupados, **config):
        self.config = SimpleNamespace(**{**self.PADROES, **config})
        self.salvos = []
        self.config.save_settings = self.salvos.append
        self.avisos = []
        self.mgr = GerenciadorFalso(ocupados=ocupados)
        handlers = {nome: MagicMock(name=nome) for nome, _, _ in ATALHOS}
        return HotkeyOrchestrator(self.mgr, self.config, handlers,
                                  on_falha=lambda falhas, mantidos: self.avisos.append((falhas, mantidos)))

    def test_padrao_ocupado_vai_para_a_alternativa_sem_aviso(self):
        orq = self._orquestrador({"ctrl+alt+l"})
        self.assertEqual([], orq.registrar_todos())
        self.assertEqual([], self.avisos)
        self.assertEqual([{"CAPTIONS_HOTKEY": "ctrl+alt+j"}], self.salvos)
        self.assertIn("ctrl+alt+j", self.mgr.ativos)
        self.assertEqual(13, len(self.mgr.ativos))
        self.assertEqual({}, orq.atalhos_com_falha())
        orq_com_es = self._orquestrador({"ctrl+alt+l"}, translate_es_hotkey="ctrl+alt+y")
        self.assertEqual([], orq_com_es.registrar_todos())
        self.assertEqual(14, len(self.mgr.ativos))
        self.assertEqual({}, orq.atalhos_com_falha())

    def test_alternativa_tambem_ocupada_avisa_como_sempre(self):
        orq = self._orquestrador({"ctrl+alt+l", "ctrl+alt+j"})
        self.assertEqual(["ctrl+alt+l"], orq.registrar_todos())
        self.assertEqual([(["ctrl+alt+l"], {})], self.avisos)
        self.assertEqual([], self.salvos)
        self.assertEqual(12, len(self.mgr.ativos))
        self.assertNotIn("ctrl+alt+j", self.mgr.ativos)
        self.assertEqual({"CAPTIONS_HOTKEY": "ctrl+alt+l"}, orq.atalhos_com_falha())

    def test_combinacao_escolhida_pela_pessoa_nao_muda(self):
        orq = self._orquestrador({"ctrl+alt+k"}, captions_hotkey="ctrl+alt+k")
        self.assertEqual(["ctrl+alt+k"], orq.registrar_todos())
        self.assertEqual([], self.salvos)
        self.assertEqual({"CAPTIONS_HOTKEY": "ctrl+alt+k"}, orq.atalhos_com_falha())

    def test_alternativa_de_outro_atalho_do_willy_nao_e_tomada(self):
        # Antes das legendas na ordem de registro (o fixar) e depois delas (o ditado, o último):
        # no segundo, só a recusa da alternativa impede as legendas de tirar a tecla do ditado.
        for campo, nome in (("sticky_hotkey", "sticky"), ("hotkey", "voice")):
            with self.subTest(atalho=nome):
                orq = self._orquestrador({"ctrl+alt+l"}, **{campo: "ctrl+alt+j"})
                self.assertEqual(["ctrl+alt+l"], orq.registrar_todos())
                self.assertEqual([], self.salvos)
                self.assertIs(self.mgr.ativos["ctrl+alt+j"], orq.handlers[nome])

    def test_so_na_partida(self):
        # Uma recarga (a pessoa trocou outro atalho) não troca o Ctrl+Alt+L que ela vê recusado.
        orq = self._orquestrador({"ctrl+alt+l", "ctrl+alt+j"})
        orq.registrar_todos()
        self.mgr.ocupados.discard("ctrl+alt+j")
        self.salvos.clear()
        self.config.hotkey = "ctrl+alt+d"
        orq.recarregar_se_necessario({"VOICE_HOTKEY": "ctrl+alt+d"})
        self.assertNotIn("ctrl+alt+j", self.mgr.ativos)
        self.assertEqual({"CAPTIONS_HOTKEY": "ctrl+alt+l"}, orq.atalhos_com_falha())
        self.assertNotIn({"CAPTIONS_HOTKEY": "ctrl+alt+j"}, self.salvos)

    def test_falhas_da_recarga(self):
        orq = self._orquestrador({"ctrl+alt+x"}, speak_hotkey="")
        orq.registrar_todos()
        self.assertEqual({}, orq.atalhos_com_falha())
        # Trocou para uma ocupada e voltou ao Ctrl+Alt+P, que funciona: não fica marcado.
        self.config.prompt_hotkey = "ctrl+alt+x"
        orq.recarregar_se_necessario({"PROMPT_HOTKEY": "ctrl+alt+x"})
        self.assertEqual({}, orq.atalhos_com_falha())
        # Sem anterior para onde voltar, fica sem tecla, e a linha dele é marcada.
        self.config.speak_hotkey = "ctrl+alt+x"
        orq.recarregar_se_necessario({"SPEAK_HOTKEY": "ctrl+alt+x"})
        self.assertEqual({"SPEAK_HOTKEY": "ctrl+alt+x"}, orq.atalhos_com_falha())


class TestAlternativaChegaAoEnv(unittest.TestCase):
    """Com o ConfigManager de verdade, num .env temporário: a próxima partida já lê o Ctrl+Alt+J."""

    def setUp(self):
        pasta = isolar_config(self)
        self.env = os.path.join(pasta, ".env")
        with open(self.env, "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=gsk_teste\n")
        os.environ.pop("CAPTIONS_HOTKEY", None)

    def test_a_alternativa_fica_no_env(self):
        config = ConfigManager()
        self.assertEqual("ctrl+alt+l", config.captions_hotkey)
        handlers = {nome: (lambda: None) for nome, _, _ in ATALHOS}
        HotkeyOrchestrator(GerenciadorFalso(ocupados={"ctrl+alt+l"}), config, handlers).registrar_todos()
        self.assertEqual("ctrl+alt+j", config.captions_hotkey)
        self.assertEqual("ctrl+alt+j", dotenv_values(self.env)["CAPTIONS_HOTKEY"])


if __name__ == "__main__":
    unittest.main()
