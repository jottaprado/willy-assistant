"""
Modal "Cancelar / Excluir" do Willy Design System.

Era o modal da exclusão no Histórico. Templates e Substituições excluíam no primeiro clique,
sem confirmar nem desfazer; os três usam este agora.
"""

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from ui.theme import (
    APPLE_BG_ACTIVE,
    APPLE_BG_HOVER,
    APPLE_DESTRUCTIVE,
    APPLE_DESTRUCTIVE_HOVER,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    BTN_PRIMARY_TEXT,
    FONT_FAMILY,
    RADIUS_BUTTON,
)

LARGURA, ALTURA = 380, 170


def confirmar_exclusao(
    parent,
    titulo: str,
    texto: str,
    ao_confirmar: Callable[[], None],
    rotulo_confirmar: str = "Excluir",
) -> ctk.CTkToplevel:
    """Abre o modal sobre a janela de `parent` e chama `ao_confirmar` só na confirmação."""
    janela = parent.winfo_toplevel()
    dialog = ctk.CTkToplevel(parent)
    dialog.title(titulo)
    dialog.geometry(f"{LARGURA}x{ALTURA}")
    dialog.resizable(False, False)
    dialog.transient(janela)
    try:
        dialog.grab_set()
    except tk.TclError:
        # A janela ainda não está na tela (Tk recusa o grab): o modal funciona sem ele.
        pass

    # Centralizar na janela
    dialog.update_idletasks()
    try:
        x = janela.winfo_x() + (janela.winfo_width() - LARGURA) // 2
        y = janela.winfo_y() + (janela.winfo_height() - ALTURA) // 2
        dialog.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass

    ctk.CTkLabel(
        dialog,
        text=titulo,
        font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
        text_color=APPLE_TEXT_PRIMARY,
    ).pack(padx=24, pady=(20, 8), anchor="w")

    ctk.CTkLabel(
        dialog,
        text=texto,
        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        text_color=APPLE_TEXT_SECONDARY,
        wraplength=330,
        justify="left",
    ).pack(padx=24, pady=(0, 20), anchor="w")

    btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_row.pack(fill="x", padx=24, pady=(0, 16))

    def _fechar():
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        try:
            dialog.destroy()
        except tk.TclError:
            pass

    def _executar():
        _fechar()
        ao_confirmar()

    dialog.cancelar = _fechar
    dialog.confirmar = _executar
    dialog.bind("<Escape>", lambda _e: _fechar())
    dialog.bind("<Return>", lambda _e: _executar())

    dialog.btn_cancelar = ctk.CTkButton(
        btn_row,
        text="Cancelar",
        font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        height=32,
        corner_radius=RADIUS_BUTTON,
        fg_color=APPLE_BG_HOVER,
        hover_color=APPLE_BG_ACTIVE,
        text_color=APPLE_TEXT_PRIMARY,
        command=_fechar,
    )
    dialog.btn_cancelar.pack(side="right", padx=(8, 0))

    dialog.btn_excluir = ctk.CTkButton(
        btn_row,
        text=rotulo_confirmar,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        height=32,
        corner_radius=RADIUS_BUTTON,
        fg_color=APPLE_DESTRUCTIVE,
        hover_color=APPLE_DESTRUCTIVE_HOVER,
        text_color=BTN_PRIMARY_TEXT,
        command=_executar,
    )
    dialog.btn_excluir.pack(side="right")

    try:
        dialog.focus_set()
    except tk.TclError:
        pass
    return dialog
