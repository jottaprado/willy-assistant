"""
Componente SectionHeader do Willy Design System.
Cabeçalho de seção em 12px semibold secundário, caixa alta com espaçamento padronizado
(24px acima e 8px abaixo) e suporte a botão de ação na linha.
"""

from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_TEXT_SECONDARY,
    FONT_FAMILY,
)


class SectionHeader(ctk.CTkFrame):
    """Título de seção padronizado estilo macOS System Settings."""

    def __init__(
        self,
        master: Any,
        text: str,
        action: Any | None = None,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        self.lbl_title = ctk.CTkLabel(
            self,
            text=text.upper(),
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_title.grid(row=0, column=0, sticky="w")

        self.action_box = ctk.CTkFrame(self, fg_color="transparent")
        self.action_box.grid(row=0, column=1, sticky="e")

        if action:
            if callable(action) and not isinstance(action, ctk.CTkBaseClass):
                w = action(self.action_box)
                if w:
                    w.pack(side="right")
            elif isinstance(action, tuple):
                txt = action[0]
                cmd = action[1] if len(action) > 1 else None
                var = action[2] if len(action) > 2 else "ghost"
                from .button import Button
                btn = Button(self.action_box, text=txt, command=cmd, variant=var)
                btn.pack(side="right")
            elif isinstance(action, ctk.CTkBaseClass):
                if getattr(action, "master", None) == self.action_box:
                    action.pack(side="right")
                else:
                    action.pack(in_=self.action_box, side="right")

    def set_action(self, text: str, command: Any | None = None, variant: str = "ghost"):
        """Cria e adiciona um botão de ação padronizado ao cabeçalho de seção."""
        from .button import Button
        for w in self.action_box.winfo_children():
            w.destroy()
        btn = Button(self.action_box, text=text, command=command, variant=variant)
        btn.pack(side="right")
        return btn
