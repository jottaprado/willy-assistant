"""
Componente PageHeader do Willy Design System.
Renderiza cabeçalho de página com título de 28px semibold, subtítulo de 13px secundário
e container de ações alinhado à direita, perfeitamente centralizado verticalmente com a linha do título.
"""

from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    FONT_FAMILY,
)


class PageHeader(ctk.CTkFrame):
    """Cabeçalho padrão unificado para todas as telas do Willy."""

    def __init__(
        self,
        master: Any,
        title: str,
        subtitle: str | None = None,
        actions: list[Any] | None = None,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        # Linha 0: Título à esquerda e Ações à direita (centralizados verticalmente entre si)
        self.lbl_title = ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(family=FONT_FAMILY, size=28, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
            height=34,
        )
        self.lbl_title.grid(row=0, column=0, sticky="w")

        self.actions_box = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_box.grid(row=0, column=1, sticky="e")

        # Linha 1: Subtítulo opcional abaixo do título
        self.lbl_subtitle = None
        if subtitle:
            self.lbl_subtitle = ctk.CTkLabel(
                self,
                text=subtitle,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="normal"),
                text_color=APPLE_TEXT_SECONDARY,
                anchor="w",
            )
            self.lbl_subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        if actions:
            for act in actions:
                if callable(act) and not isinstance(act, ctk.CTkBaseClass):
                    w = act(self.actions_box)
                    if w:
                        w.pack(side="left", padx=(8, 0))
                elif isinstance(act, tuple):
                    txt = act[0]
                    cmd = act[1] if len(act) > 1 else None
                    var = act[2] if len(act) > 2 else "secondary"
                    from .button import Button
                    btn = Button(self.actions_box, text=txt, command=cmd, variant=var)
                    btn.pack(side="left", padx=(8, 0))
                elif isinstance(act, ctk.CTkBaseClass):
                    if getattr(act, "master", None) == self.actions_box:
                        act.pack(side="left", padx=(8, 0))
                    else:
                        act.pack(in_=self.actions_box, side="left", padx=(8, 0))

    def add_action(
        self,
        text: str,
        command: Any | None = None,
        variant: str = "secondary",
        icon: Any | None = None,
        **kwargs
    ):
        """Cria e adiciona um botão de ação padronizado ao cabeçalho."""
        from .button import Button
        btn = Button(self.actions_box, text=text, command=command, variant=variant, icon=icon, **kwargs)
        btn.pack(side="left", padx=(8, 0))
        return btn

    def set_title(self, title: str):
        self.lbl_title.configure(text=title)

    def set_subtitle(self, subtitle: str):
        if self.lbl_subtitle:
            self.lbl_subtitle.configure(text=subtitle)
