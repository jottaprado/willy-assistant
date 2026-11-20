"""
Script completo para baixar e rasterizar todos os ícones necessários do Fluent System Icons.
O avatar da barra lateral é o robô de assets/willy_robot.png, não um ícone gerado aqui.

Dependências de desenvolvimento (além de requirements.txt):
    pip install "httpx>=0.28.0,<1.0.0" "reportlab>=4.0.0,<6.0.0" "svglib>=1.5.0,<3.0.0"
"""

import os
import sys

import httpx
from PIL import Image
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS_DIR = os.path.join(BASE_DIR, "assets", "icons")

# Mapeamento oficial do repositório microsoft/fluentui-system-icons
ICONS = {
    # Sidebar
    "history": ("History", "ic_fluent_history_20_regular.svg"),
    "templates": ("Document Sparkle", "ic_fluent_document_sparkle_20_regular.svg"),
    "vocabulary": ("Book", "ic_fluent_book_20_regular.svg"),
    "shortcuts": ("Keyboard", "ic_fluent_keyboard_20_regular.svg"),
    "diagnostics": ("Pulse", "ic_fluent_pulse_20_regular.svg"),
    "settings": ("Settings", "ic_fluent_settings_20_regular.svg"),
    # Ações e Componentes
    "search": ("Search", "ic_fluent_search_20_regular.svg"),
    "dismiss": ("Dismiss", "ic_fluent_dismiss_20_regular.svg"),
    "more": ("More Horizontal", "ic_fluent_more_horizontal_20_regular.svg"),
    "speaker": ("Speaker 2", "ic_fluent_speaker_2_20_regular.svg"),
    "edit": ("Edit", "ic_fluent_edit_20_regular.svg"),
    "document": ("Document", "ic_fluent_document_20_regular.svg"),
    "copy": ("Copy", "ic_fluent_copy_20_regular.svg"),
    "delete": ("Delete", "ic_fluent_delete_20_regular.svg"),
    "arrow_right": ("Arrow Right", "ic_fluent_arrow_right_20_regular.svg"),
    "add": ("Add", "ic_fluent_add_20_regular.svg"),
    "check": ("Checkmark", "ic_fluent_checkmark_20_regular.svg"),
    "empty": ("Box", "ic_fluent_box_20_regular.svg"),
    "arrow_repeat_all": ("Arrow Repeat All", "ic_fluent_arrow_repeat_all_20_regular.svg"),
}

THEMES = {
    # Primário (Ativo)
    "light": "#1D1D1F",
    "dark": "#F5F5F7",
    # Secundário (Inativo / Padrão)
    "inactive_light": "#6E6E73",
    "inactive_dark": "#98989D",
    # Terciário (Empty states / Metadados)
    "tertiary_light": "#AEAEB2",
    "tertiary_dark": "#636366",
}


def generate_fluent_icons():
    os.makedirs(ICONS_DIR, exist_ok=True)
    with httpx.Client(timeout=15.0) as client:
        for name, (folder, svg_name) in ICONS.items():
            url = f"https://raw.githubusercontent.com/microsoft/fluentui-system-icons/main/assets/{folder}/SVG/{svg_name}"
            try:
                r = client.get(url)
                if r.status_code != 200:
                    print(f"Erro {r.status_code} ao baixar {name} de {url}", file=sys.stderr)
                    continue
                raw_svg = r.text
            except httpx.HTTPError as e:
                print(f"Exceção ao baixar {name}: {e}", file=sys.stderr)
                continue

            for variant_key, fill_color in THEMES.items():
                themed_svg = raw_svg.replace('fill="#212121"', f'fill="{fill_color}"')
                if "fill=" not in themed_svg:
                    themed_svg = themed_svg.replace("<path ", f'<path fill="{fill_color}" ')

                temp_svg = os.path.join(ICONS_DIR, f"temp_{name}_{variant_key}.svg")
                out_png = os.path.join(ICONS_DIR, f"{name}_{variant_key}.png")

                with open(temp_svg, "w", encoding="utf-8") as f:
                    f.write(themed_svg)

                try:
                    drawing = svg2rlg(temp_svg)
                    # Escalar de 20x20 para 32x32 nítido
                    orig_w = drawing.width or 20
                    scale_factor = 32.0 / float(orig_w)
                    drawing.width = 32
                    drawing.height = 32
                    drawing.scale(scale_factor, scale_factor)
                    renderPM.drawToFile(drawing, out_png, fmt="PNG")

                    # Limpar fundo branco para transparência total
                    with Image.open(out_png) as img:
                        im = img.convert("RGBA")
                    datas = im.getdata()
                    new_data = []
                    for item in datas:
                        if item[0] > 250 and item[1] > 250 and item[2] > 250:
                            new_data.append((255, 255, 255, 0))
                        else:
                            new_data.append(item)
                    im.putdata(new_data)
                    im.save(out_png, "PNG")
                except (OSError, ValueError, RuntimeError) as ex:
                    print(f"Erro ao rasterizar {name}_{variant_key}: {ex}", file=sys.stderr)
                finally:
                    if os.path.exists(temp_svg):
                        try:
                            os.remove(temp_svg)
                        except OSError as rm_err:
                            print(f"Aviso ao remover {temp_svg}: {rm_err}", file=sys.stderr)

            print(f"Ícone gerado: {name} (6 variantes)")


if __name__ == "__main__":
    generate_fluent_icons()
