"""
Módulo da Aba de Ajustes & Configurações do Willy Dashboard.
Agrupa configurações de silêncio, tom de voz, idioma, perfil de IA, microfone,
chave da Groq Cloud, atalhos de teclado e backup de perfil em padrão macOS System Settings.
"""

import sys
import threading
import time
import tkinter
import webbrowser
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from core import modelos_llm
from core.audio import SAMPLE_RATE, negociar_stream
from core.audio_processing.vad import compute_rms
from core.hotkey import (
    HOTKEYS_PADRAO,
    conflito_interno,
    conflito_sistema,
    erro_formato_atalho,
)
from ui.components import (
    PageHeader,
)
from ui.tabs.regras_por_app import SecaoRegrasPorApp
from ui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_BLUE_LIGHT,
    ACCENT_CYAN,
    ACCENT_CYAN_LIGHT,
    ACCENT_GREEN,
    ACCENT_RED,
    ACCENT_RED_BORDER,
    ACCENT_RED_LIGHT_HOVER,
    APP_VERSION,
    APPLE_ACCENT,
    APPLE_ACCENT_HOVER,
    APPLE_BG_CARD,
    APPLE_BG_HOVER,
    APPLE_BORDER_CARD,
    APPLE_INPUT_BG,
    APPLE_INPUT_BORDER,
    APPLE_KEYCAP_BG,
    APPLE_KEYCAP_BORDER,
    APPLE_SEGMENT_BG,
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_TERTIARY,
    BG_RECESSED,
    BTN_PRIMARY_TEXT,
    FONT_FAMILY,
    METER_DANGER,
    METER_OK,
    METER_WARNING,
    SCROLLBAR_COLOR,
    SCROLLBAR_HOVER,
)

# Rótulo do seletor de modelo -> ID na Groq (ver core.modelos_llm).
MODELOS_NA_TELA = {
    "⚡ Flash (GPT-OSS 20B)": modelos_llm.FLASH,
    "🧠 Smart (GPT-OSS 120B)": modelos_llm.SMART,
    "💻 Coder (Qwen 3.8 27B)": modelos_llm.CODER,
}
ROTULO_DO_PADRAO = next(r for r, m in MODELOS_NA_TELA.items() if m == modelos_llm.PADRAO)


class SettingsTab(ctk.CTkScrollableFrame):
    """Componente modular da Aba de Configurações e Ajustes Globais do Willy."""

    def __init__(
        self,
        master: Any,
        callbacks: dict[str, Callable] | None = None,
        current_config: dict[str, Any] | None = None,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color="transparent",
            scrollbar_button_color=SCROLLBAR_COLOR,
            scrollbar_button_hover_color=SCROLLBAR_HOVER,
            scrollbar_fg_color="transparent",
            **kwargs,
        )
        self.callbacks = callbacks or {}
        self._dev_map: dict[str, int | None] = {"Padrão do Sistema": None}
        self._sys_dev_map: dict[str, int | None] = {"Nenhum (Apenas Microfone)": None}
        self._mic_testing = False
        self._mic_stop_event = threading.Event()
        self._falha_carregamento_config = False
        self._nome_do_campo: dict[str, str] = {}  # nome Tk do campo de atalho -> rótulo na tela

        self.grid_columnconfigure(0, weight=1)
        self._construir_ui()
        # Trocar de aba, esconder ou minimizar a janela desmapeia a aba: o teste de microfone
        # seguia com o microfone aberto e o medidor andando sem ninguém vendo.
        tkinter.Misc.bind(self, "<Unmap>", lambda e: self._parar_teste_se_ativo(), add="+")

        if current_config is not None or self.callbacks.get("get_settings"):
            self.recarregar_dados(current_config)

    def _safe_after(self, delay_ms: int, func: Callable, *args):
        """Despacha com segurança para a thread de UI evitando exceções se destruído."""
        if self.callbacks.get("safe_dispatch_ui"):
            try:
                self.callbacks["safe_dispatch_ui"](func, *args, delay_ms=delay_ms)
                return
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro em safe_dispatch_ui: {e}", file=sys.stderr)
        try:
            if self.winfo_exists():
                self.after(delay_ms, func, *args)
        except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de widget/áudio em ajustes
            pass

    def _construir_ui(self):
        self.page_header = PageHeader(
            self,
            title="Ajustes",
            subtitle="Personalize o comportamento, a inteligência e as preferências do Willy.",
        )
        self.page_header.pack(fill="x", pady=(0, 10))

        # 0. Chave da Groq API (no topo para facilitar diagnóstico e troca imediata)
        c_api = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_api.pack(fill="x", pady=6)
        self.card_credenciais = c_api
        ctk.CTkLabel(c_api, text="Credenciais da Groq API", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_api, text="O Willy usa os modelos da Groq Cloud para transcrição em tempo real. Hoje basta 1 chave gratuita e sem cartão de crédito.", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY, justify="left").pack(anchor="w", padx=16, pady=(0, 10))

        acoes_chave = ctk.CTkFrame(c_api, fg_color="transparent")
        acoes_chave.pack(anchor="w", padx=16, pady=(0, 10))

        btn_obter_chave = ctk.CTkButton(
            acoes_chave,
            text="Obter Chave Gratuita (console.groq.com/keys)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=34,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._abrir_site_groq,
        )
        btn_obter_chave.pack(side="left", padx=(0, 8))

        self.btn_testar_key = ctk.CTkButton(
            acoes_chave,
            text="Testar Chave",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=34,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._testar_chave_api,
        )
        self.btn_testar_key.pack(side="left", padx=(0, 8))

        self.btn_reverificar_cofre = ctk.CTkButton(
            acoes_chave,
            text="Reverificar Cofre",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            height=34,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._reverificar_cofre_api,
        )
        self.btn_reverificar_cofre.pack(side="left")

        passo_texto = "Passo a passo:\n1. Clique em Obter Chave Gratuita para abrir console.groq.com/keys no navegador.\n2. Entre com sua conta Google ou GitHub, clique em Create API Key e copie o código (gsk_...).\n3. Cole abaixo, clique em Testar Chave se quiser conferir antes e depois em Salvar e Aplicar Ajustes."
        ctk.CTkLabel(c_api, text=passo_texto, font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY, justify="left").pack(anchor="w", padx=16, pady=(0, 10))

        api_box = ctk.CTkFrame(c_api, fg_color="transparent")
        api_box.pack(fill="x", padx=16, pady=(0, 8))
        api_box.grid_columnconfigure(0, weight=1)

        self.entry_key = ctk.CTkEntry(api_box, placeholder_text="Cole sua chave aqui (gsk_...)", show="•", height=38, corner_radius=8, fg_color=APPLE_INPUT_BG, border_color=APPLE_INPUT_BORDER, border_width=1, text_color=APPLE_TEXT_PRIMARY)
        self.entry_key.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_ver_key = ctk.CTkButton(api_box, text="Ver", width=42, height=38, corner_radius=8, fg_color=APPLE_KEYCAP_BG, hover_color=APPLE_BG_HOVER, border_width=1, border_color=APPLE_KEYCAP_BORDER, text_color=APPLE_TEXT_PRIMARY, command=self._toggle_ver_chave)
        self.btn_ver_key.grid(row=0, column=1)

        self.lbl_status_key = ctk.CTkLabel(c_api, text="", font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"), anchor="w")
        self.lbl_status_key.pack(anchor="w", padx=16, pady=(0, 12))

        # 1. Modo de Envio do Ditado & Slider de Silêncio
        c_silencio = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_silencio.pack(fill="x", pady=6)
        self.card_modo_envio = c_silencio
        c_silencio.grid_columnconfigure(0, weight=1)

        topo_s = ctk.CTkFrame(c_silencio, fg_color="transparent")
        topo_s.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        topo_s.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topo_s,
            text="Modo de Envio do Ditado",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        self.seg_modo_envio = ctk.CTkSegmentedButton(
            c_silencio,
            values=["⚡ Automático (Silêncio)", "🛑 Manual (Pressione p/ Parar)"],
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            command=self._on_change_modo_envio,
        )
        self.seg_modo_envio.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 6))
        self.seg_modo_envio.set("⚡ Automático (Silêncio)")

        self.lbl_modo_envio_desc = ctk.CTkLabel(
            c_silencio,
            text="⚡ Automático: Envia o texto ao detectar uma pausa contínua na sua fala (ajustável no slider abaixo).",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
            justify="left",
        )
        self.lbl_modo_envio_desc.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 8))

        ctk.CTkFrame(c_silencio, height=1, fg_color=APPLE_SEPARATOR).grid(row=3, column=0, sticky="ew", padx=16, pady=4)

        topo_slider = ctk.CTkFrame(c_silencio, fg_color="transparent")
        topo_slider.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 2))
        topo_slider.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topo_slider,
            text="Tempo de Espera por Silêncio",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        self.lbl_silence_val = ctk.CTkLabel(
            topo_slider,
            text="2.2s",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=ACCENT_BLUE,
            fg_color=ACCENT_BLUE_LIGHT,
            corner_radius=6,
            width=58,
            height=22,
        )
        self.lbl_silence_val.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            c_silencio,
            text="Duração da pausa contínua que o Willy aguarda antes de enviar (apenas no modo automático).",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=APPLE_TEXT_SECONDARY,
        ).grid(row=5, column=0, sticky="w", padx=16)

        slider_frame = ctk.CTkFrame(c_silencio, fg_color="transparent")
        slider_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(6, 14))
        slider_frame.grid_columnconfigure(0, weight=1)

        self.slider_silencio = ctk.CTkSlider(
            slider_frame,
            from_=1.0,
            to=3.5,
            number_of_steps=25,
            button_color=ACCENT_BLUE,
            progress_color=ACCENT_BLUE,
            fg_color=BG_RECESSED,
            command=self._on_slider_silencio,
        )
        self.slider_silencio.set(2.2)
        self.slider_silencio.grid(row=0, column=0, sticky="ew")

        # 1.1 Card: Tom de Escrita Padrão
        c_tom = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_tom.pack(fill="x", pady=6)
        c_tom.grid_columnconfigure(0, weight=1)

        topo_tom = ctk.CTkFrame(c_tom, fg_color="transparent")
        topo_tom.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        topo_tom.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topo_tom,
            text="Tom de Escrita Padrão (Persona de Saída)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        self.seg_tone = ctk.CTkSegmentedButton(
            c_tom,
            values=["🌿 Natural / Fiel", "👔 Executivo / Formal", "⚡ Direto / Conciso", "📋 Tópicos", "💻 Técnico / Dev"],
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            command=self._on_change_tom,
        )
        self.seg_tone.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 6))
        self.seg_tone.set("🌿 Natural / Fiel")

        self.lbl_tom_desc = ctk.CTkLabel(
            c_tom,
            text="🌿 Fiel: Mantém rigorosamente as palavras, vocabulário e estilo original do usuário, corrigindo apenas pontuação e disfluências.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
            justify="left",
        )
        self.lbl_tom_desc.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 4))

        ctk.CTkLabel(
            c_tom,
            text="Dica de voz: Diga 'Willy formal: ...', 'Willy conciso: ...' ou 'Willy em tópicos: ...' para ditar com tom específico na hora!",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, slant="italic"),
            text_color=APPLE_TEXT_TERTIARY,
            anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(0, 12))

        # 1.2 Card: Idioma de Entrada do Ditado
        c_lang = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_lang.pack(fill="x", pady=6)
        c_lang.grid_columnconfigure(0, weight=1)

        topo_lang = ctk.CTkFrame(c_lang, fg_color="transparent")
        topo_lang.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        topo_lang.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topo_lang,
            text="Idioma de Entrada do Ditado",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        self.seg_input_lang = ctk.CTkSegmentedButton(
            c_lang,
            values=["🌐 Automático", "🇧🇷 Português", "🇺🇸 Inglês"],
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            command=self._on_change_idioma,
        )
        self.seg_input_lang.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 6))
        self.seg_input_lang.set("🌐 Automático")

        self.lbl_lang_desc = ctk.CTkLabel(
            c_lang,
            text="🌐 Automático: O Willy detecta sozinho se você está falando em português, inglês ou misturando termos técnicos, sem trocar de atalho.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
            justify="left",
        )
        self.lbl_lang_desc.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 12))

        # 2. Switches Inteligentes
        c_switches = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_switches.pack(fill="x", pady=6)
        c_switches.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            c_switches,
            text="Recursos Inteligentes",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 8))

        def _adicionar_switch_linha(row_idx, titulo_txt, desc_txt):
            r = ctk.CTkFrame(c_switches, fg_color="transparent")
            r.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 14))
            r.grid_columnconfigure(0, weight=1)

            info = ctk.CTkFrame(r, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(info, text=titulo_txt, font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w")
            ctk.CTkLabel(info, text=desc_txt, font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w")

            sw = ctk.CTkSwitch(r, text="", width=46, progress_color=ACCENT_BLUE, button_color=APPLE_KEYCAP_BG, button_hover_color=APPLE_BG_HOVER)
            sw.grid(row=0, column=1, sticky="e")
            return sw

        def _adicionar_divisor(row_idx):
            div = ctk.CTkFrame(c_switches, height=1, fg_color=APPLE_SEPARATOR)
            div.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=16, pady=4)

        # Switches
        self.switch_ia = _adicionar_switch_linha(1, "Polimento de Prompts com IA (Groq)", "Remove gaguejos ('éee', 'tipo assim') e estrutura o comando.")
        _adicionar_divisor(2)
        self.switch_mudo = _adicionar_switch_linha(3, "Modo Silencioso", "Desliga todos os bipes sonoros. Ideal para reuniões e trabalho noturno.")
        _adicionar_divisor(4)
        self.switch_autostart = _adicionar_switch_linha(5, "Iniciar Automaticamente com o Windows", "Inicia o Willy silenciosamente na bandeja do sistema ao ligar o computador.")
        _adicionar_divisor(6)
        self.switch_private_mode = _adicionar_switch_linha(7, "Modo Privado / Incógnito (Zero-Retention)", "Não salva ditados no histórico (.history.json). Protege senhas e dados confidenciais.")
        _adicionar_divisor(8)
        self.switch_clean_fillers = _adicionar_switch_linha(9, "Limpeza de Hesitações e Cacoetes (né, tipo assim, humm...)", "Remove automaticamente 'ééé', 'humm', 'tipo assim', 'né' e repetições gaguejadas.")
        _adicionar_divisor(10)
        self.switch_clipboard_only = _adicionar_switch_linha(11, "Modo Apenas Copiar (Sem colar no cursor)", "Copia para a área de transferência sem injetar Ctrl+V (ideal para reuniões e terminais).")
        _adicionar_divisor(12)
        self.switch_smart_paragraphing = _adicionar_switch_linha(13, "Parágrafos Inteligentes em Pausas Naturais (Smart Paragraphing)", "Estrutura raciocínios longos em parágrafos organizados ao mudar de tópico ou pausar.")
        _adicionar_divisor(14)
        self.switch_save_audio = _adicionar_switch_linha(15, "Salvar Áudio Original (.wav) junto com Textos e Atas", "Armazena o arquivo .wav com áudio puro ao lado do arquivo .md em Documentos/Willy.")
        _adicionar_divisor(16)
        self.switch_silero_vad = _adicionar_switch_linha(17, "Ignorar barulhos que não são voz", "Cadeira, teclado e batidas não seguram o microfone aberto. Desligue se o Willy cortar a sua fala baixa.")
        self.switch_silero_vad.select()
        _adicionar_divisor(18)
        self.switch_wake_word = _adicionar_switch_linha(19, "Ativação Hands-Free por Palavra de Ativação ('Ei Willy')", "Inicia a gravação automaticamente ao falar 'Ei Willy' ou 'Willy' (0.00% CPU em silêncio).")

        # 2b. Regras por Aplicativo (Contexto Automático): grava a cada mudança, fora do "Salvar".
        self.secao_regras_app = SecaoRegrasPorApp(self, callbacks=self.callbacks)
        self.secao_regras_app.pack(fill="x", pady=6)

        # 3. Atalhos Globais Personalizados
        c_hotkeys = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_hotkeys.pack(fill="x", pady=6)
        c_hotkeys.grid_columnconfigure(0, weight=1)

        box_hk_topo = ctk.CTkFrame(c_hotkeys, fg_color="transparent")
        box_hk_topo.pack(fill="x", padx=16, pady=(14, 4))
        box_hk_topo.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(box_hk_topo, text="Teclas de Atalho Personalizadas", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(box_hk_topo, text="Remapeie as combinações de teclas para não conflitar com outros aplicativos:", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).grid(row=1, column=0, sticky="w", pady=(2, 0))

        btn_ir_atalhos = ctk.CTkButton(
            box_hk_topo,
            text="Abrir Aba Atalhos ➔",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            height=28,
            corner_radius=6,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._navegar_atalhos,
        )
        btn_ir_atalhos.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))

        def _criar_hk_row(parent, label_desc, default_hk):
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=3)
            r.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(r, text=label_desc, font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=APPLE_TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
            e = ctk.CTkEntry(r, font=ctk.CTkFont(family="Consolas", size=12), height=30, width=170, corner_radius=8, fg_color=APPLE_INPUT_BG, border_color=APPLE_INPUT_BORDER, border_width=1, text_color=APPLE_ACCENT)
            e.insert(0, default_hk)
            e.grid(row=0, column=1, sticky="e")
            self._nome_do_campo[str(e)] = label_desc.split(" (")[0]
            return e

        self.entry_hk_voice = _criar_hk_row(c_hotkeys, "Ditado Principal (Push / Auto)", "ctrl+space")
        self.entry_hk_trans = _criar_hk_row(c_hotkeys, "Tradução Direta (PT para EN)", "ctrl+alt+space")
        self.entry_hk_trans_es = _criar_hk_row(c_hotkeys, "Tradução Direta (PT para ES)", "ctrl+alt+n")
        self.entry_hk_prompt = _criar_hk_row(c_hotkeys, "Prompt de Agente (/goal)", "ctrl+alt+p")
        self.entry_hk_meeting = _criar_hk_row(c_hotkeys, "Gravação de Reunião e Ata", "ctrl+alt+r")
        self.entry_hk_transform = _criar_hk_row(c_hotkeys, "Transformar Seleção por Voz", "ctrl+alt+t")
        self.entry_hk_profile = _criar_hk_row(c_hotkeys, "Alternar Perfil de IA (Dev/Exec/Puro)", "ctrl+alt+e")
        self.entry_hk_history = _criar_hk_row(c_hotkeys, "Mini-Spotlight de Histórico", "ctrl+alt+h")
        self.entry_hk_undo = _criar_hk_row(c_hotkeys, "Desfazer Último Ditado", "ctrl+alt+z")
        self.entry_hk_send = _criar_hk_row(c_hotkeys, "Ditar e Enviar (Voice-to-Enter)", "ctrl+shift+enter")
        self.entry_hk_speak = _criar_hk_row(c_hotkeys, "Leitura em Voz Alta (TTS SAPI)", "ctrl+alt+s")
        self.entry_hk_sticky = _criar_hk_row(c_hotkeys, "Fixar Janela Alvo (Sticky Focus)", "ctrl+alt+f")
        self.entry_hk_captions = _criar_hk_row(c_hotkeys, "Teleprompter / Legendas Flutuantes", "ctrl+alt+l")
        self.entry_hk_master = _criar_hk_row(c_hotkeys, "Pausar / Ligar Willy", "ctrl+shift+space")

        ctk.CTkFrame(c_hotkeys, height=10, fg_color="transparent").pack()

        # 4. Posição da Pílula Flutuante
        c_pos = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_pos.pack(fill="x", pady=6)
        ctk.CTkLabel(c_pos, text="Posição da Pílula Flutuante", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_pos, text="Defina em qual região da tela o widget do Willy deve surgir ao gravar.", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 10))

        self.seg_posicao = ctk.CTkSegmentedButton(
            c_pos,
            values=["Rodapé Central (Padrão)", "Topo da Tela", "Seguir Cursor do Mouse"],
            corner_radius=10,
            height=32,
            fg_color=APPLE_SEGMENT_BG,
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.seg_posicao.set("Rodapé Central (Padrão)")
        self.seg_posicao.pack(anchor="w", padx=16, pady=(0, 16), fill="x")

        # 5. Modelo LLM
        c_modelo = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_modelo.pack(fill="x", pady=6)
        ctk.CTkLabel(c_modelo, text="Modelo de Inteligência Artificial (LLM)", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_modelo, text="Escolha entre velocidade ultra-rápida ou inteligência máxima de raciocínio e síntese:", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 10))

        self.seg_modelo = ctk.CTkSegmentedButton(
            c_modelo,
            values=list(MODELOS_NA_TELA),
            corner_radius=10,
            height=32,
            fg_color=APPLE_SEGMENT_BG,
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.seg_modelo.set(ROTULO_DO_PADRAO)
        self.seg_modelo.pack(anchor="w", padx=16, pady=(0, 16), fill="x")

        # 6. Perfil de Processamento de IA
        c_perfil = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_perfil.pack(fill="x", pady=6)
        ctk.CTkLabel(c_perfil, text="Perfil de Processamento de IA", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        self.lbl_perfil_desc = ctk.CTkLabel(c_perfil, text="Dev & Código: Preserva identificadores técnicos em snake_case, camelCase e blocos de código inline.", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY)
        self.lbl_perfil_desc.pack(anchor="w", padx=16, pady=(0, 10))

        self.seg_perfil = ctk.CTkSegmentedButton(
            c_perfil,
            values=["💻 Dev & Código", "👔 Executivo & Prosa", "⚡ Puro (Zero-Latency)"],
            corner_radius=10,
            height=32,
            fg_color=APPLE_SEGMENT_BG,
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self._on_change_perfil,
        )
        self.seg_perfil.set("💻 Dev & Código")
        self.seg_perfil.pack(anchor="w", padx=16, pady=(0, 16), fill="x")

        # 7. Microfone de Entrada & VU Meter
        c_mic_dev = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_mic_dev.pack(fill="x", pady=6)
        ctk.CTkLabel(c_mic_dev, text="Microfone de Entrada de Áudio e VU Meter", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_mic_dev, text="Selecione o microfone que o Willy deve escutar (Fone Bluetooth, Headset ou Padrão):", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 10))

        self.combo_microfone = ctk.CTkOptionMenu(
            c_mic_dev,
            values=["Padrão do Sistema"],
            height=34,
            corner_radius=8,
            fg_color=APPLE_INPUT_BG,
            button_color=APPLE_KEYCAP_BG,
            button_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            dropdown_fg_color=APPLE_BG_CARD,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.combo_microfone.pack(anchor="w", padx=16, pady=(0, 10), fill="x")

        box_vu = ctk.CTkFrame(c_mic_dev, fg_color="transparent")
        box_vu.pack(fill="x", padx=16, pady=(0, 16))
        box_vu.grid_columnconfigure(0, weight=1)

        self.bar_vu_meter = ctk.CTkProgressBar(box_vu, orientation="horizontal", height=10, corner_radius=5, fg_color=BG_RECESSED, progress_color=METER_OK)
        self.bar_vu_meter.set(0.0)
        self.bar_vu_meter.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self.btn_test_mic_live = ctk.CTkButton(
            box_vu,
            text="🎙️ Testar Microfone",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            height=30,
            width=140,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._toggle_teste_microfone,
        )
        self.btn_test_mic_live.grid(row=0, column=1, sticky="e")

        # 8. Ganho do Microfone & Modo Sussurro
        c_gain = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_gain.pack(fill="x", pady=6)
        ctk.CTkLabel(c_gain, text="Ganho do Microfone e Modo Sussurro", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_gain, text="Amplifique digitalmente a captação para ditar sussurrando ou em ambientes noturnos silenciosos:", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 10))

        self.seg_mic_gain = ctk.CTkSegmentedButton(
            c_gain,
            values=["1.0x (Padrão)", "1.3x", "1.6x", "2.0x (Sussurro)", "2.5x (Ultra)"],
            corner_radius=10,
            height=32,
            fg_color=APPLE_SEGMENT_BG,
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.seg_mic_gain.set("1.0x (Padrão)")
        self.seg_mic_gain.pack(anchor="w", padx=16, pady=(0, 12), fill="x")

        div_whisper = ctk.CTkFrame(c_gain, height=1, fg_color=APPLE_SEPARATOR)
        div_whisper.pack(fill="x", padx=16, pady=(0, 10))

        row_whisper = ctk.CTkFrame(c_gain, fg_color="transparent")
        row_whisper.pack(fill="x", padx=16, pady=(0, 14))
        row_whisper.grid_columnconfigure(0, weight=1)

        info_whisper = ctk.CTkFrame(row_whisper, fg_color="transparent")
        info_whisper.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(info_whisper, text="Modo Sussurro (Whisper Mode)", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(info_whisper, text="Ativa software pre-amp 3.0x (+10dB boost) e reduz o limiar de silêncio para captação ultra-sensível.", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w")

        self.switch_whisper_mode = ctk.CTkSwitch(row_whisper, text="", width=46, progress_color=ACCENT_BLUE, button_color=APPLE_KEYCAP_BG, button_hover_color=APPLE_BG_HOVER)
        self.switch_whisper_mode.grid(row=0, column=1, sticky="e")

        # 9. Áudio do Sistema para Reuniões
        c_sys_audio = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_sys_audio.pack(fill="x", pady=6)
        ctk.CTkLabel(c_sys_audio, text="Áudio do Sistema e Chamadas", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_sys_audio, text="Grave os outros participantes em chamadas do Google Meet, Teams ou Zoom (Mixagem Estéreo / Loopback):", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 10))

        self.combo_sys_audio = ctk.CTkOptionMenu(
            c_sys_audio,
            values=["Nenhum (Apenas Microfone)"],
            height=34,
            corner_radius=8,
            fg_color=APPLE_INPUT_BG,
            button_color=APPLE_KEYCAP_BG,
            button_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            dropdown_fg_color=APPLE_BG_CARD,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.combo_sys_audio.pack(anchor="w", padx=16, pady=(0, 16), fill="x")

        # 10. Backup & Sincronização de Perfil
        c_backup = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_backup.pack(fill="x", pady=6)
        ctk.CTkLabel(c_backup, text="Backup e Sincronização de Perfil", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_backup, text="Exporte seus atalhos, vocabulário técnico e snippets para usar em outro PC ou restaurar. A chave da Groq não vai no arquivo:", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 12))

        # O histórico (as 100 últimas transcrições, em texto puro) só vai se a pessoa pedir: o
        # arquivo é feito para ser copiado (decisão do dono, 22/10).
        row_hist = ctk.CTkFrame(c_backup, fg_color="transparent")
        row_hist.pack(fill="x", padx=16, pady=(0, 10))
        row_hist.grid_columnconfigure(0, weight=1)
        info_hist = ctk.CTkFrame(row_hist, fg_color="transparent")
        info_hist.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(info_hist, text="Incluir o histórico de transcrições", font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(info_hist, text="As 100 últimas transcrições vão em texto puro. Deixe desligado para compartilhar o perfil.", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w")
        self.switch_incluir_historico = ctk.CTkSwitch(row_hist, text="", width=46, progress_color=ACCENT_BLUE, button_color=APPLE_KEYCAP_BG, button_hover_color=APPLE_BG_HOVER)
        self.switch_incluir_historico.grid(row=0, column=1, sticky="e")

        box_bkp_botoes = ctk.CTkFrame(c_backup, fg_color="transparent")
        box_bkp_botoes.pack(fill="x", padx=16, pady=(0, 16))
        box_bkp_botoes.grid_columnconfigure((0, 1), weight=1)

        self.btn_exportar_perfil = ctk.CTkButton(
            box_bkp_botoes,
            text="Exportar Perfil (JSON)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=36,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._exportar_perfil_json,
        )
        self.btn_exportar_perfil.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.btn_importar_perfil = ctk.CTkButton(
            box_bkp_botoes,
            text="Restaurar Perfil (JSON)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=36,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._importar_perfil_json,
        )
        self.btn_importar_perfil.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # 11. Pasta de Armazenamento Automático
        c_pasta = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_pasta.pack(fill="x", pady=6)
        ctk.CTkLabel(c_pasta, text="Pasta de Arquivos e Atas (Salvo Automático)", font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=APPLE_TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c_pasta, text="O Willy salva cada transcrição em arquivos Markdown (.md) organizados em subpastas (Atas, Prompts, Textos, etc.):", font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=APPLE_TEXT_SECONDARY).pack(anchor="w", padx=16, pady=(0, 10))

        box_dir = ctk.CTkFrame(c_pasta, fg_color="transparent")
        box_dir.pack(fill="x", padx=16, pady=(0, 16))
        box_dir.grid_columnconfigure(0, weight=1)

        self.lbl_pasta_path = ctk.CTkLabel(box_dir, text="Documentos\\Willy", font=ctk.CTkFont(family="Consolas", size=12), text_color=APPLE_ACCENT, fg_color=APPLE_INPUT_BG, corner_radius=8, height=36, anchor="w", padx=12)
        self.lbl_pasta_path.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_abrir_pasta_dir = ctk.CTkButton(
            box_dir,
            text="Abrir Pasta",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            height=36,
            corner_radius=8,
            fg_color=APPLE_KEYCAP_BG,
            hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            border_width=1,
            border_color=APPLE_KEYCAP_BORDER,
            command=self._abrir_pasta_arquivos,
        )
        self.btn_abrir_pasta_dir.grid(row=0, column=1)

        # 13. Sobre o Willy

        c_sobre = ctk.CTkFrame(self, fg_color=APPLE_BG_CARD, corner_radius=12, border_width=1, border_color=APPLE_BORDER_CARD)
        c_sobre.pack(fill="x", pady=6)
        c_sobre.grid_columnconfigure(0, weight=1)

        box_sobre = ctk.CTkFrame(c_sobre, fg_color="transparent")
        box_sobre.pack(fill="x", padx=16, pady=16)
        box_sobre.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            box_sobre,
            text="Sobre o Willy",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        self.lbl_versao_app = ctk.CTkLabel(
            box_sobre,
            text=APP_VERSION,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
        )
        self.lbl_versao_app.grid(row=1, column=0, sticky="w", pady=(2, 0))

        ctk.CTkLabel(
            box_sobre,
            text="Copiloto de voz ultrarrápido com Groq Whisper Large v3 e interface minimalista inspirada no macOS.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=APPLE_TEXT_TERTIARY,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

        # Botão Salvar Geral
        self.btn_salvar_config = ctk.CTkButton(
            self,
            text="Salvar e Aplicar Ajustes",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            height=42,
            corner_radius=10,
            fg_color=APPLE_ACCENT,
            hover_color=APPLE_ACCENT_HOVER,
            command=self.salvar_configuracoes,
        )
        self.btn_salvar_config.pack(fill="x", pady=(14, 12))

    def _testar_chave_api(self):
        chave = self.entry_key.get().strip() if hasattr(self, "entry_key") else ""
        if hasattr(self, "btn_testar_key"):
            self.btn_testar_key.configure(state="disabled", text="Testando...")
        if hasattr(self, "lbl_status_key"):
            self.lbl_status_key.configure(text="Testando chave na Groq Cloud...", text_color=APPLE_TEXT_SECONDARY)

        def _worker():
            cb = self.callbacks.get("on_validate_groq_key")
            if cb:
                try:
                    ok, msg, _lat, _info = cb(chave, salvar=False)
                except Exception as e:  # noqa: BLE001 — Fronteira defensiva ao validar chave na Groq
                    ok, msg = False, f"Erro ao testar chave: {type(e).__name__}"
            else:
                ok = bool(chave and chave != "sua_chave_aqui")
                msg = "Chave preenchida." if ok else "Informe uma chave Groq antes de testar."

            def _ui():
                if hasattr(self, "btn_testar_key") and self.btn_testar_key.winfo_exists():
                    self.btn_testar_key.configure(state="normal", text="Testar Chave")
                if hasattr(self, "lbl_status_key") and self.lbl_status_key.winfo_exists():
                    self.lbl_status_key.configure(text=msg, text_color=ACCENT_GREEN if ok else ACCENT_RED)

            self._safe_after(0, _ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _reverificar_cofre_api(self):
        fn = self.callbacks.get("on_reload_api_key")
        encontrou = False
        erro_callback = False
        if fn:
            try:
                encontrou = bool(fn())
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva ao recarregar cofre
                erro_callback = True
                print(f"[SettingsTab] Erro ao reverificar cofre: {e}", file=sys.stderr)
        cfg = (self.callbacks["get_settings"]() or {}) if self.callbacks.get("get_settings") else {}
        chave = (cfg.get("api_key") or "").strip()
        tem_chave = bool(chave and chave != "sua_chave_aqui")
        if encontrou:
            self.recarregar_dados()
            if hasattr(self, "lbl_status_key") and self.lbl_status_key.winfo_exists():
                self.lbl_status_key.configure(
                    text="Chave encontrada no cofre e recarregada na interface.",
                    text_color=ACCENT_GREEN,
                )
        elif erro_callback or bool(cfg.get("cofre_ilegivel")):
            texto = (
                "Não foi possível ler o cofre do Windows. O Willy continua com a chave que já estava em uso."
                if tem_chave
                else "Não foi possível ler o cofre do Windows. Cole a chave no campo e clique em Salvar e Aplicar Ajustes."
            )
            if hasattr(self, "lbl_status_key") and self.lbl_status_key.winfo_exists():
                self.lbl_status_key.configure(text=texto, text_color=ACCENT_RED)
        else:
            if hasattr(self, "lbl_status_key") and self.lbl_status_key.winfo_exists():
                self.lbl_status_key.configure(
                    text="Nenhuma chave encontrada no cofre ou no arquivo .env.",
                    text_color=ACCENT_AMBER,
                )

    def _navegar_atalhos(self):
        try:
            top = self.winfo_toplevel()
            if hasattr(top, "mudar_aba"):
                top.mudar_aba("shortcuts")
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
            print(f"[SettingsTab] Erro ao navegar para aba Atalhos: {e}", file=sys.stderr)

    def _abrir_site_groq(self):
        try:
            webbrowser.open("https://console.groq.com/keys")
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
            print(f"[SettingsTab] Erro ao abrir site da Groq: {e}", file=sys.stderr)
            if hasattr(self, "lbl_status_key") and self.lbl_status_key.winfo_exists():
                self.lbl_status_key.configure(
                    text="⚠️ Não foi possível abrir o navegador (https://console.groq.com/keys)",
                    text_color=ACCENT_RED,
                )

    def _abrir_pasta_arquivos(self):
        if self.callbacks.get("on_open_outputs"):
            try:
                self.callbacks["on_open_outputs"]()
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao abrir pasta de arquivos: {e}", file=sys.stderr)
                if hasattr(self, "btn_abrir_pasta_dir") and self.btn_abrir_pasta_dir.winfo_exists():
                    self.btn_abrir_pasta_dir.configure(text="Erro ao Abrir", fg_color=ACCENT_RED, text_color=BTN_PRIMARY_TEXT)
                    self._safe_after(
                        2000,
                        lambda: self.btn_abrir_pasta_dir.winfo_exists()
                        and self.btn_abrir_pasta_dir.configure(text="Abrir Pasta", fg_color=APPLE_KEYCAP_BG, text_color=APPLE_TEXT_PRIMARY),
                    )

    def _on_change_perfil(self, val):
        if not hasattr(self, "lbl_perfil_desc"):
            return
        descricoes = {
            "💻 Dev & Código": "💻 Dev & Código: Preserva identificadores técnicos em snake_case, camelCase e blocos de código inline.",
            "👔 Executivo & Prosa": "👔 Executivo & Prosa: Transforma fala espontânea em prosa corporativa elegante e culta.",
            "⚡ Puro (Zero-Latency)": "⚡ Puro: Bypassa a IA de refinamento completamente (~400ms), entregando o áudio bruto do Whisper.",
        }
        self.lbl_perfil_desc.configure(text=descricoes.get(str(val), descricoes["💻 Dev & Código"]))

    def _toggle_teste_microfone(self):
        if self._mic_testing:
            self._parar_teste_microfone()
        else:
            self._iniciar_teste_microfone()

    def _iniciar_teste_microfone(self):
        self._mic_testing = True
        self._mic_stop_event.clear()
        if hasattr(self, "btn_test_mic_live") and self.btn_test_mic_live.winfo_exists():
            self.btn_test_mic_live.configure(text="⏹️ Parar Teste", text_color=ACCENT_RED, fg_color=ACCENT_RED_LIGHT_HOVER, hover_color=ACCENT_RED_BORDER, border_color=ACCENT_RED_BORDER)
        dev_idx = None
        if hasattr(self, "_dev_map"):
            combo_val = self.combo_microfone.get()
            dev_idx = self._dev_map.get(combo_val)

        threading.Thread(target=self._worker_teste_microfone, args=(dev_idx,), daemon=True).start()

    def _parar_teste_se_ativo(self):
        if self._mic_testing:
            self._parar_teste_microfone()

    def _parar_teste_microfone(self):
        self._mic_testing = False
        self._mic_stop_event.set()
        if hasattr(self, "btn_test_mic_live") and self.btn_test_mic_live.winfo_exists():
            self.btn_test_mic_live.configure(text="🎙️ Testar Microfone", text_color=APPLE_TEXT_PRIMARY, fg_color=APPLE_KEYCAP_BG, hover_color=APPLE_BG_HOVER, border_color=APPLE_KEYCAP_BORDER)
        if hasattr(self, "bar_vu_meter") and self.bar_vu_meter.winfo_exists():
            self.bar_vu_meter.set(0.0)
            self.bar_vu_meter.configure(progress_color=METER_OK)

    def _worker_teste_microfone(self, dev_idx):
        erro_teste: Exception | None = None
        try:
            def _cb(indata, _frames, _time_info, _status):
                if not self._mic_testing:
                    return
                rms = compute_rms(indata)
                level = min(1.0, max(0.0, rms / 0.15))

                def _update_meter(lvl=level):
                    if hasattr(self, "bar_vu_meter") and self.bar_vu_meter.winfo_exists():
                        self.bar_vu_meter.set(lvl)
                        if lvl > 0.75:
                            self.bar_vu_meter.configure(progress_color=METER_DANGER)
                        elif lvl > 0.4:
                            self.bar_vu_meter.configure(progress_color=METER_WARNING)
                        else:
                            self.bar_vu_meter.configure(progress_color=METER_OK)

                self._safe_after(0, _update_meter)

            # Prefere a taxa em que a gravação está rodando. Medir noutra taxa é a
            # divergência que este teste deveria detectar, não criar.
            taxa_preferida = SAMPLE_RATE
            if self.callbacks.get("get_actual_sample_rate"):
                try:
                    taxa_preferida = self.callbacks["get_actual_sample_rate"]() or SAMPLE_RATE
                except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de widget/áudio em ajustes
                    pass

            # Mesma escada do gravador, e a mesma função. Eram três cópias disto.
            erro_stream: Exception | None = None
            try:
                stream, _ = negociar_stream(dev_idx, _cb, 1, taxa_preferida)
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                erro_stream = e
                stream = None

            if stream is None:
                detalhe = f": {erro_stream}" if erro_stream else "."
                raise RuntimeError(f"Não foi possível inicializar o microfone com as taxas suportadas{detalhe}") from erro_stream

            while self._mic_testing and not self._mic_stop_event.wait(timeout=0.05):
                pass

            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de widget/áudio em ajustes
                pass
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
            erro_teste = e
            print(f"[SettingsTab VU Meter] Erro de teste: {e}", file=sys.stderr)
        finally:
            def _finalizar_ui():
                self._parar_teste_microfone()
                if erro_teste is not None and hasattr(self, "btn_test_mic_live") and self.btn_test_mic_live.winfo_exists():
                    self.btn_test_mic_live.configure(
                        text="⚠️ Erro no Microfone",
                        text_color=ACCENT_RED,
                        fg_color=ACCENT_RED_LIGHT_HOVER,
                        border_color=ACCENT_RED_BORDER,
                    )
                    self._safe_after(
                        2000,
                        lambda: self.btn_test_mic_live.winfo_exists()
                        and self.btn_test_mic_live.configure(
                            text="🎙️ Testar Microfone",
                            text_color=APPLE_TEXT_PRIMARY,
                            fg_color=APPLE_KEYCAP_BG,
                            hover_color=APPLE_BG_HOVER,
                            border_color=APPLE_KEYCAP_BORDER,
                        ),
                    )

            self._safe_after(0, _finalizar_ui)

    def _on_change_modo_envio(self, val):
        is_auto = "Automático" in str(val)
        if hasattr(self, "lbl_modo_envio_desc"):
            if is_auto:
                self.lbl_modo_envio_desc.configure(text="⚡ Automático: Envia o texto ao detectar uma pausa contínua na sua fala (ajustável no slider abaixo).")
                if hasattr(self, "lbl_silence_val") and hasattr(self, "slider_silencio"):
                    self.lbl_silence_val.configure(text=f"{float(self.slider_silencio.get()):.1f}s", text_color=ACCENT_CYAN, fg_color=ACCENT_CYAN_LIGHT)
            else:
                self.lbl_modo_envio_desc.configure(text="🛑 Manual (Toggle): Pressione o atalho para falar. Pense com calma sem pressa; pressione o atalho novamente para transcrever.")
                if hasattr(self, "lbl_silence_val"):
                    self.lbl_silence_val.configure(text="Pausado", text_color=APPLE_TEXT_TERTIARY, fg_color=APPLE_KEYCAP_BG)

    def _on_change_tom(self, val):
        self._atualizar_desc_tom(val)

    def _atualizar_desc_tom(self, val):
        if not hasattr(self, "lbl_tom_desc"):
            return
        descricoes = {
            "🌿 Natural / Fiel": "🌿 Fiel: Mantém rigorosamente as palavras, vocabulário e estilo original do usuário, corrigindo apenas pontuação e disfluências.",
            "👔 Executivo / Formal": "👔 Formal: Eleva o vocabulário para um padrão executivo refinado e culto, ideal para e-mails e atas corporativas.",
            "⚡ Direto / Conciso": "⚡ Conciso: Direto ao ponto e sem rodeios, ideal para envio ágil no Slack, Teams e WhatsApp.",
            "📋 Tópicos": "📋 Tópicos: Converte o raciocínio falado em lista organizada com marcadores (- ), facilitando a leitura.",
            "💻 Técnico / Dev": "💻 Técnico: Preserva comandos e termos em inglês com formatação de código em Markdown inline (` `).",
        }
        self.lbl_tom_desc.configure(text=descricoes.get(str(val), descricoes["🌿 Natural / Fiel"]))

    def _on_change_idioma(self, val):
        self._atualizar_desc_idioma(val)

    def _atualizar_desc_idioma(self, val):
        if not hasattr(self, "lbl_lang_desc"):
            return
        descricoes = {
            "🌐 Automático": "🌐 Automático: O Willy detecta sozinho se você está falando em português, inglês ou misturando termos técnicos, sem trocar de atalho.",
            "🇧🇷 Português": "🇧🇷 Português: Força a transcrição nativa em português brasileiro (PT-BR).",
            "🇺🇸 Inglês": "🇺🇸 Inglês: Força a transcrição nativa em inglês internacional (EN).",
        }
        self.lbl_lang_desc.configure(text=descricoes.get(str(val), descricoes["🌐 Automático"]))

    def _on_slider_silencio(self, val):
        if hasattr(self, "seg_modo_envio") and "Manual" in self.seg_modo_envio.get():
            self.lbl_silence_val.configure(text="Pausado", text_color=APPLE_TEXT_TERTIARY, fg_color=APPLE_KEYCAP_BG)
        else:
            self.lbl_silence_val.configure(text=f"{val:.1f}s", text_color=ACCENT_CYAN, fg_color=ACCENT_CYAN_LIGHT)

    def _toggle_ver_chave(self):
        show = self.entry_key.cget("show")
        self.entry_key.configure(show="" if show == "•" else "•")

    def _exportar_perfil_json(self):
        from tkinter import filedialog
        default_name = f"willy_perfil_{time.strftime('%Y%m%d_%H%M%S')}.json"
        caminho = filedialog.asksaveasfilename(title="Exportar Perfil do Willy", defaultextension=".json", initialfile=default_name, filetypes=[("Arquivo JSON (*.json)", "*.json")])
        if not caminho:
            return

        if self.callbacks.get("on_export_profile"):
            incluir_historico = self.switch_incluir_historico.get() == 1
            try:
                ok = bool(self.callbacks["on_export_profile"](caminho, incluir_historico))
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao exportar perfil: {e}", file=sys.stderr)
                ok = False
            if ok:
                self.btn_exportar_perfil.configure(text="Perfil Exportado! ✓", fg_color=ACCENT_GREEN, text_color=BTN_PRIMARY_TEXT)
            else:
                self.btn_exportar_perfil.configure(text="Falha ao Exportar Perfil", fg_color=ACCENT_RED, text_color=BTN_PRIMARY_TEXT)
            self._safe_after(1600, lambda: self.btn_exportar_perfil.configure(text="Exportar Perfil (JSON)", fg_color=APPLE_KEYCAP_BG, text_color=APPLE_TEXT_PRIMARY))

    exportar_perfil_json = _exportar_perfil_json

    def _importar_perfil_json(self):
        from tkinter import filedialog
        caminho = filedialog.askopenfilename(title="Restaurar Perfil do Willy", filetypes=[("Arquivo JSON (*.json)", "*.json"), ("Todos os Arquivos", "*.*")])
        if not caminho:
            return

        if self.callbacks.get("on_import_profile"):
            try:
                ok = bool(self.callbacks["on_import_profile"](caminho))
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao importar perfil: {e}", file=sys.stderr)
                ok = False
            if ok:
                if self.callbacks.get("get_settings"):
                    self.recarregar_dados()
                self.btn_importar_perfil.configure(text="Perfil Restaurado! ✓", fg_color=ACCENT_GREEN, text_color=BTN_PRIMARY_TEXT)
            else:
                self.btn_importar_perfil.configure(text="Falha ao Restaurar Perfil", fg_color=ACCENT_RED, text_color=BTN_PRIMARY_TEXT)
            self._safe_after(1600, lambda: self.btn_importar_perfil.configure(text="Restaurar Perfil (JSON)", fg_color=APPLE_KEYCAP_BG, text_color=APPLE_TEXT_PRIMARY))

    importar_perfil_json = _importar_perfil_json

    def salvar_configuracoes(self):
        """Coleta todos os dados de formulário e despacha para persistência."""
        if getattr(self, "_falha_carregamento_config", False):
            if hasattr(self, "btn_salvar_config") and self.btn_salvar_config.winfo_exists():
                self.btn_salvar_config.configure(
                    text="Não salvei: configurações não foram carregadas",
                    fg_color=ACCENT_RED,
                )
            return False
        pos_map = {
            "Rodapé Central (Padrão)": "centro_inferior",
            "Topo da Tela": "topo",
            "Seguir Cursor do Mouse": "seguir_cursor",
        }
        model_map = MODELOS_NA_TELA
        tone_map = {
            "🌿 Natural / Fiel": "natural",
            "👔 Executivo / Formal": "formal",
            "⚡ Direto / Conciso": "concise",
            "📋 Tópicos": "bullet_points",
            "💻 Técnico / Dev": "technical",
        }
        output_tone = "natural"
        if hasattr(self, "seg_tone"):
            output_tone = tone_map.get(self.seg_tone.get(), "natural")

        lang_map = {
            "🌐 Automático": "auto",
            "🇧🇷 Português": "pt",
            "🇺🇸 Inglês": "en",
        }
        input_lang = "auto"
        if hasattr(self, "seg_input_lang"):
            input_lang = lang_map.get(self.seg_input_lang.get(), "auto")

        combo_val = self.combo_microfone.get()
        dev_idx = None
        if hasattr(self, "_dev_map") and combo_val in self._dev_map:
            dev_idx = self._dev_map[combo_val]

        sys_dev_idx = None
        if hasattr(self, "combo_sys_audio") and hasattr(self, "_sys_dev_map"):
            sys_val = self.combo_sys_audio.get()
            sys_dev_idx = self._sys_dev_map.get(sys_val)

        gain_map = {
            "1.0x (Padrão)": 1.0,
            "1.3x": 1.3,
            "1.6x": 1.6,
            "2.0x (Sussurro)": 2.0,
            "2.5x (Ultra)": 2.5,
        }
        mic_gain = 1.0
        if hasattr(self, "seg_mic_gain"):
            mic_gain = gain_map.get(self.seg_mic_gain.get(), 1.0)

        chave_digitada = self.entry_key.get().strip()
        is_auto_silence = True
        if hasattr(self, "seg_modo_envio"):
            is_auto_silence = "Automático" in str(self.seg_modo_envio.get())

        profile_map = {
            "💻 Dev & Código": "dev",
            "👔 Executivo & Prosa": "executivo",
            "⚡ Puro (Zero-Latency)": "puro",
        }
        processing_prof = "dev"
        if hasattr(self, "seg_perfil"):
            processing_prof = profile_map.get(self.seg_perfil.get(), "dev")

        novos_dados = {
            "AUTO_SILENCE": is_auto_silence,
            "CLEAN_FILLERS": self.switch_clean_fillers.get() == 1 if hasattr(self, "switch_clean_fillers") else True,
            "CLIPBOARD_ONLY": self.switch_clipboard_only.get() == 1 if hasattr(self, "switch_clipboard_only") else False,
            "SMART_PARAGRAPHING": self.switch_smart_paragraphing.get() == 1 if hasattr(self, "switch_smart_paragraphing") else True,
            "OUTPUT_TONE": output_tone,
            "INPUT_LANGUAGE": input_lang,
            "SILENCE_SECONDS": float(self.slider_silencio.get()),
            "REFINE_PROMPT": self.switch_ia.get() == 1,
            "PROCESSING_PROFILE": processing_prof,
            "WHISPER_MODE": self.switch_whisper_mode.get() == 1 if hasattr(self, "switch_whisper_mode") else False,
            "SILENT_MODE": self.switch_mudo.get() == 1,
            "PRIVATE_MODE": self.switch_private_mode.get() == 1 if hasattr(self, "switch_private_mode") else False,
            "SAVE_AUDIO_FILES": self.switch_save_audio.get() == 1 if hasattr(self, "switch_save_audio") else False,
            "SILERO_VAD": self.switch_silero_vad.get() == 1 if hasattr(self, "switch_silero_vad") else True,
            "WAKE_WORD_ENABLED": self.switch_wake_word.get() == 1 if hasattr(self, "switch_wake_word") else False,
            "PILL_POSITION": pos_map.get(self.seg_posicao.get(), "centro_inferior"),
            "GROQ_LLM_MODEL": model_map.get(self.seg_modelo.get(), modelos_llm.PADRAO),
            "AUDIO_DEVICE": dev_idx,
            "SYSTEM_AUDIO_DEVICE": sys_dev_idx,
            "MIC_GAIN": mic_gain,
            "GROQ_API_KEY": chave_digitada,
        }

        for chave, entry in self._entradas_de_atalho():
            novos_dados[chave] = entry.get().strip()

        # Antes de gravar qualquer coisa (o início com o Windows inclusive): a pessoa corrige o
        # campo e salva de novo, sem metade aplicada.
        reservado = self._atalho_do_sistema(novos_dados)
        if reservado:
            self._recusar_salvar(*reservado)
            return

        if hasattr(self, "switch_autostart") and self.callbacks.get("on_toggle_autostart"):
            self.callbacks["on_toggle_autostart"](self.switch_autostart.get() == 1)

        if self.callbacks.get("on_save_settings"):
            self.callbacks["on_save_settings"](novos_dados)

        if chave_digitada and chave_digitada != "sua_chave_aqui":
            self.lbl_status_key.configure(text="● Chave configurada e ativa ✓ O Willy está pronto para uso!", text_color=ACCENT_GREEN)
        else:
            self.lbl_status_key.configure(text="⚠️ Nenhuma chave configurada ainda. Cole sua chave acima e clique em Salvar.", text_color=ACCENT_AMBER)

        self.btn_salvar_config.configure(text="Ajustes Salvos com Sucesso! ✓", fg_color=ACCENT_GREEN)
        self._safe_after(1600, lambda: self.btn_salvar_config.configure(text="Salvar e Aplicar Ajustes", fg_color=ACCENT_BLUE))

    _salvar_configuracoes = salvar_configuracoes

    # (campo do .env, campo da tela) de cada atalho do Ajustes
    _CAMPOS_DE_ATALHO = (
        ("VOICE_HOTKEY", "entry_hk_voice"), ("TRANSLATE_HOTKEY", "entry_hk_trans"),
        ("TRANSLATE_ES_HOTKEY", "entry_hk_trans_es"),
        ("PROMPT_HOTKEY", "entry_hk_prompt"), ("MEETING_HOTKEY", "entry_hk_meeting"),
        ("MASTER_HOTKEY", "entry_hk_master"), ("TRANSFORM_HOTKEY", "entry_hk_transform"),
        ("PROFILE_HOTKEY", "entry_hk_profile"), ("HISTORY_HOTKEY", "entry_hk_history"),
        ("UNDO_HOTKEY", "entry_hk_undo"), ("SEND_HOTKEY", "entry_hk_send"),
        ("SPEAK_HOTKEY", "entry_hk_speak"), ("STICKY_HOTKEY", "entry_hk_sticky"),
        ("CAPTIONS_HOTKEY", "entry_hk_captions"),
    )

    def _entradas_de_atalho(self) -> list[tuple[str, Any]]:
        return [(chave, getattr(self, attr)) for chave, attr in self._CAMPOS_DE_ATALHO if hasattr(self, attr)]

    def _atalho_do_sistema(self, novos_dados: dict[str, Any]) -> tuple[Any, str] | None:
        """(campo, aviso) do primeiro atalho inválido, reservado pelo sistema ou duplicado, ou None.

        A aba Atalhos já recusava (o Keycap), e aqui o campo de texto aceitava: o Willy
        registrava Ctrl+C como atalho global, aceitava combinações inválidas ou repetidas
        entre ações e deixava o segundo atalho mudo sem avisar.
        """
        vistos: dict[str, str] = {}
        entradas_por_chave: dict[str, Any] = {}
        for chave, entry in self._entradas_de_atalho():
            entradas_por_chave[chave] = entry
            combo = str(novos_dados.get(chave, "") or "").strip()
            if not combo:
                continue
            nome = self._nome_do_campo.get(str(entry), chave)
            descricao_sistema = conflito_sistema(combo)
            if descricao_sistema:
                return entry, f"Não salvei: {nome} usa {combo}, do sistema ({descricao_sistema})"
            erro_fmt = erro_formato_atalho(combo)
            if erro_fmt:
                return entry, f"Não salvei: {nome} tem atalho inválido ({combo})"
            chave_conflito = conflito_interno(combo, vistos, chave)
            if chave_conflito:
                outro_entry = entradas_por_chave.get(chave_conflito)
                outro_nome = self._nome_do_campo.get(str(outro_entry), chave_conflito)
                return entry, f"Não salvei: {nome} repete o atalho de {outro_nome} ({combo})"
            vistos[chave] = combo
        return None

    def _recusar_salvar(self, entry: Any, aviso: str):
        entry.configure(border_color=ACCENT_RED)
        entry.focus_set()
        self.btn_salvar_config.configure(text=aviso, fg_color=ACCENT_RED)

        def _voltar():
            entry.configure(border_color=APPLE_INPUT_BORDER)
            self.btn_salvar_config.configure(text="Salvar e Aplicar Ajustes", fg_color=ACCENT_BLUE)

        self._safe_after(4000, _voltar)

    def recarregar_dados(self, cfg: dict[str, Any] | None = None):
        """Atualiza os controles visuais a partir de um dicionário de configuração."""
        if cfg is None and self.callbacks.get("get_settings"):
            try:
                cfg = self.callbacks["get_settings"]()
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao carregar configurações: {e}", file=sys.stderr)
                self._falha_carregamento_config = True
                if hasattr(self, "btn_salvar_config") and self.btn_salvar_config.winfo_exists():
                    self.btn_salvar_config.configure(text="⚠️ Erro ao carregar configurações", fg_color=ACCENT_RED)
                return
        if not cfg:
            self._falha_carregamento_config = False
            return

        try:
            if hasattr(self, "seg_modo_envio"):
                auto_silence = cfg.get("auto_silence", True)
                if auto_silence:
                    self.seg_modo_envio.set("⚡ Automático (Silêncio)")
                    self._on_change_modo_envio("⚡ Automático (Silêncio)")
                else:
                    self.seg_modo_envio.set("🛑 Manual (Pressione p/ Parar)")
                    self._on_change_modo_envio("🛑 Manual (Pressione p/ Parar)")

            self.slider_silencio.set(cfg.get("silence_seconds", 2.2))
            if not hasattr(self, "seg_modo_envio") or "Automático" in self.seg_modo_envio.get():
                self.lbl_silence_val.configure(text=f"{cfg.get('silence_seconds', 2.2):.1f}s")
            self.switch_ia.select() if cfg.get("refine_prompt", True) else self.switch_ia.deselect()
            self.switch_mudo.select() if cfg.get("silent_mode", False) else self.switch_mudo.deselect()

            pos_rev = {
                "centro_inferior": "Rodapé Central (Padrão)",
                "topo": "Topo da Tela",
                "seguir_cursor": "Seguir Cursor do Mouse",
            }
            self.seg_posicao.set(pos_rev.get(cfg.get("pill_position", "centro_inferior"), "Rodapé Central (Padrão)"))

            cur_model = cfg.get("llm_model", modelos_llm.PADRAO)
            # Um modelo fora da lista (posto à mão no .env) aparece como Smart, o padrão.
            self.seg_modelo.set(next((rotulo for rotulo, modelo in MODELOS_NA_TELA.items() if modelo == cur_model),
                                     ROTULO_DO_PADRAO))
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
            print(f"[SettingsTab] Erro ao aplicar configurações na UI: {e}", file=sys.stderr)
            self._falha_carregamento_config = True
            return

        # Carrega microfones
        if self.callbacks.get("get_audio_devices"):
            try:
                dev_list = self.callbacks["get_audio_devices"]()
                self._dev_map = {"Padrão do Sistema": None}
                values = ["Padrão do Sistema"]
                active_idx = cfg.get("audio_device")
                selected_val = "Padrão do Sistema"

                for idx, name in dev_list:
                    label = f"{name[:38]} (ID {idx})" if len(name) > 38 else f"{name} (ID {idx})"
                    self._dev_map[label] = idx
                    values.append(label)
                    if active_idx == idx:
                        selected_val = label

                self.combo_microfone.configure(values=values)
                self.combo_microfone.set(selected_val)
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao enumerar microfones: {e}", file=sys.stderr)

        # Áudio do sistema (Loopback)
        if hasattr(self, "combo_sys_audio") and self.callbacks.get("get_audio_devices"):
            try:
                sys_dev_list = self.callbacks["get_audio_devices"]()
                self._sys_dev_map = {"Nenhum (Apenas Microfone)": None}
                sys_values = ["Nenhum (Apenas Microfone)"]
                active_sys_idx = cfg.get("system_audio_device")
                selected_sys = "Nenhum (Apenas Microfone)"

                for idx, name in sys_dev_list:
                    label = f"{name[:38]} (ID {idx})" if len(name) > 38 else f"{name} (ID {idx})"
                    self._sys_dev_map[label] = idx
                    sys_values.append(label)
                    if active_sys_idx == idx:
                        selected_sys = label

                self.combo_sys_audio.configure(values=sys_values)
                self.combo_sys_audio.set(selected_sys)
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao enumerar dispositivos de áudio do sistema: {e}", file=sys.stderr)

        # Ganho do microfone
        if hasattr(self, "seg_mic_gain"):
            gain_val = float(cfg.get("mic_gain", 1.0))
            gain_rev = {1.0: "1.0x (Padrão)", 1.3: "1.3x", 1.6: "1.6x", 2.0: "2.0x (Sussurro)", 2.5: "2.5x (Ultra)"}
            self.seg_mic_gain.set(gain_rev.get(gain_val, "1.0x (Padrão)"))

        chave = cfg.get("api_key", "").strip()
        self.entry_key.delete(0, "end")
        self.entry_key.insert(0, chave)
        if chave and chave != "sua_chave_aqui":
            self.lbl_status_key.configure(text="● Chave configurada e ativa ✓ O Willy está pronto para uso!", text_color=ACCENT_GREEN)
        else:
            self.lbl_status_key.configure(text="⚠️ Nenhuma chave configurada ainda. Cole sua chave acima e clique em Salvar.", text_color=ACCENT_AMBER)

        if hasattr(self, "switch_autostart"):
            self.switch_autostart.select() if cfg.get("autostart", False) else self.switch_autostart.deselect()
        if hasattr(self, "switch_private_mode"):
            self.switch_private_mode.select() if cfg.get("private_mode", False) else self.switch_private_mode.deselect()
        if hasattr(self, "switch_clean_fillers"):
            self.switch_clean_fillers.select() if cfg.get("clean_fillers", True) else self.switch_clean_fillers.deselect()
        if hasattr(self, "switch_clipboard_only"):
            self.switch_clipboard_only.select() if cfg.get("clipboard_only", False) else self.switch_clipboard_only.deselect()
        if hasattr(self, "switch_smart_paragraphing"):
            self.switch_smart_paragraphing.select() if cfg.get("smart_paragraphing", True) else self.switch_smart_paragraphing.deselect()
        if hasattr(self, "switch_save_audio"):
            self.switch_save_audio.select() if cfg.get("save_audio_files", False) else self.switch_save_audio.deselect()
        if hasattr(self, "switch_silero_vad"):
            self.switch_silero_vad.select() if cfg.get("silero_vad", True) else self.switch_silero_vad.deselect()
        if hasattr(self, "switch_wake_word"):
            self.switch_wake_word.select() if cfg.get("wake_word_enabled", False) else self.switch_wake_word.deselect()
        if hasattr(self, "switch_whisper_mode"):
            self.switch_whisper_mode.select() if cfg.get("whisper_mode", False) else self.switch_whisper_mode.deselect()

        if hasattr(self, "seg_perfil"):
            perfil_rev = {"dev": "💻 Dev & Código", "executivo": "👔 Executivo & Prosa", "puro": "⚡ Puro (Zero-Latency)"}
            saved_prof = str(cfg.get("processing_profile", "dev")).lower()
            rotulo_prof = perfil_rev.get(saved_prof, "💻 Dev & Código")
            self.seg_perfil.set(rotulo_prof)
            self._on_change_perfil(rotulo_prof)

        if hasattr(self, "seg_tone"):
            tone_rev = {"natural": "🌿 Natural / Fiel", "formal": "👔 Executivo / Formal", "concise": "⚡ Direto / Conciso", "bullet_points": "📋 Tópicos", "technical": "💻 Técnico / Dev"}
            saved_tone = str(cfg.get("output_tone", "natural")).lower()
            rotulo_tom = tone_rev.get(saved_tone, "🌿 Natural / Fiel")
            self.seg_tone.set(rotulo_tom)
            self._atualizar_desc_tom(rotulo_tom)

        if hasattr(self, "seg_input_lang"):
            lang_rev = {"auto": "🌐 Automático", "pt": "🇧🇷 Português", "en": "🇺🇸 Inglês"}
            saved_lang = str(cfg.get("input_language", "auto")).lower()
            rotulo_lang = lang_rev.get(saved_lang, "🌐 Automático")
            self.seg_input_lang.set(rotulo_lang)
            self._atualizar_desc_idioma(rotulo_lang)

        self.recarregar_atalhos(cfg)

        if hasattr(self, "lbl_pasta_path") and self.callbacks.get("get_outputs_dir"):
            try:
                self.lbl_pasta_path.configure(text=self.callbacks["get_outputs_dir"]())
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de ação em ajustes
                print(f"[SettingsTab] Erro ao obter diretório de saída: {e}", file=sys.stderr)

        # Um perfil importado traz as regras dele.
        self.secao_regras_app.recarregar()
        self._falha_carregamento_config = False

    def recarregar_atalhos(self, cfg: dict[str, Any]):
        """Mostra nos campos de atalho o que está na config.

        Chamado também depois de cada troca: recusada pelo Windows, ela volta à combinação
        anterior, e o campo com a recusada a gravava de novo no próximo Salvar.
        """
        for chave_env, entry in self._entradas_de_atalho():
            padrao = HOTKEYS_PADRAO.get(chave_env, "")
            # Vazio fica vazio: sem combinação na config, nenhum atalho é registrado, e o
            # padrão no campo dizia que ele valia.
            val = cfg.get(chave_env.lower(), cfg.get(chave_env, padrao))
            entry.delete(0, "end")
            entry.insert(0, val)


def build_tab_settings(
    parent: Any,
    callbacks: dict[str, Callable] | None = None,
    current_config: dict[str, Any] | None = None,
) -> SettingsTab:
    """Função fábrica modular para construir e retornar a Aba de Ajustes & Configurações."""
    return SettingsTab(parent, callbacks=callbacks, current_config=current_config)
