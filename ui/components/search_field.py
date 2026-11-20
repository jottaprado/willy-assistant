"""
Componente SearchField do Willy Design System.
Campo de busca preenchido, sem borda dura, com ícone de lupa Fluent de 16px,
botão de limpar ('x') condicional e atalho discreto 'Ctrl K'.
"""

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_INPUT_BG,
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_TERTIARY,
    FONT_FAMILY,
    RADIUS_INPUT,
    carregar_icone,
)


class SearchField(ctk.CTkFrame):
    """Campo de busca refinado no estilo Apple com indicador discreto Ctrl K e botão de limpar."""

    def __init__(
        self,
        master: Any,
        placeholder: str = "Buscar",
        on_change: Callable[[str], None] | None = None,
        on_clear: Callable[[], None] | None = None,
        height: int = 36,
        **kwargs
    ):
        super().__init__(
            master,
            fg_color=APPLE_INPUT_BG,
            corner_radius=RADIUS_INPUT,
            height=height,
            **kwargs
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.on_change = on_change
        self.on_clear = on_clear

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # 1. Ícone de lupa Fluent 16px
        search_icon = carregar_icone("search", active=False, variant="secondary", size=(16, 16))
        self.lbl_icon = None
        if search_icon:
            try:
                self.lbl_icon = ctk.CTkLabel(
                    self,
                    image=search_icon,
                    text="",
                    width=24,
                    anchor="center",
                )
            except Exception:  # noqa: BLE001 — fronteira defensiva: widget/ícone Tkinter em teardown/headless
                self.lbl_icon = None

        if self.lbl_icon is None:
            self.lbl_icon = ctk.CTkLabel(
                self,
                text="⌕",
                font=ctk.CTkFont(family=FONT_FAMILY, size=14),
                text_color=APPLE_TEXT_SECONDARY,
                width=24,
                anchor="center",
            )
        self.lbl_icon.grid(row=0, column=0, padx=(10, 4), sticky="ns")

        # 2. Entrada de texto
        self.entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            fg_color="transparent",
            border_width=0,
            text_color=APPLE_TEXT_PRIMARY,
            placeholder_text_color=APPLE_TEXT_SECONDARY,
        )
        self.entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

        # 3. Indicador de atalho "Ctrl K" (Pílula sutil com borda de 1px em APPLE_SEPARATOR e raio 4px)
        self.keycap_frame = ctk.CTkFrame(
            self,
            fg_color="transparent",
            border_width=1,
            border_color=APPLE_SEPARATOR,
            corner_radius=4,
            height=20,
            cursor="xterm",
        )
        self.lbl_keycap = ctk.CTkLabel(
            self.keycap_frame,
            text="Ctrl K",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="normal"),
            text_color=APPLE_TEXT_TERTIARY,
            height=18,
            cursor="xterm",
        )
        self.lbl_keycap.pack(padx=6, pady=1)
        self.keycap_frame.grid(row=0, column=2, padx=(0, 8), sticky="e")

        # 4. Botão de limpar ("x") - inicialmente não mapeado
        dismiss_icon = carregar_icone("dismiss", active=False, variant="secondary", size=(14, 14))
        self.btn_clear = None
        if dismiss_icon:
            try:
                self.btn_clear = ctk.CTkButton(
                    self,
                    image=dismiss_icon,
                    text="",
                    width=24,
                    height=24,
                    corner_radius=12,
                    fg_color="transparent",
                    hover_color=APPLE_INPUT_BG,
                    command=self.clear,
                )
            except Exception:  # noqa: BLE001 — fronteira defensiva: widget/ícone Tkinter em teardown/headless
                self.btn_clear = None

        if self.btn_clear is None:
            self.btn_clear = ctk.CTkButton(
                self,
                text="✕",
                width=24,
                height=24,
                corner_radius=12,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                text_color=APPLE_TEXT_SECONDARY,
                fg_color="transparent",
                hover_color=APPLE_INPUT_BG,
                command=self.clear,
            )

        # Binds de clique para focar
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.lbl_icon.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.keycap_frame.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.lbl_keycap.bind("<Button-1>", lambda e: self.entry.focus_set())

    def _on_focus_in(self, event=None):
        txt = self.get()
        if txt:
            if self.keycap_frame.winfo_ismapped():
                self.keycap_frame.grid_forget()
            if not self.btn_clear.winfo_ismapped():
                self.btn_clear.grid(row=0, column=2, padx=(0, 6), sticky="ns")
        else:
            # Em foco sem texto, oculta o indicador para digitação limpa
            if self.keycap_frame.winfo_ismapped():
                self.keycap_frame.grid_forget()

    def _on_focus_out(self, event=None):
        txt = self.get()
        if not txt:
            if self.btn_clear.winfo_ismapped():
                self.btn_clear.grid_forget()
            if not self.keycap_frame.winfo_ismapped():
                self.keycap_frame.grid(row=0, column=2, padx=(0, 8), sticky="e")

    def _on_key_release(self, event=None):
        txt = self.get()
        if txt:
            if self.keycap_frame.winfo_ismapped():
                self.keycap_frame.grid_forget()
            if not self.btn_clear.winfo_ismapped():
                self.btn_clear.grid(row=0, column=2, padx=(0, 6), sticky="ns")
        else:
            if self.btn_clear.winfo_ismapped():
                self.btn_clear.grid_forget()
            # Se não tem foco, mostra Ctrl K
            try:
                focused = (self.entry.focus_get() == self.entry._entry)
            except Exception:  # noqa: BLE001 — fronteira defensiva: widget/ícone Tkinter em teardown/headless
                focused = False
            if not focused and not self.keycap_frame.winfo_ismapped():
                self.keycap_frame.grid(row=0, column=2, padx=(0, 8), sticky="e")

        if self.on_change:
            self.on_change(txt)

    def get(self) -> str:
        return self.entry.get()

    def set(self, text: str):
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self._on_key_release()

    def delete(self, first: Any, last: Any = None):
        if last is not None:
            self.entry.delete(first, last)
        else:
            self.entry.delete(first)
        self._on_key_release()

    def insert(self, index: Any, string: str):
        self.entry.insert(index, string)
        self._on_key_release()

    def focus(self):
        self.entry.focus_set()

    def clear(self):
        self.entry.delete(0, "end")
        if self.btn_clear.winfo_ismapped():
            self.btn_clear.grid_forget()
        if not self.keycap_frame.winfo_ismapped():
            self.keycap_frame.grid(row=0, column=2, padx=(0, 8), sticky="e")
        if self.on_clear:
            self.on_clear()
        if self.on_change:
            self.on_change("")
