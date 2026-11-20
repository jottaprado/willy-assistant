"""
Toda escrita no clipboard passa por ActionManager.secure_copy.

A pílula, a bandeja e a aba de histórico copiavam com pyperclip.copy: o texto ia para o
histórico do Win+V e para a nuvem, que a colagem do pipeline evita, e a falha era engolida
com a mensagem de "copiado" aparecendo do mesmo jeito.

E a bandeja copiava o RÓTULO do item. O pystray escolhe os argumentos da ação pela contagem
do __code__, e o default conta: `lambda _, t=texto:` tem dois, ele passava (icon, item), e
`t` virava o MenuItem, cujo str() é " • hello...".
"""

import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from core.actions import ActionManager
from tests.test_static_analysis import escritas_diretas_no_clipboard
from tests.willy_isolado import destruir_tk
from ui.overlays.pill import FloatingPill
from ui.overlays.tray import TrayManager
from ui.tabs.tab_history import HistoryTab

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = "Refatore o módulo de áudio para usar a taxa de 16 kHz e documente o porquê"


def _criar_bandeja(callbacks=None, base_dir=".", **kwargs) -> TrayManager:
    """Fábrica compartilhada de TrayManager com ícone simulado para testes de cópia."""
    tray = TrayManager(callbacks or {}, base_dir, **kwargs)
    tray.icon = MagicMock()
    return tray


class _BasePilulaCopia(unittest.TestCase):
    """Base com janela Tk compartilhada e fábrica de FloatingPill pronta para clique de cópia."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def _pilula(self, texto: str = PROMPT, **kwargs) -> FloatingPill:
        pill = FloatingPill(self.root, **kwargs)
        self.addCleanup(pill.destroy)
        pill.set_last_text(texto)
        pill.current_state = "success"
        return pill


class TestBandeja(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.copiado = MagicMock()
        self.tray = _criar_bandeja({"on_copied": self.copiado}, self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _item_do_prompt(self):
        menu = self.tray.build_menu(
            True, True, False, "centro_inferior", "ctrl+space", "ctrl+alt+space",
            "ctrl+shift+space", "ctrl+alt+r", "llama-3.3-70b-versatile", [{"text": PROMPT}],
        )
        (item,) = [i for i in menu.items if str(i.text).startswith("  • ")]
        self.assertIn("...", item.text, "o rótulo deveria vir truncado, senão o teste não prova nada")
        return item

    def test_clique_no_prompt_recente_copia_o_texto_completo(self):
        item = self._item_do_prompt()
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            item(self.tray.icon)  # é assim que o pystray dispara a ação
        # Sem o modo privado ligado à bandeja, conta como ligado: fora do Win+V.
        copiar.assert_called_once_with(PROMPT, ocultar_do_historico=True)
        self.copiado.assert_called_once_with()

    def test_clipboard_ocupado_nao_finge_que_copiou(self):
        item = self._item_do_prompt()
        with patch.object(ActionManager, "secure_copy", return_value=False):
            item(self.tray.icon)
        self.copiado.assert_not_called()
        titulo = self.tray.icon.notify.call_args.args[1]
        self.assertEqual("Willy não copiou", titulo)


class TestPilula(_BasePilulaCopia):
    def setUp(self):
        self.pill = self._pilula(PROMPT)

    def test_clique_copia_pelo_canal_seguro(self):
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            self.pill._on_click()
        copiar.assert_called_once_with(PROMPT, ocultar_do_historico=True)
        self.assertIn("Copiado", self.pill.canvas.itemcget(self.pill.text, "text"))

    def test_clipboard_ocupado_aparece_na_pilula(self):
        with patch.object(ActionManager, "secure_copy", return_value=False):
            self.pill._on_click()
        self.assertIn("Não copiei", self.pill.canvas.itemcget(self.pill.text, "text"))


class TestAbaDeHistorico(unittest.TestCase):
    def _aba(self):
        aba = MagicMock()
        aba.callbacks = {}  # sem "on_reuse_text": o Reusar copia, como o Copiar
        aba._copiar = lambda texto, pelo_copiar=True: HistoryTab._copiar(aba, texto, pelo_copiar)
        aba._modo_privado = lambda: HistoryTab._modo_privado(aba)
        return aba

    def test_copiar_e_reusar_passam_pelo_canal_seguro(self):
        for metodo in (HistoryTab._copiar_com_feedback, HistoryTab._reusar_com_feedback):
            with self.subTest(metodo=metodo.__name__):
                aba, botao = self._aba(), MagicMock()
                with patch.object(ActionManager, "secure_copy", return_value=True) as copiar, \
                     patch("ui.tabs.tab_history.carregar_icone", return_value=None):
                    metodo(aba, PROMPT, botao)
                copiar.assert_called_once_with(PROMPT, ocultar_do_historico=True)
                self.assertNotIn("Não copiei", str(aba._mostrar_toast.call_args))

    def test_clipboard_ocupado_nao_mostra_copiado(self):
        for metodo in (HistoryTab._copiar_com_feedback, HistoryTab._reusar_com_feedback):
            with self.subTest(metodo=metodo.__name__):
                aba, botao = self._aba(), MagicMock()
                with patch.object(ActionManager, "secure_copy", return_value=False):
                    metodo(aba, PROMPT, botao)
                aba._mostrar_toast.assert_called_once()
                self.assertIn("Não copiei", aba._mostrar_toast.call_args.args[0])
                botao.configure.assert_not_called()


class TestCanalUnico(unittest.TestCase):
    def test_nenhuma_escrita_de_clipboard_fora_do_secure_copy(self):
        self.assertEqual([], escritas_diretas_no_clipboard(), "escreva no clipboard com ActionManager.secure_copy")


if __name__ == "__main__":
    unittest.main()
