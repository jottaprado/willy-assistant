"""
Componente Button do Willy Design System.
Botão refinado com três variantes: primary (accent azul), secondary (fundo neutro), ghost (apenas texto).
Altura de 32px, raio de 8px e padding horizontal de 12px.
"""

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.theme import (
    APPLE_ACCENT,
    APPLE_ACCENT_HOVER,
    APPLE_BG_ACTIVE,
    APPLE_BG_HOVER,
    APPLE_TEXT_PRIMARY,
    BTN_PRIMARY_TEXT,
    FONT_FAMILY,
    RADIUS_BUTTON,
    carregar_icone,
)


class Button(ctk.CTkButton):
    """Botão com variantes estritas do design minimalista Apple."""

    def __init__(
        self,
        master: Any,
        text: str = "",
        variant: str = "secondary",
        icon: Any | None = None,
        command: Callable[[], None] | None = None,
        height: int = 32,
        **kwargs
    ):
        self.variant = variant

        # Resolução de cores por variante
        if variant == "primary":
            fg_color = APPLE_ACCENT
            hover_color = APPLE_ACCENT_HOVER
            text_color = BTN_PRIMARY_TEXT
            font_weight = "bold"
            border_width = 0
            border_color = None
        elif variant == "ghost":
            fg_color = "transparent"
            hover_color = APPLE_BG_HOVER
            text_color = APPLE_TEXT_PRIMARY
            font_weight = "normal"
            border_width = 0
            border_color = None
        else:  # secondary
            fg_color = APPLE_BG_HOVER
            hover_color = APPLE_BG_ACTIVE
            text_color = APPLE_TEXT_PRIMARY
            font_weight = "normal"
            border_width = 0
            border_color = None

        ctk_image = None
        if isinstance(icon, str):
            ctk_image = carregar_icone(icon, active=(variant == "primary"), size=(16, 16))
        elif icon is not None:
            ctk_image = icon

        # Se for um botão exclusivamente de ícone (sem texto), a largura padrão deve ser igual à altura (ex: 32x32)
        if "width" not in kwargs and not text and icon is not None:
            kwargs["width"] = height

        super().__init__(
            master,
            text=text,
            image=ctk_image,
            compound="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight=font_weight),
            fg_color=fg_color,
            hover_color=hover_color,
            text_color=text_color,
            corner_radius=RADIUS_BUTTON,
            height=height,
            border_width=border_width,
            border_color=border_color,
            command=command,
            **kwargs
        )
