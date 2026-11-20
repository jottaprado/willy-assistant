"""
Aba de Guia Inicial (Onboarding) do Willy Dashboard.
Orienta o novo usuário em 4 passos: chaves, microfone, atalhos e primeiro ditado.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from tkinter import filedialog
from typing import Any

import customtkinter as ctk
from dotenv import dotenv_values

from core.audio import SAMPLE_RATE, negociar_stream
from core.audio_processing.diagnostico import (
    medir_teste,
    nivel_acima_do_piso,
    parcial_do_teste,
    resumo_do_teste,
)
from core.audio_processing.vad import compute_rms
from core.config import credenciais_do_willy
from core.hotkey import HOTKEYS_PADRAO
from ui.components import (
    Button,
    Keycap,
    PageHeader,
    SectionHeader,
    quebrar_na_largura,
)
from ui.theme import (
    ACCENT_AMBER,
    ACCENT_GREEN,
    ACCENT_RED,
    APPLE_ACCENT,
    APPLE_ACCENT_HOVER,
    APPLE_ACCENT_SUBTLE,
    APPLE_BG_CARD,
    APPLE_BG_HOVER,
    APPLE_BORDER_CARD,
    APPLE_INPUT_BG,
    APPLE_INPUT_BORDER,
    APPLE_KEYCAP_BG,
    APPLE_KEYCAP_BORDER,
    APPLE_SEGMENT_BG,
    APPLE_STATUS_ONLINE,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_TERTIARY,
    APPLE_TEXT_WARNING,
    BG_RECESSED,
    FONT_FAMILY,
    METER_OK,
    RADIUS_CARD,
    SCROLLBAR_COLOR,
    SCROLLBAR_HOVER,
)

_TITULOS_PASSOS: tuple[tuple[str, str], ...] = (
    ("1 · Chaves", "Configure a sua chave gratuita"),
    ("2 · Microfone", "Escolha e teste o microfone"),
    ("3 · Atalhos", "Confira os atalhos e conflitos"),
    ("4 · Ditado", "Teste seu primeiro ditado aqui"),
)

_GANHOS_PADRAO: dict[str, float] = {
    "1.0x (Padrão)": 1.0,
    "1.3x": 1.3,
    "1.6x": 1.6,
    "2.0x (Sussurro)": 2.0,
    "2.5x (Ultra)": 2.5,
}

_IDIOMAS_ENTRADA: dict[str, str] = {
    "🌐 Automático": "auto",
    "🇧🇷 Português": "pt",
    "🇺🇸 Inglês": "en",
}
_ROTULO_POR_IDIOMA: dict[str, str] = {codigo: rotulo for rotulo, codigo in _IDIOMAS_ENTRADA.items()}
_DESCRICOES_IDIOMA: dict[str, str] = {
    "auto": "Detecta português, inglês e termos técnicos automaticamente sem trocar de atalho.",
    "pt": "Prioriza transcrição nativa em português brasileiro (PT-BR).",
    "en": "Prioriza transcrição nativa em inglês internacional (EN).",
}


class OnboardingTab(ctk.CTkScrollableFrame):
    """Assistente modular de boas-vindas e configuração inicial em 4 passos."""

    def __init__(self, master: Any, callbacks: dict[str, Callable] | None = None, **kwargs):
        super().__init__(
            master,
            fg_color="transparent",
            scrollbar_button_color=SCROLLBAR_COLOR,
            scrollbar_button_hover_color=SCROLLBAR_HOVER,
            scrollbar_fg_color="transparent",
            **kwargs,
        )
        self.callbacks = callbacks or {}
        self.grid_columnconfigure(0, weight=1)

        self.passo_atual: int = 0
        self._passos_visitados: set[int] = {0}
        self._chave_validada: bool = False
        self._mostrando_chave: bool = False
        self.mic_test_active: bool = False
        self._ditado_ativo: bool = False
        self._validando_chave: bool = False
        self._ditado_stop_event: threading.Event | None = None
        self._fila_ui: queue.SimpleQueue = queue.SimpleQueue()
        self._dreno_agendado: bool = False
        self._dev_map: dict[str, int | None] = {"Padrão do Sistema": None}
        self._keycaps: dict[str, Keycap] = {}
        self._botoes_passos: list[ctk.CTkButton] = []
        self._frames_passos: list[ctk.CTkFrame] = []

        self._construir_ui()
        self.recarregar_dados()
        self._atualizar_passo_ui()

    def _agendar_dreno_ui(self) -> None:
        if self._dreno_agendado:
            return
        try:
            if self.winfo_exists():
                self._dreno_agendado = True
                self.after(15, self._drenar_fila_ui)
        except Exception:  # noqa: BLE001 — fronteira defensiva: ciclo de vida Tkinter ao agendar dreno
            self._dreno_agendado = False

    def _drenar_fila_ui(self) -> None:
        self._dreno_agendado = False
        try:
            if not self.winfo_exists():
                return
        except Exception:  # noqa: BLE001 — fronteira defensiva: widget destruído antes do dreno
            return
        while not self._fila_ui.empty():
            func, args = self._fila_ui.get_nowait()
            try:
                func(*args)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: execução de callback na thread de UI
                print(f"[OnboardingTab] Erro no dreno de UI: {e}", file=sys.stderr)
        if not self._fila_ui.empty() or self.mic_test_active or self._ditado_ativo or self._validando_chave:
            self._agendar_dreno_ui()

    def _safe_after(self, delay_ms: int, func: Callable, *args) -> None:
        """Agenda atualização na thread da interface sem chamar Tk em thread de fundo."""
        if self.callbacks.get("safe_dispatch_ui"):
            try:
                self.callbacks["safe_dispatch_ui"](func, *args, delay_ms=delay_ms)
                return
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: despacho em safe_dispatch_ui
                print(f"[OnboardingTab] Erro em safe_dispatch_ui: {e}", file=sys.stderr)
        if threading.current_thread() is threading.main_thread():
            try:
                if self.winfo_exists():
                    self.after(delay_ms, func, *args)
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: ciclo de vida Tkinter após fechar aba
                pass
        else:
            self._fila_ui.put((func, args))

    def _ler_settings(self) -> dict[str, Any]:
        fn = self.callbacks.get("get_settings")
        if not fn:
            return {}
        try:
            return fn() or {}
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback externo get_settings
            print(f"[OnboardingTab] Erro ao ler ajustes: {e}", file=sys.stderr)
            return {}

    def _ler_catalogo(self) -> list[dict[str, Any]]:
        fn = self.callbacks.get("get_credential_catalog")
        if fn:
            try:
                itens = fn()
                if isinstance(itens, list) and itens:
                    return itens
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback get_credential_catalog
                print(f"[OnboardingTab] Erro ao ler catálogo de chaves: {e}", file=sys.stderr)
        return credenciais_do_willy()

    def _construir_ui(self) -> None:
        self.btn_pular = Button(
            self,
            text="Pular guia",
            variant="ghost",
            command=self.pular_onboarding,
        )
        self.page_header = PageHeader(
            self,
            title="Bem-vindo ao Willy",
            subtitle="Em quatro passos rápidos você deixa voz, chaves e atalhos prontos para ditar.",
            actions=[self.btn_pular],
        )
        self.page_header.pack(fill="x", pady=(0, 12))

        # Barra de progresso com 4 etapas clicáveis (etapas já abertas).
        self.stepper_frame = ctk.CTkFrame(
            self,
            fg_color=APPLE_BG_CARD,
            border_width=1,
            border_color=APPLE_BORDER_CARD,
            corner_radius=RADIUS_CARD,
        )
        self.stepper_frame.pack(fill="x", pady=(0, 14))
        for col in range(len(_TITULOS_PASSOS)):
            self.stepper_frame.grid_columnconfigure(col, weight=1, uniform="passo")

        for idx, (titulo, _sub) in enumerate(_TITULOS_PASSOS):
            btn = ctk.CTkButton(
                self.stepper_frame,
                text=titulo,
                height=34,
                corner_radius=8,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                fg_color="transparent",
                hover_color=APPLE_BG_HOVER,
                text_color=APPLE_TEXT_SECONDARY,
                command=lambda i=idx: self.ir_para_passo(i),
            )
            btn.grid(row=0, column=idx, sticky="ew", padx=6, pady=6)
            self._botoes_passos.append(btn)

        # Palco das etapas.
        self.stage_container = ctk.CTkFrame(self, fg_color="transparent")
        self.stage_container.pack(fill="x")
        self.stage_container.grid_columnconfigure(0, weight=1)

        self._frames_passos = [
            self._construir_passo_chaves(self.stage_container),
            self._construir_passo_microfone(self.stage_container),
            self._construir_passo_atalhos(self.stage_container),
            self._construir_passo_ditado(self.stage_container),
        ]

        # Navegação inferior.
        self.nav_footer = ctk.CTkFrame(self, fg_color="transparent")
        self.nav_footer.pack(fill="x", pady=(16, 12))
        self.nav_footer.grid_columnconfigure(1, weight=1)

        self.btn_voltar = Button(
            self.nav_footer,
            text="Voltar",
            variant="secondary",
            command=self.voltar_passo,
        )
        self.btn_voltar.grid(row=0, column=0, sticky="w")

        self.btn_continuar = Button(
            self.nav_footer,
            text="Continuar",
            variant="primary",
            command=self.avancar_passo,
        )
        self.btn_continuar.grid(row=0, column=2, sticky="e")

    def _novo_card(self, parent: Any) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=APPLE_BG_CARD,
            border_width=1,
            border_color=APPLE_BORDER_CARD,
            corner_radius=RADIUS_CARD,
        )
        card.pack(fill="x", pady=(0, 12))
        return card

    # -----------------------------------------------------------------
    # PASSO 1: CHAVES E PROVEDORES
    # -----------------------------------------------------------------
    def _construir_passo_chaves(self, parent: Any) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        SectionHeader(frame, text="PASSO 1 · CHAVES NECESSÁRIAS").pack(fill="x", pady=(2, 6))

        aviso = self._novo_card(frame)
        lbl_aviso = ctk.CTkLabel(
            aviso,
            text=(
                "Hoje o Willy precisa de apenas 1 chave, gratuita e sem cartão de crédito. "
                "Quando novas integrações opcionais entrarem, todas aparecerão organizadas aqui."
            ),
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_PRIMARY,
            justify="left",
            anchor="w",
        )
        lbl_aviso.pack(fill="x", padx=16, pady=14)
        quebrar_na_largura(lbl_aviso, aviso, folga=32)

        catalogo = self._ler_catalogo()
        for item in catalogo:
            self._renderizar_card_credencial(frame, item)

        return frame

    def _renderizar_card_credencial(self, parent: Any, item: dict[str, Any]) -> None:
        card = self._novo_card(parent)
        topo = ctk.CTkFrame(card, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=(14, 4))

        nome = item.get("nome", item.get("env_var", "Credencial"))
        ctk.CTkLabel(
            topo,
            text=nome,
            font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left")

        etiquetas = []
        etiquetas.append("Obrigatória" if item.get("obrigatoria") else "Opcional")
        if item.get("gratuita"):
            etiquetas.append("Gratuita")
        if item.get("sem_cartao"):
            etiquetas.append("Sem cartão")

        badge_text = " · ".join(etiquetas)
        ctk.CTkLabel(
            topo,
            text=f"  {badge_text}  ",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=APPLE_ACCENT,
            fg_color=APPLE_ACCENT_SUBTLE,
            corner_radius=6,
            height=24,
        ).pack(side="right")

        resumo = item.get("resumo", "")
        if resumo:
            lbl_res = ctk.CTkLabel(
                card,
                text=resumo,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=APPLE_TEXT_SECONDARY,
                justify="left",
                anchor="w",
            )
            lbl_res.pack(fill="x", padx=16, pady=(0, 8))
            quebrar_na_largura(lbl_res, card, folga=32)

        passos = item.get("passos") or []
        if passos:
            linhas = "\n".join(f"{i}. {p}" for i, p in enumerate(passos, start=1))
            lbl_passos = ctk.CTkLabel(
                card,
                text=linhas,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=APPLE_TEXT_SECONDARY,
                justify="left",
                anchor="w",
            )
            lbl_passos.pack(fill="x", padx=16, pady=(0, 10))
            quebrar_na_largura(lbl_passos, card, folga=32)

        url = str(item.get("url_chaves", "") or "").strip()
        if item.get("env_var") == "GROQ_API_KEY":
            acoes = ctk.CTkFrame(card, fg_color="transparent")
            acoes.pack(fill="x", padx=16, pady=(0, 10))

            if url:
                Button(
                    acoes,
                    text="Abrir console.groq.com/keys",
                    variant="secondary",
                    command=lambda u=url: self._abrir_url_segura(u),
                ).pack(side="left", padx=(0, 8))

            self.btn_importar_env = Button(
                acoes,
                text="Importar .env",
                variant="secondary",
                command=self.importar_env,
            )
            self.btn_importar_env.pack(side="left", padx=(0, 8))

            self.btn_reverificar_cofre = Button(
                acoes,
                text="Reverificar Cofre / .env",
                variant="ghost",
                command=self.reverificar_cofre,
            )
            self.btn_reverificar_cofre.pack(side="left")

            linha_input = ctk.CTkFrame(card, fg_color="transparent")
            linha_input.pack(fill="x", padx=16, pady=(0, 8))
            linha_input.grid_columnconfigure(0, weight=1)

            self.entry_api_key = ctk.CTkEntry(
                linha_input,
                placeholder_text="Cole sua chave Groq aqui (gsk_...)",
                show="•",
                height=38,
                corner_radius=8,
                fg_color=APPLE_INPUT_BG,
                border_color=APPLE_INPUT_BORDER,
                border_width=1,
                text_color=APPLE_TEXT_PRIMARY,
            )
            self.entry_api_key.grid(row=0, column=0, sticky="ew", padx=(0, 8))

            self.btn_ver_key = ctk.CTkButton(
                linha_input,
                text="Ver",
                width=52,
                height=38,
                corner_radius=8,
                fg_color=APPLE_KEYCAP_BG,
                hover_color=APPLE_BG_HOVER,
                border_width=1,
                border_color=APPLE_KEYCAP_BORDER,
                text_color=APPLE_TEXT_PRIMARY,
                command=self._alternar_visibilidade_chave,
            )
            self.btn_ver_key.grid(row=0, column=1, padx=(0, 8))

            self.btn_validar_key = Button(
                linha_input,
                text="Validar e Salvar Chave",
                variant="primary",
                height=38,
                command=self.validar_e_salvar_chave,
            )
            self.btn_validar_key.grid(row=0, column=2)

            self.lbl_status_chave = ctk.CTkLabel(
                card,
                text="Cole sua chave acima e clique em Validar e Salvar Chave.",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                text_color=APPLE_TEXT_SECONDARY,
                justify="left",
                anchor="w",
            )
            self.lbl_status_chave.pack(fill="x", padx=16, pady=(0, 14))
            quebrar_na_largura(self.lbl_status_chave, card, folga=32)

    def _abrir_url_segura(self, url: str) -> None:
        if not url.startswith("https://"):
            return
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: abertura de navegador pelo SO
            print(f"[OnboardingTab] Erro ao abrir navegador: {e}", file=sys.stderr)
            self._definir_status_chave(f"Não foi possível abrir o navegador. Acesse {url}", ACCENT_RED)

    def _alternar_visibilidade_chave(self) -> None:
        self._mostrando_chave = not self._mostrando_chave
        self.entry_api_key.configure(show="" if self._mostrando_chave else "•")
        self.btn_ver_key.configure(text="Ocultar" if self._mostrando_chave else "Ver")

    def _definir_status_chave(self, texto: str, cor: Any) -> None:
        if hasattr(self, "lbl_status_chave") and self.lbl_status_chave.winfo_exists():
            self.lbl_status_chave.configure(text=texto, text_color=cor)

    def importar_env(self) -> bool:
        """Lê apenas GROQ_API_KEY de um arquivo .env escolhido pelo usuário sem copiá-lo."""
        caminho = filedialog.askopenfilename(
            title="Selecionar arquivo .env",
            filetypes=[("Arquivos env", ".env *.env *.txt"), ("Todos os arquivos", "*.*")],
        )
        if not caminho:
            return False
        try:
            valores = dotenv_values(caminho)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: leitura de .env externo selecionado
            self._definir_status_chave(f"Não consegui ler o arquivo selecionado ({type(e).__name__}).", ACCENT_RED)
            return False

        chave = (valores.get("GROQ_API_KEY") or "").strip()
        if not chave or chave == "sua_chave_aqui":
            self._definir_status_chave("Nenhuma GROQ_API_KEY válida encontrada nesse arquivo.", ACCENT_AMBER)
            return False

        self.entry_api_key.delete(0, "end")
        self.entry_api_key.insert(0, chave)
        self._chave_validada = False
        self._atualizar_botoes_navegacao()
        self._definir_status_chave("Chave importada do arquivo. Clique em Validar e Salvar Chave.", ACCENT_AMBER)
        return True

    def reverificar_cofre(self) -> bool:
        """Relê o cofre e o .env atual sem reiniciar o programa."""
        fn = self.callbacks.get("on_reload_api_key")
        encontrou = False
        erro_callback = False
        if fn:
            try:
                encontrou = bool(fn())
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback on_reload_api_key
                erro_callback = True
                print(f"[OnboardingTab] Erro ao reverificar cofre: {e}", file=sys.stderr)
        cfg = self._ler_settings()
        chave = (cfg.get("api_key") or "").strip()
        tem_chave = bool(chave and chave != "sua_chave_aqui")
        if not encontrou and (erro_callback or bool(cfg.get("cofre_ilegivel"))):
            texto = (
                "Não foi possível ler o cofre do Windows. O Willy continua com a chave que já estava em uso."
                if tem_chave
                else "Não foi possível ler o cofre do Windows. Cole a chave no campo e clique em Validar e Salvar Chave."
            )
            self._definir_status_chave(texto, ACCENT_RED)
            return False
        if encontrou and tem_chave:
            self.entry_api_key.delete(0, "end")
            self.entry_api_key.insert(0, chave)
            self._definir_status_chave(
                "Chave recuperada do cofre com sucesso. Você já pode validar ou continuar.",
                ACCENT_GREEN,
            )
            self._chave_validada = True
            self._atualizar_botoes_navegacao()
            return True
        self._definir_status_chave("Nenhuma chave encontrada ainda no cofre ou no arquivo .env.", ACCENT_AMBER)
        return False

    def validar_e_salvar_chave(self) -> None:
        """Valida a chave Groq na API real em segundo plano antes de gravá-la no cofre."""
        chave = self.entry_api_key.get().strip() if hasattr(self, "entry_api_key") else ""
        self._validando_chave = True
        if hasattr(self, "btn_validar_key"):
            self.btn_validar_key.configure(state="disabled", text="Validando...")
        self._definir_status_chave("Conectando à Groq para validar sua chave...", APPLE_TEXT_SECONDARY)
        self._agendar_dreno_ui()

        def _worker() -> None:
            cb = self.callbacks.get("on_validate_groq_key")
            if cb:
                try:
                    ok, msg, lat, info = cb(chave, salvar=True)
                except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback on_validate_groq_key
                    ok, msg, lat, info = False, f"Erro ao validar chave: {type(e).__name__}", 0.0, {}
            else:
                ok = bool(chave and chave != "sua_chave_aqui" and not any(c.isspace() for c in chave))
                msg = "Chave salva." if ok else "Informe uma chave Groq válida."
                lat, info = 0.0, {}
            if ok:
                # Atualiza a trava antes de devolver à UI para evitar condição de corrida com avancar_passo().
                self._chave_validada = True
            self._safe_after(0, self._aplicar_resultado_validacao, ok, msg, lat, info)

        threading.Thread(target=_worker, daemon=True).start()

    def _aplicar_resultado_validacao(self, ok: bool, msg: str, _lat: float, _info: dict[str, Any]) -> None:
        self._validando_chave = False
        if hasattr(self, "btn_validar_key") and self.btn_validar_key.winfo_exists():
            self.btn_validar_key.configure(state="normal", text="Validar e Salvar Chave")
        self._chave_validada = bool(ok)
        self._definir_status_chave(msg, ACCENT_GREEN if ok else ACCENT_RED)
        self._atualizar_botoes_navegacao()

    # -----------------------------------------------------------------
    # PASSO 2: MICROFONE
    # -----------------------------------------------------------------
    def _construir_passo_microfone(self, parent: Any) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        SectionHeader(frame, text="PASSO 2 · MICROFONE E GANHO").pack(fill="x", pady=(2, 6))

        card = self._novo_card(frame)
        ctk.CTkLabel(
            card,
            text="Dispositivo de entrada",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        self.combo_microfone = ctk.CTkOptionMenu(
            card,
            values=["Padrão do Sistema"],
            height=36,
            fg_color=APPLE_INPUT_BG,
            button_color=APPLE_KEYCAP_BG,
            button_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            command=self._ao_trocar_microfone,
        )
        self.combo_microfone.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            card,
            text="Sensibilidade do microfone",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(0, 4))

        self.seg_mic_gain = ctk.CTkSegmentedButton(
            card,
            values=list(_GANHOS_PADRAO.keys()),
            command=self._ao_trocar_ganho,
        )
        self.seg_mic_gain.set("1.0x (Padrão)")
        self.seg_mic_gain.pack(fill="x", padx=16, pady=(0, 12))

        self.switch_whisper_mode = ctk.CTkSwitch(
            card,
            text="Modo Sussurro (amplifica voz baixa mantendo o ganho confortável)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_PRIMARY,
            command=self._ao_trocar_whisper_mode,
        )
        self.switch_whisper_mode.pack(anchor="w", padx=16, pady=(0, 14))

        # Card do medidor ao vivo.
        card_teste = self._novo_card(frame)
        self.lbl_mic_info = ctk.CTkLabel(
            card_teste,
            text="Teste rápido de captação",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        )
        self.lbl_mic_info.pack(anchor="w", padx=16, pady=(14, 8))

        self.prog_mic_volume = ctk.CTkProgressBar(
            card_teste,
            height=10,
            corner_radius=5,
            progress_color=METER_OK,
            fg_color=BG_RECESSED,
        )
        self.prog_mic_volume.set(0.0)
        self.prog_mic_volume.pack(fill="x", padx=16, pady=(0, 8))

        self.lbl_diagnostico_mic = ctk.CTkLabel(
            card_teste,
            text="Clique abaixo e fale uma frase curta para confirmar que o microfone capta bem.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            justify="left",
            anchor="w",
        )
        self.lbl_diagnostico_mic.pack(fill="x", padx=16, pady=(0, 10))
        quebrar_na_largura(self.lbl_diagnostico_mic, card_teste, folga=32)

        self.btn_test_mic = Button(
            card_teste,
            text="Testar Microfone (4 segundos)",
            variant="secondary",
            command=self.iniciar_teste_mic,
        )
        self.btn_test_mic.pack(anchor="w", padx=16, pady=(0, 14))
        return frame

    def _salvar_parcial(self, dados: dict[str, Any]) -> None:
        fn = self.callbacks.get("on_save_settings")
        if not fn:
            return
        try:
            fn(dados)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: persistência parcial no onboarding
            print(f"[OnboardingTab] Erro ao salvar ajuste: {e}", file=sys.stderr)

    def _ao_trocar_microfone(self, escolha: str) -> None:
        self._salvar_parcial({"AUDIO_DEVICE": self._dev_map.get(escolha)})

    def _ao_trocar_ganho(self, escolha: str) -> None:
        self._salvar_parcial({"MIC_GAIN": _GANHOS_PADRAO.get(escolha, 1.0)})

    def _ao_trocar_whisper_mode(self) -> None:
        self._salvar_parcial({"WHISPER_MODE": bool(self.switch_whisper_mode.get())})

    def iniciar_teste_mic(self) -> None:
        """Mede o áudio ao vivo do microfone selecionado usando diagnostico compartilhado."""
        if self.mic_test_active:
            return
        self.mic_test_active = True
        self.btn_test_mic.configure(text="Captando áudio... (fale agora)")
        self.lbl_diagnostico_mic.configure(text="Medindo... fale normalmente.", text_color=APPLE_TEXT_SECONDARY)
        self._agendar_dreno_ui()

        def _run_meter() -> None:
            start = time.time()
            dev_idx = self._dev_map.get(self.combo_microfone.get())
            volumes: list[float] = []
            taxa_preferida = SAMPLE_RATE
            if self.callbacks.get("get_actual_sample_rate"):
                try:
                    taxa_preferida = self.callbacks["get_actual_sample_rate"]() or SAMPLE_RATE
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: sondagem da taxa atual
                    pass

            stream = None
            chosen_sr = taxa_preferida
            try:
                stream, chosen_sr = negociar_stream(dev_idx, None, 1, taxa_preferida)
            except Exception:  # noqa: BLE001 — fronteira defensiva: abertura do stream PortAudio
                stream = None

            if stream is not None:
                try:
                    chunk_size = int(chosen_sr * 0.05)
                    while time.time() - start < 4.0 and self.mic_test_active:
                        data, _ = stream.read(chunk_size)
                        vol = compute_rms(data)
                        volumes.append(vol)
                        piso = medir_teste(volumes)[0] if len(volumes) >= 6 else 0.0
                        self._safe_after(0, self.prog_mic_volume.set, nivel_acima_do_piso(vol, piso))
                        parcial = parcial_do_teste(volumes)
                        self._safe_after(0, lambda t=parcial: self.lbl_diagnostico_mic.configure(text=t))
                        time.sleep(0.04)
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: leitura de stream durante teste
                    pass
                finally:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:  # noqa: BLE001, S110 — fronteira defensiva: encerramento de stream PortAudio
                        pass

            self.mic_test_active = False
            if volumes:
                ok_res, texto = resumo_do_teste(volumes)
                cor = ACCENT_GREEN if ok_res else APPLE_TEXT_WARNING
            else:
                texto = "Não recebi áudio desse dispositivo. Tente escolher outro microfone acima."
                cor = ACCENT_RED

            def _finalizar() -> None:
                if self.prog_mic_volume.winfo_exists():
                    self.prog_mic_volume.set(0.0)
                if self.lbl_diagnostico_mic.winfo_exists():
                    self.lbl_diagnostico_mic.configure(text=texto, text_color=cor)
                if self.btn_test_mic.winfo_exists():
                    self.btn_test_mic.configure(text="Testar Microfone (4 segundos)")

            self._safe_after(0, _finalizar)

        threading.Thread(target=_run_meter, daemon=True).start()

    # -----------------------------------------------------------------
    # PASSO 3: ATALHOS E PREFERÊNCIAS
    # -----------------------------------------------------------------
    def _construir_passo_atalhos(self, parent: Any) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        SectionHeader(frame, text="PASSO 3 · ATALHOS E IDIOMA").pack(fill="x", pady=(2, 6))

        self.card_alerta_atalho = self._novo_card(frame)
        self.lbl_alerta_atalho = ctk.CTkLabel(
            self.card_alerta_atalho,
            text="Verificando atalhos do Windows...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_SECONDARY,
            justify="left",
            anchor="w",
        )
        self.lbl_alerta_atalho.pack(fill="x", padx=16, pady=12)
        quebrar_na_largura(self.lbl_alerta_atalho, self.card_alerta_atalho, folga=32)

        card_hk = self._novo_card(frame)
        essenciais = [
            ("VOICE_HOTKEY", "Ditado Rápido", "Segure ou toque para gravar e colar onde o cursor estiver."),
            ("MASTER_HOTKEY", "Copiar Seleção + Falar", "Lê o texto selecionado e transforma pelo seu comando de voz."),
            ("TRANSLATE_HOTKEY", "Traduzir para Inglês", "Fale em português para colar direto em inglês natural."),
        ]
        for idx, (env_key, titulo, desc) in enumerate(essenciais):
            row = ctk.CTkFrame(card_hk, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(12 if idx == 0 else 8, 12 if idx == len(essenciais) - 1 else 4))
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row,
                text=titulo,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                text_color=APPLE_TEXT_PRIMARY,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

            lbl_desc = ctk.CTkLabel(
                row,
                text=desc,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=APPLE_TEXT_SECONDARY,
                justify="left",
                anchor="w",
            )
            lbl_desc.grid(row=1, column=0, sticky="ew", padx=(0, 12))
            quebrar_na_largura(lbl_desc, row, folga=180)

            padrao = HOTKEYS_PADRAO.get(env_key, "")
            kc = Keycap(
                row,
                keys=padrao,
                editable=True,
                chave_propria=env_key,
                on_change=lambda nova, k=env_key: self._ao_trocar_atalho(k, nova),
            )
            kc.grid(row=0, column=1, rowspan=2, sticky="e")
            self._keycaps[env_key] = kc

        card_idioma = self._novo_card(frame)
        ctk.CTkLabel(
            card_idioma,
            text="Idioma de entrada do ditado",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 6))

        self.seg_input_lang = ctk.CTkSegmentedButton(
            card_idioma,
            values=list(_IDIOMAS_ENTRADA.keys()),
            selected_color=APPLE_ACCENT,
            selected_hover_color=APPLE_ACCENT_HOVER,
            unselected_color=APPLE_SEGMENT_BG,
            unselected_hover_color=APPLE_BG_HOVER,
            text_color=APPLE_TEXT_PRIMARY,
            command=self._ao_trocar_idioma,
        )
        self.seg_input_lang.set("🌐 Automático")
        self.seg_input_lang.pack(fill="x", padx=16, pady=(0, 6))

        self.lbl_idioma_desc = ctk.CTkLabel(
            card_idioma,
            text=_DESCRICOES_IDIOMA["auto"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            justify="left",
            anchor="w",
        )
        self.lbl_idioma_desc.pack(fill="x", padx=16, pady=(0, 14))
        quebrar_na_largura(self.lbl_idioma_desc, card_idioma, folga=32)

        card_auto = self._novo_card(frame)
        self.switch_autostart = ctk.CTkSwitch(
            card_auto,
            text="Iniciar o Willy automaticamente junto com o Windows",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_PRIMARY,
            command=self._ao_trocar_autostart,
        )
        self.switch_autostart.pack(anchor="w", padx=16, pady=14)
        return frame

    def _ao_trocar_atalho(self, env_key: str, nova_combinacao: str) -> None:
        self._salvar_parcial({env_key: nova_combinacao})
        self._atualizar_alerta_atalhos()

    def _ao_trocar_idioma(self, escolha: str) -> None:
        codigo = _IDIOMAS_ENTRADA.get(escolha, "auto")
        self._atualizar_descricao_idioma(codigo)
        self._salvar_parcial({"INPUT_LANGUAGE": codigo})

    def _atualizar_descricao_idioma(self, codigo: str) -> None:
        if hasattr(self, "lbl_idioma_desc") and self.lbl_idioma_desc.winfo_exists():
            self.lbl_idioma_desc.configure(text=_DESCRICOES_IDIOMA.get(codigo, _DESCRICOES_IDIOMA["auto"]))

    def _ao_trocar_autostart(self) -> None:
        fn = self.callbacks.get("on_toggle_autostart")
        if fn:
            try:
                fn(bool(self.switch_autostart.get()))
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: alternância de autostart no Windows
                print(f"[OnboardingTab] Erro ao alterar autostart: {e}", file=sys.stderr)

    def _atualizar_alerta_atalhos(self) -> None:
        falhas: dict[str, str] = {}
        fn = self.callbacks.get("get_hotkey_failures")
        if fn:
            try:
                falhas = fn() or {}
            except Exception:  # noqa: BLE001 — fronteira defensiva: consulta get_hotkey_failures
                falhas = {}

        if falhas:
            itens = ", ".join(f"{k} ({v})" for k, v in falhas.items())
            texto = f"Em uso por outro programa: {itens}. Clique em um atalho abaixo para trocar."
            cor: Any = APPLE_TEXT_WARNING
        else:
            texto = "Todos os atalhos principais estão livres e prontos no Windows."
            cor = APPLE_STATUS_ONLINE
        if hasattr(self, "lbl_alerta_atalho") and self.lbl_alerta_atalho.winfo_exists():
            self.lbl_alerta_atalho.configure(text=texto, text_color=cor)

    # -----------------------------------------------------------------
    # PASSO 4: PRIMEIRO DITADO GUIADO
    # -----------------------------------------------------------------
    def _construir_passo_ditado(self, parent: Any) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        SectionHeader(frame, text="PASSO 4 · TESTE SEU PRIMEIRO DITADO").pack(fill="x", pady=(2, 6))

        card = self._novo_card(frame)
        lbl_guia = ctk.CTkLabel(
            card,
            text=(
                "Clique no botão abaixo e diga uma frase natural (por exemplo: "
                "Olá Willy, hoje quero revisar minhas tarefas com tranquilidade). "
                "O resultado aparece aqui dentro sem colar em outra janela."
            ),
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_PRIMARY,
            justify="left",
            anchor="w",
        )
        lbl_guia.pack(fill="x", padx=16, pady=(14, 10))
        quebrar_na_largura(lbl_guia, card, folga=32)

        self.btn_testar_ditado = Button(
            card,
            text="Iniciar Ditado de Teste",
            variant="primary",
            height=36,
            command=self.testar_primeiro_ditado,
        )
        self.btn_testar_ditado.pack(anchor="w", padx=16, pady=(0, 10))

        self.prog_ditado = ctk.CTkProgressBar(
            card,
            height=8,
            corner_radius=4,
            progress_color=METER_OK,
            fg_color=BG_RECESSED,
        )
        self.prog_ditado.set(0.0)
        self.prog_ditado.pack(fill="x", padx=16, pady=(0, 8))

        self.lbl_status_ditado = ctk.CTkLabel(
            card,
            text="Aguardando você iniciar o teste.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            justify="left",
            anchor="w",
        )
        self.lbl_status_ditado.pack(fill="x", padx=16, pady=(0, 14))
        quebrar_na_largura(self.lbl_status_ditado, card, folga=32)

        # Caixas de resultado (bruto vs refinado).
        card_res = self._novo_card(frame)
        ctk.CTkLabel(
            card_res,
            text="Transcrição bruta (Whisper)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 2))

        self.lbl_ditado_bruto = ctk.CTkLabel(
            card_res,
            text="...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=APPLE_TEXT_TERTIARY,
            justify="left",
            anchor="w",
        )
        self.lbl_ditado_bruto.pack(fill="x", padx=16, pady=(0, 10))
        quebrar_na_largura(self.lbl_ditado_bruto, card_res, folga=32)

        ctk.CTkLabel(
            card_res,
            text="Texto refinado (pronto para colar)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(2, 2))

        self.lbl_ditado_refinado = ctk.CTkLabel(
            card_res,
            text="O texto polido pelo Willy aparecerá aqui.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14),
            text_color=APPLE_TEXT_PRIMARY,
            justify="left",
            anchor="w",
        )
        self.lbl_ditado_refinado.pack(fill="x", padx=16, pady=(0, 14))
        quebrar_na_largura(self.lbl_ditado_refinado, card_res, folga=32)
        return frame

    def testar_primeiro_ditado(self) -> None:
        """Executa captura curta, transcrição e refino de amostra dentro da tela de guia."""
        if self._ditado_ativo:
            if self._ditado_stop_event is not None:
                self._ditado_stop_event.set()
            if hasattr(self, "btn_testar_ditado"):
                self.btn_testar_ditado.configure(state="disabled", text="Transcrevendo...")
            return

        self._ditado_ativo = True
        self._ditado_stop_event = threading.Event()
        if hasattr(self, "btn_testar_ditado"):
            self.btn_testar_ditado.configure(state="normal", text="Parar e Transcrever")
        if hasattr(self, "lbl_status_ditado"):
            self.lbl_status_ditado.configure(
                text="Ouvindo agora... fale uma frase curta e clique em Parar ou aguarde o corte automático.",
                text_color=APPLE_ACCENT,
            )
        self._agendar_dreno_ui()

        stop_evt = self._ditado_stop_event

        def _on_level(nivel: float) -> None:
            self._safe_after(0, self.prog_ditado.set, max(0.0, min(1.0, float(nivel))))

        def _worker() -> None:
            fn = self.callbacks.get("on_test_dictation")
            if fn:
                try:
                    ok, bruto, refinado, erro = fn(stop_event=stop_evt, on_level=_on_level)
                except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback on_test_dictation
                    ok, bruto, refinado, erro = False, "", "", f"Falha no teste de ditado: {type(e).__name__}"
            else:
                ok, bruto, refinado, erro = False, "", "", "Teste de ditado indisponível neste modo."
            self._safe_after(0, self._aplicar_resultado_ditado, ok, bruto, refinado, erro)

        threading.Thread(target=_worker, daemon=True).start()

    def _aplicar_resultado_ditado(self, ok: bool, bruto: str, refinado: str, erro: str) -> None:
        self._ditado_ativo = False
        self._ditado_stop_event = None
        if hasattr(self, "prog_ditado") and self.prog_ditado.winfo_exists():
            self.prog_ditado.set(0.0)
        if hasattr(self, "btn_testar_ditado") and self.btn_testar_ditado.winfo_exists():
            self.btn_testar_ditado.configure(state="normal", text="Testar Novamente")

        if ok:
            if hasattr(self, "lbl_ditado_bruto") and self.lbl_ditado_bruto.winfo_exists():
                self.lbl_ditado_bruto.configure(text=bruto or "(sem texto bruto)", text_color=APPLE_TEXT_SECONDARY)
            if hasattr(self, "lbl_ditado_refinado") and self.lbl_ditado_refinado.winfo_exists():
                self.lbl_ditado_refinado.configure(text=refinado or bruto, text_color=APPLE_TEXT_PRIMARY)
            if hasattr(self, "lbl_status_ditado") and self.lbl_status_ditado.winfo_exists():
                self.lbl_status_ditado.configure(
                    text="Tudo funcionando! Clique em Concluir para começar a usar em qualquer aplicativo.",
                    text_color=ACCENT_GREEN,
                )
        else:
            if hasattr(self, "lbl_status_ditado") and self.lbl_status_ditado.winfo_exists():
                self.lbl_status_ditado.configure(
                    text=erro or "Não capturei áudio suficiente para transcrever.",
                    text_color=ACCENT_RED,
                )

    # -----------------------------------------------------------------
    # NAVEGAÇÃO E SINCRONIZAÇÃO
    # -----------------------------------------------------------------
    def _interromper_capturas_ativas(self) -> None:
        self.mic_test_active = False
        if self._ditado_stop_event is not None:
            self._ditado_stop_event.set()

    def ir_para_passo(self, indice: int) -> None:
        if indice < 0 or indice >= len(self._frames_passos):
            return
        if indice > 0 and not self._chave_validada and indice not in self._passos_visitados:
            self._definir_status_chave("Valide sua chave Groq antes de avançar para o próximo passo.", ACCENT_AMBER)
            return
        self._interromper_capturas_ativas()
        self.passo_atual = indice
        self._passos_visitados.add(indice)
        if indice == 2:
            self._atualizar_alerta_atalhos()
        self._atualizar_passo_ui()

    def avancar_passo(self) -> None:
        if self.passo_atual == 0 and not self._chave_validada:
            self._definir_status_chave("Valide sua chave Groq antes de avançar.", ACCENT_AMBER)
            return
        if self.passo_atual >= len(self._frames_passos) - 1:
            self.concluir_onboarding()
            return
        self.ir_para_passo(self.passo_atual + 1)

    def voltar_passo(self) -> None:
        if self.passo_atual > 0:
            self.ir_para_passo(self.passo_atual - 1)

    def _atualizar_passo_ui(self) -> None:
        for i, frame in enumerate(self._frames_passos):
            if i == self.passo_atual:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_forget()

        for i, btn in enumerate(self._botoes_passos):
            titulo = _TITULOS_PASSOS[i][0]
            if i == self.passo_atual:
                btn.configure(
                    text=titulo,
                    fg_color=APPLE_ACCENT_SUBTLE,
                    text_color=APPLE_ACCENT,
                )
            elif i < self.passo_atual:
                btn.configure(
                    text=f"✓ {titulo}",
                    fg_color="transparent",
                    text_color=ACCENT_GREEN,
                )
            else:
                btn.configure(
                    text=titulo,
                    fg_color="transparent",
                    text_color=APPLE_TEXT_SECONDARY,
                )

        self._atualizar_botoes_navegacao()

    def _atualizar_botoes_navegacao(self) -> None:
        if hasattr(self, "btn_voltar"):
            self.btn_voltar.configure(state="normal" if self.passo_atual > 0 else "disabled")
        if hasattr(self, "btn_continuar"):
            if self.passo_atual >= len(self._frames_passos) - 1:
                self.btn_continuar.configure(state="normal", text="Concluir e Abrir Histórico")
            elif self.passo_atual == 0 and not self._chave_validada:
                self.btn_continuar.configure(state="disabled", text="Continuar")
            else:
                self.btn_continuar.configure(state="normal", text="Continuar")

    def recarregar_dados(self, cfg: dict[str, Any] | None = None) -> None:
        """Sincroniza campos de chave, microfone, ganho e atalhos com a config atual."""
        settings = cfg if cfg is not None else self._ler_settings()
        chave = (settings.get("api_key") or "").strip()
        if hasattr(self, "entry_api_key") and chave and chave != "sua_chave_aqui":
            if not self.entry_api_key.get().strip():
                self.entry_api_key.insert(0, chave)
            self._chave_validada = True
            self._definir_status_chave("Chave configurada. Você pode revalidar ou avançar.", ACCENT_GREEN)

        fn_devs = self.callbacks.get("get_audio_devices")
        if fn_devs and hasattr(self, "combo_microfone"):
            try:
                devs = fn_devs() or []
            except Exception:  # noqa: BLE001 — fronteira defensiva: sondagem de dispositivos de entrada
                devs = []
            self._dev_map = {"Padrão do Sistema": None}
            opcoes = ["Padrão do Sistema"]
            ativo = settings.get("audio_device")
            selecionado = "Padrão do Sistema"
            for idx, nome in devs:
                rotulo = f"{nome[:38]} (ID {idx})" if len(nome) > 38 else f"{nome} (ID {idx})"
                self._dev_map[rotulo] = idx
                opcoes.append(rotulo)
                if ativo == idx:
                    selecionado = rotulo
            self.combo_microfone.configure(values=opcoes)
            self.combo_microfone.set(selecionado)

        if hasattr(self, "seg_mic_gain"):
            ganho = float(settings.get("mic_gain", 1.0))
            rotulo = next((k for k, v in _GANHOS_PADRAO.items() if abs(v - ganho) < 0.05), "1.0x (Padrão)")
            self.seg_mic_gain.set(rotulo)

        if hasattr(self, "switch_whisper_mode"):
            if settings.get("whisper_mode", False):
                self.switch_whisper_mode.select()
            else:
                self.switch_whisper_mode.deselect()

        for env_key, kc in self._keycaps.items():
            combo = settings.get(env_key.lower(), settings.get(env_key, HOTKEYS_PADRAO.get(env_key, "")))
            if combo:
                kc.set_keys(combo)

        if hasattr(self, "seg_input_lang"):
            idioma = str(settings.get("input_language", "auto") or "auto").strip().lower()
            if idioma not in _ROTULO_POR_IDIOMA:
                idioma = "auto"
            self.seg_input_lang.set(_ROTULO_POR_IDIOMA[idioma])
            self._atualizar_descricao_idioma(idioma)

        if hasattr(self, "switch_autostart"):
            if settings.get("autostart", False):
                self.switch_autostart.select()
            else:
                self.switch_autostart.deselect()

        self._atualizar_alerta_atalhos()
        self._atualizar_botoes_navegacao()

    def pular_onboarding(self) -> None:
        """Dispensa o guia inicial gravando conclusão e abrindo o Histórico."""
        self.concluir_onboarding()

    def concluir_onboarding(self) -> None:
        """Finaliza o guia inicial e aciona o callback de transição para o Histórico."""
        self._interromper_capturas_ativas()
        fn = self.callbacks.get("on_complete_onboarding")
        if fn:
            try:
                fn(abrir_aba="history")
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback on_complete_onboarding
                print(f"[OnboardingTab] Erro ao concluir onboarding: {e}", file=sys.stderr)


def build_tab_onboarding(parent: Any, callbacks: dict[str, Callable] | None = None) -> OnboardingTab:
    """Constrói e devolve a aba de guia inicial (Onboarding)."""
    return OnboardingTab(parent, callbacks=callbacks)
