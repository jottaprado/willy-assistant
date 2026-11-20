"""
Atalho que o Windows recusa (outro programa já tem) vira aviso visível.

Antes o RegisterHotKey falhava, o aviso ia só para o stderr, que no .exe ninguém vê, e a
pessoa apertava o atalho sem nada acontecer.
"""

import ast
import os
import sys
import unittest
from unittest.mock import MagicMock

from core.hotkey import Win32HotKeyManager
from core.system.hotkey_orchestrator import HotkeyOrchestrator
from tests.willy_isolado import RAIZ, rodar_no_willy

# Combinação que nenhum programa comum usa: o primeiro gerenciador a pega, o segundo não.
COMBO_RARO = "ctrl+alt+shift+f11"


@unittest.skipUnless(sys.platform == "win32", "RegisterHotKey é do Windows")
class TestGerenciadorGuardaAsFalhas(unittest.TestCase):
    def test_combinacao_ja_registrada_entra_nas_falhas(self):
        dono = Win32HotKeyManager()
        dono.register(COMBO_RARO, lambda: None)
        dono.start()
        try:
            if dono.falhas:
                self.skipTest(f"outro programa já usa {COMBO_RARO} nesta máquina")
            segundo = Win32HotKeyManager()
            segundo.register(COMBO_RARO, lambda: None)
            segundo.start()
            try:
                self.assertEqual([COMBO_RARO], segundo.falhas)
            finally:
                segundo.stop()
        finally:
            dono.stop()

    def test_novo_start_zera_as_falhas_antigas(self):
        mgr = Win32HotKeyManager()
        mgr.falhas = ["ctrl+space"]
        mgr.start()
        try:
            self.assertEqual([], mgr.falhas)
        finally:
            mgr.stop()


class TestOrquestradorAvisa(unittest.TestCase):
    def _orquestrador(self, falhas, on_falha):
        mgr = MagicMock()
        mgr.falhas = falhas
        config = MagicMock(hotkey="ctrl+space")
        return HotkeyOrchestrator(mgr, config, {"voice": lambda: None}, on_falha=on_falha)

    def test_chama_on_falha_com_os_atalhos_recusados(self):
        avisos = []
        falhas = self._orquestrador(["ctrl+space"], lambda f, m: avisos.append((f, m))).registrar_todos()
        self.assertEqual([(["ctrl+space"], {})], avisos)
        self.assertEqual(["ctrl+space"], falhas)

    def test_sem_falha_nao_avisa(self):
        avisos = []
        self._orquestrador([], lambda f, m: avisos.append((f, m))).registrar_todos()
        self.assertEqual([], avisos)


_SCRIPT = r"""
import json, sys
from unittest.mock import MagicMock
import willy

ui = []
willy.atualizar_ui = lambda estado, msg="": ui.append([estado, msg])
willy.tray_mgr = MagicMock()
mantidos = dict(par.split(">") for par in sys.argv[2].split(",") if par) if len(sys.argv) > 2 else {}
bandeja = lambda: [list(c.args) for c in willy.tray_mgr.notify.call_args_list]
partida = len(sys.argv) > 3 and sys.argv[3] == "partida"
if not partida:
    willy.bandeja_pronta()
willy.avisar_atalhos_em_uso(sys.argv[1].split(","), mantidos)
antes_do_icone = bandeja()
if partida:
    willy.bandeja_pronta()  # o ícone sobe depois do registro dos atalhos
print("RESULTADO=" + json.dumps({"ui": ui, "antes_do_icone": antes_do_icone, "bandeja": bandeja()}))
"""


class TestAvisoNoWilly(unittest.TestCase):
    def test_um_atalho(self):
        r = rodar_no_willy(_SCRIPT, "ctrl+space")
        self.assertEqual([["warning", "Atalho não registrado: ctrl+space"]], r["ui"])
        (titulo, texto), = r["bandeja"]
        self.assertEqual("Willy: atalho não registrado", titulo)
        self.assertIn("ctrl+space", texto)
        self.assertIn("aba Atalhos", texto)

    def test_na_partida_a_bandeja_recebe_o_aviso_quando_o_icone_sobe(self):
        # Achado do verificador: as falhas eram lidas ~0,7 ms depois de a thread da bandeja
        # começar, o ícone só existia 26 a 42 ms depois, e o notify sem ícone sumia.
        r = rodar_no_willy(_SCRIPT, "ctrl+space", "", "partida")
        self.assertEqual([], r["antes_do_icone"])
        self.assertEqual(1, len(r["bandeja"]))

    def test_varios_atalhos(self):
        r = rodar_no_willy(_SCRIPT, "ctrl+space,ctrl+alt+r")
        self.assertEqual([["warning", "Atalhos não registrados: ctrl+space, ctrl+alt+r"]], r["ui"])

    def test_troca_recusada_diz_qual_continua_valendo(self):
        r = rodar_no_willy(_SCRIPT, "ctrl+alt+x", "ctrl+alt+x>ctrl+space")
        self.assertEqual([["warning", "Atalho não registrado: ctrl+alt+x (vale ctrl+space)"]], r["ui"])
        (_, texto), = r["bandeja"]
        self.assertIn("Continua valendo ctrl+space", texto)

    def test_main_liga_o_aviso_no_orquestrador(self):
        # O main() não roda em teste (sobe a interface inteira); confere a ligação no código.
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        chamadas = [
            n for n in ast.walk(arvore)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "HotkeyOrchestrator"
        ]
        self.assertEqual(1, len(chamadas))
        on_falha = {k.arg: k.value for k in chamadas[0].keywords}.get("on_falha")
        self.assertIsNotNone(on_falha, "sem on_falha, atalho recusado volta a ficar mudo")
        self.assertEqual("avisar_atalhos_em_uso", on_falha.id)

    def test_main_entrega_os_avisos_quando_a_bandeja_sobe(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        (on_ready,) = [n for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef) and n.name == "_on_ready"]
        chamadas = {getattr(n.func, "id", None) for n in ast.walk(on_ready) if isinstance(n, ast.Call)}
        self.assertIn("bandeja_pronta", chamadas, "sem isso o aviso da partida nunca chega à bandeja")


if __name__ == "__main__":
    unittest.main()
