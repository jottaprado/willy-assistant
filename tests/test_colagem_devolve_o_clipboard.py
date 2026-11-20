"""
A colagem devolve o clipboard da pessoa, mesmo com dois ditados seguidos ou sem texto antes.

- Dois ditados em menos de 250 ms: o segundo lia o primeiro como "o clipboard de antes" e o
  devolvia no fim; o que a pessoa tinha copiado se perdia.
- Sem texto no clipboard antes, nada era devolvido: o ditado ficava nele, e o próximo Ctrl+V
  da pessoa colava o ditado de novo.

Nada aqui toca o clipboard de verdade: o clipboard, o secure_copy, o teclado e o Timer são falsos.
"""

import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import actions
from core.system.injector import TextInjector


class _Clipboard:
    """O clipboard do Windows: `texto` None é sem texto (vazio, ou só uma imagem)."""

    def __init__(self, texto):
        self.texto = texto
        self.escrita_falha = False

    def escrever(self, texto):
        if self.escrita_falha:
            return False
        self.texto = texto
        return True


class _Timers:
    """threading falso: os timers só disparam quando o teste manda."""

    def __init__(self):
        self.criados = []

    def Timer(self, intervalo, funcao):
        timer = SimpleNamespace(intervalo=intervalo, funcao=funcao, cancelado=False, daemon=False, start=lambda: None)
        timer.cancel = lambda: setattr(timer, "cancelado", True)
        self.criados.append(timer)
        return timer

    def disparar(self):
        for timer in self.criados:
            if not timer.cancelado:
                timer.funcao()


class TestColagemDevolveOClipboard(unittest.TestCase):
    def setUp(self):
        self.clip, self.timers = _Clipboard("senha copiada"), _Timers()
        self.injector = TextInjector()
        for p in (patch("core.system.injector.time.sleep"), patch("core.system.injector.keyboard"),
                  patch("core.system.injector.threading", self.timers),
                  patch("core.system.injector.pyperclip", SimpleNamespace(paste=lambda: self.clip.texto)),
                  patch.object(TextInjector, "_clipboard_has_text", lambda _s: self.clip.texto is not None),
                  patch("core.actions.ActionManager.secure_copy", side_effect=self.clip.escrever)):
            p.start()
            self.addCleanup(p.stop)

    def test_uma_colagem_devolve_o_de_antes(self):
        self.assertEqual(0.25, self.injector.restore_delay)
        self.injector.paste_text("ditado")
        self.assertEqual(0.25, self.timers.criados[0].intervalo)
        self.timers.disparar()
        self.assertEqual("senha copiada", self.clip.texto)

    def test_dois_ditados_seguidos_devolvem_o_da_pessoa(self):
        self.injector.paste_text("primeiro ditado")
        self.injector.paste_text("segundo ditado")  # antes de a volta do primeiro sair
        primeira, _segunda = self.timers.criados
        self.assertTrue(primeira.cancelado, "quem devolve agora é a volta do segundo")
        self.timers.disparar()
        self.assertEqual("senha copiada", self.clip.texto)

    def test_a_pessoa_copiou_entre_os_dois_ditados_fica_o_que_ela_copiou(self):
        self.injector.paste_text("primeiro ditado")
        self.clip.texto = "copiado no meio"
        self.injector.paste_text("segundo ditado")
        self.timers.disparar()
        self.assertEqual("copiado no meio", self.clip.texto)

    def test_sem_texto_antes_o_clipboard_fica_vazio(self):
        self.clip.texto = None
        self.injector.paste_text("ditado")
        self.timers.disparar()
        self.assertEqual("", self.clip.texto)

    def test_a_pessoa_copiou_no_meio_fica_o_que_ela_copiou(self):
        self.injector.paste_text("ditado")
        self.clip.texto = "copiado agora"
        self.timers.disparar()
        self.assertEqual("copiado agora", self.clip.texto)

    def test_volta_que_ja_saiu_nao_e_herdada(self):
        # A volta do primeiro saiu; depois a pessoa copiou, por acaso, o mesmo texto do ditado.
        self.injector.paste_text("ditado")
        self.timers.disparar()
        self.clip.texto = "ditado"
        self.injector.paste_text("outro ditado")
        self.timers.disparar()
        self.assertEqual("ditado", self.clip.texto)

    def test_segunda_colagem_que_falha_nao_cancela_a_volta_da_primeira(self):
        self.injector.paste_text("primeiro ditado")
        self.clip.escrita_falha = True
        self.assertFalse(self.injector.paste_text("segundo ditado"))
        self.clip.escrita_falha = False
        self.timers.disparar()
        self.assertEqual("senha copiada", self.clip.texto)

    def test_timer_ja_expirado_da_primeira_colagem_nao_sobrescreve_segunda_colagem(self):
        """AUD-048: Se o timer da primeira colagem expirou na sua thread enquanto a segunda
        colagem estava sob CLIPBOARD_LOCK (de modo que timer.cancel() já não impede a função
        de rodar), ele não pode restaurar o clipboard antigo imediatamente após o 2º Ctrl+V."""
        self.injector.paste_text("ditado repetido")
        self.injector.paste_text("ditado repetido")
        primeiro_timer, segundo_timer = self.timers.criados
        self.assertTrue(primeiro_timer.cancelado)

        # Simula a thread do primeiro timer que já havia expirado e aguardava CLIPBOARD_LOCK:
        primeiro_timer.funcao()
        self.assertEqual(
            "ditado repetido",
            self.clip.texto,
            "o timer substituído da 1ª colagem não pode sobrescrever o 2º ditado antes do prazo do 2º timer",
        )

        # Apenas quando o segundo timer dispara no seu próprio prazo o clipboard original volta:
        segundo_timer.funcao()
        self.assertEqual("senha copiada", self.clip.texto)


class TestClipboardHasTextFormato(unittest.TestCase):
    def test_clipboard_has_text_consulta_cf_unicodetext_13_e_respeita_falso(self):
        consultados = []
        with patch.object(actions._u32, "IsClipboardFormatAvailable", side_effect=lambda fmt: (consultados.append(fmt), int(fmt == 13))[1]):
            self.assertTrue(TextInjector._clipboard_has_text())
        with patch.object(actions._u32, "IsClipboardFormatAvailable", side_effect=lambda fmt: (consultados.append(fmt), 0)[1]):
            self.assertFalse(TextInjector._clipboard_has_text())
        self.assertEqual([13, 13], consultados)


@unittest.skipUnless(sys.platform == "win32", "formatos brutos Win32 (CF_DIB, CF_HDROP)")
class TestColagemPreservaFormatosNaoTextuais(unittest.TestCase):
    """AUD-047: Formatos não-textuais no clipboard (ex.: imagem CF_DIB=8 ou arquivos CF_HDROP=15)
    não podem ser destruídos por secure_copy('') quando o timer de restauração da colagem dispara."""

    CF_BITMAP = 2
    CF_DIB = 8
    CF_UNICODETEXT = 13
    CF_HDROP = 15
    FORMATO_EXCLUSAO = 0xC0DE

    def setUp(self):
        self.timers = _Timers()
        self.injector = TextInjector()
        self.formatos: dict[int, bytes] = {}
        self._handles_ativos: dict[int, int] = {}

        self.u32_falso = MagicMock()
        self.u32_falso.OpenClipboard.return_value = 1
        self.u32_falso.CloseClipboard.return_value = 1
        self.u32_falso.RegisterClipboardFormatW.return_value = self.FORMATO_EXCLUSAO

        def _is_available(fmt):
            return int(fmt in self.formatos)

        def _enum_formats(anterior):
            chaves = list(self.formatos.keys())
            if anterior == 0:
                return chaves[0] if chaves else 0
            if anterior in chaves:
                idx = chaves.index(anterior)
                return chaves[idx + 1] if idx + 1 < len(chaves) else 0
            return 0

        def _get_data(fmt):
            if fmt == self.CF_BITMAP:
                return 0xDEAD_BEEF  # HBITMAP sintético do GDI (não é HGLOBAL)
            return self._handles_ativos.get(fmt, 0)

        def _empty():
            for h in list(self._handles_ativos.values()):
                actions._k32.GlobalFree(h)
            self._handles_ativos.clear()
            self.formatos.clear()
            return 1

        def _set_data(fmt, h_mem):
            tam = actions._k32.GlobalSize(h_mem)
            ptr = actions._k32.GlobalLock(h_mem)
            try:
                dados = ctypes.string_at(ptr, tam)
            finally:
                actions._k32.GlobalUnlock(h_mem)
            if fmt in self._handles_ativos:
                actions._k32.GlobalFree(self._handles_ativos[fmt])
            self._handles_ativos[fmt] = h_mem
            self.formatos[fmt] = dados
            return h_mem

        self.u32_falso.IsClipboardFormatAvailable.side_effect = _is_available
        self.u32_falso.EnumClipboardFormats.side_effect = _enum_formats
        self.u32_falso.GetClipboardData.side_effect = _get_data
        self.u32_falso.EmptyClipboard.side_effect = _empty
        self.u32_falso.SetClipboardData.side_effect = _set_data
        self._empty_cb = _empty

        def _ler_texto_atual():
            bruto = self.formatos.get(self.CF_UNICODETEXT, b"")
            return bruto.decode("utf-16le", errors="ignore").split("\x00", 1)[0]

        for p in (
            patch.object(actions, "_u32", self.u32_falso),
            patch("core.system.injector.time.sleep"),
            patch("core.system.injector.keyboard"),
            patch("core.system.injector.threading", self.timers),
            patch("core.system.injector.pyperclip", SimpleNamespace(paste=_ler_texto_atual)),
            patch("core.actions.pyperclip.paste", side_effect=_ler_texto_atual),
        ):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        for h in list(self._handles_ativos.values()):
            actions._k32.GlobalFree(h)
        self._handles_ativos.clear()

    def _alocar_hglobal(self, dados: bytes) -> int:
        h = actions._k32.GlobalAlloc(0x0042, max(len(dados), 1))
        ptr = actions._k32.GlobalLock(h)
        ctypes.memmove(ptr, dados, len(dados))
        actions._k32.GlobalUnlock(h)
        return h

    def _popular_clipboard(self, iniciais: dict[int, bytes]):
        self._empty_cb()
        self.formatos = dict(iniciais)
        for fmt, payload in iniciais.items():
            if fmt != self.CF_BITMAP:
                self._handles_ativos[fmt] = self._alocar_hglobal(payload)

    def test_imagem_cf_dib_no_clipboard_e_preservada_apos_colagem(self):
        bytes_imagem = b"BITMAPINFOHEADER_PRINT_DO_USUARIO_987654321"
        self._popular_clipboard({
            self.CF_DIB: bytes_imagem,
            self.CF_BITMAP: b"HANDLE_GDI_IGNORADO",
        })

        self.assertTrue(self.injector.paste_text("texto ditado pelo usuário"))
        self.timers.disparar()

        self.assertIn(self.CF_DIB, self.formatos, "a imagem CF_DIB do usuário foi destruída pela restauração")
        self.assertTrue(self.formatos[self.CF_DIB].startswith(bytes_imagem))
        self.assertNotIn(self.CF_UNICODETEXT, self.formatos, "não deve sobrar texto vazio no lugar da imagem")
        self.assertIn(self.FORMATO_EXCLUSAO, self.formatos)

    def test_dois_ditados_seguidos_preservam_arquivos_cf_hdrop_originais(self):
        bytes_hdrop = b"DROPFILES_C:\\Users\\joao\\planilha.xlsx\x00\x00"
        self._popular_clipboard({self.CF_HDROP: bytes_hdrop})

        self.assertTrue(self.injector.paste_text("primeiro ditado"))
        self.assertTrue(self.injector.paste_text("segundo ditado"))
        self.timers.disparar()

        self.assertIn(self.CF_HDROP, self.formatos, "os arquivos CF_HDROP foram destruídos após dois ditados")
        self.assertTrue(self.formatos[self.CF_HDROP].startswith(bytes_hdrop))
        self.assertNotIn(self.CF_UNICODETEXT, self.formatos)

    def test_usuario_copia_imagem_durante_janela_de_restauracao_nao_e_sobrescrita(self):
        self._popular_clipboard({
            self.CF_UNICODETEXT: "texto antigo\x00".encode("utf-16le"),
        })

        self.assertTrue(self.injector.paste_text("ditado"))
        # Antes de o timer de 250 ms disparar, o usuário tirou um print (CF_DIB)
        nova_imagem = b"NOVO_PRINT_TIRADO_PELO_USUARIO"
        self._popular_clipboard({self.CF_DIB: nova_imagem})

        self.timers.disparar()

        self.assertIn(self.CF_DIB, self.formatos, "o novo print tirado pelo usuário foi sobrescrito")
        self.assertTrue(self.formatos[self.CF_DIB].startswith(nova_imagem))
        self.assertNotIn(self.CF_UNICODETEXT, self.formatos)


if __name__ == "__main__":
    unittest.main()
