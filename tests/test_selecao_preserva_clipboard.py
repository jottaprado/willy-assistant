"""
Ler a seleção (Ctrl+Alt+S, Ctrl+Alt+T) não destrói o clipboard da pessoa.

- Com a seleção lida, o clipboard ficava com ela: o que a pessoa tinha copiado antes se perdia,
  e a colagem do resultado ainda "restaurava" a seleção no lugar.
- O .strip() tirava o recuo da primeira linha: um trecho de código perdia a indentação.
- O Ctrl+C saía com o Alt do atalho ainda pressionado, como Ctrl+Alt+C, que não copia (e num
  teclado ABNT2 é o AltGr+C, que digita "₢" por cima da seleção). Agora espera o Alt subir, e
  se ele não sobe (a pessoa segurando o atalho) não copia nem toca o clipboard.
- Com a sentinela recusada, o clipboard não tinha mudado, mas era "restaurado": sem texto antes,
  o secure_copy("") apagava a imagem que estivesse nele.

Nada aqui toca o clipboard ou o teclado de verdade: o ctypes do import local, o pyperclip, o
secure_copy, o keyboard e o GetAsyncKeyState são falsos.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from core.actions import ActionManager


class _Teclado:
    """Alt preso pelas primeiras `leituras` consultas; registra a ordem dos primeiros eventos.

    Depois de dez, só conta (sem guardar): um laço sem limite não pode encher a memória.
    """

    def __init__(self, leituras_com_alt=0, tinha_texto=True):
        self.alt, self.eventos, self.consultas_com_alt = leituras_com_alt, [], 0
        self.tinha_texto = tinha_texto
        self.formatos_consultados = []

    def IsClipboardFormatAvailable(self, fmt):
        self.formatos_consultados.append(fmt)
        return self.tinha_texto if fmt == 13 else False

    def GetAsyncKeyState(self, vk):
        if vk == 0x12 and self.alt > 0:
            self.alt -= 1
            self.consultas_com_alt += 1
            if len(self.eventos) < 10:
                self.eventos.append("alt preso")
            return -32768  # bit 0x8000 ligado, como o c_short devolve
        return 0


class _Relogio:
    """time.monotonic que anda 10 ms a cada leitura: a espera tem fim mesmo com o sleep falso."""

    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        self.agora += 0.01
        return self.agora


class TestSelecao(unittest.TestCase):
    def _ler(self, antes, selecao, tinha_texto=True, alt=0, escrita_ok=True):
        self.escritos, self.teclado = [], _Teclado(alt, tinha_texto=tinha_texto)
        estado = {"copiou": False}

        def _send(tecla):
            self.teclado.eventos.append(tecla)
            estado["copiou"] = True

        def _paste():
            if estado["copiou"]:
                return selecao if selecao is not None else self.escritos[-1]  # sem seleção, fica a sentinela
            return antes

        with patch("core.actions.pyperclip") as clip, \
             patch.object(ActionManager, "secure_copy", side_effect=lambda t: self.escritos.append(t) or escrita_ok), \
             patch("core.actions.keyboard") as teclado, \
             patch("core.actions._u32", self.teclado), \
             patch("core.actions.time.monotonic", _Relogio()), \
             patch("core.actions.time.sleep"):
            clip.paste.side_effect = _paste
            teclado.send.side_effect = _send
            return ActionManager.get_selected_text()

    def test_com_selecao_o_clipboard_volta_ao_de_antes(self):
        self.assertEqual("contrato", self._ler(antes="senha copiada antes", selecao="contrato"))
        self.assertEqual("senha copiada antes", self.escritos[-1])

    def test_clipboard_vazio_antes_fica_vazio_depois(self):
        self._ler(antes="", selecao="contrato", tinha_texto=False)
        self.assertEqual("", self.escritos[-1])

    def test_recuo_da_primeira_linha_fica(self):
        codigo = "    if ok:\n        return 1\n"
        self.assertEqual("    if ok:\n        return 1", self._ler(antes="", selecao=codigo, tinha_texto=False))

    def test_espera_o_alt_subir_antes_do_ctrl_c(self):
        self._ler(antes="x", selecao="contrato", alt=3)
        self.assertEqual(["alt preso", "alt preso", "alt preso", "ctrl+c"], self.teclado.eventos)

    def test_alt_preso_nao_copia_nem_toca_o_clipboard(self):
        self.assertIsNone(self._ler(antes="x", selecao="contrato", alt=5000))
        self.assertLessEqual(self.teclado.consultas_com_alt, 30, "a espera passou dos 250 ms")
        self.assertNotIn("ctrl+c", self.teclado.eventos)
        self.assertEqual([], self.escritos)

    def test_sentinela_recusada_nao_restaura(self):
        self.assertIsNone(self._ler(antes="", selecao="contrato", tinha_texto=False, escrita_ok=False))
        self.assertEqual(1, len(self.escritos), "só a tentativa da sentinela")

    def test_sentinela_recusada_com_texto_antes_tenta_devolver(self):
        # O secure_copy recusado pode ter esvaziado o clipboard (falha depois do EmptyClipboard).
        self.assertIsNone(self._ler(antes="senha copiada antes", selecao="contrato", escrita_ok=False))
        self.assertEqual("senha copiada antes", self.escritos[-1])

    def test_sem_selecao_o_clipboard_tambem_volta(self):
        self.assertIsNone(self._ler(antes="senha copiada antes", selecao=None))
        self.assertEqual("senha copiada antes", self.escritos[-1])


class TestEsperaDoAtalho(unittest.TestCase):
    def _esperar(self, leituras_com_alt, **kw):
        with patch("core.actions._u32", _Teclado(leituras_com_alt)), \
             patch("core.actions.time.monotonic", _Relogio()), \
             patch("core.actions.time.sleep"):
            return ActionManager.esperar_modificadores_soltos(**kw)

    def test_padrao_e_o_da_thread_do_atalho(self):
        self.assertTrue(self._esperar(10))     # ~100 ms
        self.assertFalse(self._esperar(100))   # ~1 s: passa dos 250 ms

    def test_quem_pode_espera_mais(self):
        self.assertTrue(self._esperar(100, espera_s=2.0))
        self.assertFalse(self._esperar(400, espera_s=2.0))


@unittest.skipUnless(sys.platform == "win32", "clipboard Win32 com HGLOBAL real")
class TestSelecaoPreservaFormatosNaoTextuais(unittest.TestCase):
    """Reproduz e previne o AUD-011: imagem (CF_DIB) ou arquivos (CF_HDROP) no clipboard
    não podem ser apagados por secure_copy('') ao capturar (ou tentar capturar) a seleção."""

    CF_DIB = 8
    CF_UNICODETEXT = 13
    CF_HDROP = 15
    CF_BITMAP = 2  # handle GDI não-HGLOBAL: deve ser ignorado sem travar GlobalLock
    FORMATO_EXCLUSAO = 0xC0DE

    def setUp(self):
        import ctypes

        from core import actions

        self.actions = actions
        self.ctypes = ctypes
        self.formatos: dict[int, bytes] = {}
        self._handles_ativos: dict[int, int] = {}

    def tearDown(self):
        for h in list(self._handles_ativos.values()):
            self.actions._k32.GlobalFree(h)
        self._handles_ativos.clear()

    def _alocar_hglobal(self, dados: bytes) -> int:
        h = self.actions._k32.GlobalAlloc(0x0042, max(len(dados), 1))
        ptr = self.actions._k32.GlobalLock(h)
        self.ctypes.memmove(ptr, dados, len(dados))
        self.actions._k32.GlobalUnlock(h)
        return h

    def _popular_clipboard_inicial(self, iniciais: dict[int, bytes]):
        self.formatos = dict(iniciais)
        for fmt, payload in iniciais.items():
            if fmt != self.CF_BITMAP:
                self._handles_ativos[fmt] = self._alocar_hglobal(payload)

    def _executar_get_selected_text(self, selecao_copiada: str | None):
        u32_falso = MagicMock()
        u32_falso.GetAsyncKeyState.return_value = 0
        u32_falso.OpenClipboard.return_value = 1
        u32_falso.CloseClipboard.return_value = 1
        u32_falso.RegisterClipboardFormatW.return_value = self.FORMATO_EXCLUSAO

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
                return 0xDEAD_BEEF  # HBITMAP sintético (não é HGLOBAL)
            return self._handles_ativos.get(fmt, 0)

        def _empty():
            for h in list(self._handles_ativos.values()):
                self.actions._k32.GlobalFree(h)
            self._handles_ativos.clear()
            self.formatos.clear()
            return 1

        def _set_data(fmt, h_mem):
            tam = 128
            if hasattr(self.actions._k32, "GlobalSize") and getattr(self.actions._k32.GlobalSize, "argtypes", None):
                tam = self.actions._k32.GlobalSize(h_mem)
            ptr = self.actions._k32.GlobalLock(h_mem)
            try:
                dados = self.ctypes.string_at(ptr, tam)
            finally:
                self.actions._k32.GlobalUnlock(h_mem)
            if fmt in self._handles_ativos:
                self.actions._k32.GlobalFree(self._handles_ativos[fmt])
            self._handles_ativos[fmt] = h_mem
            self.formatos[fmt] = dados
            return h_mem

        u32_falso.IsClipboardFormatAvailable.side_effect = _is_available
        u32_falso.EnumClipboardFormats.side_effect = _enum_formats
        u32_falso.GetClipboardData.side_effect = _get_data
        u32_falso.EmptyClipboard.side_effect = _empty
        u32_falso.SetClipboardData.side_effect = _set_data

        def _ler_texto_atual():
            bruto = self.formatos.get(self.CF_UNICODETEXT, b"")
            return bruto.decode("utf-16le", errors="ignore").split("\x00", 1)[0]

        def _simular_ctrl_c(tecla):
            if tecla == "ctrl+c" and selecao_copiada is not None:
                _empty()
                payload = selecao_copiada.encode("utf-16le") + b"\x00\x00"
                h = self._alocar_hglobal(payload)
                self._handles_ativos[self.CF_UNICODETEXT] = h
                self.formatos[self.CF_UNICODETEXT] = payload

        with patch.object(self.actions, "_u32", u32_falso), \
             patch("core.actions.pyperclip.paste", side_effect=_ler_texto_atual), \
             patch("core.actions.keyboard.send", side_effect=_simular_ctrl_c), \
             patch("core.actions.time.sleep"):
            return ActionManager.get_selected_text()

    def test_imagem_no_clipboard_e_preservada_apos_capturar_selecao(self):
        bytes_imagem = b"BITMAPINFOHEADER_SCREENSHOT_DO_USUARIO_1234567890"
        self._popular_clipboard_inicial({
            self.CF_DIB: bytes_imagem,
            self.CF_BITMAP: b"HANDLE_GDI_IGNORADO",
        })

        texto = self._executar_get_selected_text("trecho selecionado no editor")

        self.assertEqual("trecho selecionado no editor", texto)
        self.assertIn(self.CF_DIB, self.formatos, "a imagem CF_DIB do usuário foi destruída")
        self.assertTrue(self.formatos[self.CF_DIB].startswith(bytes_imagem))
        self.assertNotIn(self.CF_UNICODETEXT, self.formatos, "não deve sobrar texto vazio no lugar da imagem")
        self.assertIn(self.FORMATO_EXCLUSAO, self.formatos)

    def test_arquivos_copiados_cf_hdrop_sao_preservados_mesmo_sem_selecao(self):
        bytes_hdrop = b"DROPFILES_C:\\Users\\joao\\relatorio.docx\x00\x00"
        self._popular_clipboard_inicial({self.CF_HDROP: bytes_hdrop})

        texto = self._executar_get_selected_text(None)

        self.assertIsNone(texto)
        self.assertIn(self.CF_HDROP, self.formatos, "os arquivos copiados (CF_HDROP) foram destruídos")
        self.assertTrue(self.formatos[self.CF_HDROP].startswith(bytes_hdrop))
        self.assertNotIn(self.CF_UNICODETEXT, self.formatos)


class TestPollingDeSelecaoEFailSafeModificadores(unittest.TestCase):
    """AUD-012 e AUD-013: Polling curto após Ctrl+C e tratamento fail-safe de GetAsyncKeyState."""

    def test_selecao_tardia_do_app_alvo_e_capturada_via_polling(self):
        escritos = []
        teclado = _Teclado(0, tinha_texto=True)
        estado = {"copiou": False, "leituras_pos_ctrl_c": 0}

        def _send(tecla):
            teclado.eventos.append(tecla)
            estado["copiou"] = True

        def _paste():
            if not estado["copiou"]:
                return "senha copiada antes"
            estado["leituras_pos_ctrl_c"] += 1
            if estado["leituras_pos_ctrl_c"] < 4:
                return escritos[-1]  # ainda contém a sentinela nas 3 primeiras leituras
            return "seleção tardia"

        with patch("core.actions.pyperclip") as clip, \
             patch.object(ActionManager, "secure_copy", side_effect=lambda t: escritos.append(t) or True), \
             patch("core.actions.keyboard") as kbd, \
             patch("core.actions._u32", teclado), \
             patch("core.actions.time.monotonic", _Relogio()), \
             patch("core.actions.time.sleep"):
            clip.paste.side_effect = _paste
            kbd.send.side_effect = _send
            resultado = ActionManager.get_selected_text()

        self.assertEqual("seleção tardia", resultado)
        self.assertEqual(4, estado["leituras_pos_ctrl_c"])
        self.assertEqual("senha copiada antes", escritos[-1])

    def test_excecao_em_get_async_key_state_loga_e_retorna_false(self):
        import io
        from contextlib import redirect_stderr

        u32_quebrado = MagicMock()
        u32_quebrado.GetAsyncKeyState.side_effect = OSError("falha Win32 GetAsyncKeyState")
        buf = io.StringIO()
        with patch("core.actions._u32", u32_quebrado), redirect_stderr(buf):
            ok = ActionManager.esperar_modificadores_soltos()

        self.assertFalse(ok)
        self.assertIn("[ActionManager]", buf.getvalue())
        self.assertIn("GetAsyncKeyState", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
