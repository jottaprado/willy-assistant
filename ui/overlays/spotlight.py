"""
Mini-Spotlight de Histórico Rápido do Willy (estilo Apple Spotlight / Raycast).
Permite buscar e colar instantaneamente transcrições anteriores em qualquer app com Ctrl + Alt + H.
"""

import ctypes
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

import customtkinter as ctk

from core.context import ContextManager
from core.text_processing import normalize_for_search
from ui.overlays.pill import (
    _MONITORINFO,
    configurar_prototipos_monitor,
    obter_hmonitor_e_area,
)
from ui.theme import (
    FLUTUANTE_AZUL_ACAO,
    FLUTUANTE_BORDA,
    FLUTUANTE_BORDA_SUAVE,
    FLUTUANTE_CARTAO,
    FLUTUANTE_CARTAO_ATIVO,
    FLUTUANTE_CIANO_CLARO,
    FLUTUANTE_FUNDO,
    FLUTUANTE_LARANJA,
    FLUTUANTE_LILAS,
    FLUTUANTE_ROLAGEM_HOVER,
    FLUTUANTE_TEXTO,
    FLUTUANTE_TEXTO_APAGADO,
    FLUTUANTE_TEXTO_SUAVE,
    FLUTUANTE_VERDE,
)

FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else "Helvetica"
BG_DARK = FLUTUANTE_FUNDO
BG_CARD = FLUTUANTE_CARTAO
BG_CARD_ACTIVE = FLUTUANTE_CARTAO_ATIVO
BORDER_COLOR = FLUTUANTE_BORDA
BORDER_ACTIVE = FLUTUANTE_AZUL_ACAO
TEXT_PRIMARY = FLUTUANTE_TEXTO
TEXT_SECONDARY = FLUTUANTE_TEXTO_APAGADO
ACCENT_BLUE = FLUTUANTE_AZUL_ACAO
ACCENT_PURPLE = FLUTUANTE_LILAS
ACCENT_CYAN = FLUTUANTE_CIANO_CLARO
ACCENT_ORANGE = FLUTUANTE_LARANJA
ACCENT_GREEN = FLUTUANTE_VERDE
SCROLLBAR_BTN = FLUTUANTE_BORDA_SUAVE
SCROLLBAR_HOVER = FLUTUANTE_ROLAGEM_HOVER

LARGURA, ALTURA = 540, 360  # em unidades do CTk: o CTk multiplica pela escala do monitor
# Entre devolver o foco ao app e o Ctrl+V: colado no mesmo instante, o Windows ainda não
# trocou a janela ativa e o texto caía onde estava o foco antes.
ATRASO_DA_COLAGEM_S = 0.06
# Entre o <FocusOut> e a conferência: o foco passa por um instante em nenhum widget quando
# vai da busca para um cartão.
ESPERA_DO_FOCO_MS = 160
_MONITOR_DEFAULTTONEAREST = 2

__all__ = ["_MONITORINFO", "HistorySpotlight", "posicao_centralizada"]


def _carregar_win32():
    """WinDLL próprios de user32 e shcore com assinaturas de 64 bits."""
    if sys.platform != "win32":
        return None, None
    u = ctypes.WinDLL("user32")
    configurar_prototipos_monitor(u)

    sh = ctypes.WinDLL("shcore")
    sh.GetDpiForMonitor.restype = ctypes.c_long
    sh.GetDpiForMonitor.argtypes = [
        wintypes.HMONITOR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
    ]
    return u, sh


_user32, _shcore = _carregar_win32()


def _monitor_ativo(hwnd: int, cursor: tuple[int, int]) -> tuple[tuple[int, int, int, int], float] | None:
    """(área de trabalho, escala de DPI) do monitor de `hwnd` ou, sem ela, do cursor.

    None fora do Windows ou se a API falhar: quem chama cai na tela primária.
    """
    if sys.platform != "win32" or _user32 is None or _shcore is None:
        return None
    try:
        res = obter_hmonitor_e_area(_user32, hwnd, cursor)
        if res is None:
            return None
        hmon, area = res
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        escala = 1.0
        if _shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            escala = dpi_x.value / 96
        return area, escala
    except Exception:  # noqa: BLE001 — fronteira defensiva: GetDpiForMonitor / MonitorFromWindow Win32/ctypes
        return None


def posicao_centralizada(area: tuple[int, int, int, int], largura_px: int, altura_px: int) -> tuple[int, int]:
    """Canto superior esquerdo do Spotlight centrado em `area`, um pouco acima do meio."""
    left, top, right, bottom = area
    return left + (right - left - largura_px) // 2, top + (bottom - top - altura_px) // 3


class HistorySpotlight(ctk.CTkToplevel):
    """Janela flutuante minimalista para acesso rápido ao histórico de transcrições."""

    def __init__(self, master=None, on_paste_callback: Callable[[str], None] | None = None):
        super().__init__(master)
        self.on_paste_callback = on_paste_callback

        self.title("Willy Spotlight")
        self.geometry(f"{LARGURA}x{ALTURA}")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)

        # Remove bordas do SO e mantém sobreposto estilo Spotlight nativo
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.withdraw()

        self.items: list[dict[str, Any]] = []
        self.filtered_items: list[dict[str, Any]] = []
        self.selected_index: int = 0
        self.card_widgets: list[ctk.CTkFrame] = []
        # O app em que a pessoa estava quando abriu o Spotlight: é nele que a colagem cai.
        self._janela_anterior = 0
        self._timer_foco = None
        # Os itens (pelo id() do dict) que o Tab trocou para a fala antes da IA (raw_text): o
        # card mostra o original, e o Enter cola o original. Vale até o Spotlight fechar.
        self._mostrando_original: set = set()

        self._construir_ui()
        self._configurar_atalhos()

    def _construir_ui(self):
        # Borda externa estilizada Apple
        self.container_principal = ctk.CTkFrame(
            self,
            fg_color=BG_DARK,
            border_width=1,
            border_color=BORDER_COLOR,
            corner_radius=14
        )
        self.container_principal.pack(fill="both", expand=True, padx=2, pady=2)
        self.container_principal.grid_columnconfigure(0, weight=1)
        self.container_principal.grid_rowconfigure(1, weight=1)

        # Barra de Busca Superior
        busca_box = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        busca_box.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        busca_box.grid_columnconfigure(0, weight=1)

        self.entry_busca = ctk.CTkEntry(
            busca_box,
            placeholder_text="🔍  Buscar no histórico recente (↑↓ navega, Enter cola)...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            height=38,
            corner_radius=10,
            fg_color=BG_CARD,
            border_color=BORDER_COLOR,
            border_width=1,
            text_color=TEXT_PRIMARY
        )
        self.entry_busca.grid(row=0, column=0, sticky="ew")
        self.entry_busca.bind("<KeyRelease>", self._ao_digitar_busca)

        # Lista de Itens com Rolagem
        self.scroll_lista = ctk.CTkScrollableFrame(
            self.container_principal,
            fg_color="transparent",
            corner_radius=8,
            scrollbar_button_color=SCROLLBAR_BTN,
            scrollbar_button_hover_color=SCROLLBAR_HOVER,
            scrollbar_fg_color="transparent"
        )
        self.scroll_lista.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        self.scroll_lista.grid_columnconfigure(0, weight=1)

        # Rodapé com dicas de teclas
        rodape = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        rodape.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            rodape,
            text="ESC fechar   •   ↑↓ selecionar   •   TAB original/refinado   •   ENTER colar no app",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_SECONDARY
        ).pack(side="left")

        self._configurar_pool_widgets()

    def _configurar_atalhos(self):
        self.bind("<Escape>", lambda e: self.fechar())
        self.entry_busca.bind("<Escape>", lambda e: self.fechar())
        self.entry_busca.bind("<Down>", self._navegar_baixo)
        self.entry_busca.bind("<Up>", self._navegar_cima)
        self.entry_busca.bind("<Return>", self._confirmar_selecao)
        self.entry_busca.bind("<Tab>", self._alternar_original)
        self.bind("<FocusOut>", self._ao_perder_foco)

    def _ao_perder_foco(self, event):
        # Um <FocusOut> chega por widget de dentro que perde o foco: sem cancelar o anterior,
        # os timers se acumulavam.
        self._cancelar_timer_foco()
        self._timer_foco = self.after(ESPERA_DO_FOCO_MS, self._verificar_foco)

    def _cancelar_timer_foco(self):
        if self._timer_foco is not None:
            try:
                self.after_cancel(self._timer_foco)
            except tk.TclError:
                pass
            self._timer_foco = None

    def _verificar_foco(self):
        """Fecha se o foco saiu do Spotlight. Foco no Dashboard também é fora: antes só fechava
        sem foco nenhum no Willy, e o Spotlight ficava aberto por cima do painel."""
        self._timer_foco = None
        try:
            focus_widget = self.focus_get()
        except (KeyError, tk.TclError):
            focus_widget = None  # foco num widget interno do Tk (menu, diálogo nativo)
        if focus_widget is None or focus_widget.winfo_toplevel() is not self:
            self.fechar()

    def mostrar(self, history_items: list[dict[str, Any]], on_paste_callback: Callable[[str], None] | None = None):
        """Abre o Spotlight no monitor do app em que a pessoa está, com os itens mais recentes."""
        if on_paste_callback:
            self.on_paste_callback = on_paste_callback
        self._cancelar_timer_foco()

        self.items = list(reversed(history_items)) if history_items else []
        self._mostrando_original.clear()
        self.entry_busca.delete(0, "end")
        self.selected_index = 0
        self._filtrar_itens("")

        # Antes do focus_force, que faz do Spotlight a janela ativa. Janela do próprio Willy
        # (o Dashboard) não é onde colar. Já aberto (o atalho apertado de novo), o primeiro
        # plano é o próprio Spotlight: o app guardado na abertura continua sendo o destino.
        if self.state() == "withdrawn":
            anterior = ContextManager.get_foreground_hwnd()
            self._janela_anterior = 0 if ContextManager.eh_janela_do_willy(anterior) else anterior

        self.update_idletasks()
        self.geometry(f"{LARGURA}x{ALTURA}+{self._posicao_no_monitor_ativo()}")
        self.deiconify()
        self.lift()
        self.focus_force()
        self.entry_busca.focus_set()

    def _posicao_no_monitor_ativo(self) -> str:
        """"x+y" do Spotlight centrado no monitor do app anterior (ou do cursor). Abria sempre
        no primário, longe de quem trabalha no segundo monitor."""
        monitor = _monitor_ativo(self._janela_anterior, self.winfo_pointerxy())
        if monitor is None:
            area, escala = (0, 0, self.winfo_screenwidth(), self.winfo_screenheight()), 1.0
        else:
            area, escala = monitor
        # O CTk multiplica a largura pela escala do monitor em que a janela fica (a de DPI vezes
        # a da preferência); x e y vão em pixels, como estão.
        escala *= ctk.ScalingTracker.window_scaling
        x, y = posicao_centralizada(area, round(LARGURA * escala), round(ALTURA * escala))
        return f"{x}+{y}"

    def fechar(self):
        """Oculta o Spotlight."""
        self._cancelar_timer_foco()
        self.withdraw()

    def destroy(self):
        self._cancelar_timer_foco()
        super().destroy()

    def _texto_do_item(self, item: dict[str, Any]) -> str:
        """O texto que o card mostra e o Enter cola: o original, se o Tab o escolheu."""
        cru = item.get("raw_text")
        if id(item) in self._mostrando_original and isinstance(cru, str) and cru.strip():
            return cru
        return item.get("text", "")

    def _alternar_original(self, event=None):
        """Tab: o item selecionado alterna entre o texto refinado e a fala antes da IA (raw_text),
        antes de colar. Sem raw_text diferente do texto, não há o que alternar. O "break" segura
        o Tab do Tk, que passaria o foco adiante e fecharia o Spotlight pelo <FocusOut>."""
        if self.filtered_items and self.selected_index < len(self.filtered_items):
            item = self.filtered_items[self.selected_index]
            cru = item.get("raw_text")
            if isinstance(cru, str) and cru.strip() and cru != item.get("text", ""):
                self._mostrando_original.symmetric_difference_update({id(item)})
                self._renderizar_itens()
        return "break"

    def _ao_digitar_busca(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        query = self.entry_busca.get().strip().lower()
        self.selected_index = 0
        self._filtrar_itens(query)

    def _filtrar_itens(self, query: str):
        if not query:
            self.filtered_items = self.items[:8]
        else:
            q_norm = normalize_for_search(query)
            self.filtered_items = [
                it for it in self.items
                if (
                    q_norm in normalize_for_search(it.get("text", ""))
                    or q_norm in normalize_for_search(it.get("raw_text", ""))
                    or q_norm in normalize_for_search(it.get("mode", ""))
                )
            ][:8]
        self._renderizar_itens()

    def _configurar_pool_widgets(self):
        """Inicializa o Object Pool de cards e fontes cacheadas."""
        self.font_tag = ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold")
        self.font_txt = ctk.CTkFont(family=FONT_FAMILY, size=11)
        self.font_time = ctk.CTkFont(family=FONT_FAMILY, size=10)
        self.font_empty = ctk.CTkFont(family=FONT_FAMILY, size=12)

        self.pool_cards = []
        for i in range(8):
            card = ctk.CTkFrame(
                self.scroll_lista,
                corner_radius=8,
                height=48
            )
            card.grid_columnconfigure(1, weight=1)

            lbl_tag = ctk.CTkLabel(card, font=self.font_tag, width=76)
            lbl_tag.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="w")

            lbl_txt = ctk.CTkLabel(card, font=self.font_txt, anchor="w")
            lbl_txt.grid(row=0, column=1, padx=4, pady=8, sticky="ew")

            lbl_time = ctk.CTkLabel(card, font=self.font_time, width=50)
            lbl_time.grid(row=0, column=2, padx=(4, 10), pady=8, sticky="e")

            self.pool_cards.append({
                "frame": card,
                "lbl_tag": lbl_tag,
                "lbl_txt": lbl_txt,
                "lbl_time": lbl_time
            })

            # Bind UMA vez, na criação do pool. O bind do CTk força add=True, então religar a
            # cada render acumulava handlers: depois de 5 aberturas com ↑↓, um clique colava o
            # texto 16 vezes. O índice é a posição do card, que é a mesma em filtered_items.
            def _ao_clicar(_evento, i=i):
                self._selecionar_indice(i)

            for widget in (card, lbl_tag, lbl_txt, lbl_time):
                widget.bind("<Button-1>", _ao_clicar)

        self.lbl_empty = ctk.CTkLabel(
            self.scroll_lista,
            text="Nenhuma transcrição encontrada.",
            font=self.font_empty,
            text_color=TEXT_SECONDARY
        )

    def _renderizar_itens(self):
        """Atualiza a UI reciclando widgets do Object Pool."""
        self.lbl_empty.pack_forget()

        if not self.filtered_items:
            for pool_item in self.pool_cards:
                pool_item["frame"].pack_forget()
            self.lbl_empty.pack(pady=28)
            return

        modo_cores = {
            "transcribe": (ACCENT_BLUE, "🇧🇷 Ditado"),
            "send": (ACCENT_GREEN, "🚀 Enviar"),
            "translate": (ACCENT_CYAN, "🌐 Tradução"),
            "translate_es": (ACCENT_CYAN, "🌐 Tradução ES"),
            "prompt": (ACCENT_PURPLE, "🎯 Prompt"),
            "transform": (ACCENT_PURPLE, "🪄 Transformar"),
            "action": (ACCENT_ORANGE, "⚡ Ação"),
            "meeting": (ACCENT_GREEN, "🎙️ Reunião")
        }

        for idx in range(8):
            pool_item = self.pool_cards[idx]
            card = pool_item["frame"]

            if idx < len(self.filtered_items):
                item = self.filtered_items[idx]
                is_selected = (idx == self.selected_index)
                modo = item.get("mode", "transcribe")
                cor_tag, tag_label = modo_cores.get(modo, (ACCENT_BLUE, "Ditado"))
                if id(item) in self._mostrando_original:
                    tag_label = "↺ Original"
                ts = item.get("timestamp", "").split(" ")[-1]
                txt = self._texto_do_item(item).strip().replace("\n", " ")
                if len(txt) > 75:
                    txt = txt[:72] + "..."

                card.configure(
                    fg_color=BG_CARD_ACTIVE if is_selected else BG_CARD,
                    border_width=1,
                    border_color=BORDER_ACTIVE if is_selected else BORDER_COLOR
                )

                pool_item["lbl_tag"].configure(text=tag_label, text_color=cor_tag)
                pool_item["lbl_txt"].configure(
                    text=txt,
                    text_color=TEXT_PRIMARY if is_selected else FLUTUANTE_TEXTO_SUAVE
                )
                pool_item["lbl_time"].configure(text=ts)

                card.pack(fill="x", pady=2, padx=2)
            else:
                card.pack_forget()

    def _navegar_baixo(self, event=None):
        if not self.filtered_items:
            return "break"
        self.selected_index = (self.selected_index + 1) % len(self.filtered_items)
        self._renderizar_itens()
        return "break"

    def _navegar_cima(self, event=None):
        if not self.filtered_items:
            return "break"
        self.selected_index = (self.selected_index - 1) % len(self.filtered_items)
        self._renderizar_itens()
        return "break"

    def _selecionar_indice(self, idx: int):
        self.selected_index = idx
        self._confirmar_selecao()

    def _confirmar_selecao(self, event=None):
        if not self.filtered_items or self.selected_index >= len(self.filtered_items):
            return "break"

        item = self.filtered_items[self.selected_index]
        texto = self._texto_do_item(item)
        self.fechar()

        if texto and self.on_paste_callback:
            # Com o Spotlight escondido, quem ganha o foco é a escolha do Windows, e o Ctrl+V cai
            # nela. O foco volta explicitamente ao app de antes, e a colagem vai depois, fora da
            # thread da interface (ela espera o clipboard e o envio das teclas).
            if self._janela_anterior:
                ContextManager.focus_window(self._janela_anterior)
            colar = threading.Timer(ATRASO_DA_COLAGEM_S, self.on_paste_callback, args=(texto,))
            colar.daemon = True
            colar.start()

        return "break"
