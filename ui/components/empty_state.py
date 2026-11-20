"""
Componente EmptyState do Willy Design System.
Exibe estado vazio padronizado com ícone de 32px em cor terciária,
título em 15px primário e dica contextual em 13px secundário.
"""

from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_TEXT_SECONDARY,
    FONT_FAMILY,
    carregar_icone,
)


class EmptyState(ctk.CTkLabel):
    """Estado vazio centralizado e minimalista para listas e buscas sem resultados."""

    def __init__(
        self,
        master: Any,
        icon_key: str = "empty",
        title: str = "Nenhum item encontrado",
        hint: str | None = None,
        **kwargs
    ):
        if "icon" in kwargs:
            icon_key = kwargs.pop("icon")
        icon_img = carregar_icone(icon_key, active=False, variant="tertiary", size=(32, 32))
        full_text = f"{title}\n\n{hint}" if hint else title
        try:
            super().__init__(
                master,
                text=full_text,
                image=icon_img,
                compound="top",
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                text_color=APPLE_TEXT_SECONDARY,
                justify="center",
                **kwargs
            )
        except Exception:  # noqa: BLE001 — fronteira defensiva: fallback sem imagem no CTkLabel/Tkinter
            super().__init__(
                master,
                text=full_text,
                compound="top",
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                text_color=APPLE_TEXT_SECONDARY,
                justify="center",
                **kwargs
            )
        self.title_text = title
        self.hint_text = hint
