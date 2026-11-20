"""
Seção "Regras por Aplicativo (Contexto Automático)" da aba Ajustes.

Cada regra liga um app (o executável, como "slack.exe") e/ou um trecho do título da janela
("gmail") a um tom, um modo (ditado ou tradução) e uma instrução extra para a IA. O ditado feito
naquele app sai assim sem a pessoa trocar de atalho (ver TranscriptionPipeline._regra_do_destino).
Cada mudança grava na hora, pelo callback, como as substituições da aba Vocabulário.
"""

import sys
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from core.storage.settings_store import sanitizar_regras_de_app
from ui.components import Button
from ui.theme import (
    APPLE_ACCENT,
    APPLE_BG_CARD,
    APPLE_BORDER_CARD,
    APPLE_DESTRUCTIVE,
    APPLE_INPUT_BG,
    APPLE_INPUT_BORDER,
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_TERTIARY,
    FONT_FAMILY,
)

# Valor gravado -> rótulo na tela. "default" deixa valer o da configuração global.
ROTULOS_DE_TOM = {
    "default": "Tom padrão",
    "natural": "Natural",
    "formal": "Formal",
    "concise": "Conciso",
    "bullet_points": "Tópicos",
    "technical": "Técnico",
}
ROTULOS_DE_MODO = {
    "default": "Modo padrão",
    "transcribe": "Ditado",
    "translate": "Traduzir → EN",
    "translate_es": "Traduzir → ES",
}
# Os atalhos para as regras mais comuns: (rótulo, regras que ele grava).
PRESETS = (
    ("WhatsApp/Discord → Natural", ({"app_exe": "whatsapp.exe", "tone": "natural"},
                                    {"app_exe": "discord.exe", "tone": "natural"})),
    ("Word/Outlook → Formal", ({"app_exe": "winword.exe", "tone": "formal"},
                               {"app_exe": "outlook.exe", "tone": "formal"})),
    ("VS Code/Cursor → Técnico", ({"app_exe": "code.exe", "tone": "technical"},
                                  {"app_exe": "cursor.exe", "tone": "technical"})),
)


def _mesmo_filtro(a: dict[str, str], b: dict[str, str]) -> bool:
    return a["app_exe"] == b["app_exe"] and a["title_contains"] == b["title_contains"]


def descrever_regra(regra: dict[str, str]) -> str:
    """Uma linha da lista: onde vale e o que muda. Ex.: "slack.exe → Conciso · Traduzir → EN"."""
    onde = regra["app_exe"] or "qualquer app"
    if regra["title_contains"]:
        onde += f" · título contém “{regra['title_contains']}”"
    efeitos = [ROTULOS_DE_TOM.get(regra["tone"], regra["tone"])] if regra["tone"] != "default" else []
    if regra["action_mode"] != "default":
        efeitos.append(ROTULOS_DE_MODO.get(regra["action_mode"], regra["action_mode"]))
    if regra["custom_instruction"]:
        efeitos.append("instrução extra")
    return f"{onde} → {' · '.join(efeitos) or 'sem efeito'}"


class SecaoRegrasPorApp(ctk.CTkFrame):
    """O cartão das regras por aplicativo: a lista, o formulário e os presets.

    Callbacks: `get_app_rules()` -> lista; `on_save_app_rules(lista)` -> bool (grava e põe em
    vigor); `get_last_external_app()` -> (executável, título) ou None.
    """

    def __init__(self, master: Any, callbacks: dict[str, Callable] | None = None, **kwargs):
        super().__init__(master, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1,
                         border_color=APPLE_BORDER_CARD, **kwargs)
        self.callbacks = callbacks or {}
        self.regras: list[dict[str, str]] = []
        self.linhas_da_lista: list[Any] = []
        self._construir_ui()
        self.recarregar()

    def _construir_ui(self):
        ctk.CTkLabel(
            self, text="Regras por Aplicativo (Contexto Automático)", anchor="w",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY,
        ).pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            self, anchor="w", justify="left", wraplength=620,
            text=("O ditado feito num app sai no tom e no idioma dele, sem trocar de atalho. "
                  "O tom falado (\"Willy, em tópicos: ...\") e o atalho de tradução continuam valendo mais que a regra."),
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY,
        ).pack(fill="x", padx=16, pady=(0, 8))

        self.frame_lista = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_lista.pack(fill="x", padx=16)

        ctk.CTkFrame(self, height=1, fg_color=APPLE_SEPARATOR).pack(fill="x", padx=16, pady=8)

        def _campo(pai: Any, dica: str, largura: int) -> ctk.CTkEntry:
            return ctk.CTkEntry(pai, placeholder_text=dica, width=largura, height=30, corner_radius=8,
                                fg_color=APPLE_INPUT_BG, border_color=APPLE_INPUT_BORDER, border_width=1,
                                font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=APPLE_TEXT_PRIMARY)

        filtros = ctk.CTkFrame(self, fg_color="transparent")
        filtros.pack(fill="x", padx=16)
        self.entry_app = _campo(filtros, "Aplicativo .exe (ex.: slack.exe)", 210)
        self.entry_app.pack(side="left")
        self.entry_titulo = _campo(filtros, "Título contém (opcional)", 190)
        self.entry_titulo.pack(side="left", padx=(8, 0))
        self.btn_capturar = Button(filtros, text="Capturar último app", variant="secondary",
                                   command=self.capturar_ultimo_app)
        self.btn_capturar.pack(side="left", padx=(8, 0))

        efeitos = ctk.CTkFrame(self, fg_color="transparent")
        efeitos.pack(fill="x", padx=16, pady=(8, 0))
        self.opt_tom = ctk.CTkOptionMenu(efeitos, values=list(ROTULOS_DE_TOM.values()), width=130,
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        self.opt_tom.set(ROTULOS_DE_TOM["default"])
        self.opt_tom.pack(side="left")
        self.opt_modo = ctk.CTkOptionMenu(efeitos, values=list(ROTULOS_DE_MODO.values()), width=140,
                                          font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        self.opt_modo.set(ROTULOS_DE_MODO["default"])
        self.opt_modo.pack(side="left", padx=(8, 0))
        self.entry_instrucao = _campo(efeitos, "Instrução extra para a IA (opcional)", 260)
        self.entry_instrucao.pack(side="left", padx=(8, 0), fill="x", expand=True)

        acoes = ctk.CTkFrame(self, fg_color="transparent")
        acoes.pack(fill="x", padx=16, pady=(8, 0))
        self.btn_adicionar = Button(acoes, text="Adicionar regra", variant="primary", command=self.adicionar_regra)
        self.btn_adicionar.pack(side="left")
        self.lbl_status = ctk.CTkLabel(acoes, text="", anchor="w", font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                                       text_color=APPLE_TEXT_SECONDARY)
        self.lbl_status.pack(side="left", padx=(10, 0), fill="x", expand=True)

        presets = ctk.CTkFrame(self, fg_color="transparent")
        presets.pack(fill="x", padx=16, pady=(8, 14))
        ctk.CTkLabel(presets, text="Presets:", font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                     text_color=APPLE_TEXT_TERTIARY).pack(side="left", padx=(0, 6))
        self.botoes_de_preset: list[Any] = []
        for rotulo, regras in PRESETS:
            botao = Button(presets, text=rotulo, variant="ghost", command=lambda r=regras: self.aplicar_preset(r))
            botao.pack(side="left", padx=(0, 4))
            self.botoes_de_preset.append(botao)

    def _status(self, texto: str, ok: bool = True):
        self.lbl_status.configure(text=texto, text_color=APPLE_ACCENT if ok else APPLE_DESTRUCTIVE)

    def recarregar(self):
        """Relê as regras em vigor (get_app_rules) e refaz a lista."""
        ler = self.callbacks.get("get_app_rules")
        try:
            self.regras = sanitizar_regras_de_app(ler() if ler else [])
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback get_app_rules na recarga da seção
            print(f"[SecaoRegrasPorApp] Erro ao carregar regras: {e}", file=sys.stderr)
            self.regras = []
        for linha in self.linhas_da_lista:
            linha.destroy()
        self.linhas_da_lista = []
        if not self.regras:
            vazio = ctk.CTkLabel(self.frame_lista, text="Nenhuma regra. Os ditados usam o tom e o modo dos Ajustes.",
                                 anchor="w", font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                                 text_color=APPLE_TEXT_TERTIARY)
            vazio.pack(fill="x", pady=2)
            self.linhas_da_lista.append(vazio)
            return
        for indice, regra in enumerate(self.regras):
            linha = ctk.CTkFrame(self.frame_lista, fg_color="transparent")
            linha.pack(fill="x", pady=1)
            ctk.CTkLabel(linha, text=descrever_regra(regra), anchor="w",
                         font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                         text_color=APPLE_TEXT_PRIMARY).pack(side="left", fill="x", expand=True)
            Button(linha, text="Remover", variant="ghost",
                   command=lambda i=indice: self.remover_regra(i)).pack(side="right")
            self.linhas_da_lista.append(linha)

    def _salvar(self, novas: list[dict[str, Any]], feito: str) -> bool:
        """Grava a lista inteira. Sem gravar, a lista na tela continua a do disco."""
        salvar = self.callbacks.get("on_save_app_rules")
        if not salvar or not salvar(novas):
            self._status("Não consegui salvar as regras. Tente de novo", ok=False)
            return False
        self.recarregar()
        self._status(feito)
        return True

    def _com_regras(self, novas: list[dict[str, str]]) -> list[dict[str, str]]:
        """A lista atual com `novas`: a de mesmo app e título é trocada no lugar, a outra entra no fim."""
        resultado = [dict(r) for r in self.regras]
        for nova in novas:
            existente = next((i for i, r in enumerate(resultado) if _mesmo_filtro(r, nova)), None)
            if existente is None:
                resultado.append(nova)
            else:
                resultado[existente] = nova
        return resultado

    def adicionar_regra(self) -> bool:
        """A regra do formulário entra na lista (ou troca a de mesmo app e título) e é gravada."""
        tom = next((k for k, v in ROTULOS_DE_TOM.items() if v == self.opt_tom.get()), "default")
        modo = next((k for k, v in ROTULOS_DE_MODO.items() if v == self.opt_modo.get()), "default")
        regra = sanitizar_regras_de_app([{
            "app_exe": self.entry_app.get(),
            "title_contains": self.entry_titulo.get(),
            "tone": tom,
            "action_mode": modo,
            "custom_instruction": self.entry_instrucao.get(),
        }])
        if not regra:
            self._status("Diga o aplicativo (.exe) ou um trecho do título da janela", ok=False)
            return False
        regra = regra[0]
        if tom == "default" and modo == "default" and not regra["custom_instruction"]:
            self._status("Escolha um tom, um modo ou uma instrução para a regra", ok=False)
            return False
        if not self._salvar(self._com_regras([regra]), f"Regra salva: {descrever_regra(regra)}"):
            return False
        for campo in (self.entry_app, self.entry_titulo, self.entry_instrucao):
            campo.delete(0, "end")
        self.opt_tom.set(ROTULOS_DE_TOM["default"])
        self.opt_modo.set(ROTULOS_DE_MODO["default"])
        return True

    def remover_regra(self, indice: int) -> bool:
        if not 0 <= indice < len(self.regras):
            return False
        removida = self.regras[indice]
        novas = [r for i, r in enumerate(self.regras) if i != indice]
        return self._salvar(novas, f"Regra removida: {removida['app_exe'] or removida['title_contains']}")

    def aplicar_preset(self, regras: Any) -> bool:
        """Grava as regras do preset; uma de mesmo app já existente é trocada pela do preset."""
        return self._salvar(self._com_regras(sanitizar_regras_de_app(list(regras))), "Preset aplicado")

    def capturar_ultimo_app(self) -> bool:
        """Preenche o aplicativo com o último em que a pessoa estava fora do Willy."""
        capturar = self.callbacks.get("get_last_external_app")
        app = capturar() if capturar else None
        if not app or not app[0] or app[0] in ("unknown.exe", "desktop.exe"):
            self._status("Nenhum app ainda: clique no app que quer configurar e volte aqui", ok=False)
            return False
        self.entry_app.delete(0, "end")
        self.entry_app.insert(0, app[0])
        self._status(f"Capturado: {app[0]}" + (f" ({app[1][:40]})" if app[1] else ""))
        return True
