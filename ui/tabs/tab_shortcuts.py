"""
Módulo da Aba de Atalhos & Comandos de Voz do Willy Dashboard.
Redesenhado no estilo minimalista e sofisticado inspirado na Apple (macOS HIG, Raycast, Things 3).
"""

from typing import Any

import customtkinter as ctk

from core.hotkey import HOTKEYS_PADRAO, teclas_da_combinacao
from core.text_processing import TextProcessor, normalize_for_search
from ui.components import (
    Button,
    Keycap,
    PageHeader,
    SearchField,
    SectionHeader,
    quebrar_na_largura,
)
from ui.theme import (
    APPLE_SEPARATOR,
    APPLE_TEXT_PRIMARY,
    APPLE_TEXT_SECONDARY,
    APPLE_TEXT_WARNING,
    FONT_FAMILY,
    SCROLLBAR_COLOR,
    SCROLLBAR_HOVER,
)


def render_keycaps_row(parent, teclas_list):
    """
    Renderiza um conjunto de teclas físicas elegantes estilo Apple Keyboard.
    Mantido para compatibilidade reversa com testes e código legado.
    """
    return Keycap(parent, keys=teclas_list, editable=False)


def build_tab_shortcuts(parent, callbacks=None):
    """
    Constrói e retorna o frame scrollável da Aba de Atalhos & Comandos de Voz.
    """
    callbacks = callbacks or {}
    settings = {}
    if callbacks.get("get_settings"):
        try:
            settings = callbacks["get_settings"]() or {}
        except Exception:  # noqa: BLE001 — fronteira defensiva: leitura inicial de get_settings
            settings = {}

    f = ctk.CTkScrollableFrame(
        parent,
        fg_color="transparent",
        scrollbar_button_color=SCROLLBAR_COLOR,
        scrollbar_button_hover_color=SCROLLBAR_HOVER,
        scrollbar_fg_color="transparent",
    )
    f.grid_columnconfigure(0, weight=1)

    # Hotkeys padrão do sistema (fonte única em core.hotkey)
    hotkeys_padrao = dict(HOTKEYS_PADRAO)

    # Mapeamento de hotkeys existentes
    hotkeys_atuais = {
        k: settings.get(k, settings.get(k.lower(), v_default))
        for k, v_default in hotkeys_padrao.items()
    }

    keycaps_registrados: dict[str, Keycap] = {}
    # O aviso de cada linha, mostrado quando o atalho dela ficou sem tecla no Windows.
    avisos_de_falha: dict[str, ctk.CTkLabel] = {}
    # Nome de cada atalho no aviso de conflito do Keycap: o título da linha dele.
    nomes_atalhos: dict[str, str] = {}
    # Cada seção é um container com o título e as linhas dela, nesta ordem. A busca mexe nos
    # containers e nas linhas DE DENTRO; antes as linhas ficavam soltas no frame da aba, e
    # cada uma que reaparecia na busca era reempacotada no FIM da aba, depois da Pontuação.
    secoes: list[dict[str, Any]] = []

    def _nova_secao(titulo: str, pady_topo: int, pady_titulo_baixo: int = 4) -> dict[str, Any]:
        frame = ctk.CTkFrame(f, fg_color="transparent")
        frame.pack(fill="x")
        SectionHeader(frame, text=titulo).pack(fill="x", pady=(pady_topo, pady_titulo_baixo))
        secao = {"titulo": titulo, "frame": frame, "itens": []}
        secoes.append(secao)
        return secao

    def _restaurar_padroes():
        for k, v in hotkeys_padrao.items():
            hotkeys_atuais[k] = v
            if k in keycaps_registrados:
                keycaps_registrados[k].set_keys(v)
        if callbacks.get("on_save_settings"):
            try:
                callbacks["on_save_settings"](dict(hotkeys_padrao))
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callbacks de atalhos e settings
                pass

    # 1. Cabeçalho de Página Unificado com ação de Restaurar Padrões
    btn_restaurar = Button(
        f,
        text="Restaurar Padrões",
        variant="ghost",
        command=_restaurar_padroes,
    )
    page_header = PageHeader(
        f,
        title="Atalhos",
        subtitle="Configure combinações de teclas e consulte comandos de voz.",
        actions=[btn_restaurar],
    )
    page_header.pack(fill="x", pady=(0, 8))

    def _on_search(termo: str):
        """Mostra só o que casa com `termo`, sempre na ordem original, e esconde as seções que
        ficaram sem nenhum item. Desempacota tudo e reempacota em ordem: um pack() avulso
        põe o widget no fim do container."""
        termo_limpo = normalize_for_search(termo)
        for secao in secoes:
            secao["frame"].pack_forget()
        for secao in secoes:
            algum_visivel = False
            for item in secao["itens"]:
                if item["tipo"] == "pack":
                    item["widget"].pack_forget()
            for item in secao["itens"]:
                visivel = not termo_limpo or termo_limpo in item["texto"]
                algum_visivel = algum_visivel or visivel
                w = item["widget"]
                if item["tipo"] == "pack":
                    if visivel:
                        w.pack(fill="x", pady=2)
                elif visivel:
                    w.grid(row=item["row"], column=item["col"], sticky="ew", padx=6, pady=4)
                else:
                    w.grid_remove()
            if algum_visivel:
                secao["frame"].pack(fill="x")

    # 2. Campo de Busca Dinâmico
    search_field = SearchField(
        f,
        placeholder="Filtrar atalhos ou comandos de voz...",
        on_change=_on_search,
        on_clear=lambda: _on_search(""),
    )
    search_field.pack(fill="x", pady=(0, 12))

    def _salvar_atalho(chave_config: str, novo_combo: str):
        hotkeys_atuais[chave_config] = novo_combo
        if callbacks.get("on_save_settings"):
            try:
                callbacks["on_save_settings"]({chave_config: novo_combo})
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: callbacks de atalhos e settings
                pass

    def _criar_linha_atalho(
        secao: dict[str, Any],
        titulo: str,
        descricao: str,
        chave_config: str,
        combo_padrao: str,
    ):
        combo_atual = hotkeys_atuais.get(chave_config, combo_padrao)
        nomes_atalhos[chave_config] = titulo

        row_wrap = ctk.CTkFrame(secao["frame"], fg_color="transparent")
        row_wrap.pack(fill="x", pady=2)
        row_wrap.grid_columnconfigure(0, weight=1)
        row_wrap.grid_columnconfigure(1, weight=0)

        # Coluna Esquerda: Título e Descrição
        info_box = ctk.CTkFrame(row_wrap, fg_color="transparent")
        info_box.grid(row=0, column=0, sticky="ew", padx=(4, 16), pady=8)

        lbl_tit = ctk.CTkLabel(
            info_box,
            text=titulo,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_tit.pack(anchor="w")

        lbl_desc = ctk.CTkLabel(
            info_box,
            text=descricao,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            justify="left",
            wraplength=520,
            anchor="w",
        )
        lbl_desc.pack(anchor="w", pady=(2, 0))
        quebrar_na_largura(lbl_desc, info_box)

        # Só aparece com o atalho recusado (_mostrar_falhas): sem ele, a linha mostrava uma tecla
        # que não faz nada, e o aviso da partida mandava trocar aqui sem dizer qual.
        lbl_falha = ctk.CTkLabel(
            info_box,
            text="",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=APPLE_TEXT_WARNING,
            justify="left",
            wraplength=520,
            anchor="w",
        )
        quebrar_na_largura(lbl_falha, info_box)
        avisos_de_falha[chave_config] = lbl_falha

        # Coluna Direita: Keycap Interativo
        keycap = Keycap(
            row_wrap,
            keys=combo_atual,
            on_change=lambda novo: _salvar_atalho(chave_config, novo),
            editable=True,
            existing_hotkeys=hotkeys_atuais,
            chave_propria=chave_config,
            nomes_atalhos=nomes_atalhos,
        )
        keycap.grid(row=0, column=1, sticky="e", padx=(0, 4), pady=8)
        keycaps_registrados[chave_config] = keycap

        # Divisor sutil inferior de 1px
        div = ctk.CTkFrame(row_wrap, height=1, fg_color=APPLE_SEPARATOR)
        div.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        secao["itens"].append({
            "widget": row_wrap,
            "texto": normalize_for_search(f"{titulo} {descricao} {chave_config} {combo_padrao}"),
            "tipo": "pack",
        })

    # -----------------------------------------------------------------
    # SEÇÃO: DITADO
    # -----------------------------------------------------------------
    sec_ditado = _nova_secao("DITADO", 12)

    _criar_linha_atalho(
        sec_ditado,
        titulo="Ditado Inteligente",
        descricao="Toque para falar com corte automático por pausa ou segure a barra de espaço para push-to-talk.",
        chave_config="VOICE_HOTKEY",
        combo_padrao="ctrl+space",
    )

    _criar_linha_atalho(
        sec_ditado,
        titulo="Tradução Simultânea",
        descricao="Dite em português e receba o texto diretamente traduzido em inglês fluido e profissional.",
        chave_config="TRANSLATE_HOTKEY",
        combo_padrao="ctrl+alt+space",
    )

    _criar_linha_atalho(
        sec_ditado,
        titulo="Tradução Simultânea (Espanhol)",
        descricao="Dite em português e receba o texto em espanhol natural, com os seus termos e a formatação preservados.",
        chave_config="TRANSLATE_ES_HOTKEY",
        combo_padrao="ctrl+alt+n",
    )

    _criar_linha_atalho(
        sec_ditado,
        titulo="Modo Reunião",
        descricao="Gravação contínua para chamadas longas com geração automática de ata executiva pela IA.",
        chave_config="MEETING_HOTKEY",
        combo_padrao="ctrl+alt+r",
    )

    # -----------------------------------------------------------------
    # SEÇÃO: TRANSFORMAÇÃO COM IA
    # -----------------------------------------------------------------
    sec_ia = _nova_secao("TRANSFORMAÇÃO COM IA", 20)

    _criar_linha_atalho(
        sec_ia,
        titulo="Arquiteto de Prompts",
        descricao="Transforma sua fala ou o texto selecionado em uma especificação executiva completa para agentes.",
        chave_config="PROMPT_HOTKEY",
        combo_padrao="ctrl+alt+p",
    )

    _criar_linha_atalho(
        sec_ia,
        titulo="Transformar Seleção",
        descricao="Aplica comandos e instruções de voz diretamente sobre o texto selecionado na sua janela atual.",
        chave_config="TRANSFORM_HOTKEY",
        combo_padrao="ctrl+alt+t",
    )

    _criar_linha_atalho(
        sec_ia,
        titulo="Alternar Perfil de IA",
        descricao="Alterna ciclicamente entre Dev & Código, Executivo & Prosa e Puro (latência mínima sem LLM).",
        chave_config="PROFILE_HOTKEY",
        combo_padrao="ctrl+alt+e",
    )

    # -----------------------------------------------------------------
    # SEÇÃO: FERRAMENTAS
    # -----------------------------------------------------------------
    sec_ferramentas = _nova_secao("FERRAMENTAS", 20)

    _criar_linha_atalho(
        sec_ferramentas,
        titulo="Mini-Spotlight de Histórico",
        descricao="Barra flutuante para busca e colagem ultra-rápida de transcrições e prompts anteriores.",
        chave_config="HISTORY_HOTKEY",
        combo_padrao="ctrl+alt+h",
    )

    _criar_linha_atalho(
        sec_ferramentas,
        titulo="Desfazer Último Ditado",
        descricao="Reverte e apaga imediatamente o último texto colado pelo Willy em qualquer aplicativo.",
        chave_config="UNDO_HOTKEY",
        combo_padrao="ctrl+alt+z",
    )

    _criar_linha_atalho(
        sec_ferramentas,
        titulo="Leitura em Voz Alta",
        descricao="Lê em voz alta o texto selecionado em qualquer aplicativo. Aperte de novo para parar.",
        chave_config="SPEAK_HOTKEY",
        combo_padrao="ctrl+alt+s",
    )

    _criar_linha_atalho(
        sec_ferramentas,
        titulo="Fixar Janela Alvo",
        descricao="Fixa a janela em foco como destino dos ditados: o texto vai para ela mesmo com outra "
                  "janela na frente. Aperte de novo para desfixar.",
        chave_config="STICKY_HOTKEY",
        combo_padrao="ctrl+alt+f",
    )

    _criar_linha_atalho(
        sec_ferramentas,
        titulo="Legendas Ao Vivo / Teleprompter",
        descricao="Abre e fecha a janela flutuante translúcida, sempre por cima, que mostra cada texto "
                  "transcrito pelo Willy.",
        chave_config="CAPTIONS_HOTKEY",
        combo_padrao="ctrl+alt+l",
    )

    # -----------------------------------------------------------------
    # SEÇÃO: SISTEMA
    # -----------------------------------------------------------------
    sec_sistema = _nova_secao("SISTEMA", 20)

    _criar_linha_atalho(
        sec_sistema,
        titulo="Modo Repouso",
        descricao="Desativa o microfone com 0,00% de uso de processador para total privacidade durante chamadas.",
        chave_config="MASTER_HOTKEY",
        combo_padrao="ctrl+shift+space",
    )

    _criar_linha_atalho(
        sec_sistema,
        titulo="Ditar e Enviar",
        descricao="Dita sua mensagem e pressiona Enter automaticamente para envio direto no chat ativo.",
        chave_config="SEND_HOTKEY",
        combo_padrao="ctrl+shift+enter",
    )

    # -----------------------------------------------------------------
    # SEÇÃO: COMANDOS DE VOZ PARA PONTUAÇÃO
    # -----------------------------------------------------------------
    sec_voz = _nova_secao("COMANDOS DE VOZ PARA PONTUAÇÃO", 20, pady_titulo_baixo=8)

    comandos = list(TextProcessor.VOICE_COMMANDS)

    tab_voz = ctk.CTkFrame(sec_voz["frame"], fg_color="transparent")
    tab_voz.pack(fill="x", pady=(0, 24))
    tab_voz.grid_columnconfigure((0, 1), weight=1)

    for idx, (fala, efeito) in enumerate(comandos):
        row = idx // 2
        col = idx % 2
        box_item = ctk.CTkFrame(tab_voz, fg_color="transparent")
        box_item.grid(row=row, column=col, sticky="ew", padx=6, pady=4)
        box_item.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            box_item,
            text=fala,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=APPLE_TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            box_item,
            text=efeito,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=APPLE_TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w")

        div_cmd = ctk.CTkFrame(box_item, height=1, fg_color=APPLE_SEPARATOR)
        div_cmd.pack(fill="x", pady=(4, 0))

        sec_voz["itens"].append({
            "widget": box_item,
            "texto": normalize_for_search(f"{fala} {efeito}"),
            "tipo": "grid",
            "row": row,
            "col": col,
        })

    def _mostrar_falhas():
        """Marca as linhas dos atalhos que o Windows não registrou da última vez. Um atalho que a
        pessoa já trocou depois da recusa não fica marcado: a combinação da linha é outra."""
        falhas: dict[str, str] = {}
        if callbacks.get("get_hotkey_failures"):
            try:
                falhas = callbacks["get_hotkey_failures"]() or {}
            except Exception:  # noqa: BLE001 — fronteira defensiva: callbacks on_save_settings e get_hotkey_failures
                falhas = {}
        for chave, lbl in avisos_de_falha.items():
            combo = hotkeys_atuais.get(chave)
            teclas = teclas_da_combinacao(combo) if combo else frozenset()
            falha_chave = falhas.get(chave)
            if not teclas or not falha_chave or teclas_da_combinacao(falha_chave) != teclas:
                lbl.configure(text="")
                lbl.pack_forget()
                continue
            # Dois atalhos do Willy na mesma combinação (um .env editado à mão): só um registra, e
            # o outro programa do aviso seria o próprio Willy.
            dono = next(
                (
                    nomes_atalhos.get(k, k)
                    for k, c in hotkeys_atuais.items()
                    if k != chave and c and teclas_da_combinacao(c) == teclas and k not in falhas
                ),
                None,
            )
            if dono:
                texto = f"⚠️ Mesma combinação de {dono} — clique no atalho ao lado para trocar"
            else:
                texto = "⚠️ Em uso por outro programa no Windows — clique no atalho ao lado para trocar"
            lbl.configure(text=texto)
            lbl.pack(anchor="w", pady=(4, 0))

    def _sincronizar_atalhos(cfg: dict[str, Any]):
        """Mostra o que está na config. Uma troca recusada pelo Windows volta à combinação
        anterior, e o Keycap continuava mostrando a recusada."""
        for k, v_default in hotkeys_padrao.items():
            # Sem "or v_default": um campo vazio na config não registra atalho nenhum, e mostrar
            # o padrão dizia que ele valia.
            combo = cfg.get(k, cfg.get(k.lower(), v_default))
            hotkeys_atuais[k] = combo
            if k in keycaps_registrados:
                keycaps_registrados[k].set_keys(combo)
        _mostrar_falhas()

    _mostrar_falhas()
    f.sincronizar_atalhos = _sincronizar_atalhos
    f.avisos_de_falha = avisos_de_falha
    f.filtrar = _on_search
    f.secoes = secoes
    return f
