"""
Módulo da Aba de Diagnósticos & Hardware do Willy Dashboard.
Redesenhado no estilo minimalista e sofisticado inspirado na Apple (macOS HIG, Raycast, Things 3).
"""

import threading
import time
from collections.abc import Callable
from typing import Any

import customtkinter as ctk
import sounddevice as sd

from core.audio import SAMPLE_RATE, negociar_stream
from core.audio_processing.diagnostico import (
    medir_teste,
    nivel_acima_do_piso,
    parcial_do_teste,
    resumo_do_teste,
)
from core.audio_processing.vad import compute_rms
from ui.components import (
    Button,
    PageHeader,
    SectionHeader,
)
from ui.theme import (
    APPLE_BG_CARD,
    APPLE_DESTRUCTIVE,
    APPLE_SEPARATOR,
    APPLE_STATUS_ONLINE,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    BG_RECESSED,
    FONT_FAMILY,
    METER_OK,
    RADIUS_CARD,
    SCROLLBAR_COLOR,
    SCROLLBAR_HOVER,
)


class DiagnosticsTab(ctk.CTkScrollableFrame):
    """Componente modular da Aba de Diagnóstico e Testes de Hardware."""

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
        self.mic_test_active = False
        self.grid_columnconfigure(0, weight=1)

        self._construir_ui()

    def _safe_after(self, delay_ms: int, func: Callable, *args):
        """Despacha com segurança para a thread de UI evitando exceções se destruído."""
        try:
            if self.winfo_exists():
                self.after(delay_ms, func, *args)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: sondagem de dispositivos e after Tkinter
            pass

    def _construir_ui(self):
        # 1. Cabeçalho Unificado da Página
        self.page_header = PageHeader(
            self,
            title="Diagnósticos",
            subtitle="Monitore a entrada do microfone e teste a velocidade de resposta com a nuvem.",
        )
        self.page_header.pack(fill="x", pady=(0, 10))

        # -------------------------------------------------------------
        # SEÇÃO 1: ENTRADA DE ÁUDIO
        # -------------------------------------------------------------
        sec_audio = SectionHeader(self, text="ENTRADA DE ÁUDIO")
        sec_audio.pack(fill="x", pady=(10, 4))

        lbl_desc_mic = ctk.CTkLabel(
            self,
            text="Monitore o nível de captação e sensibilidade do dispositivo selecionado:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        lbl_desc_mic.pack(anchor="w", pady=(0, 8))

        # Card de Áudio Estilo macOS HIG
        card_audio = ctk.CTkFrame(
            self,
            fg_color=APPLE_BG_CARD,
            border_width=1,
            border_color=APPLE_SEPARATOR,
            corner_radius=RADIUS_CARD,
        )
        card_audio.pack(fill="x", pady=(0, 20))

        self.lbl_mic_info = ctk.CTkLabel(
            card_audio,
            text=f"Dispositivo selecionado: {self._nome_do_microfone()}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        )
        self.lbl_mic_info.pack(anchor="w", padx=16, pady=(16, 8))

        self.prog_volume = ctk.CTkProgressBar(
            card_audio,
            height=10,
            corner_radius=5,
            progress_color=METER_OK,
            fg_color=BG_RECESSED,
        )
        self.prog_volume.set(0.0)
        self.prog_volume.pack(fill="x", padx=16, pady=(4, 8))

        self.lbl_diagnostico = ctk.CTkLabel(
            card_audio,
            text="Fale normalmente durante o teste: o Willy mede o ruído ambiente e a sua voz.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_diagnostico.pack(anchor="w", padx=16, pady=(0, 10))

        self.btn_test_mic = Button(
            card_audio,
            text="Testar Nível de Volume (5 segundos)",
            variant="secondary",
            command=self.iniciar_teste_mic,
        )
        self.btn_test_mic.pack(anchor="w", padx=16, pady=(0, 16))

        # -------------------------------------------------------------
        # SEÇÃO 2: CONEXÃO COM A NUVEM
        # -------------------------------------------------------------
        sec_rede = SectionHeader(self, text="CONEXÃO COM A NUVEM")
        sec_rede.pack(fill="x", pady=(10, 4))

        lbl_desc_groq = ctk.CTkLabel(
            self,
            text="Mede o tempo real de resposta (latência) entre seu computador e a API da Groq:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        lbl_desc_groq.pack(anchor="w", pady=(0, 8))

        # Card de Rede Estilo macOS HIG
        card_rede = ctk.CTkFrame(
            self,
            fg_color=APPLE_BG_CARD,
            border_width=1,
            border_color=APPLE_SEPARATOR,
            corner_radius=RADIUS_CARD,
        )
        card_rede.pack(fill="x", pady=(0, 24))

        self.lbl_status_groq = ctk.CTkLabel(
            card_rede,
            text="Clique abaixo para verificar a latência.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_status_groq.pack(anchor="w", padx=16, pady=(16, 12))

        self.btn_test_groq = Button(
            card_rede,
            text="Medir Latência da API",
            variant="secondary",
            command=self.testar_groq_api,
        )
        self.btn_test_groq.pack(anchor="w", padx=16, pady=(0, 16))

    def _microfone_dos_ajustes(self) -> int | None:
        if self.callbacks.get("get_settings"):
            try:
                return self.callbacks["get_settings"]().get("audio_device")
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callback e abertura de stream de teste
                pass
        return None

    def _nome_do_microfone(self) -> str:
        """O microfone escolhido nos Ajustes. A aba mostrava o padrão do Windows, que pode não ser
        o que o Willy grava."""
        indice = self._microfone_dos_ajustes()
        try:
            if indice is not None:
                return sd.query_devices(indice).get("name", f"Dispositivo {indice}")
            return f"{sd.query_devices(kind='input').get('name', 'Microfone')} (padrão do Windows)"
        except Exception:  # noqa: BLE001 — fronteira defensiva: sondagem de dispositivos e after Tkinter
            return "Microfone padrão do Windows" if indice is None else f"Dispositivo {indice} (indisponível)"

    def atualizar_microfone(self) -> None:
        """Relê o microfone dos Ajustes: ao abrir a aba e quando os Ajustes mudam."""
        try:
            self.lbl_mic_info.configure(text=f"Dispositivo selecionado: {self._nome_do_microfone()}")
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: sondagem de dispositivos e after Tkinter
            pass

    def iniciar_teste_mic(self):
        """Inicia teste de áudio do microfone com negociação de taxa de amostragem."""
        if self.mic_test_active:
            return
        self.mic_test_active = True
        self.btn_test_mic.configure(text="Captando áudio... (fale agora)")

        self.atualizar_microfone()
        self.lbl_diagnostico.configure(text="Medindo... fale normalmente.", text_color=APPLE_TEXT_SECONDARY)

        def run_meter():
            start = time.time()
            dev_idx = self._microfone_dos_ajustes()
            volumes = []

            taxa_preferida = SAMPLE_RATE
            if self.callbacks.get("get_actual_sample_rate"):
                try:
                    taxa_preferida = self.callbacks["get_actual_sample_rate"]() or SAMPLE_RATE
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: leitura de stream e atualização de UI
                    pass

            stream = None
            chosen_sr = taxa_preferida
            try:
                stream, chosen_sr = negociar_stream(dev_idx, None, 1, taxa_preferida)
            except Exception:  # noqa: BLE001 — fronteira defensiva: callback e abertura de stream de teste
                stream = None

            if stream is not None:
                try:
                    chunk_size = int(chosen_sr * 0.05)  # ~50ms
                    while time.time() - start < 5.0 and self.mic_test_active:
                        data, _ = stream.read(chunk_size)
                        vol = compute_rms(data)
                        volumes.append(vol)
                        # Acima do piso medido até aqui: na C920 (ruído ~0,032), o volume / 0,05 de
                        # antes deixava a barra pela metade em silêncio.
                        piso = medir_teste(volumes)[0] if len(volumes) >= 6 else 0.0
                        self._safe_after(0, self.prog_volume.set, nivel_acima_do_piso(vol, piso))
                        texto_parcial = parcial_do_teste(volumes)
                        self._safe_after(0, lambda texto=texto_parcial: self.lbl_diagnostico.configure(text=texto))
                        time.sleep(0.04)
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: leitura de stream e atualização de UI
                    pass
                finally:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:  # noqa: BLE001, S110 — fronteira defensiva: close de stream PortAudio
                        pass

            self.mic_test_active = False
            if volumes:
                resumo, pronto = resumo_do_teste(volumes)
            elif stream is None:
                resumo, pronto = "Não consegui abrir o microfone: confira o dispositivo nos Ajustes.", False
            else:
                resumo, pronto = "O teste foi interrompido antes de medir.", False

            def _reset_mic_ui():
                try:
                    self.prog_volume.set(0.0)
                    self.btn_test_mic.configure(
                        text="Testar Nível de Volume (5 segundos)",
                    )
                    self.lbl_diagnostico.configure(
                        text=resumo, text_color=APPLE_STATUS_ONLINE if pronto else APPLE_DESTRUCTIVE)
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: leitura de stream e atualização de UI
                    pass

            self._safe_after(0, _reset_mic_ui)

        threading.Thread(target=run_meter, daemon=True).start()

    def _modelo_groq_configurado(self) -> str:
        if self.callbacks.get("get_settings"):
            try:
                modelo = self.callbacks["get_settings"]().get("llm_model")
                if modelo:
                    return str(modelo)
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callback e abertura de stream de teste
                pass
        return "Groq Cloud"

    def testar_groq_api(self):
        """Mede a latência da API da Groq Cloud e atualiza o feedback visual."""
        self.btn_test_groq.configure(text="Conectando à Groq...")
        self.lbl_status_groq.configure(text="Enviando pacote de diagnóstico...", text_color=APPLE_TEXT_SECONDARY)

        def ping():
            resultado = None
            if self.callbacks.get("on_ping_groq"):
                try:
                    resultado = self.callbacks["on_ping_groq"]()
                except Exception as ping_err:  # noqa: BLE001 — fronteira defensiva: callback on_ping_groq
                    resultado = (False, str(ping_err), 0)

            def _update_groq_ui():
                try:
                    if resultado:
                        ok, msg, ms = resultado
                        if ok:
                            self.lbl_status_groq.configure(
                                text=f"Conexão ativa · Latência: {ms:.0f} ms ({self._modelo_groq_configurado()})",
                                text_color=APPLE_STATUS_ONLINE,
                            )
                        else:
                            self.lbl_status_groq.configure(
                                text=f"Falha de conexão: {msg}",
                                text_color=APPLE_DESTRUCTIVE,
                            )
                    self.btn_test_groq.configure(text="Medir Latência da API")
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: leitura de stream e atualização de UI
                    pass

            self._safe_after(0, _update_groq_ui)

        threading.Thread(target=ping, daemon=True).start()


def build_tab_diagnostics(parent: Any, callbacks: dict[str, Callable] | None = None) -> DiagnosticsTab:
    """Função fábrica modular para construir e retornar a Aba de Diagnósticos."""
    return DiagnosticsTab(parent, callbacks=callbacks)
