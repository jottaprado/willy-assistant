"""
Componentes da barra lateral (Sidebar) do Willy Dashboard.
Implementa SidebarNavItem com alinhamento milimétrico, suporte a ícones Fluent e tooltips de status.
"""

import customtkinter as ctk

from ui.components.tooltip import ToolTip
from ui.theme import (
    ACCENT_BLUE,
    APPLE_ACCENT,
    APPLE_ACCENT_HOVER,
    APPLE_ACCENT_SUBTLE,
    APPLE_BG_HOVER,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    BTN_PRIMARY_TEXT,
    FONT_FAMILY,
    ICON_BOX,
    ICON_GAP,
    ITEM_HEIGHT,
    RADIUS_BUTTON,
    RADIUS_PILL,
    carregar_icone,
)

StatusToolTip = ToolTip


def carregar_icone_fluent(icon_key: str):
    """Carrega o ícone oficial Fluent System Icons Regular em PNG como CTkImage."""
    return carregar_icone(icon_key, active=False, variant="secondary", size=(16, 16))


class SidebarNavItem(ctk.CTkFrame):
    """Item de navegação da barra lateral com design minimalista e alinhamento milimétrico."""

    def __init__(
        self,
        master,
        icon_key,
        text,
        command,
        fallback_glyph="",
        highlighted: bool = False,
        badge_text: str = "",
        **kwargs,
    ):
        super().__init__(
            master,
            corner_radius=RADIUS_BUTTON,
            height=ITEM_HEIGHT,
            fg_color="transparent",
            cursor="hand2",
            **kwargs
        )
        self.command = command
        self.icon_key = icon_key
        self.is_active = False
        self.highlighted = bool(highlighted)
        self._badge_text = badge_text or ""
        self._usa_fallback_glyph = False

        self.grid_columnconfigure(0, minsize=ICON_BOX)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # Coluna 0: Ícone centralizado na caixa de 20px (eixo a 10px da margem interna do item)
        self.lbl_icon = None
        try:
            ctk_img = carregar_icone(icon_key, active=False, variant="secondary", size=(16, 16))
            if not ctk_img:
                ctk_img = carregar_icone_fluent(icon_key)
            if ctk_img:
                self.lbl_icon = ctk.CTkLabel(
                    self,
                    image=ctk_img,
                    text="",
                    width=ICON_BOX,
                    anchor="center",
                    cursor="hand2"
                )
        except Exception:  # noqa: BLE001 — fronteira defensiva: CTkImage/Tkinter em ambiente headless ou teardown
            self.lbl_icon = None

        if self.lbl_icon is None:
            self._usa_fallback_glyph = True
            self.lbl_icon = ctk.CTkLabel(
                self,
                text=fallback_glyph,
                width=ICON_BOX,
                anchor="center",
                font=ctk.CTkFont(size=14, weight="bold" if self.highlighted else "normal"),
                text_color=APPLE_ACCENT if self.highlighted else APPLE_TEXT_SECONDARY,
                cursor="hand2"
            )
        self.lbl_icon.grid(row=0, column=0, padx=(10, 0), pady=0, sticky="ns")

        # Coluna 1: Rótulo de texto começando exatamente 12px depois da caixa de ícone
        self.lbl_text = ctk.CTkLabel(
            self,
            text=text,
            anchor="w",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold" if self.highlighted else "normal"),
            text_color=APPLE_TEXT_PRIMARY if self.highlighted else APPLE_TEXT_SECONDARY,
            cursor="hand2"
        )
        self.lbl_text.grid(row=0, column=1, padx=(ICON_GAP, 8), pady=0, sticky="nsew")

        # Coluna 2: Selo opcional de destaque/pendência (ex.: "Começar")
        self.lbl_badge = ctk.CTkLabel(
            self,
            text=self._badge_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            fg_color=ACCENT_BLUE,
            text_color=BTN_PRIMARY_TEXT,
            corner_radius=RADIUS_PILL,
            height=18,
            padx=7,
            cursor="hand2",
        )
        if self._badge_text:
            self.lbl_badge.grid(row=0, column=2, padx=(0, 8), pady=0)

        # Eventos para toda a área do botão
        for w in (self, self.lbl_icon, self.lbl_text, self.lbl_badge):
            w.bind("<Button-1>", lambda e: self._on_click())
            w.bind("<Enter>", lambda e: self._on_enter())
            w.bind("<Leave>", lambda e: self._on_leave())

        self._aplicar_aparencia(hover=False)

    def _on_click(self):
        if self.command:
            self.command()

    def _on_enter(self):
        if not self.is_active:
            self._aplicar_aparencia(hover=True)

    def _on_leave(self):
        if not self.is_active:
            self._aplicar_aparencia(hover=False)

    def set_badge(self, badge_text: str) -> None:
        """Exibe ou oculta o selo discreto ao lado do rótulo do item."""
        self._badge_text = (badge_text or "").strip()
        if self._badge_text:
            self.lbl_badge.configure(text=self._badge_text)
            self.lbl_badge.grid(row=0, column=2, padx=(0, 8), pady=0)
        else:
            self.lbl_badge.grid_forget()

    def _aplicar_aparencia(self, hover: bool = False) -> None:
        if self.highlighted:
            if self.is_active:
                self.configure(fg_color=APPLE_ACCENT, border_width=1, border_color=APPLE_ACCENT)
                self.lbl_text.configure(
                    text_color=BTN_PRIMARY_TEXT,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                )
                if self._usa_fallback_glyph:
                    self.lbl_icon.configure(text_color=BTN_PRIMARY_TEXT)
                self.lbl_badge.configure(fg_color=BTN_PRIMARY_TEXT, text_color=ACCENT_BLUE)
            else:
                self.configure(
                    fg_color=APPLE_ACCENT_SUBTLE,
                    border_width=1,
                    border_color=APPLE_ACCENT_HOVER if hover else APPLE_ACCENT,
                )
                self.lbl_text.configure(
                    text_color=APPLE_TEXT_PRIMARY,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                )
                if self._usa_fallback_glyph:
                    self.lbl_icon.configure(text_color=APPLE_ACCENT)
                self.lbl_badge.configure(fg_color=ACCENT_BLUE, text_color=BTN_PRIMARY_TEXT)
            return

        if self.is_active:
            self.configure(fg_color=APPLE_BG_HOVER, border_width=0)
            self.lbl_text.configure(
                text_color=APPLE_TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            )
        elif hover:
            self.configure(fg_color=APPLE_BG_HOVER, border_width=0)
            self.lbl_text.configure(
                text_color=APPLE_TEXT_PRIMARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="normal"),
            )
        else:
            self.configure(fg_color="transparent", border_width=0)
            self.lbl_text.configure(
                text_color=APPLE_TEXT_SECONDARY,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="normal"),
            )

    def set_active(self, active):
        self.is_active = bool(active)
        try:
            new_img = carregar_icone(
                self.icon_key,
                active=self.is_active,
                variant="primary" if self.is_active else "secondary",
                size=(16, 16),
            )
            if new_img and self.lbl_icon:
                self.lbl_icon.configure(image=new_img)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: CTkImage/Tkinter em ambiente headless ou teardown
            pass

        self._aplicar_aparencia(hover=False)
