"""
Componente SegmentedControl do Willy Design System.
Controle segmentado em bloco único com cantos arredondados, fundo neutro,
segmento ativo em superfície clara com texto primário semibold, sem bordas divisórias.
"""

import tkinter.font as tkfont
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_BG_CARD,
    APPLE_INPUT_BG,
    APPLE_SEGMENT_BG,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    FONT_FAMILY,
    RADIUS_INPUT,
)


class SegmentedControl(ctk.CTkFrame):
    """Controle segmentado estilo Apple macOS/iOS com largura dinâmica por conteúdo sem truncamento."""

    def __init__(
        self,
        master: Any,
        options: list[str],
        selected: str | None = None,
        on_change: Callable[[str], None] | None = None,
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

        self.options = list(options)
        self._selected = selected or (self.options[0] if self.options else "")
        self.on_change = on_change
        self.buttons: dict = {}
        self._font_size = 13

        self.grid_rowconfigure(0, weight=1)
        self._construir_botoes()

    def _construir_botoes(self):
        try:
            measure_font = tkfont.Font(family=FONT_FAMILY, size=self._font_size, weight="bold")
        except Exception:  # noqa: BLE001 — fronteira defensiva: tkfont.Font sem display ativo
            measure_font = None

        total_width = 4
        for idx, opt in enumerate(self.options):
            if measure_font:
                seg_w = measure_font.measure(opt) + 24
            else:
                seg_w = len(opt) * 10 + 24

            self.grid_columnconfigure(idx, weight=0, minsize=seg_w)
            total_width += seg_w + 2

            is_active = (opt == self._selected)
            bg_col = APPLE_BG_CARD if is_active else "transparent"
            txt_col = APPLE_TEXT_PRIMARY if is_active else APPLE_TEXT_SECONDARY
            weight = "bold" if is_active else "normal"

            btn = ctk.CTkButton(
                self,
                text=opt,
                width=seg_w,
                font=ctk.CTkFont(family=FONT_FAMILY, size=self._font_size, weight=weight),
                fg_color=bg_col,
                hover_color=APPLE_SEGMENT_BG,
                text_color=txt_col,
                corner_radius=RADIUS_INPUT - 2,
                border_width=0,
                command=lambda val=opt: self._on_select(val),
            )
            btn.grid(row=0, column=idx, padx=1, pady=2, sticky="nsew")
            self.buttons[opt] = btn

        self.configure(width=total_width + 4)

    def _on_select(self, val: str):
        if val == self._selected:
            return
        self.set(val)
        if self.on_change:
            self.on_change(val)

    def get(self) -> str:
        return self._selected

    def set(self, val: str):
        if val not in self.buttons:
            # Compatibilidade flexível com variações legadas (ex: prefixos ou emojis legados)
            for k in self.buttons:
                if k.lower() in val.lower() or val.lower() in k.lower():
                    val = k
                    break
        self._selected = val
        for opt, btn in self.buttons.items():
            is_active = (opt == self._selected)
            bg_col = APPLE_BG_CARD if is_active else "transparent"
            txt_col = APPLE_TEXT_PRIMARY if is_active else APPLE_TEXT_SECONDARY
            weight = "bold" if is_active else "normal"
            btn.configure(
                fg_color=bg_col,
                text_color=txt_col,
                font=ctk.CTkFont(family=FONT_FAMILY, size=self._font_size, weight=weight)
            )

    def cget(self, attribute_name: str) -> Any:
        if attribute_name == "values":
            return self.options
        return super().cget(attribute_name)
