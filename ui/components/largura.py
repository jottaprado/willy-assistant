"""Layout que acompanha a largura real da janela, em vez de números fixos."""

from typing import Any


def quebrar_na_largura(label: Any, container: Any, folga: int = 0) -> None:
    """Faz o texto de `label` quebrar na largura de `container`.

    Com wraplength fixo (640, 520), o texto ficava preso numa coluna estreita com a janela
    em tela cheia. O wraplength do CTkLabel é em unidades sem escala e a largura do evento
    é em pixels, daí a conversão. Só reconfigura quando o valor muda: mudar a quebra muda a
    altura do label, o container recebe outro <Configure> com a mesma largura, e sem a
    comparação isso viraria trabalho repetido a cada redimensionamento.
    """

    def _ajustar(event):
        largura = event.width - folga
        if largura < 50:
            return
        alvo = label._reverse_widget_scaling(largura)
        if abs(alvo - label.cget("wraplength")) >= 1:
            label.configure(wraplength=alvo)

    container.bind("<Configure>", _ajustar, add="+")


def afastar_conteudo_da_barra(scroll: Any, margem: int) -> None:
    """Barra de rolagem de um CTkScrollableFrame na borda direita, conteúdo `margem` antes.

    `margem` em unidades do CTk. Usa o grid interno do CTkScrollableFrame 5.2.2 (versão
    fixada no requirements.txt): o canvas do conteúdo na coluna 0 e a barra na coluna 1 do
    _parent_frame. O recuo vira espaço entre os dois, preservando o recuo esquerdo que o
    próprio CTk definiu. É grid do tkinter, em pixels, por isso a escala aplicada aqui; e o
    CTk não refaz esse grid quando a escala muda, então quem chama reaplica.
    """
    canvas = getattr(scroll, "_parent_canvas", None)
    barra = getattr(scroll, "_scrollbar", None)
    if canvas is None or barra is None:
        return
    # O Tk devolve o padx como int, tupla ou "6 0", conforme o caso.
    padx = canvas.grid_info().get("padx", 0)
    tokens = padx if isinstance(padx, (tuple, list)) else str(padx).split()
    esquerda = int(float(str(tokens[0]))) if tokens else 0
    recuo = round(scroll._apply_widget_scaling(margem)) - barra.winfo_reqwidth()
    canvas.grid_configure(padx=(esquerda, max(0, recuo)))
