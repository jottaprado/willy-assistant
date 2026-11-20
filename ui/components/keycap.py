"""
Componente Keycap do Willy Design System.
Renderiza teclas físicas elegantes sem o caractere '+' entre elas.
Suporta modo de captura interativa com clique, cancelamento por Esc e callback de alteração.
"""

import tkinter
from collections.abc import Callable
from typing import Any, ClassVar, Optional

import customtkinter as ctk

from core.hotkey import (
    MODIFICADORES_NOMES,
    SISTEMA_RESERVADOS,
    TECLAS_FUNCAO,
    VK_MAP,
    conflito_interno,
    conflito_sistema,
    erro_formato_atalho,
    tecla_registravel,
    teclas_da_combinacao,
)
from ui.theme import (
    APPLE_ACCENT,
    APPLE_DESTRUCTIVE,
    APPLE_KEYCAP_BG,
    APPLE_KEYCAP_BORDER,
    APPLE_TEXT_PRIMARY,
    FONT_FAMILY,
)

__all__ = [
    "VK_MAP",
    "Keycap",
    "conflito_interno",
    "conflito_sistema",
    "erro_formato_atalho",
    "tecla_registravel",
    "teclas_da_combinacao",
]

# keysym do Tk -> nome que o parse_hotkey conhece. Gravado como o Tk chama ("prior", "next",
# "comma", "minus", "period"), o atalho era recusado ao registrar.
_TECLA_DO_TK = {
    "prior": "pageup",
    "next": "pagedown",
    "print": "printscreen",
    "scroll_lock": "scrolllock",
    "num_lock": "numlock",
    "comma": ",",
    "minus": "-",
    "period": ".",
}


class Keycap(ctk.CTkFrame):
    """Representação visual e interativa de atalhos de teclado estilo Apple Keyboard."""

    # Só um Keycap captura por vez: clicar num segundo cancela o primeiro, senão os dois
    # gravavam a mesma tecla.
    _captura_ativa: Optional["Keycap"] = None

    # Teclas reservadas do sistema operacional (fonte única em core.hotkey)
    SISTEMA_RESERVADOS: ClassVar[dict[str, str]] = SISTEMA_RESERVADOS

    def __init__(
        self,
        master: Any,
        keys: list[str] | str,
        on_change: Callable[[str], None] | None = None,
        editable: bool = True,
        existing_hotkeys: dict | None = None,
        chave_propria: str | None = None,
        nomes_atalhos: dict[str, str] | None = None,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_change = on_change
        self.editable = editable
        # {campo do .env: combinação} de todos os atalhos; `chave_propria` é o deste Keycap,
        # que não conflita consigo mesmo. `nomes_atalhos` dá o nome que aparece no aviso.
        self.existing_hotkeys = existing_hotkeys or {}
        self.chave_propria = chave_propria
        self.nomes_atalhos = nomes_atalhos if nomes_atalhos is not None else {}
        self.is_capturing = False

        self.hotkey_str = self._normalizar_hotkey(keys)
        self.keycaps_box = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2" if editable else "")
        self.keycaps_box.pack(anchor="e")

        self.lbl_conflito = None

        self._renderizar_teclas()

        if self.editable:
            self.keycaps_box.bind("<Button-1>", lambda e: self.iniciar_captura())
            # As teclas chegam ao próprio Keycap, que recebe o foco na captura. Antes o
            # <KeyPress> era ligado no toplevel e o unbind tirava junto os handlers de tecla
            # dos outros widgets da janela. tkinter.Misc.bind liga no frame em si (o bind do
            # CTkFrame liga no canvas interno, que não recebe o foco).
            tkinter.Misc.bind(self, "<KeyPress>", self._on_key_press, add="+")
            tkinter.Misc.bind(self, "<FocusOut>", lambda e: self.cancelar_captura_se_ativa(), add="+")
            # A aba escondida (grid_forget) desmapeia os widgets de dentro: captura pela metade
            # não pode sobreviver à troca de aba.
            tkinter.Misc.bind(self, "<Unmap>", lambda e: self.cancelar_captura_se_ativa(), add="+")

    def _normalizar_hotkey(self, keys: list[str] | str) -> str:
        if isinstance(keys, list):
            # Filtra '+' soltos se vierem de listas legadas
            partes = [k.strip() for k in keys if k.strip() != "+"]
            return "+".join(partes)
        return str(keys).strip()

    def _obter_lista_teclas(self) -> list[str]:
        partes = [p.strip() for p in self.hotkey_str.split("+") if p.strip()]
        return partes or ["Definir"]

    def _renderizar_teclas(self):
        for w in self.keycaps_box.winfo_children():
            w.destroy()

        if self.is_capturing:
            box_cap = ctk.CTkFrame(
                self.keycaps_box,
                fg_color=APPLE_KEYCAP_BG,
                border_width=1,
                border_color=APPLE_ACCENT,
                corner_radius=6,
                height=26,
            )
            box_cap.pack(side="left")
            ctk.CTkLabel(
                box_cap,
                text="Pressione as teclas... (Esc cancela)",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                text_color=APPLE_ACCENT,
            ).pack(padx=8, pady=3)
            return

        teclas = self._obter_lista_teclas()
        for idx, k in enumerate(teclas):
            # Formatação amigável (ex: 'ctrl' -> 'Ctrl')
            rotulo = k.capitalize()
            if rotulo.lower() == "space":
                rotulo = "Espaço"

            cap = ctk.CTkFrame(
                self.keycaps_box,
                fg_color=APPLE_KEYCAP_BG,
                border_width=1,
                border_color=APPLE_KEYCAP_BORDER,
                corner_radius=6,
                height=26,
            )
            cap.pack(side="left", padx=(0 if idx == 0 else 4, 0))

            lbl = ctk.CTkLabel(
                cap,
                text=rotulo,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                text_color=APPLE_TEXT_PRIMARY,
                width=28,
            )
            lbl.pack(padx=6, pady=2)

            if self.editable:
                cap.bind("<Button-1>", lambda e: self.iniciar_captura())
                lbl.bind("<Button-1>", lambda e: self.iniciar_captura())

    def iniciar_captura(self):
        if not self.editable or self.is_capturing:
            return
        anterior = Keycap._captura_ativa
        if anterior is not None and anterior is not self:
            try:
                anterior.cancelar_captura_se_ativa()
            except tkinter.TclError:
                pass  # o anterior já foi destruído junto com a tela dele
        Keycap._captura_ativa = self
        self.is_capturing = True
        self.teclas_pressionadas = set()
        self._renderizar_teclas()
        try:
            tkinter.Misc.focus_set(self)
        except tkinter.TclError:
            pass

    def cancelar_captura_se_ativa(self):
        if self.is_capturing:
            self.cancelar_captura()

    def _encerrar_captura(self):
        self.is_capturing = False
        if Keycap._captura_ativa is self:
            Keycap._captura_ativa = None

    def destroy(self):
        # Destruído no meio da captura (a aba refeita, a janela fechada): a vez fica livre,
        # senão a próxima captura tentaria cancelar um widget que não existe mais.
        if Keycap._captura_ativa is self:
            Keycap._captura_ativa = None
        super().destroy()

    def _on_key_press(self, event):
        if not self.is_capturing:
            return

        # Esc cancela captura
        if event.keysym in ("Escape", "Esc"):
            self.cancelar_captura()
            return "break"

        # Converte keysym para identificador
        sym = event.keysym.lower()
        key_map = {
            "control_l": "ctrl", "control_r": "ctrl",
            "alt_l": "alt", "alt_r": "alt",
            "shift_l": "shift", "shift_r": "shift",
            # "space", e não "espaço": é o nome dos atalhos padrão e do .env, e o orquestrador
            # compara o texto das combinações para achar as repetidas.
            "space": "space", "return": "enter"
        }
        nome_tecla = _TECLA_DO_TK.get(sym, key_map.get(sym, sym))

        # Teclas modificadoras sozinhas aguardam a tecla principal
        if nome_tecla in ("ctrl", "alt", "shift", "win"):
            self.teclas_pressionadas.add(nome_tecla)
            return "break"

        # Tecla principal pressionada com os modificadores do evento
        mods = []
        if event.state & 0x4:  # Control
            mods.append("ctrl")
        if event.state & 0x1:  # Shift
            mods.append("shift")
        # Alt é 0x20000 no Tk do Windows. O 0x8 é o Num Lock: lido como Alt, ele punha "alt+"
        # em todo atalho gravado com o Num Lock ligado.
        if event.state & 0x20000 or "alt" in self.teclas_pressionadas:
            mods.append("alt")

        for m in sorted(self.teclas_pressionadas):
            if m not in mods and m != nome_tecla:
                mods.append(m)

        if not mods and nome_tecla not in TECLAS_FUNCAO:
            # Exige pelo menos um modificador para atalhos gerais
            return "break"

        combo_parts = [m for m in ["ctrl", "alt", "shift", "win"] if m in mods]
        if nome_tecla not in combo_parts:
            combo_parts.append(nome_tecla)

        nova_combo = "+".join(combo_parts)
        self.finalizar_captura(nova_combo)
        return "break"

    def cancelar_captura(self):
        self._encerrar_captura()
        self._limpar_conflito()
        self._renderizar_teclas()

    def _limpar_conflito(self):
        """Tira o aviso de conflito: ele falava de uma captura que já não está na tela."""
        if self.lbl_conflito:
            self.lbl_conflito.destroy()
            self.lbl_conflito = None

    def finalizar_captura(self, nova_combo: str):
        self._encerrar_captura()

        conflito_msg = self._conflito(nova_combo)
        if not conflito_msg:
            self.hotkey_str = nova_combo
        self._renderizar_teclas()

        if conflito_msg:
            # Não salva, e o Keycap segue com a combinação de antes. Com a mesma combinação em
            # dois atalhos, o orquestrador a dá ao primeiro na ordem dele e o outro fica sem:
            # escolher Ctrl+Espaço para o prompt tirava o atalho do ditado. Uma combinação do
            # sistema (Ctrl+C) seria sequestrada no Windows inteiro.
            if not self.lbl_conflito:
                self.lbl_conflito = ctk.CTkLabel(
                    self,
                    text=conflito_msg,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                    text_color=APPLE_DESTRUCTIVE,
                )
                self.lbl_conflito.pack(anchor="e", pady=(2, 0))
            else:
                self.lbl_conflito.configure(text=conflito_msg)
            return

        self._limpar_conflito()
        if self.on_change:
            self.on_change(nova_combo)

    def _conflito(self, combo: str) -> str | None:
        """O aviso, se `combo` já é de outro atalho do Willy ou do sistema; senão None.

        Comparava a combinação com as CHAVES do dicionário ("VOICE_HOTKEY"), e nunca achava.
        """
        teclas = teclas_da_combinacao(combo)
        principal = [t for t in teclas if t not in MODIFICADORES_NOMES]
        if principal and not tecla_registravel(principal[0]):
            return f"A tecla {principal[0]} não serve para atalho global. Escolha outra"
        descricao_sistema = conflito_sistema(combo)
        if descricao_sistema:
            return f"Conflito com atalho do sistema: {descricao_sistema}. Escolha outra combinação"
        chave_conflito = conflito_interno(combo, self.existing_hotkeys, self.chave_propria)
        if chave_conflito:
            nome = self.nomes_atalhos.get(chave_conflito, chave_conflito)
            # Para trocar as teclas de dois atalhos, um deles passa antes por uma livre.
            return f"Conflito com atalho do Willy: {nome}. Escolha outra ou mude a de {nome} antes"
        return None

    def set_keys(self, keys: list[str] | str):
        self.hotkey_str = self._normalizar_hotkey(keys)
        self._limpar_conflito()
        self._renderizar_teclas()

    def get_hotkey(self) -> str:
        return self.hotkey_str

