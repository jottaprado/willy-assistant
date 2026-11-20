"""
Pílula: o clique só copia com o ditado terminado, e a largura acompanha a mensagem.

- Clicar com ela em "ouvindo" ou "processando" (ou num aviso por cima deles) copiava o texto
  do ditado ANTERIOR por cima do clipboard e trocava o "ouvindo" por "Copiado!" no meio da
  gravação. No erro de colagem, o clique continua recuperando o ditado que não foi colado.
- A largura só mudava no update_status_text: as mensagens do show_state ficavam em 340 e as
  longas saíam cortadas.
"""

import tkinter as tk
import unittest
from unittest.mock import patch

from core.actions import ActionManager
from tests.willy_isolado import destruir_tk
from ui.overlays import pill as pill_mod
from ui.overlays.pill import LARGURA_MIN, FloatingPill, largura_para

LONGA = "Transcrito, mas não consegui copiar. O texto ficou no histórico"


class _BasePilula(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.root)

    def setUp(self):
        self.pill = FloatingPill(self.root)
        self.addCleanup(self.pill.destroy)
        self.pill.set_last_text("o ditado anterior")

    def _texto(self):
        return self.pill.canvas.itemcget(self.pill.text, "text")


class TestCliqueSoCopiaNoFim(_BasePilula):
    def _clicar(self):
        with patch.object(ActionManager, "secure_copy", return_value=True) as copiar:
            self.pill._on_click()
        return copiar

    def test_ouvindo_nao_copia_nem_troca_o_texto(self):
        self.pill.show_state("listening")
        antes = self._texto()
        self._clicar().assert_not_called()
        self.assertEqual(antes, self._texto())

    def test_processando_nao_copia(self):
        self.pill.show_state("processing")
        self._clicar().assert_not_called()

    def test_erro_com_o_texto_do_ditado_anterior_nao_copia(self):
        self.pill.show_state("listening")
        self.pill.show_state("processing")
        self.pill.show_state("error", "Erro na transcrição")  # este ditado não chegou a ter texto
        self._clicar().assert_not_called()

    def test_erro_ao_colar_copia_o_texto_que_nao_foi_colado(self):
        # Modo privado: sem histórico, o clique é o único jeito de recuperar o ditado.
        self.pill.show_state("listening")
        self.pill.set_last_text("o ditado que falhou")  # o pipeline manda antes de colar
        self.pill.show_state("error", "Não consegui colar (clipboard ocupado)")
        self._clicar().assert_called_once_with("o ditado que falhou", ocultar_do_historico=True)

    def test_aviso_por_cima_da_gravacao_nao_copia(self):
        self.pill.show_state("listening")
        self.pill.show_state("idle", "Teleprompter ativo")
        self._clicar().assert_not_called()

    def test_sucesso_por_cima_da_gravacao_nao_copia(self):
        self.pill.show_state("listening")
        self.pill.show_state("success", "ok", por_cima=True)
        self._clicar().assert_not_called()

    def test_sucesso_copia(self):
        self.pill.show_state("success")
        self._clicar().assert_called_once_with("o ditado anterior", ocultar_do_historico=True)
        self.assertIn("Copiado", self._texto())

    def test_informacao_curta_copia(self):
        self.pill.show_state("idle", "Teleprompter ativo")
        self._clicar().assert_called_once_with("o ditado anterior", ocultar_do_historico=True)


class TestLarguraAcompanhaAMensagem(_BasePilula):
    def test_mensagem_longa_alarga(self):
        self.pill.show_state("error", LONGA)
        self.assertEqual(largura_para(LONGA), self.pill.width)
        self.assertGreater(self.pill.width, LARGURA_MIN)
        self.assertEqual(self.pill.width, int(self.pill.canvas.cget("width")))

    def test_volta_a_340_com_a_curta(self):
        self.pill.show_state("error", LONGA)
        self.pill.show_state("success", "ok")
        self.assertEqual(LARGURA_MIN, self.pill.width)

    def test_texto_padrao_longo_do_estado_tambem(self):
        self.pill.show_state("listening", mode="prompt")  # "🎯 Arquiteto de Prompts... (fale a tarefa do agente)"
        self.assertEqual(largura_para(self._texto()), self.pill.width)
        self.assertGreater(self.pill.width, LARGURA_MIN)

    def test_visivel_mantem_o_centro(self):
        # Longe de onde o reposicionar a poria (o rodapé central): assim os dois caminhos dão
        # posições diferentes em qualquer tela.
        # Longe das bordas também: perto delas a pílula para na margem (teste abaixo).
        self.pill.root.geometry(f"{LARGURA_MIN}x48+400+200")
        self.pill.root.update_idletasks()
        with patch.object(pill_mod, "_user32", None), \
             patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.show_state("error", LONGA)
        _, x, y = self.pill.root.geometry().split("+")
        self.assertEqual((400 + (LARGURA_MIN - largura_para(LONGA)) // 2, 200), (int(x), int(y)))

    def test_visivel_perto_da_borda_para_na_margem(self):
        # Seguindo o cursor, perto da borda direita: crescer pelo centro a punha fora da tela.
        self.pill.root.geometry(f"{LARGURA_MIN}x48+640+700")
        self.pill.root.update_idletasks()
        with patch.object(pill_mod, "_user32", None), \
             patch.object(self.pill, "_area_de_trabalho", return_value=(0, 0, 1000, 800)), \
             patch.object(self.pill.root, "winfo_viewable", return_value=1):
            self.pill.show_state("error", LONGA)
        _, x, _ = self.pill.root.geometry().split("+")
        self.assertEqual(1000 - pill_mod.MARGEM_LATERAL_CURSOR - self.pill.width, int(x))

    def test_limites(self):
        self.assertEqual(340, largura_para("ok"))
        self.assertEqual(520, largura_para("x" * 200))


class TestOverlaysMonitorEErros(_BasePilula):
    def test_monitorinfo_compartilhado_e_teleprompter_no_monitor_ativo(self):
        """AUD-062, AUD-066: _MONITORINFO e obter_hmonitor_e_area são compartilhados,
        e LiveTeleprompter.mostrar posiciona no monitor ativo."""
        from ui.overlays import spotlight as spotlight_mod
        from ui.overlays import teleprompter as tp_mod
        from ui.overlays.teleprompter import LiveTeleprompter

        self.assertIs(pill_mod._MONITORINFO, spotlight_mod._MONITORINFO)
        self.assertTrue(callable(getattr(pill_mod, "obter_hmonitor_e_area", None)))

        tp = LiveTeleprompter(self.root)
        self.addCleanup(tp.destroy)
        with patch.object(
            tp_mod,
            "obter_hmonitor_e_area",
            return_value=(99, (1920, 0, 3840, 1040)),
            create=True,
        ):
            tp.mostrar()
            tp.window.update_idletasks()
            _, x, y = tp.window.geometry().split("+")
            self.assertEqual(1920 + (1920 - 540) // 2, int(x))
            self.assertEqual(1040 - 272, int(y))

    def test_pill_tratamento_granular_de_erros_e_barras(self):
        """AUD-064, AUD-158..AUD-168: _set_bars_visibility, fail-safe de _eh_do_willy_ou_do_shell
        e logging em sys.stderr nos métodos de FloatingPill."""
        import io
        from types import SimpleNamespace

        self.assertTrue(hasattr(self.pill, "_set_bars_visibility"))

        # AUD-161: predicado _eh_do_willy_ou_do_shell lançando exceção cai em janela_alvo / cursor
        # e registra erro em sys.stderr
        stderr_buf = io.StringIO()
        self.pill._eh_do_willy_ou_do_shell = lambda _hwnd: (_ for _ in ()).throw(RuntimeError("falha predicado"))
        self.pill.janela_alvo = 777
        u32_falso = SimpleNamespace(
            GetForegroundWindow=lambda: 555,
            MonitorFromWindow=lambda hwnd, _f: 88 if hwnd == 777 else 11,
            MonitorFromPoint=lambda _pt, _f: 22,
            GetMonitorInfoW=lambda _h, _info: False,
        )
        with patch.object(pill_mod, "_user32", u32_falso), patch("sys.stderr", stderr_buf):
            self.pill._area_de_trabalho("centro_inferior", (100, 100))
        self.assertIn("falha predicado", stderr_buf.getvalue())

        # AUD-160: falha em retry_callback no _on_click é logada em sys.stderr
        stderr_click = io.StringIO()
        self.pill.current_state = "offline_retry"
        self.pill.retry_callback = lambda: (_ for _ in ()).throw(RuntimeError("falha retry"))
        with patch("sys.stderr", stderr_click):
            self.pill._on_click()
        self.assertIn("falha retry", stderr_click.getvalue())

        # AUD-164, AUD-165, AUD-166, AUD-167, AUD-168, AUD-064: falhas logadas em sys.stderr
        stderr_ops = io.StringIO()
        with patch.object(self.pill.canvas, "itemconfig", side_effect=RuntimeError("erro canvas")), \
             patch("sys.stderr", stderr_ops):
            self.pill._set_bars_visibility(False)
            self.pill.update_status_text("teste")
            self.pill.last_anim_time = 0.0
            self.pill.update_waveform(0.5, True)
            self.pill.show_state("error", "msg")
        saida = stderr_ops.getvalue()
        self.assertGreaterEqual(saida.count("erro canvas"), 4)

    def test_teleprompter_e_tray_logam_excecoes_em_stderr(self):
        """AUD-169..AUD-174: LiveTeleprompter e TrayManager registram exceções em sys.stderr."""
        import io
        from unittest.mock import MagicMock

        from ui.overlays.teleprompter import LiveTeleprompter
        from ui.overlays.tray import TrayManager

        stderr_tp = io.StringIO()
        tp = LiveTeleprompter(
            self.root,
            on_close_callback=lambda: (_ for _ in ()).throw(RuntimeError("erro close tp")),
        )
        self.addCleanup(tp.destroy)
        tp.window = MagicMock()
        tp.window.winfo_exists.return_value = True
        tp.window.after.side_effect = RuntimeError("erro after tp")
        with patch("sys.stderr", stderr_tp):
            tp.adicionar_legenda("ola")
            tp.esconder()
        tp.window = None
        self.assertIn("erro after tp", stderr_tp.getvalue())
        self.assertIn("erro close tp", stderr_tp.getvalue())

        stderr_tray = io.StringIO()
        tray = TrayManager(
            callbacks={
                "on_test": lambda: (_ for _ in ()).throw(RuntimeError("erro callback tray")),
                "on_copied": lambda: (_ for _ in ()).throw(RuntimeError("erro copied tray")),
            },
            base_dir=".",
        )
        tray.icon = MagicMock()
        with patch("ui.overlays.tray.copiar_pelo_clique", return_value=True), \
             patch.object(tray, "build_menu", side_effect=RuntimeError("erro menu tray")), \
             patch("sys.stderr", stderr_tray):
            tray._call("on_test")
            tray._copiar_prompt("texto")
            tray.update(True, True, False, "topo", "ctrl+space", "ctrl+alt+space", "ctrl+shift+space", "ctrl+alt+r", "m", [])
        saida_tray = stderr_tray.getvalue()
        self.assertIn("erro callback tray", saida_tray)
        self.assertIn("erro copied tray", saida_tray)
        self.assertIn("erro menu tray", saida_tray)

    def test_willy_abrir_vocab_pasta_e_desfazer_logam_e_avisam(self):
        """AUD-145, AUD-146, AUD-148: abrir_vocabulario, abrir_pasta_config e desfazer_ultimo_ditado."""
        import io
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy

        stderr_w = io.StringIO()
        ui_mock = MagicMock()
        os_falho = SimpleNamespace(
            path=SimpleNamespace(exists=lambda _p: True),
            startfile=MagicMock(side_effect=OSError("falha startfile")),
        )
        abrir_vocab = _funcao_do_willy(
            "abrir_vocabulario",
            os=os_falho,
            VOCAB_FILE="vocab.txt",
            atualizar_ui=ui_mock,
        )
        abrir_pasta = _funcao_do_willy(
            "abrir_pasta_config",
            os=os_falho,
            USER_DATA_DIR="appdata",
            atualizar_ui=ui_mock,
        )
        desfazer = _funcao_do_willy(
            "desfazer_ultimo_ditado",
            last_injected_text="texto",
            ActionManager=SimpleNamespace(esperar_modificadores_soltos=lambda _t: True),
            keyboard=SimpleNamespace(send=MagicMock(side_effect=RuntimeError("falha ctrl+z"))),
            sound_mgr=SimpleNamespace(sound_error=MagicMock(), sound_success=MagicMock()),
            atualizar_ui=ui_mock,
        )
        with patch("sys.stderr", stderr_w):
            abrir_vocab()
            abrir_pasta()
            desfazer()
        saida_w = stderr_w.getvalue()
        self.assertIn("falha startfile", saida_w)
        self.assertIn("falha ctrl+z", saida_w)
        self.assertGreaterEqual(ui_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
