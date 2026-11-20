"""
Testes do escritor de clipboard Win32 de `core.actions` (ActionManager.secure_copy).

As DLLs são substituídas por mocks: nenhum teste aqui toca o clipboard real da máquina.
A memória para onde o texto é copiado é um buffer ctypes de verdade, então o teste também
confere os bytes que chegariam ao sistema.
"""

import ctypes
import sys
import unittest
from unittest.mock import MagicMock, patch

from core import actions
from core.actions import ActionManager, EstadoClipboard


@unittest.skipUnless(sys.platform == "win32", "escritor Win32")
class TestPrototipos64Bits(unittest.TestCase):
    """Sem restype, o ctypes devolve c_int e trunca handles de 64 bits."""

    def test_handles_e_ponteiros_tem_tamanho_de_ponteiro(self):
        tamanho = ctypes.sizeof(ctypes.c_void_p)
        for fn in (
            actions._k32.GlobalAlloc,
            actions._k32.GlobalLock,
            actions._k32.GlobalFree,
            actions._k32.GlobalSize,
            actions._u32.SetClipboardData,
            actions._u32.GetClipboardData,
        ):
            with self.subTest(fn=fn.__name__):
                self.assertEqual(tamanho, ctypes.sizeof(fn.restype))

    def test_instancias_proprias_nao_dependem_do_windll_global(self):
        self.assertIsNot(actions._k32, ctypes.windll.kernel32)
        self.assertIsNot(actions._u32, ctypes.windll.user32)


class TestSecureCopy(unittest.TestCase):
    FORMATO_EXCLUSAO = 0xC0DE
    FORMATO_NUVEM = 0xC0DF

    def setUp(self):
        self.memoria = []
        self.k32 = MagicMock()
        self.u32 = MagicMock()
        self.k32.GlobalAlloc.side_effect = lambda flags, n: 1000 + len(self.memoria)

        def _lock(h):
            buf = ctypes.create_string_buffer(64)
            self.memoria.append(buf)
            return ctypes.addressof(buf)

        self.k32.GlobalLock.side_effect = _lock
        self.u32.OpenClipboard.return_value = True
        self.u32.SetClipboardData.return_value = 1
        formatos = {"ExcludeClipboardContentFromMonitorProcessing": self.FORMATO_EXCLUSAO,
                    "CanUploadToCloudClipboard": self.FORMATO_NUVEM}
        self.u32.RegisterClipboardFormatW.side_effect = formatos.__getitem__
        patchers = [
            patch.object(actions, "_k32", self.k32),
            patch.object(actions, "_u32", self.u32),
            patch.object(actions.time, "sleep"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_grava_texto_e_marca_de_exclusao(self):
        self.assertTrue(ActionManager.secure_copy("olá"))

        formatos = [c.args[0] for c in self.u32.SetClipboardData.call_args_list]
        self.assertEqual([actions._CF_UNICODETEXT, self.FORMATO_EXCLUSAO], formatos)
        self.assertEqual("olá\x00".encode("utf-16le"), self.memoria[0].raw[:8])
        self.u32.CloseClipboard.assert_called_once()

    def test_copia_pedida_vai_ao_win_v(self):
        # ocultar_do_historico=False: sem a marca de exclusão, o texto aparece no Win+V (decisão do
        # dono, 24/10); só não sobe para a nuvem (CanUploadToCloudClipboard, um DWORD 0).
        self.assertTrue(ActionManager.secure_copy("olá", ocultar_do_historico=False))

        formatos = [c.args[0] for c in self.u32.SetClipboardData.call_args_list]
        self.assertEqual([actions._CF_UNICODETEXT, self.FORMATO_NUVEM], formatos)
        self.assertEqual("olá\x00".encode("utf-16le"), self.memoria[0].raw[:8])
        self.assertEqual(4, self.k32.GlobalAlloc.call_args_list[1].args[1])
        self.assertEqual(b"\x00" * 4, self.memoria[1].raw[:4])
        self.u32.CloseClipboard.assert_called_once()

    def test_padrao_continua_fora_do_win_v(self):
        ActionManager.secure_copy("senha")
        ActionManager.secure_copy("senha", ocultar_do_historico=True)
        formatos = [c.args[0] for c in self.u32.SetClipboardData.call_args_list]
        self.assertEqual(2, formatos.count(self.FORMATO_EXCLUSAO))

    def test_falha_no_set_libera_a_memoria_e_fecha_o_clipboard(self):
        self.u32.SetClipboardData.return_value = 0

        self.assertFalse(ActionManager.secure_copy("texto"))

        self.k32.GlobalFree.assert_called_once_with(1000)
        self.u32.CloseClipboard.assert_called_once()

    def test_excecao_no_meio_ainda_fecha_o_clipboard(self):
        """Clipboard deixado aberto trava a cópia em todos os outros programas."""
        self.u32.EmptyClipboard.side_effect = OSError("boom")

        with self.assertRaises(OSError):
            ActionManager.secure_copy("texto")

        self.u32.CloseClipboard.assert_called_once()

    def test_clipboard_ocupado_desiste_sem_escrever(self):
        self.u32.OpenClipboard.return_value = False

        self.assertFalse(ActionManager.secure_copy("texto"))

        self.assertEqual(actions._OPEN_TENTATIVAS, self.u32.OpenClipboard.call_count)
        self.u32.EmptyClipboard.assert_not_called()
        self.u32.CloseClipboard.assert_not_called()

    def test_ocupado_na_primeira_tentativa_consegue_na_segunda(self):
        self.u32.OpenClipboard.side_effect = [False, True]

        self.assertTrue(ActionManager.secure_copy("texto"))

    def test_captura_filtra_formatos_gdi_e_restaura_formatos_hglobal(self):
        """CF_BITMAP (2) e faixas GDI (0x0200..0x03FF) não são HGLOBAL e são ignorados;
        CF_DIB (8) é capturado sem chamar GlobalFree no handle do sistema e restaurado."""
        buf_dib = ctypes.create_string_buffer(b"DIB_PAYLOAD", 11)
        self.u32.IsClipboardFormatAvailable.return_value = 0
        # Enumera: 2 (CF_BITMAP, ignorado), 0x0300 (GDI, ignorado), 8 (CF_DIB, lido), 0 (fim)
        self.u32.EnumClipboardFormats.side_effect = [2, 0x0300, 8, 0]
        self.u32.GetClipboardData.side_effect = lambda fmt: 777 if fmt == 8 else 0
        self.k32.GlobalSize.side_effect = lambda h: 11 if h == 777 else 0
        self.k32.GlobalLock.side_effect = lambda h: (
            ctypes.addressof(buf_dib) if h == 777 else self._alloc_lock(h)
        )

        estado = ActionManager.capturar_clipboard()

        self.assertEqual(
            EstadoClipboard(tinha_texto=False, texto="", formatos_brutos=((8, b"DIB_PAYLOAD"),)),
            estado,
        )
        self.assertTrue(estado.tinha_conteudo)
        # Handles de GetClipboardData pertencem ao sistema: GlobalFree jamais deve ser chamado neles
        self.k32.GlobalFree.assert_not_called()
        self.k32.GlobalUnlock.assert_called_once_with(777)

        # Configura GlobalLock de volta para a escrita da restauração
        def _lock_escrita(h):
            buf = ctypes.create_string_buffer(64)
            self.memoria.append(buf)
            return ctypes.addressof(buf)

        self.k32.GlobalLock.side_effect = _lock_escrita
        self.assertTrue(ActionManager.restaurar_clipboard(estado))

        formatos_gravados = [c.args[0] for c in self.u32.SetClipboardData.call_args_list]
        self.assertEqual([8, self.FORMATO_EXCLUSAO], formatos_gravados)
        self.assertEqual(b"DIB_PAYLOAD", self.memoria[0].raw[:11])


@unittest.skipUnless(sys.platform == "win32", "memória global e formatos Win32 reais")
class TestMemoriaEFormatosWin32Reais(unittest.TestCase):
    """Usa o _k32 real (GlobalAlloc, GlobalLock, GlobalUnlock, GlobalFree) e o
    _u32.RegisterClipboardFormatW real do Windows, interceptando apenas o envio ao clipboard
    para não alterar a área de transferência do usuário."""

    def test_aloca_memoria_global_real_de_64_bits_e_registra_formatos_reais(self):
        handles_recebidos = []

        def _capturar_set_clipboard(formato, h_mem):
            ptr = actions._k32.GlobalLock(h_mem)
            self.assertTrue(ptr, "GlobalLock real devolveu ponteiro nulo")
            try:
                # Se for texto Unicode, lê os 16 primeiros bytes; se for DWORD, lê 4 bytes
                tam = 22 if formato == actions._CF_UNICODETEXT else 4
                dados = ctypes.string_at(ptr, tam)
                handles_recebidos.append((formato, h_mem, dados))
            finally:
                actions._k32.GlobalUnlock(h_mem)
            # Como interceptamos SetClipboardData, liberamos o HGLOBAL real aqui
            self.assertIsNone(actions._k32.GlobalFree(h_mem))
            return h_mem

        with patch.object(actions._u32, "OpenClipboard", return_value=1),                 patch.object(actions._u32, "EmptyClipboard", return_value=1),                 patch.object(actions._u32, "SetClipboardData", side_effect=_capturar_set_clipboard),                 patch.object(actions._u32, "CloseClipboard", return_value=1):
            self.assertTrue(ActionManager.secure_copy("Willy 64!", ocultar_do_historico=True))
            self.assertTrue(ActionManager.secure_copy("Willy WinV", ocultar_do_historico=False))

        self.assertEqual(4, len(handles_recebidos))
        fmt_texto_1, _, bytes_texto_1 = handles_recebidos[0]
        fmt_excl, _, bytes_excl = handles_recebidos[1]
        fmt_texto_2, _, bytes_texto_2 = handles_recebidos[2]
        fmt_nuvem, _, bytes_nuvem = handles_recebidos[3]

        self.assertEqual(actions._CF_UNICODETEXT, fmt_texto_1)
        self.assertTrue(bytes_texto_1.startswith("Willy 64!\x00".encode("utf-16le")))
        self.assertGreaterEqual(fmt_excl, 0xC000, "RegisterClipboardFormatW real deve devolver ID >= 0xC000")
        self.assertEqual(b"\x00" * 4, bytes_excl)

        self.assertEqual(actions._CF_UNICODETEXT, fmt_texto_2)
        self.assertTrue(bytes_texto_2.startswith("Willy WinV\x00".encode("utf-16le")))
        self.assertGreaterEqual(fmt_nuvem, 0xC000)
        self.assertNotEqual(fmt_excl, fmt_nuvem)
        self.assertEqual(b"\x00" * 4, bytes_nuvem)


if __name__ == "__main__":
    unittest.main()
