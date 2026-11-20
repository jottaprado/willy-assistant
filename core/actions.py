"""
Módulo de Ações Rápidas por Voz (Voice Copilot) do Willy.
Permite executar transformações de IA com um comando falado sobre o texto selecionado
(ou gerar respostas rápidas instantâneas).
"""

import ctypes
import re
import sys
import threading
import time
from typing import NamedTuple

import keyboard
import pyperclip

CLIPBOARD_LOCK = threading.RLock()

# Instâncias PRÓPRIAS de kernel32/user32, com protótipos declarados. Sem restype, o ctypes
# devolve c_int e trunca os handles de 64 bits (GlobalAlloc 0x1cc3f110058 virava
# 0x3f110008): o memmove escrevia num endereço inválido. O código antigo só funcionava
# porque o pyperclip reescreve os protótipos do `ctypes.windll` global como efeito
# colateral — o que deixava a privacidade refém de uma chamada que a destruía.
if sys.platform == "win32":
    from ctypes import wintypes as _wt

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32.GlobalAlloc.argtypes = [_wt.UINT, ctypes.c_size_t]
    _k32.GlobalAlloc.restype = _wt.HGLOBAL
    _k32.GlobalLock.argtypes = [_wt.HGLOBAL]
    _k32.GlobalLock.restype = ctypes.c_void_p
    _k32.GlobalUnlock.argtypes = [_wt.HGLOBAL]
    _k32.GlobalUnlock.restype = _wt.BOOL
    _k32.GlobalFree.argtypes = [_wt.HGLOBAL]
    _k32.GlobalFree.restype = _wt.HGLOBAL
    _k32.GlobalSize.argtypes = [_wt.HGLOBAL]
    _k32.GlobalSize.restype = ctypes.c_size_t
    _u32.OpenClipboard.argtypes = [_wt.HWND]
    _u32.OpenClipboard.restype = _wt.BOOL
    _u32.EmptyClipboard.argtypes = []
    _u32.EmptyClipboard.restype = _wt.BOOL
    _u32.CloseClipboard.argtypes = []
    _u32.CloseClipboard.restype = _wt.BOOL
    _u32.SetClipboardData.argtypes = [_wt.UINT, _wt.HANDLE]
    _u32.SetClipboardData.restype = _wt.HANDLE
    _u32.GetClipboardData.argtypes = [_wt.UINT]
    _u32.GetClipboardData.restype = _wt.HANDLE
    _u32.EnumClipboardFormats.argtypes = [_wt.UINT]
    _u32.EnumClipboardFormats.restype = _wt.UINT
    _u32.RegisterClipboardFormatW.argtypes = [_wt.LPCWSTR]
    _u32.RegisterClipboardFormatW.restype = _wt.UINT
    _u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _u32.GetAsyncKeyState.restype = ctypes.c_short
    _u32.IsClipboardFormatAvailable.argtypes = [_wt.UINT]
    _u32.IsClipboardFormatAvailable.restype = _wt.BOOL
else:
    _k32 = None
    _u32 = None

_GMEM_MOVEABLE_ZEROINIT = 0x0042
_VK_SHIFT, _VK_MENU = 0x10, 0x12  # Shift e Alt
_ESPERA_DOS_MODIFICADORES_S = 0.25
_PASSO_POLL_SELECAO_S = 0.015
_TENTATIVAS_POLL_SELECAO = 16


def _esperar_modificadores_soltos(espera_s: float = _ESPERA_DOS_MODIFICADORES_S) -> bool:
    """Espera o Alt e o Shift do atalho subirem (até `espera_s`) antes do Ctrl+C. Devolve se subiram.

    O Ctrl+Alt+T e o Ctrl+Alt+S chegam com o Alt ainda pressionado: o Ctrl+C saía como
    Ctrl+Alt+C, que não copia, e a pessoa via "Selecione um texto" com o texto selecionado.
    Num teclado ABNT2, Ctrl+Alt+C é o AltGr+C, que digita "₢" por cima da seleção.
    """
    if _u32 is None:
        return True
    fim = time.monotonic() + espera_s
    try:
        while any(_u32.GetAsyncKeyState(vk) & 0x8000 for vk in (_VK_MENU, _VK_SHIFT)):
            if time.monotonic() >= fim:
                return False
            time.sleep(0.01)
    except Exception as e:  # noqa: BLE001 — fronteira defensiva: GetAsyncKeyState Win32/ctypes
        print(
            f"[ActionManager] falha ao verificar modificadores (GetAsyncKeyState): {e!r}",
            file=sys.stderr,
        )
        return False
    return True


_CF_UNICODETEXT = 13
_OPEN_TENTATIVAS = 10
_OPEN_ESPERA_S = 0.02

# Formatos ignorados na captura bruta não textual:
# - Textuais/sintéticos de texto: 1 (CF_TEXT), 7 (CF_OEMTEXT), 13 (CF_UNICODETEXT), 16 (CF_LOCALE);
# - Handles pertencentes ao GDI (HBITMAP, HMETAFILEPICT, HPALETTE, HENHMETAFILE) e não a blocos
#   HGLOBAL manipuláveis por GlobalLock/GlobalSize: 2, 3, 9, 14, 0x0082, 0x0083, 0x008E (o Windows
#   sintetiza CF_BITMAP=2 e CF_PALETTE=9 automaticamente a partir de CF_DIB=8 e CF_DIBV5=17).
# As faixas 0x0200..0x02FF (CF_PRIVATEFIRST..LAST) e 0x0300..0x03FF (CF_GDIOBJFIRST..LAST)
# também usam semântica própria de liberação.
_FORMATOS_NAO_HGLOBAL = frozenset({1, 2, 3, 7, 9, 13, 14, 16, 0x0082, 0x0083, 0x008E})
_LIMITE_BYTES_CLIPBOARD = 64 * 1024 * 1024  # 64 MB
_OPEN_CLIPBOARD_NATIVO = _u32.OpenClipboard if _u32 is not None else None


class EstadoClipboard(NamedTuple):
    """Fotografia do conteúdo da área de transferência antes de uma escrita temporária."""

    tinha_texto: bool
    texto: str = ""
    formatos_brutos: tuple[tuple[int, bytes], ...] = ()

    @property
    def tinha_conteudo(self) -> bool:
        return self.tinha_texto or bool(self.formatos_brutos)


def _abrir_clipboard() -> bool:
    """Tenta abrir o clipboard Win32 com retentativas curtas se outro processo o estiver usando."""
    if _u32 is None:
        return False
    for _ in range(_OPEN_TENTATIVAS):
        if _u32.OpenClipboard(None):
            return True
        time.sleep(_OPEN_ESPERA_S)
    return False


def _eh_formato_hglobal(fmt: int) -> bool:
    if fmt <= 0 or fmt in _FORMATOS_NAO_HGLOBAL:
        return False
    return not (0x0200 <= fmt <= 0x03FF)


def _ler_formatos_brutos() -> tuple[tuple[int, bytes], ...]:
    """Lê todos os formatos baseados em HGLOBAL presentes no clipboard (ex.: CF_DIB, CF_HDROP, PNG).

    Usado quando o clipboard não contém CF_UNICODETEXT (ex.: o usuário copiou um print ou
    arquivos no Explorer) para que a escrita temporária não destrua esses dados na restauração.
    """
    if _u32 is None or _k32 is None:
        return ()
    # Se um teste substituiu `ActionManager.secure_copy` por mock mas manteve `_u32.OpenClipboard`
    # apontando para a DLL real do Windows, não abrimos o clipboard real da máquina hospedeira.
    if (
        _OPEN_CLIPBOARD_NATIVO is not None
        and getattr(_u32, "OpenClipboard", None) is _OPEN_CLIPBOARD_NATIVO
        and ActionManager.__dict__.get("secure_copy") is not _SECURE_COPY_NATIVO
    ):
        return ()
    try:
        if not _abrir_clipboard():
            return ()
    except AttributeError:
        return ()
    formatos: list[tuple[int, bytes]] = []
    bytes_acumulados = 0
    vistos: set[int] = set()
    try:
        fmt = 0
        while len(vistos) < 256:
            proximo = _u32.EnumClipboardFormats(fmt)
            if not isinstance(proximo, int) or proximo <= 0 or proximo in vistos:
                break
            fmt = proximo
            vistos.add(fmt)
            if not _eh_formato_hglobal(fmt):
                continue
            h = _u32.GetClipboardData(fmt)
            if not h:
                continue
            tamanho = _k32.GlobalSize(h)
            if (
                not isinstance(tamanho, int)
                or tamanho <= 0
                or (bytes_acumulados + tamanho) > _LIMITE_BYTES_CLIPBOARD
            ):
                continue
            p = _k32.GlobalLock(h)
            if not p:
                continue
            try:
                dados = ctypes.string_at(p, tamanho)
            finally:
                _k32.GlobalUnlock(h)
            formatos.append((fmt, dados))
            bytes_acumulados += tamanho
    except AttributeError:
        return ()
    except Exception as e:  # noqa: BLE001 — fronteira defensiva: leitura de HGLOBAL no clipboard Win32
        print(f"[ActionManager] falha ao ler formatos brutos do clipboard: {e!r}", file=sys.stderr)
    finally:
        _u32.CloseClipboard()
    return tuple(formatos)


def _set_clipboard_data(fmt: int, payload: bytes) -> bool:
    """Grava um formato no clipboard já aberto. Libera a memória se o sistema não a assumir."""
    h = _k32.GlobalAlloc(_GMEM_MOVEABLE_ZEROINIT, max(len(payload), 1))
    if not h:
        return False
    p = _k32.GlobalLock(h)
    if not p:
        _k32.GlobalFree(h)
        return False
    ctypes.memmove(p, payload, len(payload))
    _k32.GlobalUnlock(h)
    if not _u32.SetClipboardData(fmt, h):
        # Só depois de um SetClipboardData bem-sucedido o handle passa a ser do sistema.
        _k32.GlobalFree(h)
        return False
    return True


class ActionManager:
    """Detecta e executa comandos de ação do Copiloto Willy."""

    @classmethod
    def secure_copy(cls, text: str, ocultar_do_historico: bool = True) -> bool:
        """Escreve texto no clipboard, por padrão marcado para ficar fora do histórico (Win+V) e
        da nuvem.

        É a ÚNICA escrita de clipboard dos caminhos de injeção. Qualquer cópia anterior sem a
        marca de exclusão já publica o texto no histórico, e o formato de exclusão escrito
        depois não desfaz isso. Devolve False quando não conseguiu gravar: quem chama não
        pode colar, senão cola o conteúdo antigo do clipboard.

        `ocultar_do_historico=False` deixa o texto aparecer no Win+V: é a cópia que a pessoa
        pediu, num botão "Copiar", fora do modo privado (decisão do dono, 24/10). Ele continua
        fora da área de transferência na nuvem: a decisão foi o histórico local. A colagem
        automática, a leitura da seleção e o modo privado ficam no padrão.
        """
        if _u32 is None:
            try:
                pyperclip.copy(text)
                return True
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: fallback pyperclip fora do Windows
                print(f"[ActionManager] falha ao copiar: {e!r}", file=sys.stderr)
                return False

        with CLIPBOARD_LOCK:
            # Outro processo (gerenciador de clipboard, RDP) pode estar com o clipboard aberto.
            if not _abrir_clipboard():
                print("[ActionManager] clipboard ocupado por outro processo", file=sys.stderr)
                return False

            try:
                _u32.EmptyClipboard()
                ok = _set_clipboard_data(_CF_UNICODETEXT, text.encode("utf-16le") + b"\x00\x00")
                if ok:
                    if ocultar_do_historico:
                        # Fora do histórico, da nuvem e dos monitores de clipboard.
                        marca, valor = "ExcludeClipboardContentFromMonitorProcessing", b"\x00"
                    else:
                        # No Win+V, sem subir para a nuvem (um DWORD 0).
                        marca, valor = "CanUploadToCloudClipboard", b"\x00\x00\x00\x00"
                    formato = _u32.RegisterClipboardFormatW(marca)
                    if formato:
                        _set_clipboard_data(formato, valor)
                if not ok:
                    print(f"[ActionManager] SetClipboardData falhou (erro {ctypes.get_last_error()})",
                          file=sys.stderr)
                return ok
            finally:
                _u32.CloseClipboard()

    @classmethod
    def clipboard_has_text(cls) -> bool:
        """Indica se o clipboard contém texto Unicode (CF_UNICODETEXT = 13)."""
        if _u32 is None:
            return True
        try:
            return bool(_u32.IsClipboardFormatAvailable(_CF_UNICODETEXT))
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: IsClipboardFormatAvailable Win32/ctypes
            print(
                f"[ActionManager] falha ao consultar formato de texto no clipboard: {e!r}",
                file=sys.stderr,
            )
            return True

    @classmethod
    def capturar_clipboard(
        cls,
        *,
        tem_texto: bool | None = None,
        leitor_texto=None,
    ) -> EstadoClipboard:
        """Captura o estado atual do clipboard (texto Unicode ou formatos brutos HGLOBAL)."""
        with CLIPBOARD_LOCK:
            had_text = cls.clipboard_has_text() if tem_texto is None else bool(tem_texto)
            if had_text:
                ler = pyperclip.paste if leitor_texto is None else leitor_texto
                try:
                    old_clipboard = ler()
                except Exception as e:  # noqa: BLE001 — fronteira defensiva: pyperclip.paste / leitor de clipboard
                    print(
                        f"[ActionManager] falha ao ler texto do clipboard: {e!r}",
                        file=sys.stderr,
                    )
                    old_clipboard = ""
                return EstadoClipboard(
                    tinha_texto=True,
                    texto=old_clipboard if isinstance(old_clipboard, str) else "",
                )
            return EstadoClipboard(
                tinha_texto=False,
                texto="",
                formatos_brutos=_ler_formatos_brutos(),
            )

    @classmethod
    def restaurar_formatos_brutos(cls, formatos: tuple[tuple[int, bytes], ...]) -> bool:
        """Restaura um conjunto de formatos HGLOBAL brutos no clipboard sem publicar no Win+V."""
        if _u32 is None or _k32 is None:
            return False
        with CLIPBOARD_LOCK:
            if not _abrir_clipboard():
                print("[ActionManager] clipboard ocupado ao restaurar formatos brutos", file=sys.stderr)
                return False
            try:
                _u32.EmptyClipboard()
                ok = True
                for fmt, payload in formatos:
                    if not _set_clipboard_data(fmt, payload):
                        ok = False
                if ok and formatos:
                    formato_excl = _u32.RegisterClipboardFormatW(
                        "ExcludeClipboardContentFromMonitorProcessing"
                    )
                    if formato_excl and all(f != formato_excl for f, _ in formatos):
                        _set_clipboard_data(formato_excl, b"\x00")
                return ok
            finally:
                _u32.CloseClipboard()

    @classmethod
    def restaurar_clipboard(cls, estado: EstadoClipboard | str) -> bool:
        """Restaura o clipboard para a fotografia capturada por `capturar_clipboard`."""
        if isinstance(estado, str):
            return cls.secure_copy(estado)
        if estado.formatos_brutos:
            return cls.restaurar_formatos_brutos(estado.formatos_brutos)
        return cls.secure_copy(estado.texto if estado.tinha_texto else "")

    @classmethod
    def is_action_command(cls, text: str) -> tuple[bool, str]:
        """
        Retorna (is_action, comando_extraido).
        Exemplo: 'Willy, resuma em 3 tópicos' -> (True, 'resuma em 3 tópicos')
        """
        if not text:
            return (False, "")

        clean = text.strip()
        if cls._fala_sobre_um_willy(clean):
            return (False, "")

        # Prefixo explícito: "Willy, ..." ou "Ei Willy, ..."
        m_prefix = re.match(r'^(?:willy|ei willy|opa willy)[,\s:]+(.+)$', clean, re.IGNORECASE)
        if m_prefix:
            return (True, m_prefix.group(1).strip())

        return (False, "")

    # "Willy" sem vírgula nem dois-pontos, seguido de um verbo na 3ª pessoa, é ditado sobre alguém
    # chamado Willy ("Willy mandou um abraço", "Willy chegou cedo"), e ia ao LLM como pedido. O
    # passado em -ou, -eu e -iu, que nenhum imperativo tem, e as formas comuns fora dessa regra.
    # Ficam de fora as que também são imperativo informal ("fala", "faz", "diz", "volta", "acha",
    # "vem", "trabalha") e as que começam um pedido sem a vírgula ("Willy tem como resumir isso?",
    # "Willy sabe traduzir isso?": tem, sabe, quer, precisa, vai).
    _TERCEIRA_PESSOA = frozenset(
        ["disse", "fez", "foi", "deu", "veio", "teve", "esteve", "trouxe", "quis", "pôde", "soube", "pôs", "está", "estava", "é", "era", "tinha", "ia", "vinha", "queria", "sabia", "mora", "morava", "gosta", "gostava", "achava", "precisava", "trabalhava"])

    @classmethod
    def _fala_sobre_um_willy(cls, clean: str) -> bool:
        m = re.match(r"^willy\s+([A-Za-zÀ-ÿ]+)", clean, re.IGNORECASE)
        if not m:
            return False
        palavra = m.group(1).lower()
        return palavra in cls._TERCEIRA_PESSOA or (len(palavra) > 3 and palavra.endswith(("ou", "eu", "iu")))

    # O comando começa com o verbo de leitura, e o resto só diz o que ler ("leia isso", "diga esse
    # parágrafo em voz alta", "speak this"). Qualquer outra palavra faz dele um pedido ao LLM.
    _VERBOS_DE_LEITURA = ("leia em voz alta", "fale em voz alta", "leia", "ler", "fale", "diga", "speak", "read")
    _O_QUE_LER = frozenset(
        ["isso", "isto", "esse", "essa", "este", "esta", "o", "a", "os", "as", "texto", "selecao", "selecionado", "selecionada", "trecho", "frase", "paragrafo", "em", "voz", "alta", "pra", "para", "mim", "por", "favor", "this", "it", "that", "aloud", "out", "loud", "selection", "text"])

    @classmethod
    def is_speak_command(cls, command: str) -> bool:
        """Verifica se o comando é para ler o texto em voz alta.

        Procurava "ler", "fale" e "diga" em qualquer ponto: "crie uma função para ler um arquivo
        CSV" e "fale sobre Docker" iam para a leitura em voz alta em vez do LLM.
        """
        if not command:
            return False
        from core.text_processing import normalize_for_search
        # Sem a pontuação das pontas: o Whisper fecha a fala curta com ponto, e "Willy, leia."
        # (ou "Por favor, leia isso") ia ao LLM, que colava a resposta por cima da seleção.
        c = re.sub(r"^por favor[,:\s]+", "", normalize_for_search(command)).rstrip(" .!?;:…")
        for verbo in cls._VERBOS_DE_LEITURA:
            if c == verbo or c.startswith((verbo + " ", verbo + ",")):
                return all(p in cls._O_QUE_LER for p in re.findall(r"[a-z]+", c[len(verbo):]))
        return False

    @classmethod
    def is_transform_command(cls, command: str) -> tuple[bool, str]:
        """
        Verifica se o comando falado é uma ordem de transformação (ex: 'resuma isso', 'traduza para inglês', 'torne formal').
        Retorna (is_transform, instrucao_limpa).
        """
        if not command:
            return (False, "")
        c = command.strip()
        m = re.match(r'^(?:transforme|transformar|resuma|resumir|traduza|traduzir|corrija|corrigir|melhore|melhorar|mude|mudar|reescreva|reescrever)\s+(.+)$', c, re.IGNORECASE)
        if m:
            return (True, c)
        return (False, "")

    @staticmethod
    def esperar_modificadores_soltos(espera_s: float = _ESPERA_DOS_MODIFICADORES_S) -> bool:
        """Espera (até 250 ms, ou `espera_s`) o Alt e o Shift do atalho subirem; devolve se subiram."""
        return _esperar_modificadores_soltos(espera_s)

    @classmethod
    def get_selected_text(cls) -> str | None:
        """Tenta copiar o texto atualmente selecionado no aplicativo em foco via Ctrl+C."""
        # Com o Alt ainda apertado (a pessoa segurando o atalho), não há Ctrl+C que sirva: sem
        # copiar, não lê nada, e o clipboard nem é tocado.
        if not _esperar_modificadores_soltos():
            return None
        with CLIPBOARD_LOCK:
            estado_anterior = cls.capturar_clipboard()

            # Limpa temporariamente a área de transferência para detectar se houve cópia nova.
            # Sentinela e restauração passam por secure_copy: com pyperclip, as duas entravam
            # no histórico Win+V a cada ação de transformação.
            sentinel = f"__willy_probe_{time.time()}__"
            escreveu = False
            try:
                if not cls.secure_copy(sentinel):
                    # Sem a sentinela no clipboard, o paste abaixo leria o conteúdo antigo e
                    # o devolveria como se fosse a seleção do usuário.
                    return None
                escreveu = True
                time.sleep(0.03)
                keyboard.send("ctrl+c")

                prazo = time.monotonic() + (_PASSO_POLL_SELECAO_S * _TENTATIVAS_POLL_SELECAO)
                for _ in range(_TENTATIVAS_POLL_SELECAO):
                    time.sleep(_PASSO_POLL_SELECAO_S)
                    new_clip = pyperclip.paste()
                    if new_clip and new_clip != sentinel:
                        # Só as quebras de linha das pontas: o .strip() tirava o recuo da primeira
                        # linha, e um trecho de código transformado perdia a indentação.
                        return new_clip.strip("\r\n")
                    if time.monotonic() >= prazo:
                        break
                return None
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: sondagem Ctrl+C e clipboard
                print(f"[ActionManager] falha ao ler a seleção: {e!r}", file=sys.stderr)
                return None
            finally:
                # O clipboard volta a ser o de antes, com ou sem seleção (texto Unicode, imagem
                # CF_DIB/PNG, arquivos CF_HDROP ou vazio). A sentinela recusada pode ter
                # esvaziado o clipboard (o secure_copy falha depois do EmptyClipboard): com
                # conteúdo antes, ele volta; vazio, não, para não tocar num OpenClipboard recusado.
                if escreveu or estado_anterior.tinha_conteudo:
                    cls.restaurar_clipboard(estado_anterior)


    @classmethod
    def process_action(cls, command: str, groq_service, selected_text: str | None = None) -> str | None:
        """Envia a instrução de ação para o modelo da Groq."""
        if not command or not groq_service.client:
            return None

        from core.groq_service import ERROS_PASSAGEIROS, FalhaDoLLM

        # Rota especializada para prompts e missões executivas de agentes (/goal, maestro, loop)
        if re.search(r'\b(?:prompt|miss[aã]o|goal|agente|maestro)\b', command, re.IGNORECASE):
            payload = command
            if selected_text:
                payload = f"DEMANDA / ESCOPO:\n{command}\n\nCONTEÚDO DE REFERÊNCIA:\n{selected_text}"
            try:
                res = groq_service.generate_agent_prompt(payload, extra_context=selected_text or "", estrito=True)
            except ERROS_PASSAGEIROS:
                raise
            except FalhaDoLLM as falha:
                if falha.transitoria and falha.causa is not None:
                    raise falha.causa from falha
                # Sem estrito, o modelo que falhava devolvia o payload cru ("DEMANDA / ESCOPO:..."),
                # colado sobre a seleção em silêncio.
                return None
            return res or None

        system_instruction = (
            "Você é o Copiloto de Ações Inteligente do Willy. "
            "Execute a instrução do usuário com precisão cirúrgica. "
            "Retorne RIGOROSAMENTE apenas o resultado final transformado, "
            "sem explicações, sem cumprimentos, sem introduções e sem markdown redundante."
        )

        if selected_text:
            prompt = (
                f"TEXTO SELECIONADO PELO USUÁRIO:\n\"\"\"\n{selected_text}\n\"\"\"\n\n"
                f"INSTRUÇÃO DE TRANSFORMAÇÃO:\n{command}"
            )
        else:
            prompt = f"EXECUTE A SEGUINTE INSTRUÇÃO:\n{command}"

        try:
            # Pela porta única do serviço: com os modelos de raciocínio, a chamada direta colava o
            # <think> do Qwen e estourava o tempo com o raciocínio "medium" padrão do gpt-oss.
            result = groq_service.completar_com_reserva(groq_service.client, [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ], temperature=0.1, max_tokens=2048, timeout=6.0)
            return result or None
        except ERROS_PASSAGEIROS:
            # Rede, 429 ou 5xx: o pedido ditado não tem reserva para colar. Sobe até o pipeline,
            # que guarda o áudio na fila e oferece o reenvio, em vez de dizer "Não executei".
            raise
        except FalhaDoLLM as falha:
            if falha.transitoria and falha.causa is not None:
                raise falha.causa from falha
            return None
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: chamada ao serviço LLM do Copiloto
            print(f"[ActionManager] Erro ao executar ação de IA: {e}")
            return None


_SECURE_COPY_NATIVO = ActionManager.__dict__["secure_copy"]
