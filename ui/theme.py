"""
Design System Tokens do Willy Dashboard.
Paleta inspirada em Apple macOS Light, Linear e Raycast.
"""

from core.analytics.metrics import classificar_data_historico
from versao import __version__

FONT_FAMILY = "Segoe UI"

# Superfícies Claras & Limpas
BG_APP = "#F8F9FA"          # Fundo principal da janela (off-white limpo)
BG_SIDEBAR = "#FFFFFF"      # Barra lateral em branco puro
BORDER_SUBTLE = "#E5E7EB"   # Divisores e linhas de 1px ultra-suaves
BG_CARD = "#FFFFFF"         # Superfície elevada dos cartões agrupados
BORDER_CARD = "#E5E7EB"     # Borda suave de 1px dos cartões
BG_CARD_HOVER = "#F9FAFB"   # Hover sutil dos cartões
BG_INPUT = "#FFFFFF"        # Fundo dos campos de digitação / busca
BORDER_INPUT = "#D1D5DB"    # Borda dos campos de entrada
BORDER_INPUT_FOCUS = "#2563EB"

# Tipografia de Alta Legibilidade
TEXT_PRIMARY = "#111827"    # Slate 900 / Preto carvão
TEXT_SECONDARY = "#4B5563"  # Slate 600 para legendas e metadados
TEXT_MUTED = "#6B7280"      # Gray 500 - 4.59:1 sobre BG_APP (AA para texto normal)

# Escala de Superficie Neutra (degraus abaixo do cartao)
# Nomeada por profundidade, nao por widget: o mesmo degrau serve a segmento inativo,
# keycap, trilho e painel. Espelha a escala de hover (BTN_NEUTRAL_HOVER / BG_HOVER_STRONG).
BG_SUBTLE = "#F9FAFB"       # Gray 50  - painel suave
BG_MUTED = "#F3F4F6"        # Gray 100 - superficie recuada
BG_RECESSED = "#E5E7EB"     # Gray 200 - sulco mais profundo

# Barra de Rolagem (Scrollbar adaptativa Light / Dark)
SCROLLBAR_COLOR = ("#D1D5DB", "#38383A")
SCROLLBAR_HOVER = ("#9CA3AF", "#48484A")

# Cores de Acento e Semântica (Tons Modernos e Equilibrados)
# Cada família carrega o mesmo conjunto, e a simetria é verificada por teste:
#   base (600), _HOVER (700)        -> botão sólido e seu hover
#   _LIGHT (50), _LIGHT_HOVER (100) -> botão/badge fantasma e seu hover
#   _BORDER (200)                   -> contorno de 1px
# A família roxa nasceu sem _HOVER e o dashboard usava o nome mesmo assim: era um
# NameError esperando o usuário abrir o diálogo de importar áudio.
ACCENT_BLUE = "#2563EB"         # Azul Primário moderno (Tailwind Blue 600)
ACCENT_BLUE_HOVER = "#1D4ED8"   # Blue 700
ACCENT_BLUE_LIGHT = "#EFF6FF"   # Blue 50
ACCENT_BLUE_LIGHT_HOVER = "#DBEAFE"   # Blue 100
ACCENT_BLUE_BORDER = "#BFDBFE"  # Blue 200

ACCENT_CYAN = "#0284C7"         # Sky 600
ACCENT_CYAN_HOVER = "#0369A1"   # Sky 700
ACCENT_CYAN_LIGHT = "#F0F9FF"   # Sky 50
ACCENT_CYAN_LIGHT_HOVER = "#E0F2FE"   # Sky 100
ACCENT_CYAN_BORDER = "#BAE6FD"  # Sky 200

ACCENT_GREEN = "#059669"        # Emerald 600
ACCENT_GREEN_HOVER = "#047857"  # Emerald 700
ACCENT_GREEN_LIGHT = "#ECFDF5"  # Emerald 50
ACCENT_GREEN_LIGHT_HOVER = "#D1FAE5"  # Emerald 100
ACCENT_GREEN_BORDER = "#A7F3D0" # Emerald 200

ACCENT_AMBER = "#D97706"        # Amber 600
ACCENT_AMBER_HOVER = "#B45309"  # Amber 700
ACCENT_AMBER_LIGHT = "#FFFBEB"  # Amber 50
ACCENT_AMBER_LIGHT_HOVER = "#FEF3C7"  # Amber 100
ACCENT_AMBER_BORDER = "#FDE68A" # Amber 200

ACCENT_RED = "#DC2626"          # Red 600
ACCENT_RED_HOVER = "#B91C1C"    # Red 700
ACCENT_RED_LIGHT = "#FEF2F2"    # Red 50
ACCENT_RED_LIGHT_HOVER = "#FEE2E2"    # Red 100
ACCENT_RED_BORDER = "#FECACA"   # Red 200

ACCENT_PURPLE = "#7C3AED"       # Violet 600
ACCENT_PURPLE_HOVER = "#6D28D9" # Violet 700
ACCENT_PURPLE_LIGHT = "#F5F3FF" # Violet 50
ACCENT_PURPLE_LIGHT_HOVER = "#EDE9FE" # Violet 100
ACCENT_PURPLE_BORDER = "#DDD6FE"# Violet 200

# Medidor de nível (VU meter e barras de progresso)
# Estados semânticos. O WCAG 1.4.11 pede 3:1 do que identifica o estado do componente,
# e aqui o vizinho é o trilho (BG_RECESSED), não o fundo da janela.
METER_OK = ACCENT_GREEN         # 3.04:1 sobre o trilho
METER_WARNING = "#B45309"       # Amber 700 - o ACCENT_AMBER (600) da so 2.57:1
METER_DANGER = ACCENT_RED       # 3.90:1 sobre o trilho

# Botões Padrão do Sistema
BTN_PRIMARY_BG = ACCENT_BLUE
BTN_PRIMARY_HOVER = ACCENT_BLUE_HOVER
BTN_PRIMARY_TEXT = "#FFFFFF"

BTN_NEUTRAL_BG = "#FFFFFF"
BTN_NEUTRAL_HOVER = "#F3F4F6"
BG_HOVER_STRONG = "#E5E7EB"      # Gray 200 - hover sobre superficie que ja e cinza
BTN_NEUTRAL_BORDER = "#D1D5DB"
BTN_NEUTRAL_TEXT = "#374151"

# =====================================================================
# TOKENS DE DESIGN APPLE MINIMALISTA (SUPORTE DUAL: MODO CLARO & ESCURO)
# =====================================================================
# Cores de Superfície (Light / Dark)
APPLE_BG_APP = ("#FFFFFF", "#1C1C1E")
APPLE_BG_SIDEBAR = ("#F5F5F7", "#232325")
APPLE_BG_CARD = ("#FFFFFF", "#2C2C2E")
APPLE_BG_CARD_HOVER = ("#F9FAFB", "#3A3A3C")
APPLE_BG_HOVER = ("#EFEFF1", "#2C2C2E")
APPLE_BG_ACTIVE = ("#E5E5EA", "#3A3A3C")
APPLE_SEGMENT_BG = ("#E5E5EA", "#323236")
APPLE_SEGMENT_SELECTED = ("#FFFFFF", "#636366")
APPLE_KEYCAP_BG = ("#E5E7EB", "#2C2C2E")
APPLE_KEYCAP_BORDER = ("#D1D5DB", "#3A3A3C")

# Tipografia & Cores de Texto (Contraste WCAG AA garantido em ambos os modos)
APPLE_TEXT_PRIMARY = ("#1D1D1F", "#F5F5F7")
APPLE_TEXT_SECONDARY = ("#6E6E73", "#98989D")
APPLE_TEXT_TERTIARY = ("#AEAEB2", "#636366")
# Aviso em texto (atalho recusado pelo Windows): Amber 700 dá 5,0:1 no branco, e o laranja do
# sistema no escuro, 8,3:1 no #1C1C1E.
APPLE_TEXT_WARNING = ("#B45309", "#FF9F0A")

# Linhas, Divisores & Entradas
APPLE_SEPARATOR = ("#E5E5EA", "#38383A")
APPLE_BORDER_CARD = ("#E5E5EA", "#38383A")
APPLE_INPUT_BG = ("#F2F2F7", "#2C2C2E")
APPLE_INPUT_BORDER = ("#E5E5EA", "#38383A")

# Acento Único (Apple Blue) & Semântica
APPLE_ACCENT = ("#0A84FF", "#0A84FF")
APPLE_ACCENT_HOVER = ("#0071E3", "#0071E3")
APPLE_ACCENT_SUBTLE = ("#EBF5FF", "#173451")
APPLE_DESTRUCTIVE = ("#FF3B30", "#FF453A")
APPLE_DESTRUCTIVE_HOVER = ("#D70015", "#D70015")
APPLE_DESTRUCTIVE_SUBTLE = ("#FFECEB", "#3C1816")
APPLE_STATUS_ONLINE = ("#34C759", "#30D158")

# Espaçamento (Grid de 4px)
SPACE_4 = 4
SPACE_8 = 8
SPACE_12 = 12
SPACE_16 = 16
SPACE_24 = 24
SPACE_32 = 32
SPACE_48 = 48

# Raios de Borda Centralizados
RADIUS_INPUT = 8
RADIUS_BUTTON = 8
RADIUS_CARD = 12
RADIUS_PILL = 999

# Constantes de Layout & Alinhamento Milimétrico da Interface
SIDEBAR_WIDTH = 240
SIDEBAR_PAD = 12
ICON_BOX = 20
ICON_GAP = 12
ITEM_HEIGHT = 36
CONTENT_PAD = 32
CONTENT_PAD_MAX = 96
# Até esta largura de área de conteúdo, a margem lateral é a mínima (CONTENT_PAD).
LARGURA_SEM_FOLGA = 960

# -----------------------------------------------------------------------------
# ELEMENTOS FLUTUANTES (pílula, Spotlight, legendas e o ícone desenhado da bandeja)
# -----------------------------------------------------------------------------
# Sempre escuros, sem par claro/escuro: o canvas do Tk e o PIL pedem uma cor só. Eram 90
# hex soltos em ui/overlays/, que a regra do test_theme não via (ela olhava só os
# argumentos *_color=). Cores de sistema da Apple no modo escuro.
FLUTUANTE_FUNDO = "#161618"  # fundo da pílula, do Spotlight e das legendas
FLUTUANTE_BORDA_PILULA = "#323236"  # contorno da pílula
FLUTUANTE_TEXTO = "#F5F5F7"  # texto principal
FLUTUANTE_TEXTO_APAGADO = "#86868B"  # texto secundário, estados inativos
FLUTUANTE_TEXTO_SUAVE = "#D1D1D6"  # texto de item não selecionado no Spotlight
FLUTUANTE_TEXTO_BOTAO = "#C7C7CC"  # texto dos botões das legendas
FLUTUANTE_AZUL = "#0A84FF"  # acordar, ler em voz alta, destaque das legendas
FLUTUANTE_AZUL_ACAO = "#0071E3"  # seleção e ação no Spotlight
FLUTUANTE_CIANO = "#64D2FF"  # ditado (ondas, texto do ouvindo)
FLUTUANTE_CIANO_CLARO = "#5AC8FA"  # perfil de IA, etiqueta do Spotlight
FLUTUANTE_VERDE = "#30D158"  # sucesso, ditar e enviar
FLUTUANTE_VERMELHO = "#FF453A"  # erro, volume alto, fechar
FLUTUANTE_LARANJA = "#FF9F0A"  # reunião, processando, aviso
FLUTUANTE_AMARELO = "#FFD60A"  # texto de processando, aviso e reenvio
FLUTUANTE_ROXO = "#AF52DE"  # prompt de agente
FLUTUANTE_LILAS = "#BF5AF2"  # tradução e transformar
FLUTUANTE_CARTAO = "#1E1E22"  # cartão do Spotlight
FLUTUANTE_CARTAO_ATIVO = "#262830"  # cartão selecionado do Spotlight
FLUTUANTE_BORDA = "#2E2E34"  # borda dos cartões do Spotlight
FLUTUANTE_BORDA_SUAVE = "#2C2C30"  # borda das legendas, barra de rolagem
FLUTUANTE_ROLAGEM_HOVER = "#3E3E44"  # barra de rolagem sob o mouse
FLUTUANTE_CABECALHO = "#1F1F23"  # cabeçalho das legendas
FLUTUANTE_BOTAO = "#2C2C32"  # botão das legendas
FLUTUANTE_BOTAO_HOVER = "#383840"  # botão das legendas sob o mouse
FLUTUANTE_FECHAR_HOVER = "#3D1B1E"  # fechar das legendas sob o mouse
FLUTUANTE_CAIXA_TEXTO = "#19191C"  # caixa de texto das legendas
BANDEJA_MIC_ATIVO = "#38BDF8"  # ícone desenhado da bandeja: microfone, Willy acordado
BANDEJA_MIC_INATIVO = "#64748B"  # microfone, Willy dormindo
BANDEJA_SUPORTE_ATIVO = "#FFFFFF"  # haste do microfone, acordado
BANDEJA_SUPORTE_INATIVO = "#94A3B8"  # haste do microfone, dormindo



def margem_conteudo(largura_area: float) -> int:
    """Margem lateral do conteúdo para uma área de `largura_area` ao lado da barra lateral.

    Tudo em unidades do customtkinter (as de SIDEBAR_WIDTH), não em pixels: com o Windows em
    125% ou 150%, pixel e unidade divergem.

    O conteúdo ocupa a largura toda. A margem cresce 1 px a cada 10 que passam de
    LARGURA_SEM_FOLGA, até CONTENT_PAD_MAX, para a tela cheia não ficar com o texto
    colado na barra lateral e na borda. Antes a coluna era travada em 880 px a partir de
    1184 de janela, e metade de um monitor de 1920 ficava vazia.
    """
    extra = int(max(0, largura_area - LARGURA_SEM_FOLGA) // 10)
    return min(CONTENT_PAD_MAX, CONTENT_PAD + extra)

# Versão da Aplicação (fonte única em versao.py)
APP_VERSION = f"v{__version__}"



def pluralize(count: int, singular: str, plural: str) -> str:
    """Formata contagem com pluralização gramaticalmente correta em português."""
    return f"{count} {singular if count == 1 else plural}"


def format_time_saved(saved_hours: int, saved_minutes: int, saved_seconds: int = 0) -> str:
    """Formata o tempo economizado de forma humanizada (ex: '45 s', '1 min', '3h 20m')."""
    if saved_hours > 0:
        return f"{saved_hours}h {saved_minutes}m"
    elif saved_minutes > 0:
        return f"{saved_minutes} min"
    elif saved_seconds > 0:
        return f"{saved_seconds} s"
    return "0 min"


def format_relative_date(timestamp_str: str) -> str:
    """Converte um timestamp textual em data relativa ('Hoje, 14:30', 'Ontem, 09:15', etc.)."""
    if not timestamp_str:
        return "Sem data"

    grupo, dt = classificar_data_historico(timestamp_str)
    if dt is None:
        return timestamp_str

    hora_str = dt.strftime("%H:%M")
    if grupo in ("Hoje", "Ontem"):
        return f"{grupo}, {hora_str}"
    if grupo == "Esta semana":
        dias_semana = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        dia_nome = dias_semana[dt.weekday()]
        return f"{dia_nome}, {hora_str}"
    return dt.strftime("%d/%m/%Y")


def diretorios_de_assets(base_dir: str | None = None) -> list[str]:
    """Diretórios candidatos onde assets/ pode estar (dev, PyInstaller _MEIPASS e executável frozen)."""
    import os
    import sys

    raiz_projeto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raizes: list[str] = []
    if base_dir:
        raizes.append(base_dir)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        raizes.append(meipass)
    raizes.append(raiz_projeto)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        raizes.append(exe_dir)
        raizes.append(os.path.join(exe_dir, "_internal"))

    vistos: set[str] = set()
    unicos: list[str] = []
    for r in raizes:
        norm = os.path.normcase(os.path.abspath(r))
        if norm not in vistos:
            vistos.add(norm)
            unicos.append(r)
    return unicos


def localizar_asset(*partes: str, base_dir: str | None = None) -> str | None:
    """Devolve o primeiro caminho existente para o asset relativo em `partes`."""
    import os

    for raiz in diretorios_de_assets(base_dir=base_dir):
        candidato = os.path.join(raiz, *partes)
        if os.path.exists(candidato):
            return candidato
    return None


def carregar_icone(icon_key: str, active: bool = False, variant: str = "primary", size: tuple = (16, 16)):
    """Carrega o ícone oficial Fluent System Icons Regular em PNG como CTkImage com suporte dual light/dark."""
    import customtkinter as ctk
    from PIL import Image

    aliases = {
        "more_horizontal": "more",
        "speaker_2": "speaker",
        "checkmark": "check",
    }
    icon_key = aliases.get(icon_key, icon_key)

    if variant == "tertiary":
        prefix = "tertiary"
    elif active or variant == "primary":
        prefix = "active" if localizar_asset("assets", "icons", f"{icon_key}_active_light.png") else ""
    else:
        prefix = "inactive"

    if prefix:
        light_path = localizar_asset("assets", "icons", f"{icon_key}_{prefix}_light.png")
        dark_path = localizar_asset("assets", "icons", f"{icon_key}_{prefix}_dark.png")
    else:
        light_path = localizar_asset("assets", "icons", f"{icon_key}_light.png")
        dark_path = localizar_asset("assets", "icons", f"{icon_key}_dark.png")

    if not light_path:
        light_path = localizar_asset("assets", "icons", f"{icon_key}_light.png")
    if not dark_path:
        dark_path = localizar_asset("assets", "icons", f"{icon_key}_dark.png")

    if light_path and dark_path:
        try:
            with Image.open(light_path) as im_l, Image.open(dark_path) as im_d:
                img_light = im_l.copy()
                img_dark = im_d.copy()
            return ctk.CTkImage(light_image=img_light, dark_image=img_dark, size=size)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: leitura de ícone PNG via Pillow/CTkImage
            pass
    return None


__all__ = [
    "ACCENT_AMBER",
    "ACCENT_AMBER_BORDER",
    "ACCENT_AMBER_HOVER",
    "ACCENT_AMBER_LIGHT",
    "ACCENT_AMBER_LIGHT_HOVER",
    "ACCENT_BLUE",
    "ACCENT_BLUE_BORDER",
    "ACCENT_BLUE_HOVER",
    "ACCENT_BLUE_LIGHT",
    "ACCENT_BLUE_LIGHT_HOVER",
    "ACCENT_CYAN",
    "ACCENT_CYAN_BORDER",
    "ACCENT_CYAN_HOVER",
    "ACCENT_CYAN_LIGHT",
    "ACCENT_CYAN_LIGHT_HOVER",
    "ACCENT_GREEN",
    "ACCENT_GREEN_BORDER",
    "ACCENT_GREEN_HOVER",
    "ACCENT_GREEN_LIGHT",
    "ACCENT_GREEN_LIGHT_HOVER",
    "ACCENT_PURPLE",
    "ACCENT_PURPLE_BORDER",
    "ACCENT_PURPLE_HOVER",
    "ACCENT_PURPLE_LIGHT",
    "ACCENT_PURPLE_LIGHT_HOVER",
    "ACCENT_RED",
    "ACCENT_RED_BORDER",
    "ACCENT_RED_HOVER",
    "ACCENT_RED_LIGHT",
    "ACCENT_RED_LIGHT_HOVER",
    "APPLE_ACCENT",
    "APPLE_ACCENT_HOVER",
    "APPLE_ACCENT_SUBTLE",
    "APPLE_BG_ACTIVE",
    "APPLE_BG_APP",
    "APPLE_BG_CARD",
    "APPLE_BG_CARD_HOVER",
    "APPLE_BG_HOVER",
    "APPLE_BG_SIDEBAR",
    "APPLE_BORDER_CARD",
    "APPLE_DESTRUCTIVE",
    "APPLE_DESTRUCTIVE_HOVER",
    "APPLE_DESTRUCTIVE_SUBTLE",
    "APPLE_INPUT_BG",
    "APPLE_INPUT_BORDER",
    "APPLE_KEYCAP_BG",
    "APPLE_KEYCAP_BORDER",
    "APPLE_SEGMENT_BG",
    "APPLE_SEGMENT_SELECTED",
    "APPLE_SEPARATOR",
    "APPLE_STATUS_ONLINE",
    "APPLE_TEXT_PRIMARY",
    "APPLE_TEXT_SECONDARY",
    "APPLE_TEXT_TERTIARY",
    "APPLE_TEXT_WARNING",
    "APP_VERSION",
    "BANDEJA_MIC_ATIVO",
    "BANDEJA_MIC_INATIVO",
    "BANDEJA_SUPORTE_ATIVO",
    "BANDEJA_SUPORTE_INATIVO",
    "BG_APP",
    "BG_CARD",
    "BG_CARD_HOVER",
    "BG_HOVER_STRONG",
    "BG_INPUT",
    "BG_MUTED",
    "BG_RECESSED",
    "BG_SIDEBAR",
    "BG_SUBTLE",
    "BORDER_CARD",
    "BORDER_INPUT",
    "BORDER_INPUT_FOCUS",
    "BORDER_SUBTLE",
    "BTN_NEUTRAL_BG",
    "BTN_NEUTRAL_BORDER",
    "BTN_NEUTRAL_HOVER",
    "BTN_NEUTRAL_TEXT",
    "BTN_PRIMARY_BG",
    "BTN_PRIMARY_HOVER",
    "BTN_PRIMARY_TEXT",
    "CONTENT_PAD",
    "CONTENT_PAD_MAX",
    "FLUTUANTE_AMARELO",
    "FLUTUANTE_AZUL",
    "FLUTUANTE_AZUL_ACAO",
    "FLUTUANTE_BORDA",
    "FLUTUANTE_BORDA_PILULA",
    "FLUTUANTE_BORDA_SUAVE",
    "FLUTUANTE_BOTAO",
    "FLUTUANTE_BOTAO_HOVER",
    "FLUTUANTE_CABECALHO",
    "FLUTUANTE_CAIXA_TEXTO",
    "FLUTUANTE_CARTAO",
    "FLUTUANTE_CARTAO_ATIVO",
    "FLUTUANTE_CIANO",
    "FLUTUANTE_CIANO_CLARO",
    "FLUTUANTE_FECHAR_HOVER",
    "FLUTUANTE_FUNDO",
    "FLUTUANTE_LARANJA",
    "FLUTUANTE_LILAS",
    "FLUTUANTE_ROLAGEM_HOVER",
    "FLUTUANTE_ROXO",
    "FLUTUANTE_TEXTO",
    "FLUTUANTE_TEXTO_APAGADO",
    "FLUTUANTE_TEXTO_BOTAO",
    "FLUTUANTE_TEXTO_SUAVE",
    "FLUTUANTE_VERDE",
    "FLUTUANTE_VERMELHO",
    "FONT_FAMILY",
    "ICON_BOX",
    "ICON_GAP",
    "ITEM_HEIGHT",
    "LARGURA_SEM_FOLGA",
    "METER_DANGER",
    "METER_OK",
    "METER_WARNING",
    "RADIUS_BUTTON",
    "RADIUS_CARD",
    "RADIUS_INPUT",
    "RADIUS_PILL",
    "SCROLLBAR_COLOR",
    "SCROLLBAR_HOVER",
    "SIDEBAR_PAD",
    "SIDEBAR_WIDTH",
    "SPACE_4",
    "SPACE_8",
    "SPACE_12",
    "SPACE_16",
    "SPACE_24",
    "SPACE_32",
    "SPACE_48",
    "TEXT_MUTED",
    "TEXT_PRIMARY",
    "TEXT_SECONDARY",
    "carregar_icone",
    "diretorios_de_assets",
    "format_relative_date",
    "format_time_saved",
    "localizar_asset",
    "margem_conteudo",
    "pluralize",
]
