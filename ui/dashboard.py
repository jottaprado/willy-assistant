"""
Willy Dashboard 🎙️ - Interface Gráfica Sofisticada e Minimalista Estilo Apple (macOS).
- Design refinado seguindo as diretrizes do macOS Human Interface Guidelines (HIG).
- Paleta neutra em Dark Space Gray / Obsidiana com toques Cupertino (Apple System Blue & Emerald).
- Central de controle visual do copiloto Willy:
  1. Histórico completo de prompts com busca estilo Spotlight e cópia em 1 clique.
  2. Central de atalhos com keycaps de teclado físico (Apple Keycaps).
  3. Painel de configurações agrupadas no padrão macOS System Settings.
  4. Editor integrado de vocabulário e termos técnicos.
  5. Teste de hardware (VU Meter) e medição de latência da Groq Cloud.
"""

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes

import customtkinter as ctk


def _carregar_win32_dashboard():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.IsIconic.argtypes = [wintypes.HWND]
    u.IsIconic.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    s = ctypes.WinDLL("shell32", use_last_error=True)
    s.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    s.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
    return u, s


_user32, _shell32 = _carregar_win32_dashboard()

# Configuração visual do CustomTkinter (Modo do Sistema: Light ou Dark dinâmico)
ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

# =====================================================================
# DESIGN SYSTEM TOKENS - APPLE MINIMALISTA & MODERNO
# (Modularizado em ui.theme)
# =====================================================================
from ui.components import Button, afastar_conteudo_da_barra, quebrar_na_largura
from ui.navigation import (
    SidebarNavItem,
    StatusToolTip,
    aplicar_dwm_caption_color,
)
from ui.tabs.tab_diagnostics import build_tab_diagnostics
from ui.tabs.tab_history import build_tab_history
from ui.tabs.tab_onboarding import build_tab_onboarding
from ui.tabs.tab_settings import build_tab_settings
from ui.tabs.tab_shortcuts import build_tab_shortcuts, render_keycaps_row
from ui.tabs.tab_templates import build_tab_templates
from ui.tabs.tab_vocabulary import build_tab_vocabulary
from ui.theme import (
    APPLE_ACCENT,
    APPLE_ACCENT_SUBTLE,
    APPLE_BG_APP,
    APPLE_BG_SIDEBAR,
    APPLE_SEPARATOR,
    APPLE_STATUS_ONLINE,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_TERTIARY,
    CONTENT_PAD,
    FONT_FAMILY,
    RADIUS_CARD,
    SIDEBAR_PAD,
    SIDEBAR_WIDTH,
    localizar_asset,
    margem_conteudo,
)


def construir_callbacks_padrao(cfg, snip) -> dict:
    """Constrói o dicionário completo de callbacks do WillyDashboard para execução standalone."""
    from core import AudioManager, AutoStartManager, ConfigManager
    from core.config import credenciais_do_willy

    def _transcrever_indisponivel(path, **kw):
        raise RuntimeError("Transcrever arquivo indisponível no modo isolado.")

    return {
        "get_history": cfg.load_history,
        "get_analytics": cfg.get_analytics_metrics,
        "get_audio_devices": AudioManager.get_input_devices,
        "get_system_audio_devices": getattr(AudioManager, "get_loopback_devices", list),
        "get_actual_sample_rate": lambda: 16000,
        "get_credential_catalog": lambda: credenciais_do_willy(cfg),
        "get_snippets": snip.get_snippets,
        "on_save_snippet": snip.save_snippet,
        "on_delete_snippet": snip.delete_snippet,
        "get_replacements": cfg.load_replacements,
        "on_save_replacement": cfg.add_replacement,
        "on_delete_replacement": cfg.delete_replacement,
        "get_app_rules": cfg.get_app_context_rules,
        "on_save_app_rules": cfg.save_app_context_rules,
        "on_learn_correction": cfg.learn_correction,
        "on_export_profile": cfg.export_profile,
        "on_import_profile": cfg.import_profile,
        "get_hotkey_failures": dict,
        "get_last_external_app": lambda: None,
        "on_reuse_text": lambda texto: False,
        "on_transcribe_file": _transcrever_indisponivel,
        "on_play_audio": ConfigManager.open_file,
        "on_open_outputs": cfg.open_outputs_folder,
        "on_open_file": ConfigManager.open_file,
        "get_outputs_dir": lambda: cfg.outputs_dir,
        "get_settings": lambda: {
            "auto_silence": cfg.auto_silence,
            "clean_fillers": cfg.clean_fillers,
            "clipboard_only": cfg.clipboard_only,
            "smart_paragraphing": cfg.smart_paragraphing,
            "output_tone": cfg.output_tone,
            "input_language": cfg.input_language,
            "silence_seconds": cfg.silence_seconds,
            "refine_prompt": cfg.refine_prompt,
            "silent_mode": cfg.silent_mode,
            "private_mode": cfg.private_mode,
            "outputs_dir": cfg.outputs_dir,
            "pill_position": cfg.pill_position,
            "llm_model": cfg.llm_model,
            "audio_device": cfg.audio_device,
            "system_audio_device": cfg.system_audio_device,
            "mic_gain": cfg.mic_gain,
            "prompt_hotkey": cfg.prompt_hotkey,
            "transform_hotkey": cfg.transform_hotkey,
            "profile_hotkey": cfg.profile_hotkey,
            "processing_profile": getattr(cfg, "processing_profile", "dev"),
            "whisper_mode": getattr(cfg, "whisper_mode", False),
            "voice_hotkey": cfg.hotkey,
            "translate_hotkey": cfg.translate_hotkey,
            "translate_es_hotkey": cfg.translate_es_hotkey,
            "master_hotkey": cfg.master_hotkey,
            "meeting_hotkey": cfg.meeting_hotkey,
            "history_hotkey": cfg.history_hotkey,
            "undo_hotkey": cfg.undo_hotkey,
            "send_hotkey": cfg.send_hotkey,
            "speak_hotkey": cfg.speak_hotkey,
            "sticky_hotkey": cfg.sticky_hotkey,
            "captions_hotkey": cfg.captions_hotkey,
            "save_audio_files": cfg.save_audio_files,
            "silero_vad": cfg.silero_vad,
            "wake_word_enabled": cfg.wake_word_enabled,
            "api_key": cfg.groq_api_key,
            "cofre_ilegivel": cfg.cofre_ilegivel,
            "onboarding_completed": getattr(cfg, "onboarding_completed", True),
            "autostart": AutoStartManager.is_enabled(),
        },
        "on_toggle_autostart": AutoStartManager.set_enabled,
        "get_vocab": cfg.load_vocab_text,
        "get_awake_status": lambda: True,
        "on_toggle_sleep": lambda: True,
        "on_save_settings": cfg.save_settings,
        "on_validate_groq_key": lambda chave, salvar=False: (
            False,
            "Validação indisponível no modo isolado.",
            0.0,
            {},
        ),
        "on_reload_api_key": cfg.recarregar_chave_do_cofre,
        "on_test_dictation": lambda stop_event=None, on_level=None: (
            False,
            "",
            "",
            "Teste de ditado indisponível no modo isolado.",
        ),
        "on_complete_onboarding": lambda abrir_aba="history": cfg.save_settings({"ONBOARDING_COMPLETED": True}),
        "on_save_vocab": cfg.save_vocab_text,
        "on_clear_history": cfg.clear_history,
        "on_history_changed": lambda itens: None,
        "on_ping_groq": lambda: True,
        "notify_tray": lambda title, msg: None,
        "on_close_app": lambda: sys.exit(0),
    }


_ABAS_DELEGADAS = (
    "tab_history",
    "tab_templates",
    "tab_settings",
    "tab_vocab",
    "tab_diagnostics",
)
_DELEGADOS_ABA = {
    "_abrir_modal_snippet": ("tab_templates", "abrir_modal_snippet"),
    "_deletar_snippet": ("tab_templates", "deletar_snippet"),
    "_exportar_perfil_json": ("tab_settings", "exportar_perfil_json"),
    "_importar_perfil_json": ("tab_settings", "importar_perfil_json"),
    "_salvar_configuracoes": ("tab_settings", "salvar_configuracoes"),
    "_salvar_vocabulario": ("tab_vocab", "salvar_vocabulario"),
    "_carregar_termos_tech_comuns": ("tab_vocab", "carregar_termos_tech_comuns"),
    "_adicionar_replacement": ("tab_vocab", "adicionar_replacement"),
    "_deletar_replacement": ("tab_vocab", "deletar_replacement"),
    "_iniciar_teste_mic": ("tab_diagnostics", "iniciar_teste_mic"),
    "_testar_groq_api": ("tab_diagnostics", "testar_groq_api"),
}


class WillyDashboard(ctk.CTk):
    """Janela principal nativa do painel de controle do Willy com estética Apple macOS."""

    def __init__(self, callbacks, master_app=None):
        super().__init__()
        self._prev_default_root = tk._default_root
        tk._default_root = self
        self.callbacks = callbacks

        self.title("Willy")
        self.geometry("940x670")
        self.minsize(860, 590)
        self.configure(fg_color=APPLE_BG_APP)

        # Centralizar na tela
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - 940) // 2
        y = (screen_h - 670) // 2
        self.geometry(f"940x670+{x}+{y}")

        # Configurações do ícone nativo do Windows e barra de tarefas
        try:
            _shell32.SetCurrentProcessExplicitAppUserModelID("jottaprado.willy.app.1.0")
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            pass

        ico_path = localizar_asset("assets", "willy_icon.ico")
        if ico_path:
            try:
                self.iconbitmap(ico_path)
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: teardown e ícone no Tkinter
                pass

        # Ao clicar no 'X', oculta a janela para a bandeja e avisa na primeira ocorrência
        self.protocol("WM_DELETE_WINDOW", self._on_window_close_clicked)

        # Atalho global Ctrl+K para focar campo de busca da tela ativa
        self.bind("<Control-k>", self._on_global_ctrl_k)
        self.bind("<Control-K>", self._on_global_ctrl_k)
        self.bind("<Configure>", self._on_window_configure)
        # Restaurada pela barra de tarefas a janela volta sem passar pelo mostrar(): a lista
        # deixada para depois com ela escondida é refeita aqui.
        self._historico_pendente = False
        self.bind("<Map>", self._on_janela_mapeada, add="+")
        self._maximizada_ao_esconder = False

        # Aplica cor da barra de título DWM no Windows 11
        self._after_dwm = self.after(50, self._aplicar_dwm_caption_color)

        self.history_items = []
        self.active_tab = "history"
        self.mic_test_active = False
        self._is_acordado = True
        self._tray_notice_shown = False

        self._criar_layout()
        self.recarregar_dados(completo=True)

    @property
    def history_items(self):
        tab = self.__dict__.get("tab_history")
        if tab is not None:
            return tab.history_items
        return self.__dict__.get("_history_items", [])

    @history_items.setter
    def history_items(self, value):
        self.__dict__["_history_items"] = value
        tab = self.__dict__.get("tab_history")
        if tab is not None:
            tab.history_items = value

    @property
    def mic_test_active(self):
        tab = self.__dict__.get("tab_diagnostics")
        if tab is not None:
            return tab.mic_test_active
        return self.__dict__.get("_mic_test_active", False)

    @mic_test_active.setter
    def mic_test_active(self, value):
        self.__dict__["_mic_test_active"] = value
        tab = self.__dict__.get("tab_diagnostics")
        if tab is not None:
            tab.mic_test_active = value

    @property
    def _dev_map(self):
        tab = self.__dict__.get("tab_settings")
        if tab is not None:
            return getattr(tab, "_dev_map", {})
        return self.__dict__.get("__dev_map", {})

    @_dev_map.setter
    def _dev_map(self, value):
        self.__dict__["__dev_map"] = value
        tab = self.__dict__.get("tab_settings")
        if tab is not None:
            tab._dev_map = value

    @property
    def _sys_dev_map(self):
        tab = self.__dict__.get("tab_settings")
        if tab is not None:
            return getattr(tab, "_sys_dev_map", {})
        return self.__dict__.get("__sys_dev_map", {})

    @_sys_dev_map.setter
    def _sys_dev_map(self, value):
        self.__dict__["__sys_dev_map"] = value
        tab = self.__dict__.get("tab_settings")
        if tab is not None:
            tab._sys_dev_map = value

    def __getattr__(self, name: str):
        if name.startswith("__") or name in _ABAS_DELEGADAS:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        alvo = _DELEGADOS_ABA.get(name)
        if alvo is not None:
            nome_aba, nome_real = alvo
            aba = self.__dict__.get(nome_aba)
            if aba is not None and hasattr(aba, nome_real):
                return getattr(aba, nome_real)
        for nome_aba in _ABAS_DELEGADAS:
            aba = self.__dict__.get(nome_aba)
            if aba is not None and hasattr(aba, name):
                return getattr(aba, name)
        try:
            return super().__getattr__(name)
        except AttributeError as err:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}") from err

    def _on_global_ctrl_k(self, event=None):
        """Foca o SearchField da aba ativa ou navega para o Histórico."""
        if self.active_tab == "history" and hasattr(self, "tab_history"):
            if hasattr(self.tab_history, "search_field"):
                self.tab_history.search_field.focus()
                return "break"
            elif hasattr(self.tab_history, "entry_busca"):
                self.tab_history.entry_busca.focus_set()
                return "break"
        elif self.active_tab in ("templates", "snippets") and hasattr(self, "tab_templates"):
            if hasattr(self.tab_templates, "search_field"):
                self.tab_templates.search_field.focus()
                return "break"
            elif hasattr(self.tab_templates, "entry_busca_snippets"):
                self.tab_templates.entry_busca_snippets.focus_set()
                return "break"
        else:
            self.mudar_aba("history")
            if hasattr(self, "tab_history") and hasattr(self.tab_history, "search_field"):
                self.tab_history.search_field.focus()
                return "break"

    def _aplicar_dwm_caption_color(self):
        """Aplica a cor da barra de título via DWM (DWMWA_CAPTION_COLOR = 35) no Windows 11."""
        aplicar_dwm_caption_color(self)

    def destroy(self):
        """Destrói a janela cancelando timers e preservando o default_root caso outra janela de teste exista."""
        if hasattr(self, "_after_dwm") and self._after_dwm:
            try:
                self.after_cancel(self._after_dwm)
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: teardown e ícone no Tkinter
                pass
            self._after_dwm = None

        prev = getattr(self, "_prev_default_root", None)
        try:
            super().destroy()
        finally:
            if prev is not None:
                try:
                    if prev.winfo_exists():
                        tk._default_root = prev
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: restauração de _default_root e bandeja
                    pass

    def fechar_app(self):
        """Encerra e desliga o Willy por completo (0% de CPU / 0 MB de RAM)."""
        if self.callbacks.get("on_close_app"):
            self.callbacks["on_close_app"]()
        else:
            try:
                self.quit()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: teardown e ícone no Tkinter
                pass
            try:
                self.destroy()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: teardown e ícone no Tkinter
                pass

    def _on_window_close_clicked(self):
        """Ao clicar no 'X', oculta a janela para a bandeja e notifica na primeira vez."""
        self.esconder()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            if self.callbacks.get("notify_tray"):
                try:
                    self.callbacks["notify_tray"](
                        "Willy continua ativo",
                        "O Willy continua ativo na bandeja. Para encerrar, use Sair no ícone da bandeja."
                    )
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: restauração de _default_root e bandeja
                    pass

    def esconder(self):
        """Oculta a janela para a bandeja do sistema mantendo o assistente ativo."""
        try:
            # O Tk esquece o "zoomed" ao esconder (medido): o mostrar() o devolve.
            self._maximizada_ao_esconder = self.state() == "zoomed"
            self.withdraw()
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            pass

    def minimizar(self):
        """Minimiza a janela para a barra de tarefas do Windows (permanece visível na barra)."""
        try:
            self.iconify()
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            pass

    def mostrar(self):
        """Traz a janela para a frente como ela estava: maximizada volta maximizada.

        O state("normal") e o SW_RESTORE tiravam a janela de maximizada a cada abertura pela
        bandeja.
        """
        # A lista pendente é refeita uma vez só, pelo recarregar_dados do fim, e não também pelo
        # <Map> do deiconify. Hoje o <Map> já chega depois do recarregar_dados (medido: sem esta
        # linha a lista também é refeita uma vez); zerar aqui não depende dessa ordem.
        self._historico_pendente = False
        try:
            estado = self.state()
            if estado == "withdrawn":
                self.deiconify()
                if self._maximizada_ao_esconder:
                    self.state("zoomed")
            elif estado == "iconic":
                self.deiconify()  # o Tk devolve ao estado de antes de minimizar (medido)
            self.lift()
            self.attributes("-topmost", True)
            self.after(120, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            pass

        # Foco pelo Win32 na PRÓPRIA janela. O FindWindowW(None, "Willy") devolvia a primeira
        # janela com esse título, que podia ser uma pasta "Willy" aberta no Explorer.
        try:
            hwnd = int(self.wm_frame(), 16)
            if _user32.IsIconic(hwnd):
                _user32.ShowWindow(hwnd, 9)  # SW_RESTORE: só minimizada; maximizada, ele a desmaximiza
            _user32.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            pass

        self.recarregar_dados()
        # O vocabulário muda por fora (a bandeja abre o arquivo no Bloco de Notas) enquanto a
        # janela está escondida: sem reler, o próximo auto-save gravava o texto velho por cima.
        if hasattr(self, "tab_vocab"):
            self.tab_vocab.recarregar_se_nao_editado()

    def _criar_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # -------------------------------------------------------------
        # BARRA LATERAL (SIDEBAR ESTILO macOS / RAYCAST)
        # Largura fixa de 240px com padding horizontal de 12px
        # -------------------------------------------------------------
        self.sidebar = ctk.CTkFrame(
            self,
            width=SIDEBAR_WIDTH,
            corner_radius=0,
            fg_color=APPLE_BG_SIDEBAR,
            border_width=1,
            border_color=APPLE_SEPARATOR
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(6, weight=1)  # Espaçador flexível entre seção principal e rodapé

        # Container do Cabeçalho da Marca
        # Mesma margem interna (padx=12), alinhando ao eixo dos itens
        header_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header_box.grid(row=0, column=0, padx=SIDEBAR_PAD, pady=(20, 24), sticky="ew")
        header_box.grid_columnconfigure(0, minsize=40)
        header_box.grid_columnconfigure(1, weight=1)

        # Avatar: o robô do Willy, o mesmo do ícone do app e da bandeja. 40x40 ocupa a coluna
        # de 40px e as duas linhas do cabeçalho (nome + status) sem tirar o "Willy" do eixo x=54.
        robot_img_path = localizar_asset("assets", "willy_robot.png")

        try:
            from PIL import Image
            if robot_img_path:
                with Image.open(robot_img_path) as pil_img:
                    # O PNG tem 1024px e o CTkImage reduz num passo só, sem filtro bom: o robô
                    # sairia serrilhado. Pré-reduzido com LANCZOS a 96px (cobre até 240% de escala).
                    robo = pil_img.convert("RGBA").resize((96, 96), Image.Resampling.LANCZOS)
                self.robot_ctk_img = ctk.CTkImage(light_image=robo, dark_image=robo, size=(40, 40))
            else:
                self.robot_ctk_img = None

            if self.robot_ctk_img:
                self.avatar_label = ctk.CTkLabel(
                    header_box,
                    image=self.robot_ctk_img,
                    text="",
                    width=40,
                    anchor="center"
                )
                self.avatar_label.grid(row=0, column=0, rowspan=2, padx=0, pady=0, sticky="ns")
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida da janela Tkinter/Win32
            pass

        # Nome "Willy" em 15px semibold (início em x = 42px interno / 54px da janela)
        self.logo_label = ctk.CTkLabel(
            header_box,
            text="Willy",
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w"
        )
        self.logo_label.grid(row=0, column=1, padx=(2, 0), sticky="w")

        # Status Discreto & Clicável (Pausa/Ativação com Ponto de 6px + "Ativo" em 12px secundário)
        # Alinhado exatamente no mesmo eixo x = 54px do texto "Willy"
        self.status_box = ctk.CTkFrame(header_box, fg_color="transparent", cursor="hand2")
        self.status_box.grid(row=1, column=1, padx=(0, 0), pady=(2, 0), sticky="w")

        self.status_dot = ctk.CTkFrame(
            self.status_box,
            width=6,
            height=6,
            corner_radius=3,
            fg_color=APPLE_STATUS_ONLINE,
            cursor="hand2"
        )
        self.status_dot.pack(side="left", padx=(2, 6))

        self.status_badge = ctk.CTkLabel(
            self.status_box,
            text="Ativo",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            cursor="hand2"
        )
        self.status_badge.pack(side="left")

        # Torna o status clicável para pausar/retomar Willy (sincronizado com a bandeja)
        for w in (self.status_box, self.status_dot, self.status_badge):
            w.bind("<Button-1>", lambda e: self._clicar_toggle_sleep())
            w.bind("<Enter>", lambda e: self._on_status_hover(True))
            w.bind("<Leave>", lambda e: self._on_status_hover(False))

        # Tooltip para controle de pausa
        StatusToolTip(
            self.status_box,
            lambda: "Clique para pausar" if getattr(self, "_is_acordado", True) else "Clique para ativar"
        )

        # Guia Inicial em destaque no topo do menu para descoberta imediata na primeira abertura
        self.nav_items = {}
        item_guia = SidebarNavItem(
            self.sidebar,
            icon_key="onboarding",
            text="Guia Inicial",
            command=lambda: self.mudar_aba("onboarding"),
            fallback_glyph="✦",
            highlighted=True,
        )
        item_guia.grid(row=1, column=0, padx=SIDEBAR_PAD, pady=(0, 12), sticky="ew")
        self.nav_items["onboarding"] = item_guia

        # Seção 1: Navegação Principal (Histórico, Templates, Vocabulário, Atalhos)
        # 2px de espaçamento vertical entre itens (pady=1)
        itens_principal = [
            ("history", "history", "Histórico", "◷"),
            ("snippets", "templates", "Templates", "✦"),
            ("vocab", "vocabulary", "Vocabulário", "✎"),
            ("shortcuts", "shortcuts", "Atalhos", "⌘"),
        ]

        for i, (tab_key, icon_key, label_text, fallback_glyph) in enumerate(itens_principal, start=2):
            item = SidebarNavItem(
                self.sidebar,
                icon_key=icon_key,
                text=label_text,
                command=lambda k=tab_key: self.mudar_aba(k),
                fallback_glyph=fallback_glyph
            )
            item.grid(row=i, column=0, padx=SIDEBAR_PAD, pady=1, sticky="ew")
            self.nav_items[tab_key] = item

        # Seção 2: Sistema no Rodapé da Sidebar (Diagnósticos e Ajustes)
        # 16px de espaçamento acima do grupo, alinhados exatamente aos itens de cima
        itens_sistema = [
            ("diagnostics", "diagnostics", "Diagnósticos", "∿"),
            ("settings", "settings", "Ajustes", "⚙"),
        ]

        for j, (tab_key, icon_key, label_text, fallback_glyph) in enumerate(itens_sistema, start=7):
            item = SidebarNavItem(
                self.sidebar,
                icon_key=icon_key,
                text=label_text,
                command=lambda k=tab_key: self.mudar_aba(k),
                fallback_glyph=fallback_glyph
            )
            p_top = 16 if j == 7 else 1
            p_bot = 16 if j == 8 else 1
            item.grid(row=j, column=0, padx=SIDEBAR_PAD, pady=(p_top, p_bot), sticky="ew")
            self.nav_items[tab_key] = item

        # -------------------------------------------------------------
        # ÁREA DE CONTEÚDO PRINCIPAL (MAIN CONTAINER)
        # Uma coluna só, com todo o espaço à direita da sidebar. A aba ativa vai até a borda
        # direita da janela (a barra de rolagem fica na borda real) e a margem lateral cresce
        # com a largura (ver margem_conteudo e _aplicar_margens).
        # -------------------------------------------------------------
        self.main_container = ctk.CTkFrame(self, fg_color=APPLE_BG_APP, corner_radius=0)
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main_container.grid_rowconfigure(0, weight=0)
        self.main_container.grid_rowconfigure(1, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        self._margem = CONTENT_PAD
        self._escala = None

        self.banner_onboarding = ctk.CTkFrame(
            self.main_container,
            fg_color=APPLE_ACCENT_SUBTLE,
            border_width=1,
            border_color=APPLE_ACCENT,
            corner_radius=RADIUS_CARD,
        )
        self.banner_onboarding.grid_columnconfigure(0, weight=1)
        self.lbl_banner_onboarding = ctk.CTkLabel(
            self.banner_onboarding,
            text="Falta configurar sua chave gratuita da Groq para ativar a transcrição por voz.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            justify="left",
            anchor="w",
        )
        self.lbl_banner_onboarding.grid(row=0, column=0, sticky="ew", padx=(14, 12), pady=10)
        quebrar_na_largura(self.lbl_banner_onboarding, self.banner_onboarding, folga=260)

        banner_acoes = ctk.CTkFrame(self.banner_onboarding, fg_color="transparent")
        banner_acoes.grid(row=0, column=1, sticky="e", padx=(0, 12), pady=8)
        Button(
            banner_acoes,
            text="Configurar Agora",
            variant="primary",
            command=lambda: self.mudar_aba("onboarding"),
        ).pack(side="left", padx=(0, 6))
        Button(
            banner_acoes,
            text="Ajustes",
            variant="secondary",
            command=lambda: self.mudar_aba("settings"),
        ).pack(side="left")

        self.frames_abas = {}
        self._construir_aba_historico()
        self._construir_aba_templates()
        self._construir_aba_atalhos()
        self._construir_aba_configuracoes()
        self._construir_aba_vocabulario()
        self._construir_aba_diagnosticos()
        self._construir_aba_onboarding()

        self.mudar_aba("history")

    @property
    def banner_onboarding_visivel(self) -> bool:
        """Indica se o banner discreto de configuração pendente está visível na tela."""
        return hasattr(self, "banner_onboarding") and bool(self.banner_onboarding.winfo_manager())

    def _atualizar_banner_onboarding(self, cfg=None) -> None:
        if not hasattr(self, "banner_onboarding"):
            return
        item_guia = getattr(self, "nav_items", {}).get("onboarding")
        if cfg is None:
            fn = self.callbacks.get("get_settings")
            if not fn:
                self.banner_onboarding.grid_forget()
                if item_guia is not None:
                    item_guia.set_badge("")
                return
            try:
                cfg = fn() or {}
            except Exception:  # noqa: BLE001 — fronteira defensiva: leitura de get_settings no banner
                self.banner_onboarding.grid_forget()
                if item_guia is not None:
                    item_guia.set_badge("")
                return

        chave = (cfg.get("api_key") or "").strip()
        sem_chave = not chave or chave == "sua_chave_aqui"
        pendente = sem_chave or not bool(cfg.get("onboarding_completed", True))
        if item_guia is not None:
            item_guia.set_badge("Começar" if pendente else "")

        if self.active_tab == "onboarding" or not sem_chave:
            self.banner_onboarding.grid_forget()
        else:
            self.banner_onboarding.grid(
                row=0,
                column=0,
                sticky="ew",
                padx=(self._margem, self._margem),
                pady=(16, 0),
            )

    def _on_window_configure(self, event=None):
        if event and event.widget != self:
            return
        # A largura vem da janela, não do main_container: no <Configure> da janela o grid
        # ainda não repassou o tamanho novo para os filhos. winfo_width é pixel e
        # SIDEBAR_WIDTH é unidade do CTk; com o Windows em 125% ou 150% as duas divergem.
        escala = self.main_container._get_widget_scaling()
        margem = margem_conteudo(self.winfo_width() / escala - SIDEBAR_WIDTH)
        # A escala entra na comparação porque o recuo antes da barra é em pixels e o CTk não
        # o refaz quando a janela muda para um monitor com outro DPI.
        if (margem, escala) != (self._margem, self._escala):
            self._margem, self._escala = margem, escala
            self._aplicar_margens()

    def _aplicar_margens(self):
        """Margem esquerda na aba ativa; à direita, o conteúdo recua e a barra fica na borda."""
        aba = self.frames_abas.get(self.active_tab)
        if aba is None:
            return
        # Uma chamada só, com todos os argumentos: o CTk guarda os kwargs da ÚLTIMA chamada
        # de grid() e os reaplica escalados quando o DPI muda. E .grid(), não
        # .grid_configure(): o CTkScrollableFrame só sobrescreve o grid(), que repassa ao
        # frame externo; o grid_configure do tkinter agiria no frame interno.
        aba.grid(row=1, column=0, sticky="nsew", pady=24, padx=(self._margem, 0))
        if hasattr(aba, "aplicar_margem_direita"):
            aba.aplicar_margem_direita(self._margem)
        else:
            afastar_conteudo_da_barra(aba, self._margem)
        if self.banner_onboarding_visivel:
            self.banner_onboarding.grid(
                row=0,
                column=0,
                sticky="ew",
                padx=(self._margem, self._margem),
                pady=(16, 0),
            )

    def _on_status_hover(self, entering: bool):
        if hasattr(self, "status_badge"):
            if entering:
                self.status_badge.configure(text_color=APPLE_TEXT_PRIMARY)
            else:
                self.status_badge.configure(
                    text_color=APPLE_TEXT_SECONDARY if getattr(self, "_is_acordado", True) else APPLE_TEXT_TERTIARY
                )

    def mudar_aba(self, tab_key):
        if tab_key != "onboarding" and hasattr(self, "tab_onboarding"):
            self.tab_onboarding._interromper_capturas_ativas()
        self.active_tab = tab_key
        for f in self.frames_abas.values():
            f.grid_forget()
        for k, item in self.nav_items.items():
            item.set_active(k == tab_key)

        self._aplicar_margens()
        if tab_key == "history":
            self.atualizar_lista_historico()
        elif tab_key == "snippets":
            self.atualizar_lista_templates()
        elif tab_key == "diagnostics" and hasattr(self, "tab_diagnostics"):
            # O microfone dos Ajustes pode ter mudado desde a última vez que a aba apareceu.
            self.tab_diagnostics.atualizar_microfone()
        elif tab_key == "settings":
            self._recarregar_chave_se_vazia()
        elif tab_key == "onboarding" and hasattr(self, "tab_onboarding"):
            self.tab_onboarding.recarregar_dados()
        self._atualizar_banner_onboarding()

    def _recarregar_chave_se_vazia(self) -> None:
        if not self.callbacks.get("get_settings") or not self.callbacks.get("on_reload_api_key"):
            return
        try:
            cfg = self.callbacks["get_settings"]() or {}
        except Exception:  # noqa: BLE001 — fronteira defensiva: leitura get_settings ao abrir Ajustes
            return
        chave = (cfg.get("api_key") or "").strip()
        if not chave or chave == "sua_chave_aqui":
            try:
                if self.callbacks["on_reload_api_key"]():
                    self.recarregar_ajustes()
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback on_reload_api_key
                print(f"[WillyDashboard] Erro ao recarregar chave do cofre: {e}", file=sys.stderr)

    # -----------------------------------------------------------------
    # HELPER: CRIAÇÃO DE KEYCAPS (ESTILO APPLE KEYBOARD)
    # (Modularizado em ui.tabs.tab_shortcuts)
    # -----------------------------------------------------------------
    def _criar_keycaps_row(self, parent, teclas_list):
        """Renderiza um conjunto de teclas físicas elegantes (delegado para ui.tabs.tab_shortcuts)."""
        return render_keycaps_row(parent, teclas_list)

    # -----------------------------------------------------------------
    # ABA 1: HISTÓRICO DE PROMPTS (MODULARIZADO EM ui.tabs.tab_history)
    # -----------------------------------------------------------------
    def _construir_aba_historico(self):
        tab = build_tab_history(
            self.main_container,
            # A aba avisa quando exclui: a lista do Dashboard e os "Prompts recentes" da
            # bandeja passam a ser os dela.
            callbacks={**self.callbacks, "on_history_changed": self._historico_mudou_na_aba},
            ao_aprender_vocabulario=self._vocabulario_aprendido,
            history_items=self.history_items,
        )
        self.frames_abas["history"] = tab
        self.tab_history = tab
        return tab

    def _historico_mudou_na_aba(self, itens):
        """A aba excluiu itens. Sem isto o Dashboard seguia com a lista antiga, que voltava à
        aba no próximo export, e a bandeja seguia com os "Prompts recentes" de antes."""
        self.history_items = itens
        aviso = self.callbacks.get("on_history_changed")
        if aviso:
            aviso(itens)

    def _vocabulario_aprendido(self, termos):
        """O "Ensinar ao Willy" do Histórico gravou regras e termos: a aba Vocabulário os mostra
        já, sem esperar a pessoa reabrir o painel (ver VocabularyTab.receber_termos_aprendidos)."""
        if hasattr(self, "tab_vocab"):
            self.tab_vocab.receber_termos_aprendidos(termos)

    def atualizar_lista_historico(self):
        if hasattr(self, "tab_history"):
            return self.tab_history.atualizar_lista_historico()

    # -----------------------------------------------------------------
    # ABA: TEMPLATES & SNIPPETS POR VOZ (MODULARIZADO EM ui.tabs.tab_templates)
    # -----------------------------------------------------------------
    def _construir_aba_templates(self):
        tab = build_tab_templates(self.main_container, callbacks=self.callbacks)
        self.frames_abas["snippets"] = tab
        self.tab_templates = tab
        return tab

    def atualizar_lista_templates(self):
        if hasattr(self, "tab_templates"):
            return self.tab_templates.atualizar_lista_templates()

    # -----------------------------------------------------------------
    # ABA 2: ATALHOS & COMANDOS (MODULARIZADO EM ui.tabs.tab_shortcuts)
    # -----------------------------------------------------------------
    def _construir_aba_atalhos(self):
        f = build_tab_shortcuts(self.main_container, callbacks=getattr(self, "callbacks", None))
        self.frames_abas["shortcuts"] = f
        return f

    # -----------------------------------------------------------------
    # ABA 3: CONFIGURAÇÕES (MODULARIZADO EM ui.tabs.tab_settings)
    # -----------------------------------------------------------------
    def _construir_aba_configuracoes(self):
        tab = build_tab_settings(self.main_container, callbacks=getattr(self, "callbacks", None))
        self.frames_abas["settings"] = tab
        self.tab_settings = tab
        return tab

    # -----------------------------------------------------------------
    # ABA 4: VOCABULÁRIO & JARGÕES (MODULARIZADO EM ui.tabs.tab_vocabulary)
    # -----------------------------------------------------------------
    def _construir_aba_vocabulario(self):
        tab = build_tab_vocabulary(self.main_container, callbacks=self.callbacks)
        self.frames_abas["vocab"] = tab
        self.tab_vocab = tab
        return tab

    def atualizar_lista_replacements(self):
        if hasattr(self, "tab_vocab"):
            return self.tab_vocab.atualizar_lista_replacements()

    # -----------------------------------------------------------------
    # ABA 5: MICROFONE & DIAGNÓSTICOS (MODULARIZADO EM ui.tabs.tab_diagnostics)
    # -----------------------------------------------------------------
    def _construir_aba_diagnosticos(self):
        tab = build_tab_diagnostics(self.main_container, callbacks=self.callbacks)
        self.frames_abas["diagnostics"] = tab
        self.tab_diagnostics = tab
        return tab

    def _construir_aba_onboarding(self):
        tab = build_tab_onboarding(self.main_container, callbacks=self.callbacks)
        self.frames_abas["onboarding"] = tab
        self.tab_onboarding = tab
        return tab

    # -----------------------------------------------------------------
    # SINCRONIZAÇÃO DE DADOS & ESTADO
    # -----------------------------------------------------------------
    def sincronizar_atalhos(self):
        """Faz as abas Atalhos e Ajustes mostrarem as combinações que estão na config.

        Uma troca recusada pelo Windows volta à combinação anterior, na config também, e as
        duas abas seguiam com a recusada. Só os atalhos: o recarregar_dados inteiro
        reescreveria o vocabulário que a pessoa está digitando.
        """
        if not self.callbacks.get("get_settings"):
            return
        cfg = self.callbacks["get_settings"]()
        if hasattr(self, "tab_settings"):
            self.tab_settings.recarregar_atalhos(cfg)
        self._sincronizar_aba_atalhos(cfg)

    def _sincronizar_aba_atalhos(self, cfg):
        aba = getattr(self, "frames_abas", {}).get("shortcuts")
        if aba is not None and hasattr(aba, "sincronizar_atalhos"):
            aba.sincronizar_atalhos(cfg)

    def recarregar_ajustes(self):
        """Ajustes e Atalhos a partir da config, para quem trocou um ajuste por fora da aba
        (bandeja, atalho de perfil). O resto da janela fica como está."""
        if not self.callbacks.get("get_settings"):
            return
        cfg = self.callbacks["get_settings"]()
        if hasattr(self, "tab_settings"):
            self.tab_settings.recarregar_dados(cfg)
        self._sincronizar_aba_atalhos(cfg)
        if hasattr(self, "tab_diagnostics"):
            self.tab_diagnostics.atualizar_microfone()
        self._atualizar_banner_onboarding(cfg)

    def recarregar_dados(self, completo: bool = False):
        """Relê os dados. Leve por padrão, que é o que roda depois de cada ditado: histórico,
        KPIs e o estado do Willy. Relia também Ajustes e Vocabulário, e apagava o que a pessoa
        estava editando neles (e listava os microfones de novo a cada ditado).

        completo=True, na criação da janela e no perfil importado, relê todas as abas por cima
        do que estiver na tela: Ajustes, Atalhos, Vocabulário, Templates e Histórico. O
        mostrar() (a janela voltando da bandeja) usa o leve e relê o Vocabulário à parte.
        """
        if self.callbacks.get("get_history"):
            self.history_items = self.callbacks["get_history"]()

        if completo:
            self.recarregar_ajustes()
            if self.callbacks.get("get_vocab"):
                v = self.callbacks["get_vocab"]()
                self.txt_vocab.delete("1.0", "end")
                self.txt_vocab.insert("1.0", v)
            self.atualizar_lista_replacements()
            self.atualizar_lista_templates()

        if self.callbacks.get("get_awake_status"):
            acordado = self.callbacks["get_awake_status"]()
            self.atualizar_status_willy(acordado)

        # Com a janela escondida ou minimizada, a lista não aparece para ninguém: reconstruí-la
        # custava segundos na thread da interface depois de cada ditado, com a pílula esperando.
        # Fica pendente e é refeita quando a janela volta (mostrar() ou o <Map>). Maximizada,
        # a janela está em "zoomed", não em "normal".
        if self.active_tab == "history":
            if self.state() in ("normal", "zoomed"):
                self._historico_pendente = False
                self.atualizar_lista_historico()
            else:
                self._historico_pendente = True

    def _on_janela_mapeada(self, event=None):
        # O <Map> ligado na janela chega também de cada widget de dentro dela.
        if event is not None and event.widget is not self:
            return
        if self._historico_pendente and self.active_tab == "history":
            self._historico_pendente = False
            self.after_idle(self.atualizar_lista_historico)

    def atualizar_status_willy(self, acordado):
        self._is_acordado = acordado
        if acordado:
            if hasattr(self, "status_badge"):
                self.status_badge.configure(text="Ativo", text_color=APPLE_TEXT_SECONDARY)
            if hasattr(self, "status_dot"):
                self.status_dot.configure(fg_color=APPLE_STATUS_ONLINE)
        else:
            if hasattr(self, "status_badge"):
                self.status_badge.configure(text="Pausado", text_color=APPLE_TEXT_TERTIARY)
            if hasattr(self, "status_dot"):
                self.status_dot.configure(fg_color=APPLE_TEXT_TERTIARY)

    def _clicar_toggle_sleep(self):
        if self.callbacks.get("on_toggle_sleep"):
            novo_estado = self.callbacks["on_toggle_sleep"]()
            self.atualizar_status_willy(novo_estado)


if __name__ == "__main__":
    from core import ConfigManager, SnippetManager
    from core.config import cofre_do_sistema

    cfg = ConfigManager(cofre=cofre_do_sistema())
    snip = SnippetManager()
    app = WillyDashboard(callbacks=construir_callbacks_padrao(cfg, snip))
    app.mostrar()
    app.mainloop()
