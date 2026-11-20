"""
O "Copiar" clicado pela pessoa vai para o histórico do Win+V, a não ser no modo privado.

Decisão do dono: os cliques de "Copiar" (Histórico, "Prompts recentes" da bandeja e o clique na
pílula) se comportam como um Ctrl+C e aparecem no Win+V; a colagem automática e tudo no modo
privado continuam fora dele. Sem como saber do modo privado, conta como ligado.
"""

import ast
import os
import unittest
from unittest.mock import patch

from core.actions import ActionManager
from tests.test_copia_segura import _BasePilulaCopia, _criar_bandeja
from tests.willy_isolado import destruir_tk
from ui.components.copia import copiar_pelo_clique
from ui.tabs.tab_history import HistoryTab

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCopiarPeloClique(unittest.TestCase):
    def test_fora_do_modo_privado_vai_para_o_win_v(self):
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            self.assertTrue(copiar_pelo_clique("texto", modo_privado=False))
        copiar.assert_called_once_with("texto", ocultar_do_historico=False)

    def test_no_modo_privado_fica_fora(self):
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            copiar_pelo_clique("texto", modo_privado=True)
        copiar.assert_called_once_with("texto", ocultar_do_historico=True)

    def test_falha_ao_gravar_volta_false(self):
        with patch.object(ActionManager, "secure_copy", return_value=False):
            self.assertFalse(copiar_pelo_clique("texto", modo_privado=False))


class TestComAAssinaturaDeVerdade(unittest.TestCase):
    """Os outros testes trocam o secure_copy por um MagicMock, que aceita qualquer nome: com a
    assinatura de verdade, um parâmetro renomeado no core reprova aqui."""

    def test_o_nome_do_parametro_e_o_do_core(self):
        with patch.object(ActionManager, "secure_copy", autospec=True, return_value=True) as copiar:
            copiar_pelo_clique("texto", modo_privado=False)
        copiar.assert_called_once_with("texto", ocultar_do_historico=False)


class TestAbaDeHistorico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import customtkinter as ctk
        cls.root = ctk.CTk()
        cls.root.withdraw()
        cls.callbacks = {}
        cls.aba = HistoryTab(
            cls.root,
            callbacks=cls.callbacks,
            history_items=[{"id": "1", "text": "texto do cartão", "mode": "transcribe", "timestamp": "2026-10-29 10:00:00"}],
        )

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.aba, cls.root)

    def _copiar(self, callbacks):
        self.aba.callbacks = callbacks
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            self.aba._copiar("texto")
        return copiar.call_args.kwargs["ocultar_do_historico"]

    def test_le_o_modo_privado_dos_ajustes_na_aba_real(self):
        self.assertFalse(self._copiar({"get_settings": lambda: {"private_mode": False}}))
        self.assertTrue(self._copiar({"get_settings": lambda: {"private_mode": True}}))

    def test_reusar_que_nao_achou_o_app_fica_fora_do_win_v_no_botao_real(self):
        import customtkinter as ctk
        self.aba.callbacks = {"get_settings": lambda: {"private_mode": False}, "on_reuse_text": lambda t: False}
        btn_real = ctk.CTkButton(self.aba, text="")
        agendados = []
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar, \
                patch.object(self.aba, "_safe_after", side_effect=lambda ms, fn, *a: agendados.append((ms, fn, a))):
            self.aba._reusar_com_feedback("texto", btn_real)
        copiar.assert_called_once_with("texto", ocultar_do_historico=True)
        timers_icone = [(fn, a) for ms, fn, a in agendados if ms == 1500]
        self.assertEqual(1, len(timers_icone))
        btn_real.destroy()
        timers_icone[0][0](*timers_icone[0][1])

    def test_sem_como_saber_fica_fora_do_win_v(self):
        self.assertTrue(self._copiar({}))
        self.assertTrue(self._copiar({"get_settings": dict}))

        def _quebra():
            raise RuntimeError("config")

        self.assertTrue(self._copiar({"get_settings": _quebra}))


class TestBandeja(unittest.TestCase):
    def _copiar(self, **kwargs):
        tray = _criar_bandeja(callbacks={}, base_dir=".", **kwargs)
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            tray._copiar_prompt("texto")
        return copiar.call_args.kwargs["ocultar_do_historico"]

    def test_segue_o_modo_privado(self):
        self.assertFalse(self._copiar(modo_privado_getter=lambda: False))
        self.assertTrue(self._copiar(modo_privado_getter=lambda: True))

    def test_sem_o_getter_fica_fora_do_win_v(self):
        self.assertTrue(self._copiar())


class TestPilula(_BasePilulaCopia):
    def _clicar(self, pill):
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            pill._on_click()
        return copiar.call_args.kwargs["ocultar_do_historico"]

    def test_segue_o_modo_privado_a_cada_clique(self):
        privado = [False]
        pill = self._pilula("o ditado", modo_privado_getter=lambda: privado[0])
        self.assertFalse(self._clicar(pill))
        privado[0] = True  # ligado com o Willy aberto
        pill.current_state = "success"
        self.assertTrue(self._clicar(pill))

    def test_sem_o_getter_fica_fora_do_win_v(self):
        self.assertTrue(self._clicar(self._pilula("o ditado")))


class TestWillyLigaOModoPrivado(unittest.TestCase):
    """willy.py não é importável em teste: confere no código que o main() passa o getter."""

    def _chamadas(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        main = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        return {n.func.id: n for n in ast.walk(main)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("FloatingPill", "TrayManager")}

    def test_pilula_e_bandeja_recebem_o_modo_privado_da_config(self):
        chamadas = self._chamadas()
        for nome in ("FloatingPill", "TrayManager"):
            with self.subTest(nome):
                kw = {k.arg: k.value for k in chamadas[nome].keywords}
                self.assertIn("modo_privado_getter", kw)
                self.assertEqual("lambda: config_mgr.private_mode", ast.unparse(kw["modo_privado_getter"]))


if __name__ == "__main__":
    unittest.main()
