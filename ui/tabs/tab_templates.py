"""
Módulo da Aba de Templates & Snippets de Voz do Willy Dashboard.
Redesenhado no estilo minimalista e sofisticado inspirado na Apple (macOS HIG, Raycast, Things 3).
"""

import inspect
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from core.text_processing import normalize_for_search
from ui.components import (
    Button,
    EmptyState,
    PageHeader,
    SearchField,
    confirmar_exclusao,
    quebrar_na_largura,
)
from ui.theme import (
    APPLE_BG_APP,
    APPLE_BG_CARD_HOVER,
    APPLE_DESTRUCTIVE,
    APPLE_INPUT_BG,
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    FONT_FAMILY,
    RADIUS_INPUT,
    SCROLLBAR_COLOR,
    SCROLLBAR_HOVER,
)


def _aceita_old_trigger(gravar: Callable | None) -> bool:
    """O on_save_snippet sabe renomear no lugar? O SnippetManager.save_snippet ganhou o
    parâmetro old_trigger; sem ele (antes do Bloco 7A, ou num callback de 3 argumentos), a
    troca de gatilho grava o novo e apaga o antigo."""
    if gravar is None:
        return False
    try:
        return "old_trigger" in inspect.signature(gravar).parameters
    except (TypeError, ValueError):
        return False


class TemplatesTab(ctk.CTkScrollableFrame):
    """Componente modular da Aba de Templates e Snippets de Voz."""

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

        self._construir_ui()

    def _safe_after(self, delay_ms: int, func: Callable, *args):
        """Despacha com segurança para a thread de UI evitando exceções se o widget for destruído."""
        if self.callbacks.get("safe_dispatch_ui"):
            try:
                self.callbacks["safe_dispatch_ui"](func, *args, delay_ms=delay_ms)
                return
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callbacks e teardown de widgets/modal Tkinter
                pass
        try:
            if self.winfo_exists():
                self.after(delay_ms, func, *args)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: geometria e after da janela Tkinter
            pass

    def _construir_ui(self):
        # 1. Cabeçalho da Página Unificado (Único botão primary da tela)
        self.page_header = PageHeader(
            self,
            title="Templates",
            subtitle="Gatilhos de voz para inserção de blocos estruturados de texto.",
        )
        self.page_header.pack(fill="x", pady=(0, 14))

        self.btn_novo_snippet = self.page_header.add_action(
            "+ Novo template",
            variant="primary",
            command=lambda: self.abrir_modal_snippet(),
        )

        # 2. Campo de Busca com componente SearchField compartilhado
        self.search_field = SearchField(
            self,
            placeholder="Filtrar templates por gatilho ou título...",
            on_change=lambda t: self.atualizar_lista_templates(),
        )
        self.search_field.pack(fill="x", pady=(0, 12))
        self.entry_busca_snippets = self.search_field.entry

        # 3. Container dos cartões de template
        self.scroll_snippets = ctk.CTkFrame(self, fg_color="transparent")
        self.scroll_snippets.pack(fill="both", expand=True, pady=(0, 10))
        self.scroll_snippets.grid_columnconfigure(0, weight=1)

        self.atualizar_lista_templates()

    def atualizar_lista_templates(self):
        """Atualiza a lista visual de templates cadastrados aplicando eventuais filtros de busca."""
        for w in self.scroll_snippets.winfo_children():
            try:
                w.destroy()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callbacks e teardown de widgets/modal Tkinter
                pass

        snippets: list[dict[str, Any]] = []
        if self.callbacks.get("get_snippets"):
            try:
                raw = self.callbacks["get_snippets"]() or []
                if isinstance(raw, dict):
                    snippets = [
                        v if isinstance(v, dict) else {"trigger": k, "title": k, "content": str(v)}
                        for k, v in raw.items()
                    ]
                elif isinstance(raw, list):
                    snippets = [s for s in raw if isinstance(s, dict)]
            except Exception:  # noqa: BLE001 — fronteira defensiva: callbacks e teardown de widgets/modal Tkinter
                snippets = []

        termo = normalize_for_search(self.entry_busca_snippets.get()) if hasattr(self, "entry_busca_snippets") else ""
        if termo:
            snippets = [
                s for s in snippets
                if termo in normalize_for_search(s.get("trigger", ""))
                or termo in normalize_for_search(s.get("title", ""))
                or termo in normalize_for_search(s.get("content", ""))
            ]

        if not snippets:
            vazio = EmptyState(
                self.scroll_snippets,
                icon="empty",
                title="Nenhum template cadastrado ainda",
                hint="Clique em '+ Novo template' acima para criar seu primeiro atalho de voz!",
            )
            vazio.pack(pady=40)
            return

        for s in snippets:
            self._criar_card_template(s)

    def _criar_card_template(self, s: dict[str, Any]):
        """Cria e renderiza o cartão de um template com preview em fonte de interface e ações discretas."""
        card = ctk.CTkFrame(
            self.scroll_snippets,
            fg_color="transparent",
        )
        card.pack(fill="x", pady=2)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)

        trigger = s.get("trigger", "")
        titulo = s.get("title", trigger.title())
        conteudo = s.get("content", "")

        # Coluna Esquerda: Gatilho + Título + Preview
        info_col = ctk.CTkFrame(card, fg_color="transparent")
        info_col.grid(row=0, column=0, sticky="ew", padx=(4, 16), pady=8)

        head_row = ctk.CTkFrame(info_col, fg_color="transparent")
        head_row.pack(anchor="w")

        lbl_tit = ctk.CTkLabel(
            head_row,
            text=titulo,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        )
        lbl_tit.pack(side="left")

        lbl_gatilho = ctk.CTkLabel(
            head_row,
            text=f" · {trigger}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
        )
        lbl_gatilho.pack(side="left")

        preview_text = conteudo if len(conteudo) <= 160 else conteudo[:157] + "..."
        lbl_prev = ctk.CTkLabel(
            info_col,
            text=preview_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=APPLE_TEXT_SECONDARY,
            justify="left",
            wraplength=640,
            anchor="w",
        )
        lbl_prev.pack(anchor="w", pady=(3, 0))
        quebrar_na_largura(lbl_prev, info_col)

        # Coluna Direita: Ações discretas
        botoes_box = ctk.CTkFrame(card, fg_color="transparent")
        botoes_box.grid(row=0, column=1, sticky="e", padx=(0, 4), pady=8)

        btn_edit = Button(
            botoes_box,
            text="Editar",
            variant="secondary",
            command=lambda snip=s: self.abrir_modal_snippet(snip),
        )
        btn_edit.pack(side="left", padx=(0, 6))

        btn_del = Button(
            botoes_box,
            text="Excluir",
            variant="ghost",
            command=lambda tr=trigger: self.confirmar_excluir_snippet(tr),
        )
        btn_del.pack(side="left")

        # Divisor sutil de 1px inferior
        div = ctk.CTkFrame(card, height=1, fg_color=APPLE_SEPARATOR)
        div.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Efeito de hover suave
        def _enter(e):
            card.configure(fg_color=APPLE_BG_CARD_HOVER)

        def _leave(e):
            card.configure(fg_color="transparent")

        for w in (card, info_col, head_row, lbl_tit, lbl_gatilho, lbl_prev):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

    criar_card_template = _criar_card_template

    def abrir_modal_snippet(self, item: dict[str, Any] | None = None):
        """Abre a janela modal minimalista para cadastro ou edição de template."""
        win = ctk.CTkToplevel(self)
        titulo_janela = "Novo Template" if not item else "Editar Template"
        win.title(titulo_janela)
        win.geometry("520x460")
        win.configure(fg_color=APPLE_BG_APP)

        try:
            top_level = self.winfo_toplevel()
            win.transient(top_level)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: geometria e after da janela Tkinter
            pass

        try:
            win.grab_set()
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: geometria e after da janela Tkinter
            pass

        try:
            top_level = self.winfo_toplevel()
            top_level.update_idletasks()
            x = top_level.winfo_x() + (top_level.winfo_width() - 520) // 2
            y = top_level.winfo_y() + (top_level.winfo_height() - 460) // 2
            win.geometry(f"520x460+{max(0, x)}+{max(0, y)}")
        except Exception:  # noqa: BLE001 — fronteira defensiva: geometria e after da janela Tkinter
            win.geometry("520x460")

        box = ctk.CTkFrame(win, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=24, pady=20)
        box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            box,
            text=titulo_janela,
            font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))

        ctk.CTkLabel(
            box,
            text="Gatilho de voz (o que você fala):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
        ).grid(row=1, column=0, sticky="w")

        ent_trigger = ctk.CTkEntry(
            box,
            placeholder_text="ex: template de bug, proposta comercial",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            height=36,
            corner_radius=RADIUS_INPUT,
            fg_color=APPLE_INPUT_BG,
            border_width=0,
            text_color=APPLE_TEXT_PRIMARY,
            placeholder_text_color=APPLE_TEXT_SECONDARY,
        )
        ent_trigger.grid(row=2, column=0, sticky="ew", pady=(4, 12))
        if item:
            ent_trigger.insert(0, item.get("trigger", ""))

        ctk.CTkLabel(
            box,
            text="Título de identificação:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
        ).grid(row=3, column=0, sticky="w")

        ent_title = ctk.CTkEntry(
            box,
            placeholder_text="ex: Bug Report GitHub",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            height=36,
            corner_radius=RADIUS_INPUT,
            fg_color=APPLE_INPUT_BG,
            border_width=0,
            text_color=APPLE_TEXT_PRIMARY,
            placeholder_text_color=APPLE_TEXT_SECONDARY,
        )
        ent_title.grid(row=4, column=0, sticky="ew", pady=(4, 12))
        if item:
            ent_title.insert(0, item.get("title", ""))

        ctk.CTkLabel(
            box,
            text="Conteúdo a ser inserido:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
        ).grid(row=5, column=0, sticky="w")

        txt_conteudo = ctk.CTkTextbox(
            box,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            height=130,
            corner_radius=RADIUS_INPUT,
            fg_color=APPLE_INPUT_BG,
            border_width=0,
            text_color=APPLE_TEXT_PRIMARY,
        )
        txt_conteudo.grid(row=6, column=0, sticky="nsew", pady=(4, 16))
        if item:
            txt_conteudo.insert("1.0", item.get("content", ""))

        btn_box = ctk.CTkFrame(box, fg_color="transparent")
        btn_box.grid(row=7, column=0, sticky="ew")
        btn_box.grid_columnconfigure(0, weight=1)

        # O que não deu certo aparece aqui, com o modal aberto e o que foi digitado intacto.
        lbl_erro = ctk.CTkLabel(
            btn_box,
            text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_DESTRUCTIVE,
            justify="left",
            anchor="w",
            wraplength=250,
        )
        lbl_erro.pack(side="left", fill="x", expand=True)

        def _fechar_modal():
            try:
                win.grab_release()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callbacks e teardown de widgets/modal Tkinter
                pass
            try:
                win.destroy()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callbacks e teardown de widgets/modal Tkinter
                pass

        win.fechar = _fechar_modal
        win.bind("<Escape>", lambda _e: _fechar_modal())

        gatilho_antigo = (item or {}).get("trigger", "").strip()
        # O gatilho novo que este modal já gravou: no "Tente de novo" depois de o antigo não
        # sair, ele é deste template, e não de outro.
        ja_gravado = []

        def salvar():
            tr = ent_trigger.get().strip()
            ti = ent_title.get().strip()
            co = txt_conteudo.get("1.0", "end").strip()
            if not tr or not co:
                lbl_erro.configure(text="Preencha o gatilho e o conteúdo")
                return
            trocou_o_gatilho = bool(gatilho_antigo) and tr.lower() != gatilho_antigo.lower()
            if trocou_o_gatilho and tr.lower() not in ja_gravado and self._gatilho_de_outro_template(tr, gatilho_antigo):
                # Salvar gravaria por cima do outro template, e excluir o antigo depois o perdia.
                lbl_erro.configure(text=f'Já existe um template com o gatilho "{tr}"')
                return
            # Fecha só com o True: o modal sumia com a gravação falha, e o template se perdia.
            gravar = self.callbacks.get("on_save_snippet")
            if trocou_o_gatilho and _aceita_old_trigger(gravar):
                # O save renomeia no mesmo lugar da lista, numa gravação só. Gravar o novo e
                # apagar o antigo mandava o template para o fim da lista.
                if gravar(tr, ti or tr.title(), co, old_trigger=gatilho_antigo) is not True:
                    lbl_erro.configure(text="Não salvei o template. Tente de novo")
                    return
                _fechar_modal()
                self.atualizar_lista_templates()
                return
            if not gravar or gravar(tr, ti or tr.title(), co) is not True:
                lbl_erro.configure(text="Não salvei o template. Tente de novo")
                return
            # O save atualiza pelo gatilho: com ele trocado, o antigo ficava na lista também,
            # e os dois disputavam a mesma fala.
            if trocou_o_gatilho:
                ja_gravado.append(tr.lower())
                excluir = self.callbacks.get("on_delete_snippet")
                if not excluir or excluir(gatilho_antigo) is not True:
                    self.atualizar_lista_templates()
                    lbl_erro.configure(text=f'Salvei, mas o gatilho antigo "{gatilho_antigo}" continua. Tente de novo')
                    return
            _fechar_modal()
            self.atualizar_lista_templates()

        # Para os testes: o que o botão Salvar faz e os campos que ele lê.
        win.salvar = salvar
        win.campos = {"gatilho": ent_trigger, "titulo": ent_title, "conteudo": txt_conteudo}
        win.lbl_erro = lbl_erro

        btn_salvar = Button(
            btn_box,
            text="Salvar Template",
            variant="primary",
            command=salvar,
        )
        btn_salvar.pack(side="right", padx=(8, 0))

        btn_canc = Button(
            btn_box,
            text="Cancelar",
            variant="secondary",
            command=_fechar_modal,
        )
        btn_canc.pack(side="right")
        return win

    _abrir_modal_snippet = abrir_modal_snippet

    def _gatilho_de_outro_template(self, gatilho: str, gatilho_antigo: str) -> bool:
        """`gatilho` já é de outro template (sem contar o que está sendo editado)? Na mesma
        comparação do save, que trata "reunião" e "reuniao" como o mesmo gatilho falado."""
        existentes = []
        if self.callbacks.get("get_snippets"):
            try:
                existentes = self.callbacks["get_snippets"]() or []
            except Exception:  # noqa: BLE001 — fronteira defensiva: callbacks e teardown de widgets/modal Tkinter
                existentes = []
        if isinstance(existentes, dict):
            existentes = [{"trigger": k} for k in existentes]
        alvo = normalize_for_search(gatilho)
        return any(normalize_for_search(s.get("trigger", "")) == alvo
                   and s.get("trigger", "").strip().lower() != gatilho_antigo.lower()
                   for s in existentes)

    def confirmar_excluir_snippet(self, trigger: str):
        """O "Excluir" do template confirma antes, como no Histórico: era no primeiro clique,
        sem confirmar nem desfazer."""
        return confirmar_exclusao(self, "Excluir Template",
                                  f'Excluir o template "{trigger}"? Falar o gatilho deixa de colar o texto.',
                                  lambda: self.deletar_snippet(trigger))

    def deletar_snippet(self, trigger: str):
        """Exclui o snippet identificado pelo gatilho."""
        if self.callbacks.get("on_delete_snippet"):
            self.callbacks["on_delete_snippet"](trigger)
        self.atualizar_lista_templates()

    _deletar_snippet = deletar_snippet


def build_tab_templates(parent: Any, callbacks: dict[str, Callable] | None = None) -> TemplatesTab:
    """Função fábrica modular para instanciar e retornar a Aba de Templates."""
    return TemplatesTab(parent, callbacks=callbacks)
