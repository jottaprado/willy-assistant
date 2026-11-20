"""
Módulo de Teleprompter Flutuante & Legendas em Tempo Real do Willy.
Janela translúcida Always-on-Top estilo macOS para acompanhar reuniões e ditados longos.
"""

import sys
import time
import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from core.context import ContextManager
from ui.overlays.pill import _user32, obter_hmonitor_e_area
from ui.theme import (
    FLUTUANTE_AZUL,
    FLUTUANTE_BORDA_SUAVE,
    FLUTUANTE_BOTAO,
    FLUTUANTE_BOTAO_HOVER,
    FLUTUANTE_CABECALHO,
    FLUTUANTE_CAIXA_TEXTO,
    FLUTUANTE_FECHAR_HOVER,
    FLUTUANTE_FUNDO,
    FLUTUANTE_TEXTO,
    FLUTUANTE_TEXTO_APAGADO,
    FLUTUANTE_TEXTO_BOTAO,
    FLUTUANTE_VERDE,
    FLUTUANTE_VERMELHO,
)

FONT_FAMILY = "Segoe UI"
BG_DARK = FLUTUANTE_FUNDO
BORDER_COLOR = FLUTUANTE_BORDA_SUAVE
TEXT_COLOR = FLUTUANTE_TEXTO
ACCENT_BLUE = FLUTUANTE_AZUL
ACCENT_GREEN = FLUTUANTE_VERDE
HEADER_BG = FLUTUANTE_CABECALHO
TEXT_MUTED = FLUTUANTE_TEXTO_APAGADO
BTN_BG = FLUTUANTE_BOTAO
BTN_HOVER = FLUTUANTE_BOTAO_HOVER
BTN_TEXT = FLUTUANTE_TEXTO_BOTAO
CLOSE_HOVER = FLUTUANTE_FECHAR_HOVER
COLOR_DESTRUCTIVE = FLUTUANTE_VERMELHO
TEXTBOX_BG = FLUTUANTE_CAIXA_TEXTO


class LiveTeleprompter:
    """Janela flutuante translúcida para exibição de legendas e teleprompter em tempo real."""

    def __init__(self, root: tk.Tk | None = None, on_close_callback: Callable[[], None] | None = None):
        self.root_master = root
        self.on_close = on_close_callback
        self.window: ctk.CTkToplevel | None = None
        self.txt_captions: ctk.CTkTextbox | None = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self.is_visible = False

    def _posicionar_no_monitor_ativo(self, fg_anterior: int = 0) -> None:
        """Posiciona a janela no centro-inferior da área de trabalho do monitor ativo."""
        if not self.window:
            return
        try:
            cursor = self.window.winfo_pointerxy()
            res = obter_hmonitor_e_area(_user32, fg_anterior, cursor)
            if res is not None:
                left, top, right, bottom = res[1]
                x = left + (right - left - 540) // 2
                y = max(top + 40, bottom - 272)
            else:
                screen_w = self.window.winfo_screenwidth()
                screen_h = self.window.winfo_screenheight()
                x = (screen_w - 540) // 2
                y = screen_h - 320
            self.window.geometry(f"540x220+{x}+{y}")
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            print(f"[LiveTeleprompter] Erro ao posicionar janela: {e}", file=sys.stderr)

    def mostrar(self):
        """Abre ou traz para o primeiro plano a janela do teleprompter."""
        fg_anterior = 0
        if _user32 is not None:
            try:
                cand = _user32.GetForegroundWindow()
                if cand and not ContextManager.eh_janela_do_willy(cand) and not ContextManager.eh_janela_do_shell(cand):
                    fg_anterior = cand
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback/withdraw/Win32 no teleprompter
                print(f"[LiveTeleprompter] Erro ao consultar janela em foco: {e}", file=sys.stderr)

        if self.window and self.window.winfo_exists():
            if not self.is_visible:
                self._posicionar_no_monitor_ativo(fg_anterior)
            self.window.deiconify()
            self.window.lift()
            self.window.attributes("-topmost", True)
            self.is_visible = True
            return

        self.window = ctk.CTkToplevel(self.root_master)
        self.window.title("Willy - Legendas ao Vivo (Live Captions)")
        self.window.geometry("540x220")
        self.window.minsize(360, 140)
        self.window.configure(fg_color=BG_DARK)
        self.window.attributes("-topmost", True)

        try:
            self.window.attributes("-alpha", 0.92)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            print(f"[LiveTeleprompter] Erro ao definir transparência: {e}", file=sys.stderr)

        self._posicionar_no_monitor_ativo(fg_anterior)

        self.window.protocol("WM_DELETE_WINDOW", self.esconder)

        # Header / Barra de Controle Draggable
        header = ctk.CTkFrame(self.window, height=32, fg_color=HEADER_BG, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        lbl_tit = ctk.CTkLabel(
            header,
            text=" 🪟  Willy Live Captions ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=TEXT_MUTED
        )
        lbl_tit.pack(side="left", padx=8)

        btn_limpar = ctk.CTkButton(
            header,
            text="Limpar",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            width=50,
            height=20,
            corner_radius=4,
            fg_color=BTN_BG,
            hover_color=BTN_HOVER,
            text_color=BTN_TEXT,
            command=self.limpar
        )
        btn_limpar.pack(side="right", padx=6)

        btn_fechar = ctk.CTkButton(
            header,
            text="✕",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=24,
            height=20,
            corner_radius=4,
            fg_color="transparent",
            hover_color=CLOSE_HOVER,
            text_color=COLOR_DESTRUCTIVE,
            command=self.esconder
        )
        btn_fechar.pack(side="right", padx=(0, 4))

        # Permite arrastar a janela clicando no header
        for w in (header, lbl_tit):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        # Caixa de Texto das Legendas
        container = ctk.CTkFrame(self.window, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        self.txt_captions = ctk.CTkTextbox(
            container,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14),
            text_color=TEXT_COLOR,
            fg_color=TEXTBOX_BG,
            border_width=1,
            border_color=BORDER_COLOR,
            corner_radius=8,
            wrap="word"
        )
        self.txt_captions.pack(fill="both", expand=True)
        self.txt_captions.insert("end", "🎙️ Legendas ao vivo iniciadas. Fale ou reproduza um áudio...\n\n")
        self.txt_captions.see("end")

        self.is_visible = True

    def _start_drag(self, event):
        # A distância do ponteiro ao canto da janela, em coordenadas da tela. O event.x é
        # relativo ao widget clicado, que anda junto com a janela, e o winfo_x ainda não tem a
        # posição do último geometry() quando os movimentos chegam em rajada: a janela ia aos
        # saltos atrás do ponteiro.
        if self.window:
            self._drag_start_x = event.x_root - self.window.winfo_x()
            self._drag_start_y = event.y_root - self.window.winfo_y()

    def _on_drag(self, event):
        if self.window:
            self.window.geometry(f"+{event.x_root - self._drag_start_x}+{event.y_root - self._drag_start_y}")

    def adicionar_legenda(self, texto: str, prefixo: str = ""):
        """Adiciona um bloco de texto com rolagem automática suave."""
        if not texto or not texto.strip():
            return

        if not self.window or not self.window.winfo_exists():
            return

        hora = time.strftime("%H:%M:%S")
        tag = f"[{hora}] " if not prefixo else f"[{hora} {prefixo}] "
        linha = f"{tag}{texto.strip()}\n\n"

        def _update():
            if self.txt_captions and self.txt_captions.winfo_exists():
                self.txt_captions.insert("end", linha)
                self.txt_captions.see("end")

        try:
            self.window.after(0, _update)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            print(f"[LiveTeleprompter] Erro ao agendar atualização de legenda: {e}", file=sys.stderr)

    def limpar(self):
        """Limpa o conteúdo do teleprompter."""
        if self.txt_captions and self.txt_captions.winfo_exists():
            self.txt_captions.delete("1.0", "end")

    def esconder(self):
        """Oculta o teleprompter."""
        if self.window and self.window.winfo_exists():
            try:
                self.window.withdraw()
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback/withdraw/Win32 no teleprompter
                print(f"[LiveTeleprompter] Erro ao ocultar janela: {e}", file=sys.stderr)
        self.is_visible = False
        if self.on_close:
            try:
                self.on_close()
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback/withdraw/Win32 no teleprompter
                print(f"[LiveTeleprompter] Erro no callback on_close: {e}", file=sys.stderr)

    def destroy(self):
        """Fecha a janela de vez, no encerramento do Willy. O willy.py já chamava destroy() e
        o método não existia: o AttributeError era engolido, e a janela só fechava junto com a
        raiz logo depois. Sem o método, quem o chamasse em outro ponto não fechava nada."""
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass  # já destruída junto com a raiz
        self.window = None
        self.txt_captions = None
        self.is_visible = False

    def toggle(self):
        """Alterna visibilidade do teleprompter."""
        if self.is_visible and self.window and self.window.winfo_exists() and self.window.winfo_viewable():
            self.esconder()
        else:
            self.mostrar()
