"""
Componente ToolTip do Willy Design System.
Exibe um tooltip flutuante e discreto no padrão Apple macOS ao passar o mouse sobre botões.
"""

import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_BG_CARD,
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    FONT_FAMILY,
)


class ToolTip:
    """Tooltip flutuante no estilo Apple com cantos arredondados e borda sutil."""

    def __init__(self, widget: Any, text: str | Callable[[], str], delay_ms: int = 250):
        self.widget = widget
        self.text_source = text
        self.text_func = text
        self.delay_ms = delay_ms
        self.tip_window = None
        self._after_id = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay_ms, self.show_tip)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: after no widget Tkinter
            pass

    def _on_leave(self, event=None):
        self._cancel()
        self.hide_tip()

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: after_cancel / destroy no Tkinter
                pass
            self._after_id = None

    def show_tip(self, event=None):
        if self.tip_window or not self.widget.winfo_exists():
            return
        fonte = getattr(self, "text_source", None) or getattr(self, "text_func", None)
        text = fonte() if callable(fonte) else fonte
        if not text:
            return

        x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        frame = ctk.CTkFrame(
            tw,
            fg_color=APPLE_BG_CARD,
            border_width=1,
            border_color=APPLE_SEPARATOR,
            corner_radius=6,
        )
        frame.pack()

        lbl = ctk.CTkLabel(
            frame,
            text=text,
            text_color=APPLE_TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="normal"),
            padx=8,
            pady=4,
        )
        lbl.pack()

    def hide_tip(self, event=None):
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: after_cancel / destroy no Tkinter
                pass
            self.tip_window = None
