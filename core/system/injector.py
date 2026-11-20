"""
Módulo de Injeção de Texto e Controle de Área de Transferência do Willy.
"""

import sys
import threading
import time
from typing import NamedTuple

from core.actions import CLIPBOARD_LOCK, ActionManager, EstadoClipboard

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    import pyperclip
except ImportError:
    pyperclip = None


class _Restauracao(NamedTuple):
    """A volta do clipboard agendada por uma colagem, enquanto não sai."""

    timer: threading.Timer
    colado: str                # o texto que a colagem escreveu
    original: EstadoClipboard  # o clipboard da pessoa antes dela (texto, formatos brutos ou vazio)


class TextInjector:
    """
    Injeta texto simulando Ctrl+V e opcionalmente Enter, com preservação
    estrita e atômica da área de transferência original via try/finally e sentinela (ACH-04).
    """

    def __init__(self, restore_delay: float = 0.25):
        self.restore_delay = restore_delay
        self._restauracao: _Restauracao | None = None

    @staticmethod
    def _clipboard_has_text() -> bool:
        """Verifica se a área de transferência do Windows possui texto antes da injeção."""
        return ActionManager.clipboard_has_text()

    def paste_text(self, text: str, auto_send: bool = False) -> bool:
        """
        Injeta o texto na janela atualmente em foco através da área de transferência.
        Garante que o conteúdo original do clipboard seja preservado e restaurado
        apenas se o usuário não tiver copiado algo novo no intervalo.
        """
        if not text or not pyperclip or not keyboard:
            return False

        with CLIPBOARD_LOCK:
            estado_atual = ActionManager.capturar_clipboard(
                tem_texto=self._clipboard_has_text(),
                leitor_texto=pyperclip.paste,
            )
            pendente = self._restauracao
            if pendente and estado_atual.tinha_texto and estado_atual.texto == pendente.colado:
                # A colagem anterior ainda não devolveu o clipboard: ele tem o texto dela, e o da
                # pessoa é o de antes. Dois ditados seguidos deixavam o primeiro no clipboard, e
                # o que a pessoa tinha copiado (texto, imagem ou arquivos) se perdia.
                original = pendente.original
            else:
                original = estado_atual

            escreveu = False
            try:
                # Única escrita, já marcada para ficar fora do Win+V. Se falhou, o clipboard
                # ainda tem o conteúdo anterior (talvez uma senha): colar seria injetá-lo.
                if not ActionManager.secure_copy(text):
                    return False
                escreveu = True
                if pendente:
                    # Esta colagem assume a volta: a anterior devolveria o texto que estava nele.
                    pendente.timer.cancel()
                    self._restauracao = None
                time.sleep(0.06)
                keyboard.send("ctrl+v")

                if auto_send:
                    time.sleep(0.08)
                    keyboard.send("enter")

                return True
            except Exception as e:  # noqa: BLE001 — fronteira de injeção de teclado/clipboard
                print(f"[TextInjector] falha ao colar: {e!r}", file=sys.stderr)
                return False
            finally:
                # Só há o que restaurar se o clipboard foi de fato sobrescrito por algo diferente.
                mesmo_texto = (
                    original.tinha_texto
                    and not original.formatos_brutos
                    and original.texto == text
                )
                if escreveu and not mesmo_texto:
                    def _restaurar():
                        with CLIPBOARD_LOCK:
                            if self._restauracao is not registro:
                                # Outra colagem já substituiu ou cancelou esta restauração:
                                # não tocar no clipboard nem sobrescrever o novo ditado.
                                return
                            try:
                                # Restaurar via ActionManager.restaurar_clipboard: devolve texto ou
                                # formatos brutos HGLOBAL (CF_DIB, CF_HDROP) fora do histórico Win+V.
                                if (
                                    self._clipboard_has_text()
                                    and pyperclip
                                    and pyperclip.paste() == text
                                ):
                                    ActionManager.restaurar_clipboard(original)
                            except Exception as e:  # noqa: BLE001 — fronteira de restauração assíncrona do clipboard
                                print(f"[TextInjector] falha ao restaurar clipboard: {e!r}",
                                      file=sys.stderr)
                            finally:
                                # Já saiu: uma colagem depois desta não pode herdar o original dela.
                                if self._restauracao is registro:
                                    self._restauracao = None

                    timer = threading.Timer(self.restore_delay, _restaurar)
                    timer.daemon = True
                    registro = self._restauracao = _Restauracao(timer, text, original)
                    timer.start()


# Instância global compartilhada
default_injector = TextInjector()
