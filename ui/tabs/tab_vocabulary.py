"""
Módulo da Aba de Vocabulário & Dicionário Fonético do Willy Dashboard.
Redesenhado no estilo minimalista e sofisticado inspirado na Apple (macOS HIG, Raycast, Things 3).
"""

import sys
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.components import (
    Button,
    EmptyState,
    PageHeader,
    SearchField,
    SectionHeader,
    confirmar_exclusao,
)
from ui.theme import (
    APPLE_BG_CARD_HOVER,
    APPLE_DESTRUCTIVE,
    APPLE_INPUT_BG,
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_TERTIARY,
    FONT_FAMILY,
    RADIUS_BUTTON,
    RADIUS_INPUT,
    SCROLLBAR_COLOR,
    SCROLLBAR_HOVER,
)


class VocabularyTab(ctk.CTkScrollableFrame):
    """Componente modular da Aba de Vocabulário e Dicionário Fonético."""

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
        self._debounce_save_timer = None
        self._reset_salvar_timer = None
        self._reset_preset_timer = None
        # O texto da caixa tem algo que o auto-save ainda não gravou (ou não conseguiu gravar).
        self._edicao_nao_salva = False
        self.grid_columnconfigure(0, weight=1)

        self._construir_ui()

    def _cancelar_timer(self, attr_name: str):
        timer_id = getattr(self, attr_name, None)
        if timer_id is not None:
            try:
                self.after_cancel(timer_id)
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: after_cancel e destroy de widgets Tkinter
                pass
            setattr(self, attr_name, None)

    def destroy(self):
        for attr in ("_debounce_save_timer", "_reset_salvar_timer", "_reset_preset_timer"):
            self._cancelar_timer(attr)
        super().destroy()

    def _construir_ui(self):
        # 1. Cabeçalho Unificado da Página
        self.page_header = PageHeader(
            self,
            title="Vocabulário",
            subtitle="Adicione termos técnicos e regras de auto-correção fonética.",
        )
        self.page_header.pack(fill="x", pady=(0, 10))

        # -------------------------------------------------------------
        # SEÇÃO 1: TERMOS
        # -------------------------------------------------------------
        sec_termos = SectionHeader(self, text="TERMOS")
        sec_termos.pack(fill="x", pady=(10, 4))

        lbl_desc_termos = ctk.CTkLabel(
            self,
            text="Palavras-chave, jargões, nomes próprios e tecnologias que o Whisper priorizará ao transcrever:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        lbl_desc_termos.pack(anchor="w", pady=(0, 8))

        # Textbox de Vocabulário
        self.txt_vocab = ctk.CTkTextbox(
            self,
            height=120,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            fg_color=APPLE_INPUT_BG,
            border_width=0,
            corner_radius=RADIUS_INPUT,
            text_color=APPLE_TEXT_PRIMARY,
        )
        self.txt_vocab.pack(fill="x", pady=(0, 8))
        self.txt_vocab.bind("<KeyRelease>", self._on_vocab_keyrelease)

        # Barra de Ações de Vocabulário
        box_acoes_vocab = ctk.CTkFrame(self, fg_color="transparent")
        box_acoes_vocab.pack(fill="x", pady=(0, 16))
        box_acoes_vocab.grid_columnconfigure(0, weight=1)

        box_acoes_esq = ctk.CTkFrame(box_acoes_vocab, fg_color="transparent")
        box_acoes_esq.grid(row=0, column=0, sticky="w")

        self.btn_salvar_vocab = Button(
            box_acoes_esq,
            text="Salvar Vocabulário",
            variant="secondary",
            command=self.salvar_vocabulario,
        )
        self.btn_salvar_vocab.pack(side="left", padx=(0, 8))

        self.btn_importar_vocab = Button(
            box_acoes_esq,
            text="Importar...",
            variant="ghost",
            command=self._importar_vocabulario,
        )
        self.btn_importar_vocab.pack(side="left", padx=(0, 8))

        self.btn_exportar_vocab = Button(
            box_acoes_esq,
            text="Exportar...",
            variant="ghost",
            command=self._exportar_vocabulario,
        )
        self.btn_exportar_vocab.pack(side="left")

        self.lbl_status_salvo = ctk.CTkLabel(
            box_acoes_vocab,
            text="Salvo",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_TERTIARY,
        )
        self.lbl_status_salvo.grid(row=0, column=1, sticky="e")

        # -------------------------------------------------------------
        # SEÇÃO 2: SUBSTITUIÇÕES
        # -------------------------------------------------------------
        self.btn_preset_tech = Button(
            self,
            text="Presets Tech",
            variant="ghost",
            command=self.carregar_termos_tech_comuns,
        )
        sec_reps = SectionHeader(self, text="SUBSTITUIÇÕES", action=self.btn_preset_tech)
        sec_reps.pack(fill="x", pady=(16, 4))

        lbl_desc_reps = ctk.CTkLabel(
            self,
            text="Substituição instantânea por limite de palavra. Se você ditar o termo, ele será trocado automaticamente:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        )
        lbl_desc_reps.pack(anchor="w", pady=(0, 8))

        # Formulário de Nova Regra De ➔ Para
        box_form = ctk.CTkFrame(self, fg_color="transparent")
        box_form.pack(fill="x", pady=(0, 12))
        box_form.grid_columnconfigure(0, weight=2)
        box_form.grid_columnconfigure(2, weight=2)

        self.entry_rep_de = ctk.CTkEntry(
            box_form,
            placeholder_text="Quando ouvir... (ex: jota)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            height=36,
            corner_radius=RADIUS_INPUT,
            fg_color=APPLE_INPUT_BG,
            border_width=0,
            text_color=APPLE_TEXT_PRIMARY,
            placeholder_text_color=APPLE_TEXT_SECONDARY,
        )
        self.entry_rep_de.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkLabel(
            box_form,
            text="→",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14),
            text_color=APPLE_TEXT_SECONDARY,
        ).grid(row=0, column=1, padx=4)

        self.entry_rep_para = ctk.CTkEntry(
            box_form,
            placeholder_text="Substituir por... (ex: Jotta Prado)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            height=36,
            corner_radius=RADIUS_INPUT,
            fg_color=APPLE_INPUT_BG,
            border_width=0,
            text_color=APPLE_TEXT_PRIMARY,
            placeholder_text_color=APPLE_TEXT_SECONDARY,
        )
        self.entry_rep_para.grid(row=0, column=2, sticky="ew", padx=(8, 8))

        self.btn_add_rep = Button(
            box_form,
            text="+ Adicionar",
            variant="secondary",
            command=self.adicionar_replacement,
        )
        self.btn_add_rep.grid(row=0, column=3)

        # Divisor sutil
        div_rep = ctk.CTkFrame(self, height=1, fg_color=APPLE_SEPARATOR)
        div_rep.pack(fill="x", pady=(0, 10))

        # Aviso de regra não gravada: só aparece quando há o que dizer.
        self.lbl_status_reps = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_DESTRUCTIVE,
            anchor="w",
        )
        self._div_rep = div_rep

        # Campo de busca para filtrar regras de substituição
        self._filtro_reps = ""
        self.search_reps = SearchField(
            self,
            placeholder="Filtrar regras de substituição...",
            on_change=self._filtrar_replacements,
            on_clear=lambda: self._filtrar_replacements(""),
        )
        self.search_reps.pack(fill="x", pady=(0, 10))

        # Lista de regras ativas
        self.frame_reps_lista = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_reps_lista.pack(fill="x", pady=(0, 24))

        self.carregar_dados()

    def _on_vocab_keyrelease(self, event=None):
        """Debounce de 500ms para auto-save de vocabulário."""
        self._edicao_nao_salva = True
        self.lbl_status_salvo.configure(text="Salvando...", text_color=APPLE_TEXT_TERTIARY)
        self._cancelar_timer("_debounce_save_timer")
        self._debounce_save_timer = self.after(500, self.salvar_vocabulario)

    def _restaurar_botao_salvar(self):
        self._reset_salvar_timer = None
        if self.winfo_exists() and hasattr(self, "btn_salvar_vocab") and self.btn_salvar_vocab.winfo_exists():
            self.btn_salvar_vocab.configure(text="Salvar Vocabulário")

    def _restaurar_botao_preset(self):
        self._reset_preset_timer = None
        if self.winfo_exists() and hasattr(self, "btn_preset_tech") and self.btn_preset_tech.winfo_exists():
            self.btn_preset_tech.configure(text="Carregar presets tech")

    def salvar_vocabulario(self):
        """Salva o conteúdo textual do vocabulário através do callback da aplicação.

        "Salvo" só quando o callback diz que gravou. A gravação atômica falha com o arquivo
        bloqueado ou sem permissão, e a aba dizia "Salvo" do mesmo jeito: a pessoa achava que
        os termos valiam no próximo ditado.
        """
        self._cancelar_timer("_debounce_save_timer")
        if not self.winfo_exists():
            return
        conteudo = self.txt_vocab.get("1.0", "end").strip()
        salvou = False
        if self.callbacks.get("on_save_vocab"):
            salvou = bool(self.callbacks["on_save_vocab"](conteudo))
        if not salvou:
            self.lbl_status_salvo.configure(text="Não salvei. Tente de novo", text_color=APPLE_DESTRUCTIVE)
            return
        self._edicao_nao_salva = False
        self.lbl_status_salvo.configure(text="Salvo", text_color=APPLE_TEXT_TERTIARY)
        self.btn_salvar_vocab.configure(text="Salvo")
        self._cancelar_timer("_reset_salvar_timer")
        self._reset_salvar_timer = self.after(1500, self._restaurar_botao_salvar)

    def _avisar_reps(self, texto: str):
        """Mostra (ou tira, com texto vazio) o aviso de regra não gravada."""
        if texto:
            self.lbl_status_reps.configure(text=texto)
            self.lbl_status_reps.pack(fill="x", pady=(0, 8), before=self._div_rep)
        else:
            self.lbl_status_reps.configure(text="")
            self.lbl_status_reps.pack_forget()

    def _regras(self) -> dict[str, str]:
        if not self.callbacks.get("get_replacements"):
            return {}
        try:
            return self.callbacks["get_replacements"]() or {}
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback get_replacements
            print(f"[VocabularyTab] Erro ao obter substituições: {e}", file=sys.stderr)
            return {}

    def _importar_vocabulario(self):
        from tkinter import filedialog
        caminho = filedialog.askopenfilename(
            title="Importar Vocabulário",
            filetypes=[("Arquivos de Texto", "*.txt"), ("Todos os Arquivos", "*.*")]
        )
        if caminho:
            try:
                try:
                    with open(caminho, "r", encoding="utf-8-sig") as f:
                        conteudo = f.read()
                except UnicodeDecodeError:
                    with open(caminho, "r", encoding="cp1252") as f:
                        conteudo = f.read()
                self.txt_vocab.delete("1.0", "end")
                self.txt_vocab.insert("1.0", conteudo)
                self._edicao_nao_salva = True  # até o salvar abaixo dar certo
                self.salvar_vocabulario()
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: importação/exportação de vocabulário
                print(f"[VocabularyTab] Erro ao importar vocabulário de '{caminho}': {e}", file=sys.stderr)
                self.lbl_status_salvo.configure(text="Erro ao importar arquivo", text_color=APPLE_DESTRUCTIVE)

    def _exportar_vocabulario(self):
        from tkinter import filedialog
        caminho = filedialog.asksaveasfilename(
            title="Exportar Vocabulário",
            defaultextension=".txt",
            filetypes=[("Arquivos de Texto", "*.txt"), ("Todos os Arquivos", "*.*")]
        )
        if caminho:
            try:
                conteudo = self.txt_vocab.get("1.0", "end").strip()
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(conteudo)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: importação/exportação de vocabulário
                print(f"[VocabularyTab] Erro ao exportar vocabulário para '{caminho}': {e}", file=sys.stderr)
                self.lbl_status_salvo.configure(text="Erro ao exportar arquivo", text_color=APPLE_DESTRUCTIVE)

    def carregar_termos_tech_comuns(self):
        """Carrega lista pré-definida de termos técnicos comuns para auto-correção fonética."""
        presets = [
            ("k8s", "Kubernetes"),
            ("dock", "Docker"),
            ("postegres", "PostgreSQL"),
            ("postgre", "PostgreSQL"),
            ("postgree", "PostgreSQL"),
            ("git hub", "GitHub"),
            ("git lab", "GitLab"),
            ("vs code", "VS Code"),
            ("react", "React"),
            ("next", "Next.js"),
            ("tailwind", "Tailwind CSS"),
            ("type script", "TypeScript"),
            ("java script", "JavaScript"),
            ("node", "Node.js"),
            ("fast api", "FastAPI"),
            ("pr", "PR"),
            ("mr", "MR"),
            ("ci cd", "CI/CD"),
            ("api", "API"),
            ("llm", "LLM"),
            ("groq", "Groq"),
            ("whisper", "Whisper"),
            ("front end", "frontend"),
            ("back end", "backend"),
        ]
        salvar = self.callbacks.get("on_save_replacement")
        if not salvar:
            return
        falharam = sum(1 for de, para in presets if not salvar(de, para))
        self.atualizar_lista_replacements()
        if falharam:
            self._avisar_reps(f"{falharam} de {len(presets)} presets não foram salvos. Tente de novo")
            return
        self._avisar_reps("")
        if hasattr(self, "btn_preset_tech") and self.btn_preset_tech.winfo_exists():
            self.btn_preset_tech.configure(text="Presets carregados")
            self._cancelar_timer("_reset_preset_timer")
            self._reset_preset_timer = self.after(2000, self._restaurar_botao_preset)

    def adicionar_replacement(self):
        """Cadastra nova regra de substituição de/para."""
        de = self.entry_rep_de.get().strip()
        para = self.entry_rep_para.get().strip()
        if not de or not para:
            return

        salvou = False
        if self.callbacks.get("on_save_replacement"):
            salvou = bool(self.callbacks["on_save_replacement"](de, para))
        if not salvou:
            # O que a pessoa digitou fica nos campos, para tentar de novo.
            self._avisar_reps(f'Não salvei a regra "{de}". Tente de novo')
            return

        self._avisar_reps("")
        self.entry_rep_de.delete(0, "end")
        self.entry_rep_para.delete(0, "end")
        self.atualizar_lista_replacements()

    def confirmar_excluir_replacement(self, de: str, para: str):
        """O "Excluir" da regra confirma antes, como no Histórico: era no primeiro clique, sem
        confirmar nem desfazer."""
        return confirmar_exclusao(self, "Excluir Substituição",
                                  f'Excluir a regra "{de}" → "{para}"? O termo volta a sair como o Whisper o escreve.',
                                  lambda: self.deletar_replacement(de))

    def deletar_replacement(self, de: str):
        """Remove regra de substituição pelo termo de origem."""
        excluiu = False
        if self.callbacks.get("on_delete_replacement"):
            excluiu = bool(self.callbacks["on_delete_replacement"](de))
        self.atualizar_lista_replacements()
        # O store devolve False também para regra que já não existia: aí não há o que avisar.
        if excluiu or de not in self._regras():
            self._avisar_reps("")
        else:
            self._avisar_reps(f'Não excluí a regra "{de}". Tente de novo')

    def _filtrar_replacements(self, termo: str):
        """Filtra visualmente as substituições com base no texto da busca."""
        self._filtro_reps = termo
        self.atualizar_lista_replacements()

    def atualizar_lista_replacements(self):
        """Re-renderiza a lista visual de regras fonéticas ativas."""
        if not hasattr(self, "frame_reps_lista") or not self.frame_reps_lista.winfo_exists():
            return

        for w in self.frame_reps_lista.winfo_children():
            try:
                w.destroy()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: after_cancel e destroy de widgets Tkinter
                pass

        reps = self._regras()

        if not reps:
            vazio = EmptyState(
                self.frame_reps_lista,
                icon="empty",
                title="Nenhuma regra cadastrada",
                hint="Adicione termos acima para substituir automaticamente durante o ditado.",
            )
            vazio.pack(pady=20)
            return

        termo = (getattr(self, "_filtro_reps", "") or "").strip().lower()
        if termo:
            reps_filtrados = {
                de: para for de, para in reps.items()
                if termo in de.lower() or termo in para.lower()
            }
            if not reps_filtrados:
                vazio = EmptyState(
                    self.frame_reps_lista,
                    icon="search",
                    title="Nenhuma regra encontrada",
                    hint=f"Nenhuma regra corresponde a '{termo}'.",
                )
                vazio.pack(pady=20)
                return
            reps = reps_filtrados

        for de, para in sorted(reps.items()):
            row = ctk.CTkFrame(
                self.frame_reps_lista,
                fg_color="transparent",
                corner_radius=RADIUS_BUTTON,
                height=36,
            )
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=0)

            # Conteúdo da regra
            txt_box = ctk.CTkFrame(row, fg_color="transparent")
            txt_box.grid(row=0, column=0, sticky="w", padx=8)

            lbl_de = ctk.CTkLabel(
                txt_box,
                text=de,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                text_color=APPLE_TEXT_PRIMARY,
            )
            lbl_de.pack(side="left")

            lbl_seta = ctk.CTkLabel(
                txt_box,
                text="  →  ",
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                text_color=APPLE_TEXT_SECONDARY,
            )
            lbl_seta.pack(side="left")

            lbl_para = ctk.CTkLabel(
                txt_box,
                text=para,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                text_color=APPLE_TEXT_PRIMARY,
            )
            lbl_para.pack(side="left")

            # Botão excluir discreto
            btn_del = Button(
                row,
                text="Excluir",
                variant="ghost",
                command=lambda k=de, v=para: self.confirmar_excluir_replacement(k, v),
            )
            btn_del.grid(row=0, column=1, sticky="e", padx=4)

            # Efeito suave de hover
            def _enter(e, r=row):
                r.configure(fg_color=APPLE_BG_CARD_HOVER)

            def _leave(e, r=row):
                r.configure(fg_color="transparent")

            for w in (row, txt_box, lbl_de, lbl_seta, lbl_para):
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

            # Divisor sutil
            div = ctk.CTkFrame(self.frame_reps_lista, height=1, fg_color=APPLE_SEPARATOR)
            div.pack(fill="x", padx=4, pady=(2, 0))

    def carregar_dados(self):
        """Carrega vocabulário e regras do storage através dos callbacks."""
        if self.callbacks.get("get_vocab"):
            v = self.callbacks["get_vocab"]()
            self.txt_vocab.delete("1.0", "end")
            self.txt_vocab.insert("1.0", v)
            self._edicao_nao_salva = False

        self.atualizar_lista_replacements()

    def recarregar_se_nao_editado(self):
        """Relê o vocabulário e as regras do disco, a menos que a caixa tenha edição que o
        auto-save ainda não gravou.

        O arquivo também muda por fora: a bandeja o abre no Bloco de Notas. Com o texto velho
        na tela, o próximo auto-save gravava por cima e apagava o que foi editado lá.
        """
        if not self._edicao_nao_salva:
            self.carregar_dados()

    def receber_termos_aprendidos(self, termos: list[str]):
        """O "Ensinar ao Willy" do Histórico gravou regras e termos no disco.

        As regras são relidas sempre. A caixa, só sem edição pendente; com ela, os termos que
        faltam entram no fim da caixa: o auto-save grava a caixa inteira, e sem eles apagaria do
        arquivo o que acabou de ser aprendido.
        """
        if not self._edicao_nao_salva:
            self.carregar_dados()
            return
        self.atualizar_lista_replacements()
        na_caixa = {t.strip().casefold() for linha in self.txt_vocab.get("1.0", "end").splitlines()
                    if not linha.strip().startswith("#") for t in linha.split(",") if t.strip()}
        for termo in termos:
            if termo.strip() and termo.strip().casefold() not in na_caixa:
                atual = self.txt_vocab.get("1.0", "end-1c")
                self.txt_vocab.insert("end", ("" if not atual or atual.endswith("\n") else "\n") + termo.strip())
                na_caixa.add(termo.strip().casefold())


def build_tab_vocabulary(parent: Any, callbacks: dict[str, Callable] | None = None) -> VocabularyTab:
    """Função fábrica modular para construir e retornar a Aba de Vocabulário."""
    return VocabularyTab(parent, callbacks=callbacks)
