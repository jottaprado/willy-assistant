"""
Módulo de Ícone e Menu na Bandeja do Sistema (System Tray) do Willy.
Utiliza pystray com ícones dinâmicos de alta resolução e menu contextual completo.
"""

import os
import sys
from collections.abc import Callable
from typing import Any

import pystray
from PIL import Image, ImageDraw

from core import modelos_llm
from ui.components.copia import copiar_pelo_clique
from ui.theme import (
    BANDEJA_MIC_ATIVO,
    BANDEJA_MIC_INATIVO,
    BANDEJA_SUPORTE_ATIVO,
    BANDEJA_SUPORTE_INATIVO,
    diretorios_de_assets,
)


class TrayManager:
    """Gerencia o ícone e menu contextual na bandeja do Windows."""

    def __init__(self, callbacks: dict[str, Callable], base_dir: str,
                 modo_privado_getter: Callable[[], bool] | None = None):
        self.callbacks = callbacks
        # Lido a cada cópia: o modo privado muda com o Willy aberto. Sem ele, conta como
        # ligado (o texto não vai para o histórico do Win+V).
        self._modo_privado = modo_privado_getter or (lambda: True)
        self.base_dir = base_dir
        self.icon: pystray.Icon | None = None

    def get_icon_image(self, active: bool = True) -> Image.Image:
        """Carrega o ícone do robô Willy (colorido se acordado, cinza translúcido se dormindo)."""
        nome_img = "willy_robot.png" if active else "willy_robot_sleeping.png"

        candidates: list[str] = []
        for raiz in diretorios_de_assets(base_dir=self.base_dir):
            candidates.append(os.path.join(raiz, "assets", nome_img))
            candidates.append(os.path.join(raiz, nome_img))

        for path in candidates:
            if os.path.exists(path):
                try:
                    with Image.open(path) as raw_img:
                        img = raw_img.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
                    return img
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: pystray.Icon.stop no encerramento
                    pass

        # Fallback desenhado se a imagem não for encontrada
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cor_mic = BANDEJA_MIC_ATIVO if active else BANDEJA_MIC_INATIVO
        cor_suporte = BANDEJA_SUPORTE_ATIVO if active else BANDEJA_SUPORTE_INATIVO

        d.ellipse((22, 10, 42, 34), fill=cor_mic)
        d.rectangle((26, 22, 38, 40), fill=cor_mic)
        d.arc((14, 20, 50, 44), 0, 180, fill=cor_suporte, width=4)
        d.line((32, 44, 32, 54), fill=cor_suporte, width=4)
        d.line((20, 54, 44, 54), fill=cor_suporte, width=4)
        return img

    def build_menu(self, is_awake: bool, refine_enabled: bool,
                   silent_mode: bool, pill_pos: str,
                   hotkey: str, trans_hotkey: str, master_hotkey: str, meeting_hotkey: str,
                    llm_model: str, history_items: list[dict[str, Any]],
                    prompt_hotkey: str = "ctrl+alt+p",
                    auto_silence: bool = True,
                    pendentes: int = 0,
                    trans_es_hotkey: str = "") -> pystray.Menu:
        """Constrói a estrutura dinâmica do menu contextual da bandeja.

        `pendentes` é o tamanho da fila de áudios à espera de reenvio.
        """
        status_texto = "🎙️ Willy (ATIVO)" if is_awake else "💤 Willy (DORMINDO)"
        acao_toggle = "💤 Colocar Willy para dormir" if is_awake else "✨ Acordar Willy"

        marcador_ia = "✓" if refine_enabled else " "
        marcador_silencioso = "✓" if silent_mode else " "
        desc_modo_envio = "⚡ Automático (Silêncio)" if auto_silence else "🛑 Manual (Toggle)"

        menu_posicoes = [
            pystray.MenuItem(
                f"{'●' if pill_pos == 'centro_inferior' else '○'} Rodapé Central (Padrão)",
                lambda: self._call("on_set_position", "centro_inferior")
            ),
            pystray.MenuItem(
                f"{'●' if pill_pos == 'topo' else '○'} Topo da Tela",
                lambda: self._call("on_set_position", "topo")
            ),
            pystray.MenuItem(
                f"{'●' if pill_pos == 'seguir_cursor' else '○'} Seguir Cursor do Mouse",
                lambda: self._call("on_set_position", "seguir_cursor")
            ),
        ]

        menu_modelos = [
            pystray.MenuItem(
                f"{'●' if llm_model == modelos_llm.FLASH else '○'} ⚡ Flash / Ultra-Fast (GPT-OSS 20B)",
                lambda: self._call("on_set_model", modelos_llm.FLASH)
            ),
            pystray.MenuItem(
                f"{'●' if llm_model == modelos_llm.SMART else '○'} 🧠 Smart / Equilibrado (GPT-OSS 120B)",
                lambda: self._call("on_set_model", modelos_llm.SMART)
            ),
            pystray.MenuItem(
                f"{'●' if llm_model == modelos_llm.CODER else '○'} 💻 Coder / Resumos (Qwen 3.8 27B)",
                lambda: self._call("on_set_model", modelos_llm.CODER)
            ),
        ]

        itens = [
            pystray.MenuItem("🖥️ Abrir Painel do Willy", lambda: self._call("on_open_dashboard"), default=True),
        ]
        if pendentes:
            # A pílula só aceita o clique de reenvio por 5,5 s: daqui, a fila fica ao alcance sempre.
            itens.append(pystray.MenuItem(f"🔁 Reenviar áudio salvo ({pendentes})",
                                          lambda: self._call("on_retry_audio")))
        itens += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(status_texto, None, enabled=False),
            pystray.MenuItem(f"{acao_toggle} ({master_hotkey})", lambda: self._call("on_toggle_sleep")),
            pystray.MenuItem(f"⌨️ Falar em Português: {hotkey}", None, enabled=False),
            pystray.MenuItem(f"🌐 Falar ➔ Inglês: {trans_hotkey}", None, enabled=False),
            *([pystray.MenuItem(f"🌐 Falar ➔ Espanhol: {trans_es_hotkey}", None, enabled=False)]
              if trans_es_hotkey else []),
            pystray.MenuItem(f"🎙️ Modo Reunião (Ata): {meeting_hotkey}", lambda: self._call("on_toggle_meeting")),
            pystray.MenuItem(f"🎯 Prompt de Agente (/goal): {prompt_hotkey}", lambda: self._call("on_toggle_prompt")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"🎙️ Envio de Ditado: {desc_modo_envio}", lambda: self._call("on_toggle_auto_silence")),
            pystray.MenuItem(f"[{marcador_ia}] Polimento de Prompt com IA", lambda: self._call("on_toggle_refine")),
            pystray.MenuItem("⚡ Modelo de IA (LLM)", pystray.Menu(*menu_modelos)),
            pystray.MenuItem(f"[{marcador_silencioso}] Modo Silencioso (Sem bipes)", lambda: self._call("on_toggle_silent")),
            pystray.MenuItem("🎯 Posição da Pílula", pystray.Menu(*menu_posicoes)),
            pystray.MenuItem("📝 Editar vocabulário / jargões", lambda: self._call("on_open_vocab")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📋 PROMPTS RECENTES (clique para copiar):", None, enabled=False),
        ]

        if history_items:
            for p in reversed(history_items[-5:]):
                texto_p = p.get("text", "") if isinstance(p, dict) else str(p)
                resumo = texto_p if len(texto_p) <= 36 else texto_p[:33] + "..."
                itens.append(pystray.MenuItem(f"  • {resumo}", self._acao_copiar(texto_p)))
        else:
            itens.append(pystray.MenuItem("  (Willy ainda não anotou nada)", None, enabled=False))

        itens.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📁 Abrir Pasta de Arquivos (Documentos\\Willy)", lambda: self._call("on_open_outputs")),
            pystray.MenuItem("⚙️ Abrir pasta de configuração (AppData)", lambda: self._call("on_open_folder")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Fechar Willy por completo (Sair)", lambda: self._call("on_exit"))
        ])

        return pystray.Menu(*itens)

    def _call(self, name: str, *args):
        if self.callbacks.get(name):
            try:
                self.callbacks[name](*args)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: pystray notify/update na bandeja do Windows
                print(f"[TrayManager] Erro no callback {name!r}: {e}", file=sys.stderr)

    def _acao_copiar(self, texto: str) -> Callable[[], None]:
        """Ação de menu, sem argumentos, que copia o texto COMPLETO.

        O pystray escolhe os argumentos pela contagem do __code__, e o default conta:
        `lambda _, t=texto:` tem dois, ele passava (icon, item), e `t` virava o MenuItem. A
        cópia levava o rótulo truncado (" • hello...") em vez do prompt.
        """
        return lambda: self._copiar_prompt(texto)

    def _copiar_prompt(self, texto: str):
        try:
            # O clique da pessoa vai para o Win+V, a não ser no modo privado.
            if not copiar_pelo_clique(texto, self._modo_privado()):
                if self.icon:
                    self.icon.notify("O clipboard está ocupado por outro programa.", "Willy não copiou")
                return
            if self.callbacks.get("on_copied"):
                self.callbacks["on_copied"]()
            if self.icon:
                self.icon.notify("Prompt copiado para a área de transferência!", "Willy copiou! 📋")
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: pystray notify/update na bandeja do Windows
            print(f"[TrayManager] Erro ao copiar prompt recente: {e}", file=sys.stderr)

    def notify(self, title: str, message: str) -> None:
        """Exibe uma notificação nativa da bandeja do sistema."""
        try:
            if self.icon:
                self.icon.notify(message, title)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: pystray.Icon.notify pode falhar sem shell ativo
            pass

    def update(self, is_awake: bool, refine_enabled: bool,
               silent_mode: bool, pill_pos: str,
               hotkey: str, trans_hotkey: str, master_hotkey: str,
               meeting_hotkey: str, llm_model: str,
               history_items: list[dict[str, Any]],
               prompt_hotkey: str = "ctrl+alt+p",
               auto_silence: bool = True,
               pendentes: int = 0,
               trans_es_hotkey: str = "") -> None:
        """Atualiza a aparência e opções do menu da bandeja."""
        if not self.icon:
            return
        try:
            self.icon.menu = self.build_menu(
                is_awake, refine_enabled, silent_mode, pill_pos,
                hotkey, trans_hotkey, master_hotkey, meeting_hotkey,
                llm_model, history_items,
                prompt_hotkey=prompt_hotkey,
                auto_silence=auto_silence,
                pendentes=pendentes,
                trans_es_hotkey=trans_es_hotkey,
            )
            self.icon.icon = self.get_icon_image(active=is_awake)
            self.icon.title = f"Willy ({'Ativo' if is_awake else 'Dormindo'})"
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: pystray notify/update na bandeja do Windows
            print(f"[TrayManager] Erro ao atualizar bandeja: {e}", file=sys.stderr)

    def start(self, on_ready: Callable | None = None) -> None:
        """Inicializa o ícone da bandeja."""
        img = self.get_icon_image(active=True)
        self.icon = pystray.Icon("Willy", img, "Willy (Ativo)")

        def _setup(icon) -> None:
            # O pystray só torna o ícone visível sozinho quando setup=None. Com setup próprio,
            # o ícone nunca aparecia, e o X do dashboard mandava "sair pela bandeja".
            icon.visible = True
            if on_ready:
                on_ready(icon)

        self.icon.run(setup=_setup)

    def stop(self) -> None:
        """Finaliza e remove o ícone da bandeja."""
        if self.icon:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: pystray.Icon.stop no encerramento
                pass
            self.icon = None
